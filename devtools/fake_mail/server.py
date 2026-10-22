"""开发用的内存邮件服务器：SMTP（STARTTLS、AUTH PLAIN/LOGIN）、IMAP（含 IDLE）、POP3。

用途：本地没有 Docker / GreenMail 时联调 gleaner.mailsvc，也被 server/tests 用作测试替身。
它是测试工具，不属于 server/ 的自研要求范围。docker-compose 的 dev profile 仍使用 GreenMail。

    python devtools/fake_mail/server.py --smtp 2525 --imap 1143 --pop3 1110
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import ipaddress
import ssl
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StoredMail:
    uid: int
    raw: bytes
    flags: set[str] = field(default_factory=set)


@dataclass
class Mailbox:
    uidvalidity: int = 1700000000
    next_uid: int = 1
    mails: list[StoredMail] = field(default_factory=list)
    waiters: list[asyncio.Event] = field(default_factory=list)

    def add(self, raw: bytes) -> StoredMail:
        m = StoredMail(self.next_uid, raw)
        self.next_uid += 1
        self.mails.append(m)
        for w in self.waiters:
            w.set()
        return m


def make_self_signed(host: str = "localhost") -> ssl.SSLContext:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(host), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            False,
        )
        .sign(key, hashes.SHA256())
    )
    d = Path(tempfile.mkdtemp())
    (d / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (d / "k.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(d / "c.pem", d / "k.pem")
    ctx.cert_path = str(d / "c.pem")  # type: ignore[attr-defined]
    return ctx


def client_context_for(server_ctx: ssl.SSLContext) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=server_ctx.cert_path)  # type: ignore[attr-defined]
    return ctx


class FakeMailServer:
    def __init__(
        self, users: dict[str, str] | None = None, *, tls: ssl.SSLContext | None = None
    ) -> None:
        self.users = users or {"student@test.local": "secret"}
        self.boxes: dict[str, Mailbox] = {u: Mailbox() for u in self.users}
        self.tls = tls or make_self_signed()
        self.sent: list[tuple[str, list[str], bytes]] = []
        self.temp_fail_next = 0  # 让下几次 DATA 返回 451，用于测试重试
        self._servers: list[asyncio.base_events.Server] = []

    def deliver(self, user: str, raw: bytes) -> None:
        self.boxes.setdefault(user, Mailbox()).add(raw)

    async def start(
        self, host: str = "127.0.0.1", smtp: int = 0, imap: int = 0, pop3: int = 0
    ) -> tuple[int, int, int]:
        s1 = await asyncio.start_server(self._smtp, host, smtp)
        s2 = await asyncio.start_server(self._imap, host, imap)
        s3 = await asyncio.start_server(self._pop3, host, pop3)
        self._servers = [s1, s2, s3]
        return tuple(s.sockets[0].getsockname()[1] for s in self._servers)  # type: ignore[return-value]

    async def close(self) -> None:
        for s in self._servers:
            s.close()

    # ---- SMTP ----
    async def _smtp(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        def out(s: str) -> None:
            w.write(s.encode() + b"\r\n")

        out("220 fake.local ESMTP ready")
        authed = False
        tls_on = False
        mail_from = ""
        rcpts: list[str] = []
        try:
            while True:
                line = (await r.readuntil(b"\r\n")).decode().rstrip("\r\n")
                cmd = line.split(" ", 1)[0].upper()
                if cmd == "EHLO":
                    out("250-fake.local")
                    if not tls_on:
                        out("250-STARTTLS")
                    out("250-AUTH PLAIN LOGIN")
                    out("250 8BITMIME")
                elif cmd == "STARTTLS":
                    out("220 go ahead")
                    await w.drain()
                    await w.start_tls(self.tls)
                    tls_on = True
                elif cmd == "AUTH":
                    parts = line.split()
                    if parts[1].upper() == "PLAIN":
                        _, user, pw = base64.b64decode(parts[2]).decode().split("\0")
                    else:
                        out("334 VXNlcm5hbWU6")
                        await w.drain()
                        user = base64.b64decode((await r.readuntil(b"\r\n")).strip()).decode()
                        out("334 UGFzc3dvcmQ6")
                        await w.drain()
                        pw = base64.b64decode((await r.readuntil(b"\r\n")).strip()).decode()
                    if self.users.get(user) == pw:
                        authed = True
                        out("235 ok")
                    else:
                        out("535 bad credentials")
                elif cmd == "MAIL":
                    if not authed:
                        out("530 auth required")
                    else:
                        mail_from = line.split(":", 1)[1].strip("<> ")
                        rcpts = []
                        out("250 ok")
                elif cmd == "RCPT":
                    addr = line.split(":", 1)[1].strip("<> ")
                    if addr.endswith("@reject.local"):
                        out("550 no such user")
                    else:
                        rcpts.append(addr)
                        out("250 ok")
                elif cmd == "DATA":
                    out("354 end with .")
                    await w.drain()
                    buf = bytearray()
                    while True:
                        ln = await r.readuntil(b"\r\n")
                        if ln == b".\r\n":
                            break
                        buf += ln[1:] if ln.startswith(b"..") else ln
                    if self.temp_fail_next > 0:
                        self.temp_fail_next -= 1
                        out("451 try again later")
                    else:
                        self.sent.append((mail_from, rcpts, bytes(buf)))
                        for rc in rcpts:
                            if rc in self.boxes:
                                self.boxes[rc].add(bytes(buf))
                        out("250 queued")
                elif cmd == "RSET":
                    out("250 ok")
                elif cmd == "QUIT":
                    out("221 bye")
                    await w.drain()
                    break
                else:
                    out("502 unknown")
                await w.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            w.close()

    # ---- IMAP ----
    async def _imap(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        def out(s: str | bytes) -> None:
            w.write((s.encode() if isinstance(s, str) else s) + b"\r\n")

        out("* OK fake IMAP4rev1 ready")
        user = None
        box: Mailbox | None = None
        try:
            while True:
                line = (await r.readuntil(b"\r\n")).decode().rstrip("\r\n")
                tag, _, rest = line.partition(" ")
                cmd = rest.split(" ", 1)[0].upper()
                args = rest[len(cmd) + 1 :]
                if cmd == "CAPABILITY":
                    out("* CAPABILITY IMAP4rev1 IDLE UIDPLUS AUTH=PLAIN")
                    out(f"{tag} OK done")
                elif cmd == "LOGIN":
                    u, p = [x.strip('"') for x in args.split(" ", 1)]
                    if self.users.get(u) == p:
                        user = u
                        out(f"{tag} OK logged in")
                    else:
                        out(f"{tag} NO bad credentials")
                elif cmd in ("SELECT", "EXAMINE"):
                    if not user:
                        out(f"{tag} NO login first")
                    else:
                        box = self.boxes[user]
                        out(f"* {len(box.mails)} EXISTS")
                        out(f"* OK [UIDVALIDITY {box.uidvalidity}] ok")
                        out(f"* OK [UIDNEXT {box.next_uid}] ok")
                        out(f"{tag} OK [READ-ONLY] done")
                elif cmd == "UID" and box is not None:
                    sub, _, a = args.partition(" ")
                    if sub.upper() == "SEARCH":
                        lo = 1
                        if a.upper().startswith("UID "):
                            lo = int(a.split()[1].split(":")[0])
                        uids = [str(m.uid) for m in box.mails if m.uid >= lo]
                        out("* SEARCH " + " ".join(uids) if uids else "* SEARCH")
                        out(f"{tag} OK done")
                    elif sub.upper() == "FETCH":
                        wanted = {int(x) for x in a.split(" ", 1)[0].split(",")}
                        for i, m in enumerate(box.mails, 1):
                            if m.uid in wanted:
                                w.write(
                                    f"* {i} FETCH (UID {m.uid} FLAGS ({' '.join(sorted(m.flags))}) BODY[] {{{len(m.raw)}}}\r\n".encode()
                                )
                                w.write(m.raw)
                                out(")")
                        out(f"{tag} OK done")
                elif cmd == "IDLE" and box is not None:
                    out("+ idling")
                    await w.drain()
                    ev = asyncio.Event()
                    box.waiters.append(ev)
                    known = len(box.mails)
                    done_task = asyncio.ensure_future(r.readuntil(b"\r\n"))
                    wait_task = asyncio.ensure_future(ev.wait())
                    finished, _ = await asyncio.wait(
                        {done_task, wait_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if wait_task in finished:
                        out(f"* {len(box.mails)} EXISTS")
                        await w.drain()
                        await done_task
                    else:
                        wait_task.cancel()
                    box.waiters.remove(ev)
                    _ = known
                    out(f"{tag} OK idle done")
                elif cmd == "LOGOUT":
                    out("* BYE")
                    out(f"{tag} OK bye")
                    await w.drain()
                    break
                else:
                    out(f"{tag} BAD unknown")
                await w.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            w.close()

    # ---- POP3 ----
    async def _pop3(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        def out(s: str) -> None:
            w.write(s.encode() + b"\r\n")

        out("+OK fake POP3")
        user = None
        box: Mailbox | None = None
        try:
            while True:
                line = (await r.readuntil(b"\r\n")).decode().rstrip("\r\n")
                cmd, _, arg = line.partition(" ")
                cmd = cmd.upper()
                if cmd == "USER":
                    user = arg
                    out("+OK")
                elif cmd == "PASS":
                    if user and self.users.get(user) == arg:
                        box = self.boxes[user]
                        out("+OK logged in")
                    else:
                        out("-ERR bad login")
                elif cmd == "STAT" and box:
                    out(f"+OK {len(box.mails)} {sum(len(m.raw) for m in box.mails)}")
                elif cmd == "UIDL" and box:
                    out("+OK")
                    for i, m in enumerate(box.mails, 1):
                        out(f"{i} uid-{m.uid}")
                    out(".")
                elif cmd == "RETR" and box:
                    m = box.mails[int(arg) - 1]
                    out("+OK")
                    for ln in m.raw.split(b"\r\n"):
                        w.write((b"." + ln if ln.startswith(b".") else ln) + b"\r\n")
                    out(".")
                elif cmd == "QUIT":
                    out("+OK bye")
                    await w.drain()
                    break
                else:
                    out("-ERR")
                await w.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            w.close()


async def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smtp", type=int, default=2525)
    ap.add_argument("--imap", type=int, default=1143)
    ap.add_argument("--pop3", type=int, default=1110)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    srv = FakeMailServer({"student@test.local": "secret", "alerts@test.local": "secret"})
    ports = await srv.start(a.host, a.smtp, a.imap, a.pop3)
    print(
        f"fake mail: smtp={ports[0]} imap={ports[1]} pop3={ports[2]} (users: student@test.local / secret)"
    )
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(_main())
