"""自研 POP3 客户端（RFC 1939），作为不支持 IMAP 的邮箱的兼容方案。"""

from __future__ import annotations

import ssl

from .base import LineConn, MailError


class POP3Client:
    def __init__(
        self,
        host: str,
        port: int = 995,
        *,
        tls: bool = True,
        timeout: float = 30.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.tls = tls
        self.timeout = timeout
        self.ssl_context = ssl_context
        self.conn: LineConn | None = None

    async def _status(self) -> str:
        """单行应答以 +OK 或 -ERR 开头（§3）。"""
        assert self.conn
        line = (await self.conn.readline()).decode("utf-8", "replace")
        if line.startswith("+OK"):
            return line[3:].strip()
        raise MailError(f"POP3 error: {line}")

    async def _cmd(self, line: str, *, secret: bool = False) -> str:
        assert self.conn
        await self.conn.sendline(line, secret=secret)
        return await self._status()

    async def _multiline(self) -> list[bytes]:
        """多行应答以单独一行 '.' 结束，行首多余的 '.' 需去掉（§3 字节填充）。"""
        assert self.conn
        lines: list[bytes] = []
        while True:
            ln = await self.conn.readline()
            if ln == b".":
                return lines
            lines.append(ln[1:] if ln.startswith(b"..") else ln)

    async def connect(self) -> None:
        self.conn = await LineConn.open(
            self.host, self.port, tls=self.tls, timeout=self.timeout, ssl_context=self.ssl_context
        )
        await self._status()

    async def login(self, user: str, password: str) -> None:
        await self._cmd(f"USER {user}")
        await self._cmd(f"PASS {password}", secret=True)

    async def stat(self) -> tuple[int, int]:
        parts = (await self._cmd("STAT")).split()
        return int(parts[0]), int(parts[1])

    async def uidl(self) -> dict[int, str]:
        """{消息序号: 唯一 ID}。UIDL 跨会话不变，用于增量同步（§7）。"""
        await self._cmd("UIDL")
        out: dict[int, str] = {}
        for ln in await self._multiline():
            n, uid = ln.decode().split(None, 1)
            out[int(n)] = uid.strip()
        return out

    async def retr(self, n: int) -> bytes:
        await self._cmd(f"RETR {n}")
        return b"\r\n".join(await self._multiline()) + b"\r\n"

    async def quit(self) -> None:
        if self.conn:
            try:
                await self._cmd("QUIT")
            except MailError:
                pass
            await self.conn.close()
            self.conn = None
