import asyncio
import datetime as dt
import hashlib
import os
import time

import pytest

from gleaner import security
from gleaner.common.hashring import HashRing
from gleaner.core.changes import classify, diff
from gleaner.core.extract import TZ, clean_title, extract_deadline, extract_facts, summarize
from gleaner.core.scoring import UserProfile, in_quiet_hours, s_deadline, score_item
from gleaner.gateway.ratelimit import TokenBucket
from gleaner.net.http import HTTPClient, HTTPServer, Router, ServerConfig
from gleaner.obs.metrics import Registry
from gleaner.storage.db import Database
from gleaner.transfer.service import TransferService

REF = dt.datetime(2026, 10, 21, 10, 0, tzinfo=TZ)  # 周三


@pytest.mark.parametrize(
    "text,expect",
    [
        ("请于10月30日23:59前提交", "2026-10-30 23:59"),
        ("本周五前提交实验报告", "2026-10-23 23:59"),
        ("Assignment due Oct 30, 11:59 PM", "2026-10-30 23:59"),
        ("截止日期 2026-10-30", "2026-10-30 23:59"),
        ("下周三下午3点前交", "2026-10-28 15:00"),
        ("明天晚上8点截止", "2026-10-22 20:00"),
        ("deadline: next Friday", "2026-10-30 23:59"),
        ("11月6日（周五）截止", "2026-11-06 23:59"),
        ("1月5日前提交", "2027-01-05 23:59"),
    ],
)
def test_deadline_extraction(text, expect):
    m = extract_deadline(text, REF)
    assert m is not None and m.at.strftime("%Y-%m-%d %H:%M") == expect


def test_no_deadline_without_context():
    assert extract_deadline("下周三的课调整到周四", REF) is None
    assert extract_deadline("今天天气不错", REF) is None


def test_title_summary_facts():
    assert clean_title("【CS3001】关于第三次作业调整的通知") == "第三次作业调整"
    assert clean_title("Re: 关于期中考试安排的通知") == "期中考试安排"
    s = summarize("第一句话。第二句话！第三句话。")
    assert s == "第一句话。第二句话！"
    f = extract_facts("面向2024级计算机学院本科生，地点：教三201")
    assert "2024级" in f["grades"] and f["places"] == ["教三201"]


def test_scoring_formula_and_tiers():
    now = time.time()
    p = UserProfile(1, grade="2024级", major="计算机", courses=["网络编程"])
    item = {
        "title": "实验一 截止",
        "summary": "",
        "deadline_at": now + 3600,
        "course": "CS3105 网络编程",
        "kind": "assignment",
    }
    s = score_item(item, p, source_id=1, source_weight=1.0, now=now)
    # 100 × (0.30×1 + 0.25×0.5 + 0.25×1 + 0.20×1) = 87.5
    assert s.total == 88 and s.priority == "urgent"
    low = score_item(
        {"title": "图书馆讲座", "summary": ""}, p, source_id=2, source_weight=0.4, now=now
    )
    assert low.priority == "low"
    # 重要变更：距截止不足 7 天升为紧急
    imp = score_item(
        {"title": "x", "deadline_at": now + 3 * 86400},
        p,
        source_id=2,
        source_weight=0.1,
        important_change=True,
        now=now,
    )
    assert imp.priority == "urgent"
    p.block_words = ["讲座"]
    assert score_item({"title": "讲座"}, p, source_id=2, source_weight=1, now=now).total == 0
    assert s_deadline(now + 4 * 86400, now) == pytest.approx(0.5)


def test_quiet_hours_wraps_midnight():
    p = UserProfile(1, quiet_start="23:00", quiet_end="07:00")
    at = lambda h: dt.datetime(2026, 10, 21, h, 30, tzinfo=TZ).timestamp()  # noqa: E731
    assert in_quiet_hours(p, at(23)) and in_quiet_hours(p, at(2)) and not in_quiet_hours(p, at(12))


def test_change_classification():
    d = diff(
        {"deadline_at": 2000000.0, "attachments": [{"name": "a.pdf"}]},
        {"deadline_at": 2000000.0 - 2 * 86400, "attachments": [{"name": "b.pdf"}]},
    )
    important, note = classify(d)
    assert important and "截止提前 2 天" in note and "附件替换" in note
    important, note = classify(diff({"body": "请  提交"}, {"body": "请提交报告"}))
    assert not important and note == "内容措辞调整"
    assert diff({"body": "a  b"}, {"body": "a b"}) == {}


def test_hash_ring_balance_and_failover():
    ring = HashRing(["push-1", "push-2", "push-3"])
    counts = {}
    for u in range(3000):
        n = ring.get(f"user:{u}")
        counts[n] = counts.get(n, 0) + 1
    assert all(700 < c < 1300 for c in counts.values())
    before = {u: ring.get(f"user:{u}") for u in range(1000)}
    ring.remove("push-2")
    moved = sum(1 for u, n in before.items() if n != "push-2" and ring.get(f"user:{u}") != n)
    assert moved == 0  # 只有原先在 push-2 上的用户被迁移
    assert ring.get("user:1", exclude={"push-1", "push-3"}) is None


def test_token_bucket():
    b = TokenBucket(rate=10, burst=3)
    assert [b.allow("k")[0] for _ in range(4)] == [True, True, True, False]
    time.sleep(0.11)
    assert b.allow("k")[0]


def test_tokens_and_encryption():
    t = security.sign_token({"uid": 5, "tv": 1}, ttl=60)
    assert security.verify_token(t)["uid"] == 5
    assert security.verify_token(t[:-2] + "xx") is None
    assert security.verify_token(security.sign_token({"uid": 5}, ttl=-1)) is None
    blob = security.encrypt({"cookie": "abc"}, aad=b"1:2")
    assert security.decrypt(blob, aad=b"1:2") == {"cookie": "abc"}
    from cryptography.exceptions import InvalidTag

    with pytest.raises(InvalidTag):
        security.decrypt(blob, aad=b"1:3")  # 密文不能挪用到别的用户或来源
    h = security.hash_password("password1")
    assert security.verify_password(h, "password1") and not security.verify_password(h, "x")


def test_metrics_exposition_format():
    r = Registry()
    c = r.counter("x_total", "help", ("a",))
    c.inc(2, 'q"1')
    h = r.histogram("lat_seconds", "lat", buckets=(0.1, 1))
    h.observe(0.05)
    h.observe(5)
    text = r.render()
    assert 'x_total{a="q\\"1"} 2' in text
    assert 'lat_seconds_bucket{le="0.1"} 1' in text and 'lat_seconds_bucket{le="+Inf"} 2' in text
    assert "lat_seconds_count 2" in text


async def test_transfer_chunked_resume_and_range(tmp_path, db_url):
    db = await Database(db_url("t.db")).connect()
    uid = await db.insert(
        "users", {"email": "a@b.c", "password_hash": "x", "created_at": time.time()}
    )
    notes = []

    async def user_of(req):
        return {"id": uid} if req.headers.get("X-User") else None

    async def notify(u, p):
        notes.append(p["status"])

    router = Router()
    TransferService(db, str(tmp_path), user_of, notify).register(router)
    srv = HTTPServer(router, ServerConfig(host="127.0.0.1", port=0))
    await srv.start()
    base = f"http://127.0.0.1:{srv.port}/api/transfer"
    data = os.urandom(300_000)
    sha = hashlib.sha256(data).hexdigest()
    async with HTTPClient() as c:
        created = (await c.post(base, headers={"X-User": "1"})).json()
        code = created["code"]
        joined = (await c.post(f"{base}/{code}/join", json_body={"device": "Pixel"})).json()
        th = {"X-Transfer-Token": joined["token"]}
        assert (await c.get(f"{base}/{code}")).status == 403
        fid = (
            await c.post(
                f"{base}/{code}/files",
                json_body={"name": "a.bin", "size": len(data), "sha256": sha},
                headers=th,
            )
        ).json()["id"]
        chunk = 100_000
        # 先传两块，模拟断线
        for start in (0, chunk):
            r = await c.request(
                "PUT",
                f"{base}/{code}/files/{fid}",
                body=data[start : start + chunk],
                headers={**th, "Content-Range": f"bytes {start}-{start + chunk - 1}/{len(data)}"},
            )
            assert r.status == 200
        # 跳块上传被拒绝，返回已接收字节数
        r = await c.request(
            "PUT",
            f"{base}/{code}/files/{fid}",
            body=b"x",
            headers={**th, "Content-Range": f"bytes 250000-250000/{len(data)}"},
        )
        assert r.status == 409 and r.json()["received"] == 2 * chunk
        # 断点续传：查询进度后继续
        received = (await c.get(f"{base}/{code}/files/{fid}", headers=th)).json()["received"]
        r = await c.request(
            "PUT",
            f"{base}/{code}/files/{fid}",
            body=data[received:],
            headers={**th, "Content-Range": f"bytes {received}-{len(data) - 1}/{len(data)}"},
        )
        assert r.json()["status"] == "done"
        # Range 断点下载
        r = await c.get(
            f"{base}/{code}/files/{fid}/content", headers={**th, "Range": "bytes=100-199"}
        )
        assert r.status == 206 and r.body == data[100:200]
        full = await c.get(f"{base}/{code}/files/{fid}/content", headers=th)
        assert hashlib.sha256(full.body).hexdigest() == r.headers.get("X-Content-SHA256") == sha
    assert notes[:2] == ["paired", "file"] and notes[-1] == "done"
    await srv.close()
    await db.close()


async def test_db_transaction_rollback(db_url):
    db = await Database(db_url("r.db")).connect()
    uid = await db.insert("users", {"email": "z@b.c", "password_hash": "x", "created_at": 0})
    with pytest.raises(RuntimeError):
        async with db.transaction():
            await db.execute("UPDATE users SET next_seq = 99 WHERE id = ?", uid)
            raise RuntimeError
    assert await db.fetchval("SELECT next_seq FROM users WHERE id = ?", uid) == 0

    async def bump():
        async with db.transaction():
            await db.execute("UPDATE users SET next_seq = next_seq + 1 WHERE id = ?", uid)
            return await db.fetchval("SELECT next_seq FROM users WHERE id = ?", uid)

    seqs = await asyncio.gather(*(bump() for _ in range(20)))
    assert sorted(seqs) == list(range(1, 21))  # 并发分配的 seq 不重复
    await db.close()


async def test_low_priority_delivery_is_pushed_silently(tmp_path, db_url):
    from gleaner.core.pipeline import Pipeline

    db = await Database(db_url("p.db")).connect()
    uid = await db.insert("users", {"email": "s@b.c", "password_hash": "x", "created_at": 0})
    sid = await db.insert(
        "sources", {"type": "web", "name": "讲座", "endpoint": "http://x/", "created_at": 0}
    )
    await db.execute(
        "INSERT INTO subscriptions (user_id, source_id, weight, created_at) VALUES (?, ?, 0.1, 0)",
        uid,
        sid,
    )
    routed = []

    async def route(topic, payload):
        routed.append((topic, payload))

    pipe = Pipeline(db, route)
    await pipe.ingest(
        {
            "source_id": sid,
            "status": "ok",
            "items": [
                {"key": "web:1", "kind": "notice", "title": "图书馆讲座", "url": "http://x/1"}
            ],
        }
    )
    [(topic, p)] = [r for r in routed if r[0].startswith("u.")]
    assert topic == f"u.{uid}" and p["priority"] == "low" and p["silent"] is True
    assert not [r for r in routed if r[0] == "mqtt.publish"]
    await db.close()


async def test_digest_email_is_opt_in(tmp_path, monkeypatch, db_url):
    import datetime as dt

    from gleaner.core import reminders
    from gleaner.core.extract import TZ
    from gleaner.core.pipeline import Pipeline

    sent = []

    async def fake_send(to, subject, text, **kw):
        sent.append((to, subject, text))
        return True

    monkeypatch.setattr(reminders, "send_platform_mail", fake_send)
    db = await Database(db_url("d.db")).connect()
    for email, opt in (("a@x.com", 1), ("b@x.com", 0)):
        await db.insert(
            "users",
            {
                "email": email,
                "password_hash": "x",
                "digest_time": "08:00",
                "digest_email": opt,
                "created_at": 0,
            },
        )
    routed = []

    async def route(topic, payload):
        routed.append(topic)

    now = dt.datetime(2026, 10, 22, 8, 0, tzinfo=TZ).timestamp()
    assert await reminders.publish_digests(db, Pipeline(db, route), now) == 2
    assert [s[0] for s in sent] == ["a@x.com"] and "每日摘要" in sent[0][1]
    assert routed.count("mqtt.publish") == 2
    # 同一天不会重复发送
    assert await reminders.publish_digests(db, Pipeline(db, route), now + 30) == 0
    await db.close()


async def test_personal_sources_are_scoped_per_user(db_url):
    """两个用户各自登录同一个 Moodle：作业互不覆盖；个人数据只与本人或公共来源合并（compose 实测发现）。"""
    from gleaner.core.pipeline import Pipeline

    db = await Database(db_url("s.db")).connect()

    async def route(topic, payload):
        pass

    pipe = Pipeline(db, route)

    async def user_with(email: str, *types: str) -> tuple[int, dict[str, int]]:
        uid = await db.insert("users", {"email": email, "password_hash": "x", "created_at": 0})
        out = {}
        for t in types:
            sid = await db.insert(
                "sources",
                {"type": t, "name": t, "endpoint": "http://m/", "owner_id": uid, "created_at": 0},
            )
            await db.execute(
                "INSERT INTO subscriptions (user_id, source_id, created_at) VALUES (?, ?, 0)",
                uid,
                sid,
            )
            out[t] = sid
        return uid, out

    def assign(title: str) -> dict:
        return {
            "key": "moodle:m:assign:1001",
            "kind": "assignment",
            "title": title,
            "url": "http://m/mod/assign/view.php?id=1001",
            "alias_keys": ["url:m/mod/assign/view.php?id=1001"],
        }

    a, sa = await user_with("a@x.com", "moodle")
    b, sb = await user_with("b@x.com", "moodle", "imap")
    shared = await db.insert(
        "sources", {"type": "web", "name": "学院通知", "endpoint": "http://c/", "created_at": 0}
    )
    await db.execute(
        "INSERT INTO subscriptions (user_id, source_id, created_at) VALUES (?, ?, 0)", b, shared
    )

    ok = {"status": "ok"}
    assert (await pipe.ingest({**ok, "source_id": sa["moodle"], "items": [assign("实验一")]}))[
        "new"
    ] == 1
    # 同一个 Moodle 作业，B 用自己的账号采到：应该是 B 自己的一条，而不是被当成 A 那条“未变化”
    assert (await pipe.ingest({**ok, "source_id": sb["moodle"], "items": [assign("实验一")]}))[
        "new"
    ] == 1

    async def visible(uid: int) -> list[str]:
        rows = await db.fetch(
            "SELECT i.title FROM items i JOIN subscriptions s ON s.source_id = i.source_id "
            "AND s.user_id = ? ORDER BY i.id",
            uid,
        )
        return [r["title"] for r in rows]

    assert await visible(a) == ["实验一"] and await visible(b) == ["实验一"]

    # B 的提醒邮件链接到同一作业：合并进 B 自己的那条，不能合并进 A 的
    mail = {
        "key": "mail:<m1@m>",
        "kind": "notice",
        "title": "作业提醒",
        "url": "http://m/mod/assign/view.php?id=1001",
        "alias_keys": ["url:m/mod/assign/view.php?id=1001"],
    }
    assert (await pipe.ingest({**ok, "source_id": sb["imap"], "items": [mail]}))["merged"] == 1
    owner_of_merged = await db.fetchval(
        "SELECT s.owner_id FROM item_aliases al JOIN items i ON i.id = al.item_id "
        "JOIN sources s ON s.id = i.source_id WHERE al.source_id = ?",
        sb["imap"],
    )
    assert owner_of_merged == b

    # 个人邮件仍能与公共来源（学院通知）合并
    notice = {
        "key": "web:http://c/n/1",
        "kind": "notice",
        "title": "讲座通知",
        "url": "http://c/n/1",
        "alias_keys": ["url:c/n/1"],
    }
    await pipe.ingest({**ok, "source_id": shared, "items": [notice]})
    mail2 = {**notice, "key": "mail:<m2@m>"}
    assert (await pipe.ingest({**ok, "source_id": sb["imap"], "items": [mail2]}))["merged"] == 1
    await db.close()


async def test_migration_scopes_existing_personal_keys(db_url):
    url = db_url("m.db")
    db = await Database(url).connect()
    uid = await db.insert("users", {"email": "m@x.com", "password_hash": "x", "created_at": 0})
    personal = await db.insert(
        "sources",
        {"type": "moodle", "name": "m", "endpoint": "http://m/", "owner_id": uid, "created_at": 0},
    )
    shared = await db.insert(
        "sources", {"type": "web", "name": "w", "endpoint": "http://w/", "created_at": 0}
    )
    ids = {}
    for sid, key in ((personal, "moodle:m:assign:1"), (shared, "web:http://w/1")):
        ids[sid] = await db.insert(
            "items",
            {
                "source_id": sid,
                "identity_key": key,
                "kind": "notice",
                "title": key,
                "first_seen_at": 0,
                "updated_at": 0,
            },
        )
        await db.execute(
            "INSERT INTO item_aliases (alias_key, item_id, source_id, created_at) VALUES (?, ?, ?, 0)",
            "url:" + key,
            ids[sid],
            sid,
        )
    # 模拟迁移 2、3 发布之前的旧库：删掉这两条执行记录，重新连接时会补跑
    await db.execute("DELETE FROM schema_migrations WHERE version IN (2, 3)")
    await db.close()
    for _ in range(2):  # 执行过的迁移不会重复执行
        db = await Database(url).connect()
        await db.close()
    db = await Database(url).connect()
    versions = [
        r["version"]
        for r in await db.fetch("SELECT version FROM schema_migrations ORDER BY version")
    ]
    assert versions == sorted(set(versions)) and {2, 3} <= set(versions)
    keys = {
        r["source_id"]: r["identity_key"]
        for r in await db.fetch("SELECT source_id, identity_key FROM items")
    }
    aliases = {
        r["source_id"]: r["alias_key"]
        for r in await db.fetch("SELECT source_id, alias_key FROM item_aliases")
    }
    assert keys == {personal: f"@{uid}/moodle:m:assign:1", shared: "web:http://w/1"}
    assert aliases == {personal: f"@{uid}/url:moodle:m:assign:1", shared: "url:web:http://w/1"}
    await db.close()


def test_moodle_ws_url_keeps_query_separator():
    """Python 3.12 的 urljoin 会丢掉末尾空的“?”；容器里 Moodle Web Service 曾因此一直拿不到 token。"""
    from gleaner.collector.session import moodle_ws_url

    url = moodle_ws_url("https://m.example.edu/my/", "a" * 32, "mod_assign_get_assignments")
    assert url.startswith("https://m.example.edu/webservice/rest/server.php?wstoken=")
    assert "wsfunction=mod_assign_get_assignments" in url


def test_to_pg_placeholders() -> None:
    from gleaner.storage.db import to_pg

    assert to_pg("SELECT ? , '?' , \"a?\" , 'x%' , ?") == "SELECT %s , '?' , \"a?\" , 'x%%' , %s"
    assert to_pg("WHERE k LIKE '@%' AND v = ?") == "WHERE k LIKE '@%%' AND v = %s"
    assert to_pg("SELECT 'it''s ?'") == "SELECT 'it''s ?'"


async def test_maintenance_retention(tmp_path, db_url):
    from gleaner.core.maintenance import run_maintenance

    db = await Database(db_url("mt.db")).connect()
    now = 1_800_000_000.0
    old = now - 400 * 86400
    uid = await db.insert("users", {"email": "mt@x.com", "password_hash": "x", "created_at": 0})
    shared_orphan = await db.insert(
        "sources", {"type": "web", "name": "o", "endpoint": "http://o/", "created_at": 0}
    )
    mail_src = await db.insert(
        "sources",
        {"type": "imap", "name": "m", "endpoint": "imap://m", "owner_id": uid, "created_at": 0},
    )
    moodle = await db.insert(
        "sources",
        {
            "type": "moodle",
            "name": "md",
            "endpoint": "http://md/",
            "owner_id": uid,
            "status": "need_login",
            "created_at": 0,
        },
    )
    for sid in (mail_src, moodle):
        await db.execute(
            "INSERT INTO subscriptions (user_id, source_id, created_at) VALUES (?, ?, 0)", uid, sid
        )
    mail_item = await db.insert(
        "items",
        {
            "source_id": mail_src,
            "identity_key": "m1",
            "kind": "mail",
            "title": "t",
            "body": "正文",
            "first_seen_at": old,
            "updated_at": old,
        },
    )
    fresh_mail = await db.insert(
        "items",
        {
            "source_id": mail_src,
            "identity_key": "m2",
            "kind": "mail",
            "title": "t",
            "body": "新正文",
            "first_seen_at": now,
            "updated_at": now,
        },
    )
    await db.execute(
        "INSERT INTO credentials (user_id, source_id, auth_type, secret_encrypted, updated_at) VALUES (?, ?, 'ws_token', ?, ?)",
        uid,
        moodle,
        b"x",
        old,
    )
    await db.execute(
        "INSERT INTO credentials (user_id, source_id, auth_type, secret_encrypted, updated_at) VALUES (?, ?, 'app_password', ?, ?)",
        uid,
        mail_src,
        b"x",
        old,
    )
    for seq, t, item in ((1, old, mail_item), (2, now, fresh_mail), (3, now, 999_999)):
        await db.execute(
            "INSERT INTO deliveries (user_id, seq, item_id, kind, payload, created_at) VALUES (?, ?, ?, 'item', '{}', ?)",
            uid,
            seq,
            item,
            t,
        )
    await db.execute(
        "INSERT INTO op_log (user_id, op_id, result, created_at) VALUES (?, 'c:a', '{}', ?)",
        uid,
        old,
    )
    await db.execute(
        "INSERT INTO email_codes (email, code_hash, expires_at, attempts, sent_at) VALUES ('a@b.c', 'h', ?, 0, ?)",
        old,
        old,
    )
    await db.execute(
        "INSERT INTO sent_mails (user_id, idempotency_key, status, created_at) VALUES (?, 'k1', 'sending', ?)",
        uid,
        now - 3600,
    )
    await db.insert(
        "sessions", {"id": "s-old", "user_id": uid, "created_at": old, "last_seen_at": old}
    )
    await db.insert(
        "sessions", {"id": "s-new", "user_id": uid, "created_at": now, "last_seen_at": now}
    )
    tid = await db.insert(
        "transfers",
        {"user_id": uid, "pair_code": "ABC234", "token": "t", "created_at": old, "expires_at": old},
    )
    tdir = tmp_path / "transfers" / str(tid)
    tdir.mkdir(parents=True)
    (tdir / "1.part").write_bytes(b"x")

    out = await run_maintenance(db, str(tmp_path), now=now)
    assert out["mail_bodies"] == 1 and out["deliveries"] == 1 and out["orphan_deliveries"] == 1
    bodies = {
        r["identity_key"]: r["body"] for r in await db.fetch("SELECT identity_key, body FROM items")
    }
    assert bodies == {"m1": "", "m2": "新正文"}
    assert [r["seq"] for r in await db.fetch("SELECT seq FROM deliveries")] == [2]
    assert await db.fetchval("SELECT COUNT(*) FROM op_log") == 0
    assert await db.fetchval("SELECT COUNT(*) FROM email_codes") == 0
    assert await db.fetchval("SELECT status FROM sent_mails") == "failed"
    assert [r["id"] for r in await db.fetch("SELECT id FROM sessions")] == ["s-new"]
    # 失效的来源会话被删，邮箱的应用专用密码保留
    assert [r["auth_type"] for r in await db.fetch("SELECT auth_type FROM credentials")] == [
        "app_password"
    ]
    assert not await db.fetchone("SELECT 1 FROM sources WHERE id = ?", shared_orphan)
    assert not tdir.exists() and await db.fetchval("SELECT COUNT(*) FROM transfers") == 0
    # 再跑一次什么都不做
    again = await run_maintenance(db, str(tmp_path), now=now)
    assert not any(again.values())
    await db.close()


def test_data_key_rotation_and_legacy_blobs(monkeypatch):
    import os as _os

    from gleaner import security

    k1, k2 = _os.urandom(32).hex(), _os.urandom(32).hex()
    monkeypatch.delenv("GLEANER_DATA_KEY", raising=False)
    legacy_key = security._derived_key()
    nonce = b"\0" * 12
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    legacy = nonce + AESGCM(legacy_key).encrypt(nonce, b'{"a": 1}', b"aad")  # 旧格式密文
    monkeypatch.setenv("GLEANER_DATA_KEY", k1)
    blob1 = security.encrypt({"b": 2}, aad=b"aad")
    assert blob1[:2] == b"GK" and security.decrypt(blob1, aad=b"aad") == {"b": 2}
    assert security.decrypt(legacy, aad=b"aad") == {"a": 1}  # 旧格式仍可解密（派生密钥兜底）
    # 轮换：新密钥 k2，旧密钥放进 GLEANER_DATA_KEY_OLD
    monkeypatch.setenv("GLEANER_DATA_KEY", k2)
    monkeypatch.setenv("GLEANER_DATA_KEY_OLD", k1)
    assert security.decrypt(blob1, aad=b"aad") == {"b": 2}
    monkeypatch.delenv("GLEANER_DATA_KEY_OLD")
    with pytest.raises(Exception):  # noqa: B017  （没有旧密钥时解不开）
        security.decrypt(blob1, aad=b"aad")
    monkeypatch.setenv("GLEANER_DATA_KEY", "abcd")
    assert any("32 字节" in p for p in security.check_secrets())
