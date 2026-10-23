"""基于手写反应器的 WebSocket 服务端。

socket 读写、HTTP 升级握手、帧编解码、ping/pong、心跳判死、写缓冲都在反应器线程里完成；
业务逻辑在 asyncio 线程里：连接建立、收到文本消息、连接关闭三类事件经
``loop.call_soon_threadsafe`` 投递过去，业务侧发送则经 ``reactor.call_soon_threadsafe`` 投递回来。

    非 WebSocket 请求（/health、/metrics）由同步的 ``http_handler`` 在反应器线程里应答后关闭连接。
"""

from __future__ import annotations

import asyncio
import errno
import logging
import selectors
import socket
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..http.message import Request, Response, http_date
from ..http.parser import HTTPParser, ParseError
from ..reactor import Reactor
from .protocol import (
    CloseCode,
    Closed,
    Message,
    Opcode,
    WSConnection,
    encode_frame,
    handshake_response,
)

log = logging.getLogger(__name__)

READ = selectors.EVENT_READ
WRITE = selectors.EVENT_WRITE


class ReactorPeer:
    """业务侧看到的连接句柄：发送是非阻塞的（入队后由反应器线程写出）。"""

    def __init__(self, server: ReactorWSServer, conn: _Conn) -> None:
        self._server = server
        self._conn = conn
        self.peer = conn.addr
        self.inbox: asyncio.Queue[str | None] | None = None
        self._pending = 0  # 已入队但还没交给反应器的字节数
        self._lock = threading.Lock()

    @property
    def buffered(self) -> int:
        return self._pending + len(self._conn.out)

    @property
    def closed(self) -> bool:
        return self._conn.closed

    def send_text(self, text: str) -> None:
        frame = encode_frame(Opcode.TEXT, text.encode("utf-8"))  # 服务端帧不掩码（§5.1）
        with self._lock:
            self._pending += len(frame)

        def write() -> None:
            with self._lock:
                self._pending -= len(frame)
            self._conn.write(frame)

        self._server.reactor.call_soon_threadsafe(write)

    def close(self, code: int = CloseCode.NORMAL, reason: str = "") -> None:
        self._server.reactor.call_soon_threadsafe(lambda: self._conn.close_ws(code, reason))

    def abort(self) -> None:
        self._server.reactor.call_soon_threadsafe(self._conn.abort)


class _Conn:
    def __init__(self, server: ReactorWSServer, sock: socket.socket, addr: tuple[str, int]) -> None:
        self.server = server
        self.sock = sock
        self.addr = addr
        self.parser = HTTPParser("request", max_header_bytes=16 * 1024, max_body_bytes=64 * 1024)
        self.ws: WSConnection | None = None
        self.peer: ReactorPeer | None = None
        self.out = bytearray()
        self.writing = False
        self.closed = False
        self.close_after_flush = False
        self.accepted_at = time.monotonic()
        self.last_rx = time.monotonic()
        self.last_ping = time.monotonic()

    # -- 读 ----------------------------------------------------------------------

    def on_event(self, sock: Any, mask: int) -> None:
        if mask & WRITE:
            self.flush()
        if mask & READ and not self.closed:
            self.on_readable()

    def on_readable(self) -> None:
        try:
            data = self.sock.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self.abort()
            return
        if not data:
            self.abort()
            return
        self.last_rx = time.monotonic()
        self.server.bytes_in += len(data)
        if self.ws is None:
            self.on_http(data)
        else:
            self.on_ws(data)

    def on_http(self, data: bytes) -> None:
        try:
            msgs = self.parser.feed(data)
        except ParseError as e:
            self.respond(Response.error(e.status, str(e)))
            return
        for req in msgs:
            assert isinstance(req, Request)
            req.peer = self.addr
            if req.path == self.server.path and "websocket" in req.headers.tokens("Upgrade"):
                self.upgrade(req)
                return
            self.respond(self.server.http(req))
            return

    def upgrade(self, req: Request) -> None:
        offered = req.headers.tokens("Sec-WebSocket-Protocol")
        chosen = next((p for p in self.server.subprotocols if p in offered), None)
        resp = handshake_response(req, chosen)
        if resp.status != 101:
            self.respond(resp)
            return
        self.write(resp.encode_head())
        self.ws = WSConnection(is_client=False, max_message=self.server.max_message)
        self.peer = ReactorPeer(self.server, self)
        self.server.opened(self.peer, req)
        leftover = self.parser.take_buffer()
        if leftover:
            self.on_ws(leftover)

    def on_ws(self, data: bytes) -> None:
        assert self.ws is not None and self.peer is not None
        events, reply = self.ws.receive_data(data)
        if reply:
            self.write(reply)  # pong、close 回应由状态机自动生成
        for ev in events:
            if isinstance(ev, Closed):
                self.close_after_flush = True
                self.flush()
                return
            if isinstance(ev, Message) and ev.opcode == Opcode.TEXT:
                self.server.message(self.peer, ev.data.decode("utf-8"))

    def respond(self, resp: Response) -> None:
        resp.headers.setdefault("Date", http_date())
        resp.headers["Connection"] = "close"
        resp.headers["Content-Length"] = str(len(resp.body))
        self.write(resp.encode_head() + resp.body)
        self.close_after_flush = True
        self.flush()

    # -- 写 ----------------------------------------------------------------------

    def write(self, data: bytes) -> None:
        if self.closed:
            return
        self.out += data
        self.flush()

    def flush(self) -> None:
        while self.out and not self.closed:
            try:
                n = self.sock.send(self.out)
            except (BlockingIOError, InterruptedError):
                break
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    break
                self.abort()
                return
            self.server.bytes_out += n
            del self.out[:n]
        if self.closed:
            return
        want = bool(self.out)
        if want != self.writing:
            # 只在有待写数据时关注可写事件，避免 epoll 水平触发空转
            self.writing = want
            self.server.reactor.modify(self.sock, READ | WRITE if want else READ, self.on_event)
        if not self.out and self.close_after_flush:
            self.abort()

    # -- 关闭 --------------------------------------------------------------------

    def close_ws(self, code: int, reason: str) -> None:
        if self.ws is None or self.closed:
            return
        self.write(self.ws.send_close(code, reason))
        self.close_after_flush = True
        self.flush()

    def abort(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.server.reactor.unregister(self.sock)
        try:
            self.sock.close()
        except OSError:
            pass
        self.server.conns.discard(self)
        if self.peer is not None:
            self.server.closed(self.peer)


class ReactorWSServer:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        on_open: Callable[[ReactorPeer, Request], Awaitable[None]],
        http_handler: Callable[[Request], Response] | None = None,
        path: str = "/ws",
        subprotocols: tuple[str, ...] = (),
        selector: str = "auto",
        heartbeat: tuple[float, float] = (25.0, 60.0),
        handshake_timeout: float = 10.0,
        max_message: int = 4 * 1024 * 1024,
    ) -> None:
        self.host = host
        self.max_message = max_message  # 超出以 1009 关闭（RFC 6455 §7.4.1）
        self.port = port
        self.path = path
        self.subprotocols = subprotocols
        self.on_open = on_open
        self.http_handler = http_handler
        self.heartbeat = heartbeat
        self.handshake_timeout = handshake_timeout
        self._tick_period = min(1.0, heartbeat[0] / 2)
        self.reactor = Reactor(selector)
        self.conns: set[_Conn] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.listener: socket.socket | None = None
        self.accepted = 0
        self.bytes_in = 0
        self.bytes_out = 0

    @property
    def selector_name(self) -> str:
        return self.reactor.kind

    async def start(self) -> int:
        self.loop = asyncio.get_running_loop()
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind((self.host, self.port))
        ls.listen(4096)
        ls.setblocking(False)
        self.listener = ls
        self.port = ls.getsockname()[1]
        self.reactor.register(ls, READ, self._on_accept)
        self.reactor.call_later(self._tick_period, self._tick)
        self.reactor.start_thread(f"ws-reactor-{self.port}")
        return self.port

    async def close(self) -> None:
        def shutdown() -> None:
            for c in list(self.conns):
                c.abort()
            if self.listener:
                self.reactor.unregister(self.listener)
                self.listener.close()

        self.reactor.call_soon_threadsafe(shutdown)
        await asyncio.to_thread(self.reactor.stop)

    # -- 反应器线程 ----------------------------------------------------------------

    def _on_accept(self, sock: Any, mask: int) -> None:
        assert self.listener is not None
        for _ in range(64):  # 一次事件里尽量多接受几个连接
            try:
                cs, addr = self.listener.accept()
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            cs.setblocking(False)
            cs.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn = _Conn(self, cs, addr)
            self.conns.add(conn)
            self.accepted += 1
            self.reactor.register(cs, READ, conn.on_event)

    def _tick(self) -> None:
        """定期巡检（默认每秒）：握手超时、心跳 ping、超时无数据判死。"""
        now = time.monotonic()
        interval, timeout = self.heartbeat
        for c in list(self.conns):
            if c.ws is None:
                if now - c.accepted_at > self.handshake_timeout:
                    c.abort()
                continue
            if now - c.last_rx > timeout:
                c.abort()
            elif now - c.last_ping >= interval:
                c.last_ping = now
                c.write(encode_frame(Opcode.PING, str(int(time.time())).encode()))
        self.reactor.call_later(self._tick_period, self._tick)

    def http(self, req: Request) -> Response:
        if self.http_handler is None:
            return Response.error(404)
        try:
            return self.http_handler(req)
        except Exception:
            log.exception("http handler failed")
            return Response.error(500)

    # -- 投递到 asyncio 线程 --------------------------------------------------------

    def opened(self, peer: ReactorPeer, req: Request) -> None:
        assert self.loop is not None

        def start() -> None:
            peer.inbox = asyncio.Queue()
            self.loop.create_task(self.on_open(peer, req))  # type: ignore[union-attr]

        self.loop.call_soon_threadsafe(start)

    def message(self, peer: ReactorPeer, text: str) -> None:
        assert self.loop is not None
        self.loop.call_soon_threadsafe(lambda: peer.inbox.put_nowait(text) if peer.inbox else None)

    def closed(self, peer: ReactorPeer) -> None:
        if self.loop is None or self.loop.is_closed():
            return
        self.loop.call_soon_threadsafe(lambda: peer.inbox.put_nowait(None) if peer.inbox else None)
