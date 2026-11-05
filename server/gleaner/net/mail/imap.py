"""自研 IMAP4rev1 客户端（RFC 3501）与 IDLE 扩展（RFC 2177）。

只实现收信所需的命令：CAPABILITY、LOGIN / AUTHENTICATE XOAUTH2、SELECT、
UID SEARCH、UID FETCH（BODY.PEEK，不改变已读状态）、IDLE / DONE、LOGOUT。
"""

from __future__ import annotations

import asyncio
import base64
import re
import ssl
from dataclasses import dataclass, field

from .base import LineConn, MailError

_LITERAL = re.compile(rb"\{(\d+)\+?\}$")
_UID = re.compile(rb"UID (\d+)")
_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")


@dataclass
class Response:
    """一条服务器响应：文本部分中的字面量（§4.3）以 ``{n}`` 占位，内容在 literals 中。"""

    line: bytes
    literals: list[bytes] = field(default_factory=list)


@dataclass
class MailboxInfo:
    exists: int = 0
    uidvalidity: int = 0
    uidnext: int = 0


def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class IMAPClient:
    def __init__(
        self,
        host: str,
        port: int = 993,
        *,
        tls: bool = True,
        timeout: float = 30.0,
        ssl_context: ssl.SSLContext | None = None,
        egress_guard: bool = False,
    ) -> None:
        self.host = host
        self.egress_guard = egress_guard
        self.port = port
        self.tls = tls
        self.timeout = timeout
        self.ssl_context = ssl_context
        self.conn: LineConn | None = None
        self.capabilities: set[str] = set()
        self._tag = 0
        self.untagged: list[Response] = []

    async def connect(self) -> None:
        self.conn = await LineConn.open(
            self.host,
            self.port,
            tls=self.tls,
            timeout=self.timeout,
            ssl_context=self.ssl_context,
            egress_guard=self.egress_guard,
        )
        greet = await self._read_response()
        if not greet.line.startswith((b"* OK", b"* PREAUTH")):
            raise MailError(f"bad greeting {greet.line!r}")
        await self.capability()

    async def _read_response(self, timeout: float | None = None) -> Response:
        """读取一条完整响应，包括嵌在行内的任意个字面量。"""
        assert self.conn
        resp = Response(b"")
        while True:
            line = await self.conn.readline(timeout)
            resp.line += line
            m = _LITERAL.search(line)
            if not m:
                return resp
            resp.literals.append(await self.conn.readexactly(int(m.group(1))))

    def _next_tag(self) -> str:
        self._tag += 1
        return f"G{self._tag:04d}"

    async def command(self, cmd: str, *, secret: bool = False) -> list[Response]:
        """发送命令，收集 untagged 响应直到带标签的完成应答（§2.2.2）。"""
        assert self.conn
        tag = self._next_tag()
        await self.conn.sendline(f"{tag} {cmd}", secret=secret)
        out: list[Response] = []
        tb = tag.encode()
        while True:
            r = await self._read_response()
            if r.line.startswith(tb + b" "):
                status = r.line[len(tb) + 1 :].split(b" ", 1)[0]
                if status != b"OK":
                    raise MailError(f"{cmd.split()[0]} failed: {r.line.decode('utf-8', 'replace')}")
                return out
            if r.line.startswith(b"+"):
                # 继续请求：XOAUTH2 失败时服务器发回错误详情，回空行结束
                await self.conn.sendline("")
                continue
            out.append(r)

    async def capability(self) -> set[str]:
        for r in await self.command("CAPABILITY"):
            if r.line.upper().startswith(b"* CAPABILITY"):
                self.capabilities = set(r.line.decode().upper().split()[2:])
        return self.capabilities

    async def login(self, user: str, password: str) -> None:
        await self.command(f"LOGIN {quote(user)} {quote(password)}", secret=True)
        await self.capability()

    async def authenticate_xoauth2(self, user: str, access_token: str) -> None:
        raw = f"user={user}\x01auth=Bearer {access_token}\x01\x01".encode()
        await self.command(f"AUTHENTICATE XOAUTH2 {base64.b64encode(raw).decode()}", secret=True)

    async def select(self, mailbox: str = "INBOX", readonly: bool = True) -> MailboxInfo:
        info = MailboxInfo()
        verb = "EXAMINE" if readonly else "SELECT"
        for r in await self.command(f"{verb} {quote(mailbox)}"):
            parts = r.line.split()
            if len(parts) >= 3 and parts[2] == b"EXISTS":
                info.exists = int(parts[1])
            m = re.search(rb"\[UIDVALIDITY (\d+)\]", r.line)
            if m:
                info.uidvalidity = int(m.group(1))
            m = re.search(rb"\[UIDNEXT (\d+)\]", r.line)
            if m:
                info.uidnext = int(m.group(1))
        return info

    async def uid_search(self, criteria: str) -> list[int]:
        uids: list[int] = []
        for r in await self.command(f"UID SEARCH {criteria}"):
            if r.line.startswith(b"* SEARCH"):
                uids += [int(x) for x in r.line.split()[2:]]
        return sorted(uids)

    async def uid_fetch(
        self, uids: list[int], what: str = "(UID FLAGS BODY.PEEK[])"
    ) -> dict[int, tuple[bytes, list[str]]]:
        """返回 {uid: (原始报文, flags)}。BODY.PEEK 不会给邮件加 \\Seen（§6.4.5）。"""
        if not uids:
            return {}
        out: dict[int, tuple[bytes, list[str]]] = {}
        seqset = ",".join(str(u) for u in uids)
        for r in await self.command(f"UID FETCH {seqset} {what}"):
            if b" FETCH " not in r.line:
                continue
            m = _UID.search(r.line)
            if not m:
                continue
            fm = _FLAGS.search(r.line)
            flags = fm.group(1).decode().split() if fm else []
            out[int(m.group(1))] = (r.literals[0] if r.literals else b"", flags)
        return out

    async def idle(self, timeout: float = 29 * 60) -> list[Response]:
        """进入 IDLE，等到服务器推送 EXISTS / EXPUNGE 或超时后发送 DONE（RFC 2177 §3）。

        RFC 建议客户端至少每 29 分钟重新发起 IDLE，以免被服务器的 30 分钟超时断开。
        """
        assert self.conn
        if "IDLE" not in self.capabilities:
            raise MailError("server does not support IDLE")
        tag = self._next_tag()
        await self.conn.sendline(f"{tag} IDLE")
        cont = await self._read_response()
        if not cont.line.startswith(b"+"):
            raise MailError(f"IDLE rejected: {cont.line!r}")
        events: list[Response] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    r = await self._read_response(timeout=remaining)
                except MailError as e:
                    if str(e) == "timeout":
                        break
                    raise
                events.append(r)
                if r.line.endswith((b"EXISTS", b"EXPUNGE", b"RECENT")):
                    break
        finally:
            await self.conn.sendline("DONE")
        tb = tag.encode()
        while True:
            r = await self._read_response()
            if r.line.startswith(tb + b" "):
                break
            events.append(r)
        return events

    async def logout(self) -> None:
        if self.conn:
            try:
                await self.command("LOGOUT")
            except MailError:
                pass
            await self.conn.close()
            self.conn = None
