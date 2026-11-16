"""Opt-in browser runtime checks use loopback fixtures and no account credentials."""

import asyncio
import gzip
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from devtools.monitoring.youtube_browser import BrowserProbe, ResponseGuard


@pytest.fixture
async def runtime():
    pw = pytest.importorskip("playwright.async_api")
    hits = []
    body = b"<html><script>window.example=1</script><p>complete \xc3\xa9 HTML</p></html>"

    async def handle(reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            path = head.split(b" ")[1].decode()
            hits.append(path)
            if path in ("/start", "/script"):
                writer.write(
                    b"HTTP/1.1 302 Found\r\nLocation: /denied\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            else:
                content = {
                    "/page": b'<html><script src="/script"></script></html>',
                    "/workers": b"<script>window.workerBlocked=false;try{const w=new Worker('/worker.js');w.onerror=()=>window.workerBlocked=true}catch(e){window.workerBlocked=true}</script>",
                }.get(path, body)
                encoding = b""
                if path == "/gzip":
                    content = gzip.compress(content)
                    encoding = b"Content-Encoding: gzip\r\n"
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'\r\n"
                    + encoding
                    + b"Content-Length: "
                    + str(len(content)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + content
                )
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    driver = await pw.async_playwright().start()
    try:
        try:
            browser = await driver.chromium.launch(headless=True)
        except pw.Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip("optional Chromium runtime is not installed")
            raise
        context = await browser.new_context(service_workers="block", ignore_https_errors=False)
        routed = []
        observers = {}

        async def route(request_route):
            path = urlsplit(request_route.request.url).path
            routed.append(path)
            if path == "/denied":
                await request_route.abort()
            else:
                if request_route.request.resource_type == "document":
                    observer = observers.get(request_route.request.frame.page)
                    if observer:
                        observer.document_released = {
                            "lower_mono": time.monotonic(),
                            "lower_utc": time.time(),
                        }
                await request_route.continue_()

        await context.route("**/*", route)

        async def page():
            p = await context.new_page()
            cdp = await context.new_cdp_session(p)
            await cdp.send("Network.enable")
            guard = ResponseGuard(cdp)
            guard.timing_observer = SimpleNamespace(
                target=f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/ok",
                request_clocks={},
                document_released=None,
                guard=guard,
            )
            observers[p] = guard.timing_observer
            cdp.on(
                "Network.requestWillBeSent",
                lambda e: BrowserProbe.request_started(guard.timing_observer, e),
            )
            await guard.install()
            return p, guard

        yield (
            f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}",
            page,
            hits,
            routed,
            body,
            pw.Error,
        )
        await browser.close()
    finally:
        await driver.stop()
        server.close()
        await server.wait_closed()


async def test_response_guard_stops_redirect_before_route_invisible_second_hop(runtime):
    origin, new_page, hits, routed, body, error = runtime
    p, guard = await new_page()
    with pytest.raises(error):
        await p.goto(origin + "/start")
    assert hits == ["/start"] and routed == ["/start"]
    assert guard.redirects == 1 and not guard.failed
    await p.close()
    p, guard = await new_page()
    response = await p.goto(origin + "/ok")
    assert await response.body() == body
    policies = "\n".join(await response.header_values("content-security-policy"))
    assert "default-src 'self'" in policies and "worker-src 'none'" in policies
    assert guard.original_body == body
    timing = BrowserProbe.request_bounds(guard.timing_observer)
    assert timing["request_start_observed"] is True
    assert timing["started_lower_mono"] <= timing["started_upper_mono"]
    assert timing["started_lower_utc"] <= timing["started_upper_utc"]
    assert not guard.failed
    await p.close()


async def test_subresource_redirect_is_also_blocked(runtime):
    origin, new_page, hits, _routed, _body, _error = runtime
    p, guard = await new_page()
    await p.goto(origin + "/page")
    assert "/script" in hits and "/denied" not in hits
    assert guard.redirects == 1 and not guard.failed
    await p.close()


async def test_native_csp_prevents_worker_network_escape(runtime):
    origin, new_page, hits, _routed, _body, _error = runtime
    p, guard = await new_page()
    await p.goto(origin + "/workers")
    await p.wait_for_function("window.workerBlocked === true", timeout=3000)
    assert await p.evaluate("window.workerBlocked") is True
    assert "/worker.js" not in hits
    assert not guard.failed
    await p.close()


async def test_response_guard_preserves_complete_decoded_compressed_html(runtime):
    origin, new_page, _hits, _routed, body, _error = runtime
    p, guard = await new_page()
    response = await p.goto(origin + "/gzip")
    assert guard.original_body == await response.body() == body
    assert not guard.failed
    await p.close()
