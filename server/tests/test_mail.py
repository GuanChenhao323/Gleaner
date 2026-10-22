import asyncio

import pytest
from fake_mail.server import FakeMailServer, client_context_for

from gleaner.net.mail import (
    Attachment,
    IMAPClient,
    MailError,
    OutgoingMail,
    POP3Client,
    SMTPClient,
    build_message,
    dot_stuff,
    parse_mail,
    send_with_retry,
)

USER = "student@test.local"


@pytest.fixture
async def mail():
    srv = FakeMailServer()
    ports = await srv.start()
    yield srv, ports, client_context_for(srv.tls)
    await srv.close()


def test_dot_stuffing():
    assert dot_stuff(b"a\n.b\n..c") == b"a\r\n..b\r\n...c\r\n"


def test_build_and_parse_mime_with_chinese_and_attachment():
    mid, raw = build_message(
        OutgoingMail(
            sender=USER,
            to=["t@x"],
            subject="关于第三次作业的截止时间",
            text="老师您好，\n请见附件。https://moodle.test/mod/assign/view.php?id=3",
            attachments=[Attachment("报告.pdf", b"%PDF-1.4 fake", "application/pdf")],
        )
    )
    assert b"=?utf-8?" in raw.lower()  # RFC 2047 编码标题
    p = parse_mail(raw)
    assert p.subject == "关于第三次作业的截止时间"
    assert p.attachments == [("报告.pdf", 13)]
    assert p.links == ["https://moodle.test/mod/assign/view.php?id=3"]
    assert p.message_id == mid


async def test_smtp_starttls_auth_send(mail):
    srv, (smtp, _, _), ctx = mail
    c = SMTPClient("127.0.0.1", smtp, username=USER, password="secret", ssl_context=ctx)
    ctx.check_hostname = False
    res = await c.send(
        OutgoingMail(
            sender=USER, to=[USER, "x@reject.local"], subject="hi", text=".leading dot\nline"
        )
    )
    await c.quit()
    assert res.accepted == [USER] and "x@reject.local" in res.rejected
    assert any("STARTTLS" in t for t in res.transcript)
    assert not any("secret" in t for t in res.transcript)  # 会话记录不泄露密码
    _frm, _rcpts, raw = srv.sent[0]
    assert b"\r\n.leading dot" in raw


async def test_smtp_bad_auth_and_retry(mail):
    srv, (smtp, _, _), ctx = mail
    ctx.check_hostname = False
    c = SMTPClient("127.0.0.1", smtp, username=USER, password="wrong", ssl_context=ctx)
    with pytest.raises(MailError) as ei:
        await c.connect()
    assert ei.value.code == 535 and not ei.value.temporary
    await c.conn.close()

    srv.temp_fail_next = 2
    res = await send_with_retry(
        mail=OutgoingMail(sender=USER, to=[USER], subject="retry", text="x"),
        base_delay=0.01,
        host="127.0.0.1",
        port=smtp,
        username=USER,
        password="secret",
        ssl_context=ctx,
    )
    assert res.accepted == [USER] and len(srv.sent) == 1


async def test_imap_select_search_fetch_and_idle(mail):
    srv, (_, imap, _), _ = mail
    _, raw1 = build_message(
        OutgoingMail(
            sender="moodle@school.edu",
            to=[USER],
            subject="作业提醒：实验一",
            text="截止 2026-11-06 23:59",
        )
    )
    srv.deliver(USER, raw1)
    c = IMAPClient("127.0.0.1", imap, tls=False)
    await c.connect()
    assert "IDLE" in c.capabilities
    await c.login(USER, "secret")
    info = await c.select("INBOX")
    assert info.exists == 1 and info.uidvalidity == 1700000000 and info.uidnext == 2
    uids = await c.uid_search("UID 1:*")
    msgs = await c.uid_fetch(uids)
    assert parse_mail(msgs[1][0]).subject == "作业提醒：实验一"

    async def later():
        await asyncio.sleep(0.2)
        srv.deliver(USER, raw1)

    t = asyncio.create_task(later())
    events = await c.idle(timeout=3)
    await t
    assert any(e.line.endswith(b"EXISTS") for e in events)
    assert await c.uid_search("UID 2:*") == [2]
    # IDLE 超时后正常 DONE
    events = await c.idle(timeout=0.2)
    assert events == [] or all(not e.line.endswith(b"EXISTS") for e in events)
    await c.logout()


async def test_imap_bad_login(mail):
    _srv, (_, imap, _), _ = mail
    c = IMAPClient("127.0.0.1", imap, tls=False)
    await c.connect()
    with pytest.raises(MailError):
        await c.login(USER, "nope")
    await c.logout()


async def test_pop3_uidl_retr(mail):
    srv, (_, _, pop), _ = mail
    _, raw = build_message(OutgoingMail(sender="a@b", to=[USER], subject="pop", text=".dot\nend"))
    srv.deliver(USER, raw)
    c = POP3Client("127.0.0.1", pop, tls=False)
    await c.connect()
    await c.login(USER, "secret")
    assert (await c.stat())[0] == 1
    assert await c.uidl() == {1: "uid-1"}
    got = await c.retr(1)
    assert parse_mail(got).text.startswith(".dot")
    await c.quit()


async def test_timeout_on_silent_server():
    async def silent(r, w):
        await asyncio.sleep(3)

    s = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = s.sockets[0].getsockname()[1]
    c = IMAPClient("127.0.0.1", port, tls=False, timeout=0.2)
    with pytest.raises(MailError, match="timeout"):
        await c.connect()
    s.close()
