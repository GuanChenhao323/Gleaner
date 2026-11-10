"""自研异步 HTTP/1.1 客户端。

- 按 (scheme, host, port) 复用 keep-alive 连接；每主机并发上限 + 全局并发上限
- 连接超时与读取超时分开设置
- chunked / Content-Length / 读到关闭 三种响应体
- gzip 解压、Cookie Jar、重定向、条件请求由调用方传头部
- 可注入自研 DNS 解析器
"""

from __future__ import annotations

import asyncio
import gzip
import ipaddress
import ssl
import time
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from ..egress import EgressDenied, checked_addresses
from .cookies import CookieJar
from .message import Headers, Request, Response
from .parser import HTTPParser, ParseError

Resolver = Callable[[str], Awaitable[str]]

DEFAULT_UA = "GleanerBot/0.1 (+https://github.com/gleaner-campus; course project)"


class HTTPError(Exception):
    """网络层失败：连接、超时、协议错误。``kind`` 用于来源状态的错误分类。"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind  # connect / timeout / protocol / tls / dns


@dataclass
class ClientStats:
    connections_opened: int = 0
    connections_reused: int = 0
    requests: int = 0
    bytes_received: int = 0


@dataclass
class _Conn:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    parser: HTTPParser
    last_used: float = field(default_factory=time.monotonic)

    def close(self) -> None:
        if not self.writer.is_closing():
            self.writer.close()


@dataclass
class ClientResponse(Response):
    url: str = ""
    elapsed: float = 0.0
    history: list[str] = field(default_factory=list)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class HTTPClient:
    def __init__(
        self,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        per_host_limit: int = 4,
        total_limit: int = 100,
        idle_timeout: float = 30.0,
        keep_alive: bool = True,
        resolver: Resolver | None = None,
        ssl_context: ssl.SSLContext | None = None,
        user_agent: str = DEFAULT_UA,
        egress_guard: bool = False,
    ) -> None:
        # egress_guard：只允许连接公网地址（访问用户填写的网址时打开，防 SSRF，见 net/egress.py）
        self.egress_guard = egress_guard
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.per_host_limit = per_host_limit
        self.idle_timeout = idle_timeout
        self.keep_alive = keep_alive
        self.resolver = resolver
        self.ssl_context = ssl_context or ssl.create_default_context()
        self.user_agent = user_agent
        self.stats = ClientStats()
        self._idle: dict[tuple[str, str, int], list[_Conn]] = {}
        self._host_sem: dict[tuple[str, str, int], asyncio.Semaphore] = {}
        self._total_sem = asyncio.Semaphore(total_limit)

    async def close(self) -> None:
        for conns in self._idle.values():
            for c in conns:
                c.close()
        self._idle.clear()

    async def __aenter__(self) -> HTTPClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # -- 便捷方法 ----------------------------------------------------------------

    async def get(self, url: str, **kw: object) -> ClientResponse:
        return await self.request("GET", url, **kw)  # type: ignore[arg-type]

    async def post(self, url: str, **kw: object) -> ClientResponse:
        return await self.request("POST", url, **kw)  # type: ignore[arg-type]

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | Headers | None = None,
        body: bytes = b"",
        json_body: object = None,
        cookies: CookieJar | None = None,
        follow_redirects: bool = True,
        max_redirects: int = 5,
        timeout: float | None = None,
    ) -> ClientResponse:
        import json as _json

        if json_body is not None:
            body = _json.dumps(json_body, ensure_ascii=False).encode()
            headers = Headers(headers.items() if isinstance(headers, Headers) else (headers or {}))
            headers.setdefault("Content-Type", "application/json")
        history: list[str] = []
        t0 = time.perf_counter()
        while True:
            resp = await self._request_once(method, url, headers, body, cookies, timeout)
            if (
                follow_redirects
                and resp.status in (301, 302, 303, 307, 308)
                and "Location" in resp.headers
            ):
                if len(history) >= max_redirects:
                    raise HTTPError("protocol", "too many redirects")
                history.append(url)
                new_url = urljoin(url, resp.headers["Location"])
                if _origin(new_url) != _origin(url) and headers:
                    # 跳到别的源：不把调用方显式给的凭证带过去（RFC 9110 §15.4 安全考虑）
                    headers = _without_credentials(headers)
                url = new_url
                if resp.status == 303 or (resp.status in (301, 302) and method == "POST"):
                    method, body = "GET", b""
                continue
            resp.url = url
            resp.history = history
            resp.elapsed = time.perf_counter() - t0
            return resp

    # -- 实现 --------------------------------------------------------------------

    async def _request_once(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | Headers | None,
        body: bytes,
        cookies: CookieJar | None,
        timeout: float | None,
    ) -> ClientResponse:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https") or not parts.hostname:
            raise HTTPError("protocol", f"unsupported url {url}")
        host = parts.hostname
        port = parts.port or (443 if scheme == "https" else 80)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        h = Headers(headers.items() if isinstance(headers, Headers) else (headers or {}))
        default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
        h.setdefault("Host", host if default_port else f"{host}:{port}")
        h.setdefault("User-Agent", self.user_agent)
        h.setdefault("Accept-Encoding", "gzip")
        h.setdefault("Accept", "*/*")
        if not self.keep_alive:
            h["Connection"] = "close"
        if body or method in ("POST", "PUT", "PATCH"):
            h["Content-Length"] = str(len(body))
        if cookies is not None:
            ch = cookies.header_for(host, parts.path or "/", scheme == "https")
            if ch:
                h["Cookie"] = ch
        req = Request(method=method.upper(), target=target, headers=h, body=body)
        key = (scheme, host, port)
        sem = self._host_sem.setdefault(key, asyncio.Semaphore(self.per_host_limit))
        rt = timeout or self.read_timeout
        async with self._total_sem, sem:
            for attempt in range(2):
                conn, reused = await self._acquire(key)
                try:
                    resp = await self._roundtrip(conn, req, rt)
                except HTTPError as e:
                    conn.close()
                    # 复用的空闲连接可能已被服务器关闭：幂等请求换新连接重试一次
                    if (
                        reused
                        and attempt == 0
                        and e.kind == "stale"
                        and req.method in ("GET", "HEAD", "PUT", "DELETE", "OPTIONS")
                    ):
                        continue
                    if e.kind == "stale":
                        raise HTTPError("protocol", "connection closed before response") from e
                    raise
                except BaseException:
                    conn.close()
                    raise
                self.stats.requests += 1
                if self.keep_alive and resp.keep_alive and req.keep_alive and conn.parser.idle:
                    conn.last_used = time.monotonic()
                    self._idle.setdefault(key, []).append(conn)
                else:
                    conn.close()
                break
        if cookies is not None:
            for sc in resp.headers.get_all("Set-Cookie"):
                cookies.set_from_header(sc, host, parts.path or "/", scheme == "https")
        enc = resp.headers.get("Content-Encoding", "").lower()
        if enc in ("gzip", "x-gzip") and resp.body:
            try:
                resp.body = gzip.decompress(resp.body)
            except (OSError, EOFError, zlib.error) as e:
                raise HTTPError("protocol", "bad gzip body") from e
        elif enc == "deflate" and resp.body:
            resp.body = zlib.decompress(resp.body)
        return resp

    async def _acquire(self, key: tuple[str, str, int]) -> tuple[_Conn, bool]:
        pool = self._idle.get(key, [])
        now = time.monotonic()
        while pool:
            c = pool.pop()
            if (
                now - c.last_used < self.idle_timeout
                and not c.writer.is_closing()
                and not c.reader.at_eof()
            ):
                self.stats.connections_reused += 1
                return c, True
            c.close()
        scheme, host, port = key
        addrs = [host]
        if self.egress_guard:
            try:
                addrs = await checked_addresses(host, port, self.resolver)
            except EgressDenied as e:
                raise HTTPError("blocked", str(e)) from e
            except OSError as e:
                raise HTTPError("dns", f"{host}: {e}") from e
        elif self.resolver is not None and not _is_ip(host) and host != "localhost":
            try:
                addrs = [await self.resolver(host)]
            except Exception as e:
                raise HTTPError("dns", f"{host}: {e}") from e
        # 解析出多个地址时依次尝试（例如 localhost 的 ::1 拒绝连接时退到 127.0.0.1）；
        # TLS 错误不是地址问题，直接报错，不换地址重试
        err: HTTPError | None = None
        for addr in addrs:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        addr,
                        port,
                        ssl=self.ssl_context if scheme == "https" else None,
                        server_hostname=host if scheme == "https" else None,
                        limit=2**20,
                    ),
                    self.connect_timeout,
                )
            except TimeoutError:
                err = HTTPError("timeout", f"connect {host}:{port}")
                continue
            except ssl.SSLError as e:
                raise HTTPError("tls", str(e)) from e
            except OSError as e:
                err = HTTPError("connect", f"{host}:{port} {e}")
                continue
            self.stats.connections_opened += 1
            return _Conn(reader, writer, HTTPParser("response")), False
        assert err is not None
        raise err

    async def _roundtrip(self, conn: _Conn, req: Request, read_timeout: float) -> ClientResponse:
        conn.parser.expect_response(req.method)
        try:
            conn.writer.write(req.encode_head() + req.body)
            await conn.writer.drain()
        except (ConnectionError, OSError) as e:
            raise HTTPError("stale", str(e)) from e
        got_any = False
        while True:
            try:
                data = await asyncio.wait_for(conn.reader.read(65536), read_timeout)
            except TimeoutError as e:
                raise HTTPError("timeout", "read timeout") from e
            except (ConnectionError, OSError) as e:
                raise HTTPError("stale" if not got_any else "connect", str(e)) from e
            try:
                if not data:
                    if not got_any:
                        raise HTTPError("stale", "closed by peer")
                    msgs = conn.parser.feed_eof()
                else:
                    got_any = True
                    self.stats.bytes_received += len(data)
                    msgs = conn.parser.feed(data)
            except ParseError as e:
                raise HTTPError("protocol", str(e)) from e
            for m in msgs:
                assert isinstance(m, Response)
                if 100 <= m.status < 200 and m.status != 101:
                    conn.parser.expect_response(req.method)
                    continue  # 跳过 1xx 中间响应
                return ClientResponse(
                    status=m.status,
                    headers=m.headers,
                    body=m.body,
                    version=m.version,
                    reason=m.reason,
                )
            if not data:
                raise HTTPError("protocol", "incomplete response")


_CREDENTIAL_HEADERS = ("authorization", "proxy-authorization", "cookie")


def _origin(url: str) -> tuple[str, str, int | None]:
    p = urlsplit(url)
    scheme = p.scheme.lower()
    return scheme, (p.hostname or "").lower(), p.port or (443 if scheme == "https" else 80)


def _without_credentials(headers: dict[str, str] | Headers) -> Headers:
    return Headers((k, v) for k, v in headers.items() if k.lower() not in _CREDENTIAL_HEADERS)
