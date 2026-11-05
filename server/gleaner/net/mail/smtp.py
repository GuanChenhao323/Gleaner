"""自研 SMTP 客户端（RFC 5321）与 STARTTLS（RFC 3207）、AUTH（RFC 4954）。

会话：EHLO → STARTTLS → EHLO → AUTH → MAIL FROM → RCPT TO → DATA → QUIT
MIME 组装使用标准库 email（只用于构造报文，已获老师同意）。
"""

from __future__ import annotations

import asyncio
import base64
import random
import socket
import ssl
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from .base import LineConn, MailError


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime_type: str = "application/octet-stream"


@dataclass
class OutgoingMail:
    sender: str
    to: list[str]
    subject: str
    text: str
    cc: list[str] = field(default_factory=list)
    html: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    message_id: str | None = None


def build_message(mail: OutgoingMail, domain: str = "gleaner.local") -> tuple[str, bytes]:
    """组装 MIME 报文，返回 (Message-ID, 原始字节)。附件 Base64 编码。"""
    import datetime as _dt

    msg = EmailMessage()
    msg["From"] = mail.sender
    msg["To"] = ", ".join(mail.to)
    if mail.cc:
        msg["Cc"] = ", ".join(mail.cc)
    msg["Subject"] = mail.subject
    msg["Date"] = format_datetime(_dt.datetime.now(_dt.UTC))
    mid = mail.message_id or make_msgid(idstring=uuid.uuid4().hex[:12], domain=domain)
    msg["Message-ID"] = mid
    msg.set_content(mail.text)
    if mail.html:
        msg.add_alternative(mail.html, subtype="html")
    for a in mail.attachments:
        maintype, _, subtype = a.mime_type.partition("/")
        msg.add_attachment(
            a.content, maintype=maintype, subtype=subtype or "octet-stream", filename=a.filename
        )
    return mid, msg.as_bytes(policy=msg.policy.clone(linesep="\r\n"))


def dot_stuff(data: bytes) -> bytes:
    """DATA 阶段：行首的 '.' 前再加一个 '.'，并保证以 CRLF 结尾（RFC 5321 §4.5.2）。"""
    data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    if not data.endswith(b"\r\n"):
        data += b"\r\n"
    lines = data.split(b"\r\n")
    return b"\r\n".join(b"." + ln if ln.startswith(b".") else ln for ln in lines)


@dataclass
class SMTPResult:
    message_id: str
    accepted: list[str]
    rejected: dict[str, str]
    transcript: list[str]


class SMTPClient:
    def __init__(
        self,
        host: str,
        port: int = 587,
        *,
        username: str | None = None,
        password: str | None = None,
        security: str = "starttls",  # starttls / tls / none
        timeout: float = 30.0,
        ssl_context: ssl.SSLContext | None = None,
        egress_guard: bool = False,
        local_hostname: str | None = None,
    ) -> None:
        self.host = host
        self.egress_guard = egress_guard
        self.port = port
        self.username = username
        self.password = password
        self.security = security
        self.timeout = timeout
        self.ssl_context = ssl_context
        self.local_hostname = local_hostname or socket.getfqdn() or "localhost"
        self.extensions: dict[str, str] = {}
        self.conn: LineConn | None = None

    async def _reply(self) -> tuple[int, list[str]]:
        """多行应答：``250-xxx`` 继续，``250 xxx`` 结束（§4.2）。"""
        assert self.conn
        lines: list[str] = []
        while True:
            raw = (await self.conn.readline()).decode("utf-8", "replace")
            if len(raw) < 3 or not raw[:3].isdigit():
                raise MailError(f"bad SMTP reply {raw!r}")
            lines.append(raw[4:])
            if len(raw) == 3 or raw[3] == " ":
                return int(raw[:3]), lines

    async def _cmd(
        self, line: str, expect: tuple[int, ...], *, secret: bool = False
    ) -> tuple[int, list[str]]:
        assert self.conn
        await self.conn.sendline(line, secret=secret)
        code, lines = await self._reply()
        if code not in expect:
            raise MailError(
                f"{line.split()[0]} -> {code} {' '.join(lines)}", code, temporary=400 <= code < 500
            )
        return code, lines

    async def _ehlo(self) -> None:
        _, lines = await self._cmd(f"EHLO {self.local_hostname}", (250,))
        self.extensions = {}
        for ln in lines[1:]:
            k, _, v = ln.partition(" ")
            self.extensions[k.upper()] = v

    async def connect(self) -> None:
        self.conn = await LineConn.open(
            self.host,
            self.port,
            tls=self.security == "tls",
            timeout=self.timeout,
            ssl_context=self.ssl_context,
            egress_guard=self.egress_guard,
        )
        code, lines = await self._reply()
        if code != 220:
            raise MailError(f"greeting {code} {lines}", code, temporary=400 <= code < 500)
        await self._ehlo()
        if self.security == "starttls":
            if "STARTTLS" not in self.extensions:
                raise MailError("server does not support STARTTLS")
            await self._cmd("STARTTLS", (220,))
            await self.conn.start_tls(self.host, self.ssl_context)
            await self._ehlo()  # TLS 后必须重新 EHLO（RFC 3207 §4.2）
        if self.username is not None:
            await self._auth()

    async def _auth(self) -> None:
        mechs = set(self.extensions.get("AUTH", "").upper().split())
        user = self.username or ""
        pw = self.password or ""
        if "PLAIN" in mechs or not mechs:
            token = base64.b64encode(f"\0{user}\0{pw}".encode()).decode()
            await self._cmd(f"AUTH PLAIN {token}", (235,), secret=True)
        elif "LOGIN" in mechs:
            await self._cmd("AUTH LOGIN", (334,))
            await self._cmd(base64.b64encode(user.encode()).decode(), (334,), secret=True)
            await self._cmd(base64.b64encode(pw.encode()).decode(), (235,), secret=True)
        else:
            raise MailError(f"no supported AUTH mechanism in {mechs}")

    async def send(self, mail: OutgoingMail) -> SMTPResult:
        mid, raw = build_message(mail)
        return await self.send_raw(mail.sender, mail.to + mail.cc, raw, mid)

    async def send_raw(
        self, sender: str, rcpts: list[str], raw: bytes, message_id: str = ""
    ) -> SMTPResult:
        if self.conn is None:
            await self.connect()
        assert self.conn
        await self._cmd(f"MAIL FROM:<{sender}>", (250,))
        accepted: list[str] = []
        rejected: dict[str, str] = {}
        for r in rcpts:
            await self.conn.sendline(f"RCPT TO:<{r}>")
            code, lines = await self._reply()
            if code in (250, 251):
                accepted.append(r)
            else:
                rejected[r] = f"{code} {' '.join(lines)}"
        if not accepted:
            await self._cmd("RSET", (250,))
            first = next(iter(rejected.values()), "")
            raise MailError(
                f"all recipients rejected: {rejected}",
                int(first[:3] or 550),
                temporary=first.startswith("4"),
            )
        await self._cmd("DATA", (354,))
        await self.conn.send(dot_stuff(raw) + b".\r\n")
        code, lines = await self._reply()
        if code != 250:
            raise MailError(f"DATA -> {code} {lines}", code, temporary=400 <= code < 500)
        return SMTPResult(message_id, accepted, rejected, list(self.conn.transcript))

    async def quit(self) -> None:
        if self.conn:
            try:
                await self._cmd("QUIT", (221,))
            except MailError:
                pass
            await self.conn.close()
            self.conn = None


async def send_with_retry(
    factory: type[SMTPClient] | None = None,
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
    mail: OutgoingMail,
    **client_kw: object,
) -> SMTPResult:
    """4xx 临时错误按指数退避 + 抖动重试；5xx 永久错误直接抛出。"""
    cls = factory or SMTPClient
    last: MailError | None = None
    for i in range(attempts):
        client = cls(**client_kw)  # type: ignore[arg-type]
        try:
            res = await client.send(mail)
            await client.quit()
            return res
        except MailError as e:
            last = e
            if client.conn:
                await client.conn.close()
            if not e.temporary:
                raise
            await asyncio.sleep(base_delay * 2**i * (0.5 + random.random()))
        except OSError as e:
            last = MailError(str(e), temporary=True)
            await asyncio.sleep(base_delay * 2**i * (0.5 + random.random()))
    assert last
    raise last
