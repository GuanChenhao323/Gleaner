"""One checked IP per request; original Host/SNI; no hidden redirects or retries."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import ssl
import zlib
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx  # noqa: TID251 — user-approved exception, scoped to this transport only.

from ..collector.fetcher import RobotsRules, parse_retry_after, parse_robots
from ..net.egress import is_public
from .auth import AuthManager
from .models import AuthLease, Clock, FetchPlan, MonitorError, SafeResponse, SitePolicy

Resolver = Callable[[str, int], Awaitable[list[str]]]


async def resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(x[4][0]) for x in infos))


class HTTPXTransport:
    def __init__(
        self,
        policy: SitePolicy,
        auth: AuthManager,
        *,
        clock: Clock | None = None,
        resolver: Resolver = resolve,
        engine: httpx.AsyncBaseTransport | None = None,
        verify: ssl.SSLContext | bool = True,
        get_not_before: Callable[[], float] = lambda: 0,
        set_not_before: Callable[[float], None] = lambda _: None,
        event: Callable[[dict], None] = lambda _: None,
        max_wire: int = 4 * 1024 * 1024,
        max_decoded: int = 8 * 1024 * 1024,
        total_timeout: float = 30,
        connect_timeout: float = 10,
    ) -> None:
        if verify is False:
            raise ValueError("TLS verification is required")
        self.policy, self.auth, self.clock = policy, auth, clock or Clock()
        self.resolver, self.get_not_before, self.set_not_before, self.event = (
            resolver,
            get_not_before,
            set_not_before,
            event,
        )
        self.max_wire, self.max_decoded = max_wire, max_decoded
        self.total_timeout, self.connect_timeout = total_timeout, connect_timeout
        self._lock, self._global = asyncio.Lock(), asyncio.Semaphore(4)
        self._next_start = 0.0
        self._robots: tuple[float, RobotsRules] | None = None
        # httpx logs full request URLs at INFO; this component emits a fixed, redacted event instead.
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
        self._client = httpx.AsyncClient(
            transport=engine
            or httpx.AsyncHTTPTransport(
                verify=verify,
                retries=0,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=0),
                trust_env=False,
            ),
            timeout=httpx.Timeout(30, connect=connect_timeout),
            trust_env=False,
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _ip(self, url: str) -> tuple[str, str]:
        p = urlsplit(url)
        async with asyncio.timeout(self.connect_timeout):
            addresses = await self.resolver(
                p.hostname or "", p.port or (443 if p.scheme == "https" else 80)
            )
        if not addresses:
            raise MonitorError("dns", retryable=True)
        allowed_local = self.policy.local_test and self.policy.host in (
            "127.0.0.1",
            "::1",
            "localhost",
        )
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError:
                raise MonitorError("blocked") from None
            if not (parsed.is_loopback if allowed_local else is_public(address)):
                raise MonitorError("blocked")
        ip = addresses[0]
        authority = f"[{ip}]" if ":" in ip else ip
        if p.port:
            authority += f":{p.port}"
        return urlunsplit((p.scheme, authority, p.path, p.query, "")), p.netloc

    async def _one(
        self, url: str, lease: AuthLease | None, *, kind: str
    ) -> tuple[int, dict[str, str], bytes]:
        self.policy.canonical(url)
        if kind == "content" and self._robots:
            p = urlsplit(url)
            if not self._robots[1].allowed(p.path + ("?" + p.query if p.query else "")):
                raise MonitorError("robots_denied")
        # A single policy/transport owns host pacing across robots, pages and redirects.
        async with self._global, self._lock:
            left = self.get_not_before() - self.clock.utc()
            if left > 0:
                raise MonitorError("rate_limited", retryable=True, retry_after_s=left)
            await self.clock.sleep(self._next_start - self.clock.mono())
            headers = {
                "Host": urlsplit(url).netloc,
                "User-Agent": "GleanerMonitor/1.0",
                "Accept-Encoding": "gzip, deflate",
                "Accept": "text/html, text/plain",
                "Connection": "close",
            }
            if lease is not None:
                headers["Cookie"] = self.auth.header(lease, url)
            crawl_delay = self._robots[1].crawl_delay if self._robots else 0
            self._next_start = self.clock.mono() + max(self.policy.host_gap_s, crawl_delay)
            started = self.clock.mono()
            async with asyncio.timeout(self.connect_timeout) as connecting:
                pinned, _ = await self._ip(url)

                async def trace(name: str, info: dict[str, Any]) -> None:
                    if name == "connection.start_tls.complete" or (
                        urlsplit(url).scheme == "http" and name == "connection.connect_tcp.complete"
                    ):
                        connecting.reschedule(None)

                request = httpx.Request(
                    "GET",
                    pinned,
                    headers=headers,
                    extensions={
                        "sni_hostname": self.policy.host,
                        "trace": trace,
                        "timeout": {
                            "connect": self.connect_timeout,
                            "read": 30,
                            "write": 10,
                            "pool": 10,
                        },
                    },
                )
                response = await self._client.send(request, stream=True, follow_redirects=False)
            wire = 0
            chunks: list[bytes] = []
            decoded = 0
            try:
                encoding = response.headers.get("content-encoding", "").lower().strip()
                if encoding not in ("", "identity", "gzip", "deflate"):
                    raise MonitorError("unsupported_encoding")
                decoder = (
                    zlib.decompressobj(31 if encoding == "gzip" else zlib.MAX_WBITS)
                    if encoding in ("gzip", "deflate")
                    else None
                )
                async for chunk in response.aiter_raw():
                    wire += len(chunk)
                    if wire > self.max_wire:
                        raise MonitorError("response_too_large")
                    piece = (
                        decoder.decompress(chunk, self.max_decoded - decoded + 1)
                        if decoder
                        else chunk
                    )
                    decoded += len(piece)
                    if decoded > self.max_decoded or (decoder and decoder.unconsumed_tail):
                        raise MonitorError("response_too_large")
                    chunks.append(piece)
                if decoder and (not decoder.eof or decoder.unused_data):
                    raise MonitorError("bad_encoding")
                if lease is not None:
                    self.auth.update_cookies(lease, response.headers.get_list("set-cookie"), url)
                selected = {
                    key: response.headers[key]
                    for key in ("content-type", "location", "retry-after")
                    if key in response.headers
                }
                status = response.status_code
                self.event(
                    {
                        "kind": kind,
                        "path": urlsplit(url).path,
                        "status": status,
                        "wire_bytes": wire,
                        "decoded_bytes": decoded,
                        "started_mono": started,
                        "finished_mono": self.clock.mono(),
                        "utc": self.clock.utc(),
                    }
                )
                if status in (429, 503):
                    delay = parse_retry_after(selected.get("retry-after"), self.clock.utc())
                    if delay is not None:
                        self.set_not_before(max(self.get_not_before(), self.clock.utc() + delay))
                        raise MonitorError("rate_limited", retryable=True, retry_after_s=delay)
                if status >= 500:
                    raise MonitorError("upstream_5xx", retryable=True)
                return status, selected, b"".join(chunks)
            finally:
                await response.aclose()
                # Do not let HTTPX retain a second, unscoped credential store.
                self._client.cookies.clear()

    async def _chain(
        self, url: str, lease: AuthLease | None, *, kind: str
    ) -> tuple[str, int, dict[str, str], bytes]:
        for hop in range(4):
            status, headers, body = await self._one(url, lease, kind=kind)
            if status not in (301, 302, 303, 307, 308):
                return url, status, headers, body
            location = headers.get("location")
            if not location or hop == 3:
                raise MonitorError("redirect_limit")
            nxt = urljoin(url, location)
            p = urlsplit(nxt)
            if p.hostname == "login.must.edu.mo" or p.path.startswith("/login/"):
                raise MonitorError("auth_required")
            self.policy.canonical(nxt)
            url = nxt
        raise MonitorError("redirect_limit")

    async def fetch(self, plan: FetchPlan, auth: AuthLease | None) -> SafeResponse:
        url = self.policy.canonical(plan.canonical_url, target=True)
        if plan.method != "GET" or plan.validators:
            raise MonitorError("unsupported")
        try:
            async with asyncio.timeout(self.total_timeout):
                if self._robots is None or self._robots[0] <= self.clock.mono():
                    _, status, _, body = await self._chain(
                        self.policy.origin + "/robots.txt", None, kind="robots"
                    )
                    if status == 200:
                        rules = parse_robots(body.decode("utf-8", "replace"), "gleanermonitor")
                    elif 400 <= status < 500:
                        rules = RobotsRules()
                    else:
                        raise MonitorError("robots_unavailable", retryable=True)
                    self._robots = (self.clock.mono() + 3600, rules)
                rules = self._robots[1]
                path = urlsplit(url).path + (
                    "?" + urlsplit(url).query if urlsplit(url).query else ""
                )
                if not rules.allowed(path):
                    raise MonitorError("robots_denied")
                final, status, headers, body = await self._chain(url, auth, kind="content")
                if status == 304:
                    raise MonitorError("missing_baseline")
                if status == 404:
                    raise MonitorError("target_missing")
                return SafeResponse(status, final, headers.get("content-type", ""), body)
        except MonitorError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise MonitorError("timeout", retryable=True) from None
        except (ssl.SSLError, zlib.error):
            raise MonitorError("tls_or_encoding") from None
        except httpx.ConnectError as exc:
            # Inspect exception types/causes internally, never expose raw URL/header text.
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                raise MonitorError("tls") from None
            raise MonitorError("network", retryable=True) from None
        except (OSError, httpx.HTTPError):
            raise MonitorError("network", retryable=True) from None
