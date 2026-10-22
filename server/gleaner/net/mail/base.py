"""邮件协议共用的行式连接：读取 CRLF 行、超时、STARTTLS 升级。"""

from __future__ import annotations

import asyncio
import ssl


class MailError(Exception):
    def __init__(self, message: str, code: int | None = None, temporary: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.temporary = temporary


class LineConn:
    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, timeout: float
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.timeout = timeout
        self.transcript: list[str] = []  # 调试与演示用的会话记录（密码已打码）

    @classmethod
    async def open(
        cls,
        host: str,
        port: int,
        *,
        tls: bool,
        timeout: float = 30.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> LineConn:
        ctx = ssl_context or ssl.create_default_context()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host,
                port,
                ssl=ctx if tls else None,
                server_hostname=host if tls else None,
                limit=2**22,
            ),
            timeout,
        )
        return cls(reader, writer, timeout)

    async def start_tls(self, host: str, ssl_context: ssl.SSLContext | None = None) -> None:
        """在已有 TCP 连接上升级为 TLS（SMTP STARTTLS，RFC 3207）。"""
        await self.writer.start_tls(
            ssl_context or ssl.create_default_context(), server_hostname=host
        )

    async def readline(self, timeout: float | None = None) -> bytes:
        try:
            line = await asyncio.wait_for(self.reader.readuntil(b"\r\n"), timeout or self.timeout)
        except asyncio.IncompleteReadError as e:
            raise MailError("connection closed", temporary=True) from e
        except asyncio.LimitOverrunError as e:
            raise MailError("line too long") from e
        except TimeoutError as e:
            raise MailError("timeout", temporary=True) from e
        self.transcript.append("S: " + line.decode("utf-8", "replace").rstrip())
        return line[:-2]

    async def readexactly(self, n: int) -> bytes:
        try:
            return await asyncio.wait_for(self.reader.readexactly(n), self.timeout)
        except asyncio.IncompleteReadError as e:
            raise MailError("connection closed", temporary=True) from e
        except TimeoutError as e:
            raise MailError("timeout", temporary=True) from e

    async def send(self, data: bytes, *, secret: bool = False) -> None:
        self.transcript.append(
            "C: " + ("<redacted>" if secret else data.decode("utf-8", "replace").rstrip()[:200])
        )
        self.writer.write(data)
        await self.writer.drain()

    async def sendline(self, line: str, *, secret: bool = False) -> None:
        await self.send(line.encode("utf-8") + b"\r\n", secret=secret)

    async def close(self) -> None:
        if not self.writer.is_closing():
            self.writer.close()
        try:
            await asyncio.wait_for(self.writer.wait_closed(), 2)
        except Exception:
            pass
