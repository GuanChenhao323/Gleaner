"""Restricted Playwright experiment, not a general browser backend.

The CONNECT proxy pins the sole allowed origin via the existing resolver. It never
terminates TLS. Per-request routes enforce robots/pacing, with service workers and
websockets blocked. No auth state, response body, trace, or browser error is logged.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import math
import re
import time
from collections import Counter
from urllib.parse import urlsplit

from gleaner.collector.fetcher import parse_retry_after, parse_robots
from gleaner.monitoring.models import MonitorError, SafeResponse
from gleaner.monitoring.transport import CloudflareDNS, HTTPXTransport
from gleaner.net.egress import is_public
from gleaner.net.http.cookies import Cookie, CookieJar


class ResponseGuard:
    """Stop redirects before Chromium follows them, including route-invisible hops."""

    def __init__(self, cdp):
        self.cdp = cdp
        self.redirects = 0
        self.failed = False
        self.original_body = None
        self.document_received = None

    async def install(self):
        self.cdp.on("Fetch.requestPaused", self.paused)
        await self.cdp.send(
            "Fetch.enable",
            {"patterns": [{"urlPattern": "*", "requestStage": "Response"}]},
        )

    async def paused(self, event):
        from playwright.async_api import Error as BrowserError

        request_id = event["requestId"]
        status = event.get("responseStatusCode")
        if status is not None and event.get("resourceType") == "Document":
            self.document_received = {
                "network_id": event.get("networkId"),
                "upper_mono": time.monotonic(),
                "upper_utc": time.time(),
            }
        try:
            if status is not None and 300 <= status < 400 and status != 304:
                self.redirects += 1
                await self.cdp.send(
                    "Fetch.failRequest",
                    {"requestId": request_id, "errorReason": "BlockedByClient"},
                )
                return
            params = {"requestId": request_id}
            if status == 200 and event.get("resourceType") == "Document":
                # Add restrictions without changing original HTML bytes or weakening site CSP.
                headers = event.get("responseHeaders", [])
                content_type = next(
                    (
                        h["value"]
                        for h in headers
                        if h["name"].lower() == "content-type"
                    ),
                    "",
                )
                charset = re.search(
                    r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type, re.IGNORECASE
                )
                if charset and charset[1].lower() not in ("utf-8", "utf8", "us-ascii"):
                    self.failed = True
                    await self.cdp.send(
                        "Fetch.failRequest",
                        {"requestId": request_id, "errorReason": "BlockedByClient"},
                    )
                    return
                result = await self.cdp.send(
                    "Fetch.getResponseBody", {"requestId": request_id}
                )
                body = (
                    base64.b64decode(result["body"])
                    if result["base64Encoded"]
                    else result["body"].encode("utf-8")
                )
                if len(body) > 8 * 1024 * 1024:
                    self.failed = True
                    await self.cdp.send(
                        "Fetch.failRequest",
                        {"requestId": request_id, "errorReason": "BlockedByClient"},
                    )
                    return
                self.original_body = body
                params.update(
                    responseCode=status,
                    responsePhrase=event.get("responseStatusText") or "OK",
                    body=base64.b64encode(body).decode("ascii"),
                    responseHeaders=[
                        *[
                            h
                            for h in headers
                            if h["name"].lower()
                            not in ("content-length", "content-encoding")
                        ],
                        {"name": "Content-Length", "value": str(len(body))},
                        {
                            "name": "Content-Security-Policy",
                            "value": "connect-src 'none'; worker-src 'none'; frame-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'",
                        },
                    ],
                )
                # Explicit original decoded bytes are required: header-only overrides
                # were ineffective in the installed runtime. Bytes stay in memory.
                await self.cdp.send("Fetch.fulfillRequest", params)
                return
            await self.cdp.send("Fetch.continueResponse", params)
        except BrowserError:
            # A paused request never gets implicitly continued on error.
            self.failed = True


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
                    self.emit(
                        {
                            "kind": "browser_tunnel_denied",
                            "reason": "unapproved_destination",
                            "utc": time.time(),
                        }
                    )
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
        self.http = HTTPXTransport(
            policy, auth, resolver=CloudflareDNS(policy.host, event=self.emit), **kwargs
        )
        self.tunnel = PinnedTunnel(policy.host, self.http.resolver, self.emit)
        self.runtime = self.browser = self.context = self.page = self.cdp = None
        self.rules = None
        self.rules_until = 0
        self.next_start = 0
        self.lock = asyncio.Lock()
        self.blocked = Counter()
        self.allowed = Counter()
        self.active = False
        self.document_admitted = False
        self.guard = None
        self.route_failed = False
        self.target = policy.target_urls[0]
        self.request_clocks = {}
        self.document_released = None

    async def robots(self):
        if time.monotonic() < self.rules_until:
            return
        _final, status, headers, body = await self.http._chain(
            self.policy.origin + "/robots.txt", None, kind="robots"
        )
        if (
            status != 200
            or headers.get("content-type", "").split(";")[0].strip().lower()
            != "text/plain"
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
            and re.fullmatch(r"/s/desktop/[A-Za-z0-9_./-]+\.(?:js|css)", p.path)
            and not {".", ".."}.intersection(p.path.split("/"))
            and not p.query
        ):
            return None
        return "dependency"

    async def trim_cookies(self):
        for cookie in await self.context.cookies():
            if cookie.get("partitionKey") or not self.policy.cookie_allowed(
                cookie["name"],
                cookie["domain"],
                cookie["path"],
                not cookie["domain"].startswith("."),
                cookie["secure"],
            ):
                await self.context.clear_cookies(
                    name=cookie["name"], domain=cookie["domain"], path=cookie["path"]
                )

    async def sync_auth(self, lease):
        """Browser is the owner; mirror only approved in-memory state for fencing/counts."""
        await self.trim_cookies()
        c = self.auth.current(lease)
        cookies = []
        for item in await self.context.cookies():
            cookies.append(
                Cookie(
                    name=item["name"],
                    value=item["value"],
                    domain=item["domain"].lstrip("."),
                    path=item["path"],
                    expires=None if item["expires"] == -1 else item["expires"],
                    secure=item["secure"],
                    http_only=item["httpOnly"],
                    host_only=not item["domain"].startswith("."),
                    same_site=item["sameSite"].lower(),
                )
            )
        jar = CookieJar(cookies)

        def values(j):
            return [
                {k: v for k, v in item.items() if k != "created"}
                for item in j.to_list()
            ]

        changed = values(c.jar) != values(jar)
        if changed:
            c.jar = jar
            c.revision += 1
        self.emit(
            {
                "kind": "browser_cookie_state",
                "cookie_count": len(jar),
                "changed": changed,
                "utc": time.time(),
            }
        )
        if not cookies:
            self.auth.require_auth(c.auth_id)
            raise MonitorError("auth_required")

    async def route(self, route):
        from playwright.async_api import Error as BrowserError

        try:
            await self._route(route)
        except BrowserError:
            if self.active:
                self.route_failed = True
            self.blocked["cancelled"] += 1

    async def _route(self, route):
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
            if request.frame != self.page.main_frame:
                self.blocked["frame"] += 1
                await route.abort("blockedbyclient")
                return
            if request.resource_type == "document":
                if self.document_admitted:
                    self.blocked["extra_document"] += 1
                    await route.abort("blockedbyclient")
                    return
                self.document_admitted = True
            await self.trim_cookies()
            self.next_start = time.monotonic() + max(
                self.policy.host_gap_s, self.rules.crawl_delay
            )
            if request.resource_type == "document":
                self.document_released = {
                    "lower_mono": time.monotonic(),
                    "lower_utc": time.time(),
                }
            await route.continue_()
            self.allowed[request.resource_type] += 1

    def request_started(self, event):
        if event.get("type") == "Document" and event["request"]["url"] == self.target:
            self.request_clocks[event["requestId"]] = (
                event["timestamp"],
                event["wallTime"],
            )

    def request_bounds(self):
        lo, hi = self.document_released, self.guard.document_received
        if not lo or not hi or hi["network_id"] not in self.request_clocks:
            raise MonitorError("browser_missing_request_timing")
        bounds = {**lo, **{k: v for k, v in hi.items() if k != "network_id"}}
        if not all(
            type(v) in (int, float) and math.isfinite(v) for v in bounds.values()
        ) or any(lo[f"lower_{c}"] > hi[f"upper_{c}"] for c in ("mono", "utc")):
            raise MonitorError("browser_missing_request_timing")
        return {
            "started_mono": lo["lower_mono"],
            "started_utc": lo["lower_utc"],
            "request_start_observed": True,
            "timing_basis": "network_send_bounds",
            **{f"started_{k}": v for k, v in bounds.items()},
        }

    async def open(self, lease):
        from playwright.async_api import async_playwright

        proxy = await self.tunnel.start()
        self.runtime = await async_playwright().start()
        self.browser = await self.runtime.chromium.launch(
            headless=True,
            proxy={"server": proxy},
            args=[
                "--disable-quic",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            ],
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
        await self.cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        self.cdp.on("Network.requestWillBeSent", self.request_started)
        self.guard = ResponseGuard(self.cdp)
        await self.guard.install()
        self.emit(
            {
                "kind": "browser_started",
                "browser_version": self.browser.version,
                "memory_only": True,
                "tls_verification_enabled": True,
                "service_workers": "blocked",
                "redirects": "blocked_before_following",
                "workers_and_subframes": "blocked_by_csp",
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
            self.document_released = None
            self.request_clocks.clear()
            self.blocked.clear()
            self.allowed.clear()
            self.document_admitted = False
            self.route_failed = False
            self.guard.failed = False
            self.guard.redirects = 0
            self.guard.original_body = None
            self.guard.document_received = None
            self.active = True
            async with asyncio.timeout(35):
                response = await self.page.goto(
                    self.target, wait_until="commit", timeout=30000
                )
                if response is None or response.url != self.target:
                    raise MonitorError("browser_navigation")
                body = await response.body()
                if response.status == 200 and body != self.guard.original_body:
                    raise MonitorError("browser_body_mismatch")
                if len(body) > self.http.max_decoded:
                    raise MonitorError("response_too_large")
                headers = await response.all_headers()
                self.auth.update_cookies(
                    lease, await response.header_values("set-cookie"), self.target
                )
                timing = self.request_bounds()
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
                account_menu_visible = False
                try:
                    await self.page.locator("button#avatar-btn").wait_for(
                        state="visible", timeout=20000
                    )
                    account_menu_visible = True
                except BrowserError:
                    pass
                try:
                    await self.page.wait_for_function(
                        "() => typeof window.ytcfg?.get === 'function'", timeout=1000
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
                        "account_menu_visible": account_menu_visible,
                        "blocked_requests": dict(self.blocked),
                        "allowed_requests": dict(self.allowed),
                        "blocked_redirects": self.guard.redirects,
                        "utc": time.time(),
                    }
                )
                if dom_logged_in is False:
                    raise MonitorError("auth_required")
                if self.route_failed or self.guard.failed:
                    raise MonitorError("browser_policy_failure")
                await self.sync_auth(lease)
                return SafeResponse(
                    response.status, response.url, headers.get("content-type", ""), body
                )
        except MonitorError:
            raise
        except (BrowserError, TimeoutError) as error:
            code = (
                "browser_tls"
                if "ERR_CERT_" in str(error) or "ERR_SSL_" in str(error)
                else "browser_redirect_denied"
                if self.guard and self.guard.redirects
                else self.tunnel.last_error or "browser_navigation"
            )
            raise MonitorError(code) from None
        except Exception:  # noqa: BLE001 -- redact errors at the credential boundary.
            # Never let driver exceptions emit page text, headers or credential values.
            raise MonitorError("browser_runtime") from None
        finally:
            self.active = False
            if self.guard:
                self.guard.original_body = None
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
