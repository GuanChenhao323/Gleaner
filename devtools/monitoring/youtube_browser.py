"""Restricted Playwright experiment, not a general browser backend.

The CONNECT proxy pins the sole allowed origin via the existing resolver. It never
terminates TLS. Per-request routes enforce robots/pacing, with service workers and
websockets blocked. No auth state, response body, trace, or browser error is logged.
"""

from __future__ import annotations

import asyncio
import ipaddress
import math
import time
from collections import Counter
from urllib.parse import urlsplit

from gleaner.collector.fetcher import parse_retry_after, parse_robots
from gleaner.monitoring.models import MonitorError, SafeResponse
from gleaner.monitoring.transport import HTTPXTransport
from gleaner.net.egress import is_public


class PinnedTunnel:
    def __init__(self, host, resolver, emit):
        self.host, self.resolver, self.emit = host, resolver, emit
        self.server = None
        self.tasks = set()
        self.writers = set()
        self.lock = asyncio.Lock()
        self.last_error = None

    async def start(self):
        self.server = await asyncio.start_server(
            self.handle, "127.0.0.1", 0, limit=8192
        )
        return f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        upstream = None
        try:
            async with asyncio.timeout(15):
                header = await reader.readuntil(b"\r\n\r\n")
                first = header.split(b"\r\n", 1)[0]
                if first != f"CONNECT {self.host}:443 HTTP/1.1".encode():
                    writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                    await writer.drain()
                    return
                # Serialise cache misses; validate every returned address before opening TCP.
                async with self.lock:
                    addresses = await self.resolver(self.host, 443)
                if not addresses or any(
                    not is_public(a) or not ipaddress.ip_address(a).is_global
                    for a in addresses
                ):
                    raise MonitorError("blocked")
                remote, upstream = await asyncio.open_connection(addresses[0], 443)
                self.writers.add(upstream)
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()

            async def relay(source, destination):
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()

            directions = [
                asyncio.create_task(relay(reader, upstream)),
                asyncio.create_task(relay(remote, writer)),
            ]
            try:
                await asyncio.wait(directions, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for direction in directions:
                    direction.cancel()
                await asyncio.gather(*directions, return_exceptions=True)
        except (
            OSError,
            ValueError,
            TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            MonitorError,
        ) as error:
            self.last_error = (
                error.code
                if isinstance(error, MonitorError)
                else "browser_tunnel_network"
            )
            self.emit(
                {
                    "kind": "browser_tunnel_failure",
                    "error": self.last_error,
                    "utc": time.time(),
                }
            )
        finally:
            for stream in (writer, upstream):
                if stream is not None:
                    stream.close()
                    self.writers.discard(stream)
            self.tasks.discard(task)

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in list(self.writers):
            writer.close()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class BrowserProbe:
    def __init__(self, policy, auth, **kwargs):
        if kwargs.get("registered_target_fallback"):
            raise ValueError("browser experiment requires strict robots")
        self.policy, self.auth = policy, auth
        self.event = kwargs.get("event", lambda _: None)
        self.emit = kwargs.get("policy_event", lambda _: None)
        self.http = HTTPXTransport(policy, auth, **kwargs)
        self.tunnel = PinnedTunnel(policy.host, self.http.resolver, self.emit)
        self.runtime = self.browser = self.context = self.page = self.cdp = None
        self.rules = None
        self.rules_until = 0
        self.next_start = 0
        self.lock = asyncio.Lock()
        self.blocked = Counter()
        self.active = False
        self.target = policy.target_urls[0]
        self.request_clocks = {}
        self.document_timing = None

    async def robots(self):
        if time.monotonic() < self.rules_until:
            return
        _final, status, headers, body = await self.http._chain(
            self.policy.origin + "/robots.txt", None, kind="robots"
        )
        if (
            status != 200
            or headers.get("content-type", "").split(";")[0].lower() != "text/plain"
        ):
            raise MonitorError("robots_unavailable")
        try:
            self.rules = parse_robots(body.decode("utf-8-sig"), "gleanermonitor")
        except UnicodeDecodeError:
            raise MonitorError("robots_unavailable") from None
        self.rules_until = time.monotonic() + 3600
        self.next_start = max(self.next_start, self.http._next_start)
        if not self.rules.allowed(urlsplit(self.target).path):
            raise MonitorError("robots_denied")

    def permit(self, url, method, resource_type):
        try:
            p = urlsplit(url)
            if (
                p.scheme != "https"
                or p.netloc != self.policy.host
                or p.port not in (None, 443)
                or p.username
                or p.password
                or p.fragment
            ):
                return "scope"
        except ValueError:
            return "scope"
        path = p.path + ("?" + p.query if p.query else "")
        if not self.rules or not self.rules.allowed(path):
            return "robots"
        if method != "GET":
            return "method"
        if resource_type == "document":
            return None if url == self.target else "navigation"
        if (
            resource_type in ("script", "stylesheet")
            and p.path.startswith("/s/desktop/")
            and not p.query
        ):
            return None
        return "dependency"

    async def trim_cookies(self):
        for cookie in await self.context.cookies():
            if cookie["name"] not in self.policy.cookie_names or cookie[
                "domain"
            ].lstrip(".") not in ("youtube.com", self.policy.host):
                await self.context.clear_cookies(
                    name=cookie["name"], domain=cookie["domain"], path=cookie["path"]
                )

    async def route(self, route):
        request = route.request
        reason = (
            self.permit(request.url, request.method, request.resource_type)
            if self.active
            else "idle"
        )
        if reason:
            self.blocked[reason] += 1
            await route.abort("blockedbyclient")
            return
        async with self.lock:
            await asyncio.sleep(max(0, self.next_start - time.monotonic()))
            if not self.active:
                self.blocked["idle"] += 1
                await route.abort("blockedbyclient")
                return
            await self.trim_cookies()
            self.next_start = time.monotonic() + max(
                self.policy.host_gap_s, self.rules.crawl_delay
            )
            await route.continue_()

    def request_started(self, event):
        if event.get("type") == "Document" and event["request"]["url"] == self.target:
            self.request_clocks[event["requestId"]] = (
                event["timestamp"],
                event["wallTime"],
            )

    def response_received(self, event):
        response = event["response"]
        if event.get("type") != "Document" or response["url"] != self.target:
            return
        clock = self.request_clocks.get(event["requestId"])
        timing = response.get("timing", {})
        request_time, send_start = timing.get("requestTime"), timing.get("sendStart")
        if clock and all(
            type(x) in (float, int) and math.isfinite(x) and x >= 0
            for x in (request_time, send_start)
        ):
            mono = request_time + send_start / 1000
            self.document_timing = {
                "started_mono": mono,
                "started_utc": clock[1] + mono - clock[0],
                "request_start_observed": True,
            }

    async def open(self, lease):
        from playwright.async_api import async_playwright

        proxy = await self.tunnel.start()
        self.runtime = await async_playwright().start()
        self.browser = await self.runtime.chromium.launch(
            headless=True,
            proxy={"server": proxy},
            args=["--disable-quic"],
        )
        self.context = await self.browser.new_context(
            ignore_https_errors=False,
            service_workers="block",
            accept_downloads=False,
            user_agent="GleanerMonitor/1.0",
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        await self.context.route("**/*", self.route)

        async def deny_websocket(ws):
            self.blocked["websocket"] += 1
            await ws.close()

        await self.context.route_web_socket("**/*", deny_websocket)
        seed = []
        for c in self.auth.current(lease).jar.to_list():
            item = {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"]
                if c["host_only"]
                else "." + c["domain"].lstrip("."),
                "path": c["path"],
                "secure": c["secure"],
                "httpOnly": c["http_only"],
            }
            if c["expires"] is not None:
                item["expires"] = c["expires"]
            same_site = {
                "strict": "Strict",
                "lax": "Lax",
                "none": "None",
                "no_restriction": "None",
            }.get(c["same_site"])
            if same_site:
                item["sameSite"] = same_site
            seed.append(item)
        await self.context.add_cookies(seed)
        seed.clear()
        self.page = await self.context.new_page()
        self.cdp = await self.context.new_cdp_session(self.page)
        await self.cdp.send("Network.enable")
        self.cdp.on("Network.requestWillBeSent", self.request_started)
        self.cdp.on("Network.responseReceived", self.response_received)
        self.emit(
            {
                "kind": "browser_started",
                "browser_version": self.browser.version,
                "memory_only": True,
                "tls_verification_enabled": True,
                "service_workers": "blocked",
                "utc": time.time(),
            }
        )

    async def fetch(self, plan, lease):
        from playwright.async_api import Error as BrowserError

        self.policy.canonical(plan.canonical_url, target=True)
        self.auth.current(lease)
        if plan.method != "GET" or plan.validators:
            raise MonitorError("unsupported")
        try:
            await self.robots()
            if self.browser is None:
                await self.open(lease)
            self.document_timing = None
            self.request_clocks.clear()
            self.blocked.clear()
            self.active = True
            async with asyncio.timeout(35):
                response = await self.page.goto(
                    self.target, wait_until="commit", timeout=30000
                )
                if response is None or response.url != self.target:
                    raise MonitorError("browser_navigation")
                body = await response.body()
                if len(body) > self.http.max_decoded:
                    raise MonitorError("response_too_large")
                headers = await response.all_headers()
                self.auth.update_cookies(
                    lease, await response.header_values("set-cookie"), self.target
                )
                timing = self.document_timing
                if timing is None:
                    raise MonitorError("browser_missing_request_timing")
                self.event(
                    {
                        "kind": "content",
                        "status": response.status,
                        "decoded_bytes": len(body),
                        "wire_bytes": None,
                        **timing,
                        "finished_mono": time.monotonic(),
                        "utc": time.time(),
                    }
                )
                if response.status in (429, 503):
                    delay = parse_retry_after(headers.get("retry-after"), time.time())
                    raise MonitorError("rate_limited", retry_after_s=delay or 600)
                # Allow bounded, policy-checked page execution; collect no DOM content.
                dom_logged_in = None
                try:
                    await self.page.wait_for_function(
                        "() => typeof window.ytcfg?.get === 'function'", timeout=8000
                    )
                    value = await self.page.evaluate(
                        "() => window.ytcfg.get('LOGGED_IN')"
                    )
                    dom_logged_in = value if type(value) is bool else None
                except BrowserError:
                    pass
                self.emit(
                    {
                        "kind": "browser_observation",
                        "dom_logged_in": dom_logged_in,
                        "blocked_requests": dict(self.blocked),
                        "utc": time.time(),
                    }
                )
                if dom_logged_in is False:
                    raise MonitorError("auth_required")
                return SafeResponse(
                    response.status, response.url, headers.get("content-type", ""), body
                )
        except MonitorError:
            raise
        except (BrowserError, TimeoutError) as error:
            code = (
                "browser_tls"
                if "ERR_CERT_" in str(error) or "ERR_SSL_" in str(error)
                else self.tunnel.last_error or "browser_navigation"
            )
            raise MonitorError(code) from None
        except Exception:  # noqa: BLE001 -- redact errors at the credential boundary.
            # Never let driver exceptions emit page text, headers or credential values.
            raise MonitorError("browser_runtime") from None
        finally:
            self.active = False
            if self.page is not None and not self.page.is_closed():
                try:
                    await self.page.goto(
                        "about:blank", wait_until="commit", timeout=5000
                    )
                except BrowserError:
                    pass
                self.emit(
                    {
                        "kind": "browser_idle",
                        "target_page_closed": self.page.url == "about:blank",
                        "utc": time.time(),
                    }
                )

    async def close(self):
        self.active = False
        try:
            if self.browser is not None:
                await self.browser.close()
            if self.runtime is not None:
                await self.runtime.stop()
        finally:
            await self.tunnel.close()
            await self.http.close()
