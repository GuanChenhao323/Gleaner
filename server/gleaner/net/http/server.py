"""自研 HTTP/1.1 服务端（asyncio streams，Linux 上底层是 epoll）。

特性：keep-alive 与空闲超时、请求头大小限制、Content-Length / chunked 请求体、
chunked 流式响应、gzip 压缩、协议升级（WebSocket）、SO_REUSEPORT 多进程。
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import re
import socket
import ssl
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .message import Headers, Request, Response, http_date
from .parser import HTTPParser, ParseError

log = logging.getLogger(__name__)

Handler = Callable[[Request], Awaitable[Response]]
Middleware = Callable[[Request, Handler], Awaitable[Response]]
# 升级回调：拿到原始 reader/writer 与解析器剩余字节后接管连接
UpgradeHandler = Callable[[asyncio.StreamReader, asyncio.StreamWriter, bytes], Awaitable[None]]

_COMPRESSIBLE = (
    "text/",
    "application/json",
    "application/javascript",
    "image/svg+xml",
    "application/xml",
    "application/wasm",
)


@dataclass
class _Route:
    method: str
    pattern: re.Pattern[str]
    handler: Handler


class Router:
    """按方法与路径模板路由，``/api/items/{id}`` 中的参数写入 ``request.params``。"""

    def __init__(self) -> None:
        self._routes: list[_Route] = []
        self._prefixes: list[tuple[str, Handler]] = []

    def add(self, method: str, path: str, handler: Handler) -> None:
        regex = "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path) + "$"
        self._routes.append(_Route(method.upper(), re.compile(regex), handler))

    def route(self, method: str, path: str) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            for m in method.split(","):
                self.add(m.strip(), path, fn)
            return fn

        return deco

    def mount(self, prefix: str, handler: Handler) -> None:
        """前缀挂载，常用于静态文件或反向代理。"""
        self._prefixes.append((prefix, handler))

    async def __call__(self, req: Request) -> Response:
        path = req.path
        allowed: set[str] = set()
        for r in self._routes:
            m = r.pattern.match(path)
            if not m:
                continue
            if r.method != req.method and not (r.method == "GET" and req.method == "HEAD"):
                allowed.add(r.method)
                continue
            req.params = m.groupdict()
            return await r.handler(req)
        for prefix, handler in self._prefixes:
            if path.startswith(prefix):
                return await handler(req)
        if allowed:
            resp = Response.error(405, "method not allowed")
            resp.headers["Allow"] = ", ".join(sorted(allowed))
            return resp
        return Response.error(404, f"no route for {path}")


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    keepalive_timeout: float = 15.0
    header_timeout: float = 10.0
    max_header_bytes: int = 64 * 1024
    max_body_bytes: int = 32 * 1024 * 1024
    max_requests_per_conn: int = 1000
    gzip_min_bytes: int = 1024
    reuse_port: bool = False
    ssl_context: ssl.SSLContext | None = None
    server_name: str = "Gleaner/0.1"


@dataclass
class ServerStats:
    connections_total: int = 0
    connections_active: int = 0
    requests_total: int = 0
    responses_by_status: dict[int, int] = field(default_factory=dict)
    request_seconds_sum: float = 0.0


class HTTPServer:
    def __init__(
        self,
        handler: Handler,
        config: ServerConfig | None = None,
        middlewares: list[Middleware] | None = None,
    ) -> None:
        self.config = config or ServerConfig()
        self.stats = ServerStats()
        self._handler = handler
        self._middlewares = middlewares or []
        self._server: asyncio.base_events.Server | None = None
        self._conns: set[asyncio.Task[None]] = set()

    @property
    def port(self) -> int:
        assert self._server is not None
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        cfg = self.config
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if cfg.reuse_port and hasattr(socket, "SO_REUSEPORT"):
            # 多进程共享同一端口，由内核做连接分发，绕开 GIL
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind((cfg.host, cfg.port))
        sock.listen(1024)
        sock.setblocking(False)
        self._server = await asyncio.start_server(
            self._on_conn, sock=sock, ssl=cfg.ssl_context, limit=2**20
        )

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._server:
            self._server.close()
            for t in list(self._conns):
                t.cancel()
            await asyncio.gather(*self._conns, return_exceptions=True)
            await self._server.wait_closed()

    async def _dispatch(self, req: Request) -> Response:
        handler: Handler = self._handler
        for mw in reversed(self._middlewares):
            handler = _bind(mw, handler)
        return await handler(req)

    async def _on_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._conns.add(task)
        self.stats.connections_total += 1
        self.stats.connections_active += 1
        sock = writer.get_extra_info("socket")
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
        peer = writer.get_extra_info("peername")
        try:
            await self._serve_conn(reader, writer, peer)
        except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError):
            pass
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("connection handler crashed")
        finally:
            self.stats.connections_active -= 1
            self._conns.discard(task)
            if not writer.is_closing():
                writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1.0)
            except (Exception, asyncio.CancelledError):
                pass

    async def _serve_conn(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer: tuple[str, int] | None,
    ) -> None:
        cfg = self.config
        parser = HTTPParser(
            "request", max_header_bytes=cfg.max_header_bytes, max_body_bytes=cfg.max_body_bytes
        )
        served = 0
        pending: list[Request] = []
        while served < cfg.max_requests_per_conn:
            if not pending:
                # 空闲时用 keep-alive 超时，读到半条消息后用头部超时（防 slowloris）
                timeout = cfg.keepalive_timeout if parser.idle else cfg.header_timeout
                try:
                    data = await asyncio.wait_for(reader.read(65536), timeout)
                except TimeoutError:
                    if not parser.idle:
                        await self._write_simple(writer, Response.error(408, "request timeout"))
                    return
                if not data:
                    return
                try:
                    pending.extend(m for m in parser.feed(data) if isinstance(m, Request))
                except ParseError as e:
                    await self._write_simple(writer, Response.error(e.status, str(e)))
                    return
                continue
            req = pending.pop(0)
            req.peer = peer
            served += 1
            t0 = time.perf_counter()
            if req.headers.get("Expect", "").lower() == "100-continue":
                pass  # 解析器已缓冲完整请求体时才会到这里，无需再发 100
            try:
                resp = await self._dispatch(req)
            except Exception:
                log.exception("handler error for %s %s", req.method, req.target)
                resp = Response.error(500, "internal error")
            keep = req.keep_alive and resp.keep_alive and served < cfg.max_requests_per_conn
            if resp.upgrade is not None and resp.status == 101:
                writer.write(resp.encode_head())
                await writer.drain()
                self._count(resp.status, t0)
                await resp.upgrade(reader, writer, parser.take_buffer())
                return
            await self._write_response(writer, req, resp, keep)
            self._count(resp.status, t0)
            if not keep:
                return

    def _count(self, status: int, t0: float) -> None:
        s = self.stats
        s.requests_total += 1
        s.responses_by_status[status] = s.responses_by_status.get(status, 0) + 1
        s.request_seconds_sum += time.perf_counter() - t0

    async def _write_simple(self, writer: asyncio.StreamWriter, resp: Response) -> None:
        resp.headers["Connection"] = "close"
        resp.headers["Content-Length"] = str(len(resp.body))
        writer.write(resp.encode_head() + resp.body)
        try:
            await writer.drain()
        except ConnectionError:
            pass

    async def _write_response(
        self, writer: asyncio.StreamWriter, req: Request, resp: Response, keep: bool
    ) -> None:
        h = resp.headers
        h.setdefault("Date", http_date())
        h.setdefault("Server", self.config.server_name)
        h["Connection"] = "keep-alive" if keep else "close"
        if keep and req.version == "HTTP/1.0":
            h["Keep-Alive"] = f"timeout={int(self.config.keepalive_timeout)}"
        no_body = req.method == "HEAD" or resp.status in (204, 304) or resp.status < 200
        if resp.stream is not None and not no_body:
            if req.version == "HTTP/1.0":
                chunks = [c async for c in resp.stream]
                resp.body, resp.stream = b"".join(chunks), None
            else:
                await self._write_chunked(writer, resp)
                return
        body = resp.body
        if not no_body and self._should_gzip(req, resp):
            body = gzip.compress(body, compresslevel=5)
            h["Content-Encoding"] = "gzip"
            h.add("Vary", "Accept-Encoding")
        if resp.status not in (204, 304) and resp.status >= 200:
            h["Content-Length"] = str(len(body))
        writer.write(resp.encode_head() + (b"" if no_body else body))
        await writer.drain()

    async def _write_chunked(self, writer: asyncio.StreamWriter, resp: Response) -> None:
        """chunked 传输编码（RFC 9112 §7.1）：每块 ``size CRLF data CRLF``，以 0 块结束。"""
        resp.headers.remove("Content-Length")
        resp.headers["Transfer-Encoding"] = "chunked"
        writer.write(resp.encode_head())
        assert resp.stream is not None
        async for chunk in resp.stream:
            if chunk:
                writer.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                await writer.drain()
        writer.write(b"0\r\n\r\n")
        await writer.drain()

    def _should_gzip(self, req: Request, resp: Response) -> bool:
        if "Content-Encoding" in resp.headers or len(resp.body) < self.config.gzip_min_bytes:
            return False
        if "gzip" not in req.headers.tokens("Accept-Encoding"):
            return False
        ctype = resp.headers.get("Content-Type", "")
        return ctype.startswith(_COMPRESSIBLE)


def _bind(mw: Middleware, nxt: Handler) -> Handler:
    async def h(req: Request) -> Response:
        return await mw(req, nxt)

    return h


def make_headers(**kv: str) -> Headers:
    return Headers({k.replace("_", "-"): v for k, v in kv.items()})
