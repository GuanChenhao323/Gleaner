"""One checked IP per request; original Host/SNI; no hidden redirects or retries."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import socket
import ssl
import zlib
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import httpx  # noqa: TID251 — user-approved exception, scoped to this transport only.

from ..collector.fetcher import RobotsRules, parse_retry_after, parse_robots
from ..net.egress import is_public
from .auth import AuthManager
from .models import (
    AccessVerdict,
    AuthLease,
    Clock,
    FetchPlan,
    MonitorError,
    SafeResponse,
    SitePolicy,
)

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
        resolver: Resolver | None = None,
        engine: httpx.AsyncBaseTransport | None = None,
        verify: ssl.SSLContext | bool = True,
        get_not_before: Callable[[], float] = lambda: 0,
        set_not_before: Callable[[float], None] = lambda _: None,
        event: Callable[[dict], None] = lambda _: None,
        inspect_access: Callable[[SafeResponse], AccessVerdict] | None = None,
        registered_target_fallback: bool = False,
        policy_event: Callable[[dict], None] = lambda _: None,
        max_wire: int = 4 * 1024 * 1024,
        max_decoded: int = 8 * 1024 * 1024,
        total_timeout: float = 30,
        connect_timeout: float = 10,
    ) -> None:
        if verify is False:
            raise ValueError("TLS verification is required")
        self.policy, self.auth, self.clock = policy, auth, clock or Clock()
        self.resolver, self.get_not_before, self.set_not_before, self.event = (
            resolver or ProxyCompatibleDNS(policy.host, clock=self.clock),
            get_not_before,
            set_not_before,
            event,
        )
        self.max_wire, self.max_decoded = max_wire, max_decoded
        self.total_timeout, self.connect_timeout = total_timeout, connect_timeout
        self.inspect_access = inspect_access
        if registered_target_fallback and (
            policy.origin != "https://moodle.must.edu.mo"
            or len(policy.target_urls) != 1
            or inspect_access is None
        ):
            raise ValueError(
                "registered-target fallback requires one explicit MUST Moodle target and an authentication inspector"
            )
        self.registered_target_fallback, self.policy_event = (
            registered_target_fallback,
            policy_event,
        )
        self._lock, self._global = asyncio.Lock(), asyncio.Semaphore(4)
        self._next_start = 0.0
        self._robots: tuple[float, RobotsRules] | None = None
        self._robots_identity: tuple[str, int] | None = None
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
            if not (
                parsed.is_loopback if allowed_local else is_public(address) and parsed.is_global
            ):
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
            # Pacing belongs to the overall request budget, not the DNS/TCP/TLS budget.
            await self.clock.sleep(self._next_start - self.clock.mono())
            headers = {
                "Host": urlsplit(url).netloc,
                "User-Agent": "GleanerMonitor/1.0",
                "Accept-Encoding": "gzip, deflate",
                "Accept": "text/html, text/plain",
                "Connection": "close",
            }
            crawl_delay = self._robots[1].crawl_delay if self._robots else 0
            async with asyncio.timeout(self.connect_timeout) as connecting:
                pinned, _ = await self._ip(url)
                if lease is not None:
                    headers["Cookie"] = self.auth.header(lease, url)
                started = self.clock.mono()
                self._next_start = started + max(self.policy.host_gap_s, crawl_delay)

                async def trace(name: str, info: dict[str, Any]) -> None:
                    nonlocal started
                    if name == "http11.send_request_headers.started":
                        started = self.clock.mono()
                        self._next_start = max(
                            self._next_start, started + max(self.policy.host_gap_s, crawl_delay)
                        )
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
                if lease is not None:
                    self.auth.update_cookies(lease, response.headers.get_list("set-cookie"), url)
                status = response.status_code
                delay = parse_retry_after(response.headers.get("retry-after"), self.clock.utc())
                if status == 429 or (status == 503 and delay is not None):
                    delay = self.policy.min_interval_s if delay is None else delay
                    self.set_not_before(max(self.get_not_before(), self.clock.utc() + delay))
                    self.event(
                        {
                            "kind": kind,
                            "path": urlsplit(url).path,
                            "status": status,
                            "wire_bytes": 0,
                            "decoded_bytes": 0,
                            "started_mono": started,
                            "finished_mono": self.clock.mono(),
                            "utc": self.clock.utc(),
                        }
                    )
                    raise MonitorError("rate_limited", retryable=True, retry_after_s=delay)
                if status >= 500:
                    raise MonitorError("upstream_5xx", retryable=True)
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
                selected = {
                    key: response.headers[key]
                    for key in ("content-type", "location", "retry-after")
                    if key in response.headers
                }
                status = response.status_code
                redirect_diagnostic = {}
                if status in (301, 302, 303, 307, 308) and "location" in selected:
                    try:
                        destination = urlsplit(urljoin(url, selected["location"]))
                        known_paths = {
                            "/robots.txt",
                            "/mod/assign/view.php",
                            "/login/index.php",
                            "/my/",
                            "/",
                        }
                        redirect_diagnostic = {
                            "redirect_path": destination.path
                            if destination.path in known_paths
                            else "[unapproved_path]",
                            "redirect_same_origin": destination.scheme
                            == urlsplit(self.policy.origin).scheme
                            and destination.hostname == self.policy.host
                            and (destination.port or 443)
                            == (urlsplit(self.policy.origin).port or 443),
                        }
                    except ValueError:
                        redirect_diagnostic = {
                            "redirect_path": "[invalid]",
                            "redirect_same_origin": False,
                        }
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
                        **redirect_diagnostic,
                    }
                )
                return status, selected, b"".join(chunks)
            finally:
                await response.aclose()
                # Do not let HTTPX retain a second, unscoped credential store.
                self._client.cookies.clear()

    async def _chain(
        self, url: str, lease: AuthLease | None, *, kind: str
    ) -> tuple[str, int, dict[str, str], bytes]:
        target_url = url
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
            if (
                kind == "robots"
                and self.inspect_access
                and self.inspect_access(
                    SafeResponse(status, url, headers.get("content-type", ""), body)
                ).state
                == "auth_required"
            ):
                raise MonitorError("auth_required")
            if (
                kind == "robots"
                and hop == 0
                and status == 303
                and lease is not None
                and self.registered_target_fallback
                and nxt == self.policy.origin + "/my/"
            ):
                # This is an unusable robots response, NOT a grant from the dashboard.
                # The caller explicitly opted into the separately registered single-target policy.
                raise MonitorError("robots_dashboard_redirect")
            approved = self.policy.canonical(nxt, target=kind == "content")
            if kind == "content" and approved != target_url:
                raise MonitorError("blocked")
            url = nxt
        raise MonitorError("redirect_limit")

    async def fetch(self, plan: FetchPlan, auth: AuthLease | None) -> SafeResponse:
        url = self.policy.canonical(plan.canonical_url, target=True)
        if plan.method != "GET" or plan.validators:
            raise MonitorError("unsupported")
        try:
            async with asyncio.timeout(self.total_timeout):
                identity = (auth.auth_id, auth.generation) if auth else None
                if (
                    self._robots is None
                    or self._robots[0] <= self.clock.mono()
                    or identity != self._robots_identity
                ):
                    try:
                        final, status, headers, body = await self._chain(
                            self.policy.origin + "/robots.txt", auth, kind="robots"
                        )
                    except MonitorError as error:
                        if error.code != "robots_dashboard_redirect":
                            raise
                        p = urlsplit(url)
                        target_path = p.path + ("?" + p.query if p.query else "")
                        rules = parse_robots(
                            f"User-agent: GleanerMonitor\nDisallow: /\nAllow: {target_path}$",
                            "gleanermonitor",
                        )
                        self.policy_event(
                            {
                                "kind": "robots_fallback",
                                "reason": "dashboard_redirect",
                                "scope": "one_registered_target",
                                "utc": self.clock.utc(),
                            }
                        )
                    else:
                        robots_response = SafeResponse(
                            status, final, headers.get("content-type", ""), body
                        )
                        if status == 401 or (
                            self.inspect_access
                            and self.inspect_access(robots_response).state == "auth_required"
                        ):
                            raise MonitorError("auth_required")
                        if status == 200:
                            if (
                                headers.get("content-type", "").split(";")[0].strip().lower()
                                != "text/plain"
                            ):
                                raise MonitorError("robots_unavailable", retryable=True)
                            try:
                                rules = parse_robots(body.decode("utf-8-sig"), "gleanermonitor")
                            except UnicodeDecodeError:
                                raise MonitorError("robots_unavailable", retryable=True) from None
                        elif 400 <= status < 500:
                            rules = RobotsRules()
                        else:
                            raise MonitorError("robots_unavailable", retryable=True)
                    self._robots = (self.clock.mono() + 3600, rules)
                    self._robots_identity = identity
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


class CloudflareDNS:
    host = "cloudflare-dns.com"
    bootstrap = "https://1.1.1.1/dns-query"

    def __init__(
        self,
        allowed_host: str,
        *,
        clock: Clock | None = None,
        engine: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.allowed_host = allowed_host
        self.clock = clock or Clock()
        self.engine = engine
        self.cached: tuple[float, list[str]] | None = None
        self.not_before = 0.0

    async def __call__(self, host: str, port: int) -> list[str]:
        if host != self.allowed_host:
            raise MonitorError("blocked")
        if self.not_before > self.clock.utc():
            raise MonitorError(
                "dns_rate_limited",
                retryable=True,
                retry_after_s=self.not_before - self.clock.utc(),
            )
        if self.cached and self.cached[0] > self.clock.mono():
            return self.cached[1].copy()
        request = httpx.Request(
            "GET",
            self.bootstrap + "?" + urlencode({"name": host, "type": "A"}),
            headers={
                "Host": self.host,
                "Accept": "application/dns-json",
                "Accept-Encoding": "identity",
            },
            extensions={
                "sni_hostname": self.host,
                "timeout": {"connect": 3, "read": 5, "write": 3, "pool": 3},
            },
        )
        try:
            async with (
                asyncio.timeout(5),
                httpx.AsyncClient(
                    transport=self.engine or httpx.AsyncHTTPTransport(retries=0, trust_env=False),
                    trust_env=False,
                    follow_redirects=False,
                ) as client,
            ):
                response = await client.send(request, stream=True, follow_redirects=False)
                try:
                    if response.status_code in (429, 503):
                        delay = parse_retry_after(
                            response.headers.get("retry-after"), self.clock.utc()
                        )
                        delay = 600 if delay is None else delay
                        self.not_before = self.clock.utc() + delay
                        raise MonitorError("dns_rate_limited", retryable=True, retry_after_s=delay)
                    if response.status_code != 200 or response.headers.get(
                        "content-encoding", "identity"
                    ) not in ("", "identity"):
                        raise MonitorError("dns", retryable=True)
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise MonitorError("dns", retryable=True)
                    data = json.loads(body)
                finally:
                    await response.aclose()
            if (
                not isinstance(data, dict)
                or type(data.get("Status")) is not int
                or data["Status"] != 0
            ):
                raise MonitorError("dns", retryable=True)
            addresses, ttls = [], []
            for answer in data.get("Answer", []):
                if answer.get("type") != 1:
                    continue
                address = ipaddress.ip_address(answer["data"])
                ttl = float(answer["TTL"])
                if (
                    address.version != 4
                    or not address.is_global
                    or not math.isfinite(ttl)
                    or ttl < 0
                ):
                    raise MonitorError("blocked")
                addresses.append(str(address))
                ttls.append(ttl)
            if not addresses:
                raise MonitorError("dns", retryable=True)
            self.cached = (self.clock.mono() + min(300, *ttls), addresses)
            return addresses.copy()
        except MonitorError:
            raise
        except (
            httpx.HTTPError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ):
            raise MonitorError("dns", retryable=True) from None


class ProxyCompatibleDNS:
    """Re-resolve synthetic benchmark addresses; never connect to them directly."""

    def __init__(
        self,
        host: str,
        *,
        clock: Clock | None = None,
        system: Resolver = resolve,
        public: Resolver | None = None,
    ) -> None:
        self.host, self.system = host, system
        self.public = public or CloudflareDNS(host, clock=clock)

    async def __call__(self, host: str, port: int) -> list[str]:
        if host != self.host:
            raise MonitorError("blocked")
        addresses = await self.system(host, port)
        networks = (ipaddress.ip_network("198.18.0.0/15"), ipaddress.ip_network("2001:2::/48"))
        try:
            synthetic = [any(ipaddress.ip_address(a) in n for n in networks) for a in addresses]
        except ValueError:
            raise MonitorError("blocked") from None
        # Reject mixed private answers as usual; only known Fake-IP ranges trigger DoH.
        if any(synthetic) and all(
            fake or ipaddress.ip_address(a).is_global
            for a, fake in zip(addresses, synthetic, strict=True)
        ):
            try:
                ipaddress.ip_address(host)
            except ValueError:
                return await self.public(host, port)
        return addresses
