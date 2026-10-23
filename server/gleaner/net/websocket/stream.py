"""WebSocket 的 asyncio 封装：服务端接管升级连接、客户端主动连接、心跳。"""

from __future__ import annotations

import asyncio
import contextlib
import ssl
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from ..http.message import Request, Response
from ..http.parser import HTTPParser
from .protocol import (
    CloseCode,
    Closed,
    Message,
    Opcode,
    State,
    WSConnection,
    client_handshake,
    handshake_response,
)


class ConnectionClosed(Exception):
    def __init__(self, code: int, reason: str = "") -> None:
        super().__init__(f"websocket closed {code} {reason}")
        self.code = code
        self.reason = reason


class WebSocket:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        is_client: bool,
        leftover: bytes = b"",
        max_message: int = 4 * 1024 * 1024,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.conn = WSConnection(is_client=is_client, max_message=max_message)
        self._pending: list[Message | Closed] = []
        self._leftover = leftover
        self._send_lock = asyncio.Lock()
        self.last_seen = time.monotonic()
        self.last_pong = time.monotonic()
        self._hb_task: asyncio.Task[None] | None = None
        self.peer = writer.get_extra_info("peername")

    @property
    def closed(self) -> bool:
        return self.conn.state is State.CLOSED or self.writer.is_closing()

    @property
    def write_buffer_size(self) -> int:
        t = self.writer.transport
        return t.get_write_buffer_size() if t is not None else 0

    async def _write(self, data: bytes) -> None:
        if not data:
            return
        async with self._send_lock:
            if self.writer.is_closing():
                raise ConnectionClosed(CloseCode.ABNORMAL, "transport closing")
            self.writer.write(data)
            await self.writer.drain()

    async def send(self, data: str | bytes) -> None:
        if self.conn.state is not State.OPEN:
            raise ConnectionClosed(self.conn.close_code or CloseCode.ABNORMAL)
        frame = self.conn.send_text(data) if isinstance(data, str) else self.conn.send_binary(data)
        await self._write(frame)

    async def ping(self, data: bytes = b"") -> None:
        await self._write(self.conn.send_ping(data))

    async def recv(self) -> Message:
        """返回下一条 TEXT/BINARY 消息；收到 close 时抛 ConnectionClosed。"""
        while True:
            while self._pending:
                ev = self._pending.pop(0)
                if isinstance(ev, Closed):
                    await self._shutdown()
                    raise ConnectionClosed(ev.code, ev.reason)
                if ev.opcode == Opcode.PONG:
                    self.last_pong = time.monotonic()
                    continue
                if ev.opcode == Opcode.PING:
                    continue
                return ev
            if self._leftover:
                data, self._leftover = self._leftover, b""
            else:
                try:
                    data = await self.reader.read(65536)
                except (ConnectionError, OSError):
                    data = b""
            if not data:
                await self._shutdown()
                raise ConnectionClosed(CloseCode.ABNORMAL, "eof")
            self.last_seen = time.monotonic()
            events, reply = self.conn.receive_data(data)
            if reply:
                with contextlib.suppress(ConnectionError, ConnectionClosed):
                    await self._write(reply)
            self._pending.extend(events)

    async def close(
        self, code: int = CloseCode.NORMAL, reason: str = "", timeout: float = 2.0
    ) -> None:
        if self.conn.state is State.OPEN:
            with contextlib.suppress(ConnectionError, ConnectionClosed, OSError):
                await self._write(self.conn.send_close(code, reason))
            # 等待对端回应 close（§7.1.2），超时后直接断开 TCP
            with contextlib.suppress(Exception):
                async with asyncio.timeout(timeout):
                    while True:
                        await self.recv()
        await self._shutdown()

    async def _shutdown(self) -> None:
        if self._hb_task and self._hb_task is not asyncio.current_task():
            self._hb_task.cancel()
        if not self.writer.is_closing():
            self.writer.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.writer.wait_closed(), 1)

    def start_heartbeat(self, interval: float = 25.0, timeout: float = 60.0) -> None:
        """每 ``interval`` 秒发 ping；``timeout`` 秒内既无 pong 也无其他数据则判定断开。"""

        async def loop() -> None:
            try:
                while not self.closed:
                    await asyncio.sleep(interval)
                    if time.monotonic() - max(self.last_pong, self.last_seen) > timeout:
                        self.conn.state = State.CLOSED
                        self.writer.close()
                        return
                    await self.ping(str(int(time.time())).encode())
            except (ConnectionError, ConnectionClosed, OSError):
                pass

        self._hb_task = asyncio.get_running_loop().create_task(loop())

    def __aiter__(self) -> WebSocket:
        return self

    async def __anext__(self) -> Message:
        try:
            return await self.recv()
        except ConnectionClosed as e:
            raise StopAsyncIteration from e


class HandshakeError(Exception):
    pass


async def connect(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    ssl_context: ssl.SSLContext | None = None,
) -> WebSocket:
    """自研 WebSocket 客户端（本地采集代理、压测、测试使用）。"""
    parts = urlsplit(url)
    secure = parts.scheme == "wss"
    host = parts.hostname or "localhost"
    port = parts.port or (443 if secure else 80)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            host,
            port,
            ssl=(ssl_context or ssl.create_default_context()) if secure else None,
            server_hostname=host if secure else None,
        ),
        timeout,
    )
    req, expected = client_handshake(f"{host}:{port}", path, headers)
    writer.write(req.encode_head())
    await writer.drain()
    parser = HTTPParser("response")
    parser.expect_response("GET")
    resp: Response | None = None
    async with asyncio.timeout(timeout):
        while resp is None:
            data = await reader.read(65536)
            if not data:
                raise HandshakeError("closed during handshake")
            msgs = parser.feed(data)
            if msgs:
                m = msgs[0]
                assert isinstance(m, Response)
                resp = m
    if resp.status != 101 or resp.headers.get("Sec-WebSocket-Accept") != expected:
        writer.close()
        raise HandshakeError(f"handshake failed: {resp.status} {resp.body[:200]!r}")
    return WebSocket(reader, writer, is_client=True, leftover=parser.take_buffer())


def websocket_route(
    on_connect: Callable[[WebSocket, Request], Awaitable[None]],
    *,
    heartbeat: tuple[float, float] | None = None,
    subprotocols: tuple[str, ...] = (),
    max_message: int = 4 * 1024 * 1024,
) -> Callable[[Request], Awaitable[Response]]:
    """把 ``on_connect(ws, request)`` 包装成 HTTP 处理器：校验握手后返回 101 并接管连接。

    ``subprotocols``：服务端支持的子协议，从客户端 Sec-WebSocket-Protocol 中选第一个匹配的回显（§4.2.2）。
    ``max_message``：单条消息上限，超出以 1009 关闭（§7.4.1）。
    """

    async def handler(req: Request) -> Response:
        offered = req.headers.tokens("Sec-WebSocket-Protocol")
        chosen = next((p for p in subprotocols if p in offered), None)
        resp = handshake_response(req, chosen)
        if resp.status != 101:
            return resp

        async def takeover(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter, leftover: bytes
        ) -> None:
            ws = WebSocket(
                reader, writer, is_client=False, leftover=leftover, max_message=max_message
            )
            if heartbeat:
                ws.start_heartbeat(*heartbeat)
            try:
                await on_connect(ws, req)
            except ConnectionClosed:
                pass
            finally:
                if not ws.closed:
                    await ws.close(CloseCode.GOING_AWAY)
                await ws._shutdown()

        resp.upgrade = takeover
        return resp

    return handler
