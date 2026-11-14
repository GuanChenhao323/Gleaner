import asyncio
import json
from argparse import Namespace
from types import SimpleNamespace
from typing import ClassVar

import pytest
from devtools.monitoring.page_run import normalize, summarize
from devtools.monitoring.youtube_browser import BrowserProbe, PinnedTunnel
from devtools.monitoring.youtube_compare import (
    INITIAL_COOKIES,
    TARGET,
    NetworkInspector,
    experimental_policy,
    make_harness,
)
from monitoring_helpers import FakeClock, cookie

from gleaner.collector.fetcher import parse_robots
from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.models import MonitorError, SafeResponse
from gleaner.monitoring.profiles import page_policy


def credentials():
    return [
        cookie("BOOTSTRAP_SECRET", name=INITIAL_COOKIES[0], domain=".youtube.com", host_only=False)
    ]


async def test_experiment_preserves_response_state_without_changing_default():
    original = page_policy("youtube", TARGET)
    policy = experimental_policy("youtube", TARGET)
    assert "SID" in original.cookie_names
    assert "SID" not in policy.cookie_names
    auth = AuthManager(policy, FakeClock())
    context = auth.create(1, "test")
    auth.import_cookies(
        context.auth_id,
        credentials(),
        backend_epoch=auth.backend_epoch,
        expected_revision=0,
        request_id="one",
    )
    lease = await auth.acquire(context.auth_id)
    auth.update_cookies(
        lease,
        [
            "LOGIN_INFO=SERVER_SECRET; Domain=.youtube.com; Path=/; Secure; HttpOnly",
            "SID=OTHER_SECRET; Domain=.youtube.com; Path=/; Secure",
        ],
        TARGET,
    )
    assert "LOGIN_INFO=SERVER_SECRET" in auth.header(lease, TARGET)
    assert "OTHER_SECRET" not in auth.header(lease, TARGET)
    assert not normalize([{"name": "LOGIN_INFO", "value": "BROWSER_SECRET"}], INITIAL_COOKIES)
    assert original == page_policy("youtube", TARGET)


async def test_experiment_registration_keeps_binding_and_exact_parameters(tmp_path):
    args = Namespace(
        site="youtube",
        target=TARGET,
        interval=600,
        duration=7200,
        report=str(tmp_path / "report.jsonl"),
        port=0,
        backend="http",
        robots_fallback="strict",
    )
    harness = make_harness(args)
    try:
        with pytest.raises(MonitorError, match="binding_denied"):
            harness.monitor.register(harness.params, owner_id=2, bridge_id="debug-browser")
        with pytest.raises(MonitorError, match="invalid"):
            harness.monitor.register(
                harness.params | {"interval_s": True}, owner_id=1, bridge_id="debug-browser"
            )
        with pytest.raises(MonitorError):
            harness.monitor.register(
                harness.params | {"target_url": "https://evil.example/"},
                owner_id=1,
                bridge_id="debug-browser",
            )
        assert (
            harness.monitor.register(
                harness.params, owner_id=1, bridge_id="debug-browser"
            ).target_url
            == TARGET
        )
    finally:
        await harness.close()


def test_network_comparison_does_not_emit_identity_or_html():
    events = []
    inspector = NetworkInspector("youtube", events.append)

    def response(ip):
        body = (
            "<script>ytcfg.set("
            + json.dumps(
                {
                    "LOGGED_IN": True,
                    "INNERTUBE_CONTEXT": {"client": {"remoteHost": ip}},
                    "secret": "HTML_SECRET",
                }
            )
            + ");</script>"
        )
        return SafeResponse(200, TARGET, "text/html", body.encode())

    inspector.inspect(response("8.8.8.8"))
    inspector.inspect(response("8.8.8.8"))
    inspector.inspect(response("1.1.1.1"))
    assert [e["network_identity_changed"] for e in events if "network_identity_changed" in e] == [
        None,
        False,
        True,
    ]
    assert all(x not in repr(events) for x in ("8.8.8.8", "1.1.1.1", "HTML_SECRET"))


def test_browser_continuity_uses_conservative_network_bounds():
    rounds = []
    for i in range(13):
        rounds.append(
            {
                "state": "delivered",
                "request_start_observed": True,
                "timing_basis": "network_send_bounds",
                "content_started_mono": i * 601,
                "content_started_utc": 10000 + i * 601,
                "content_started_lower_mono": i * 601,
                "content_started_upper_mono": i * 601 + 1,
                "content_started_lower_utc": 10000 + i * 601,
                "content_started_upper_utc": 10001 + i * 601,
                "mono": i * 601 + 100,
                "utc": 10100 + i * 601,
            }
        )
    assert summarize(rounds, 7200, 600)["passed"]
    assert summarize(rounds, 7212, 600)["span_s"] == 7211
    assert not summarize(rounds, 7212, 600)["passed"]
    rounds[0]["content_started_upper_mono"] = 5
    assert not summarize(rounds, 7200, 600)["passed"]
    rounds[0]["content_started_upper_mono"] = -1
    assert summarize(rounds, 7200, 600)["observed_content_requests"] == 12


@pytest.mark.parametrize(
    "url,method,kind,reason",
    [
        (TARGET, "GET", "document", None),
        ("https://www.youtube.com/s/desktop/build/jsbin/app.js", "GET", "script", None),
        ("https://www.youtube.com/youtubei/v1/browse", "POST", "fetch", "robots"),
        (TARGET, "POST", "document", "method"),
        ("https://www.youtube.com/@other/videos", "GET", "document", "navigation"),
        ("https://accounts.google.com/", "GET", "document", "scope"),
        ("https://www.youtube.com:444/", "GET", "document", "scope"),
        ("https://www.youtube.com/s/desktop/app.js?secret=x", "GET", "script", "dependency"),
        ("https://www.youtube.com/s/desktop/%2e%2e/app.js", "GET", "script", "dependency"),
        ("https://www.youtube.com/s/desktop/../app.js", "GET", "script", "dependency"),
        ("https://127.0.0.1/", "GET", "document", "scope"),
        ("http://www.youtube.com/", "GET", "document", "scope"),
    ],
)
async def test_browser_request_policy_checks_every_dependency(url, method, kind, reason):
    policy = experimental_policy("youtube", TARGET)
    probe = BrowserProbe(policy, AuthManager(policy))
    probe.rules = parse_robots("User-agent: *\nDisallow: /youtubei/", "gleanermonitor")
    try:
        assert probe.permit(url, method, kind) == reason
    finally:
        await probe.close()


async def test_tunnel_denies_unapproved_destination_before_resolution():
    called = []

    async def resolve(host, port):
        called.append(host)
        return ["8.8.8.8"]

    tunnel = PinnedTunnel("www.youtube.com", resolve, lambda _: None)
    origin = await tunnel.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", int(origin.rsplit(":", 1)[1]))
        writer.write(b"CONNECT accounts.google.com:443 HTTP/1.1\r\n\r\n")
        await writer.drain()
        assert b"403" in await reader.read()
        writer.close()
        await writer.wait_closed()
        assert not called
    finally:
        await tunnel.close()


async def test_tunnel_rejects_private_dns_without_connecting(monkeypatch):
    async def resolve(host, port):
        return ["127.0.0.1"]

    events = []
    tunnel = PinnedTunnel("www.youtube.com", resolve, events.append)
    origin = await tunnel.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", int(origin.rsplit(":", 1)[1]))

    async def denied(*args, **kwargs):
        raise AssertionError("upstream TCP must not be opened")

    monkeypatch.setattr(asyncio, "open_connection", denied)
    try:
        writer.write(b"CONNECT www.youtube.com:443 HTTP/1.1\r\n\r\n")
        await writer.drain()
        assert await reader.read() == b""
        assert events[0]["error"] == "blocked"
    finally:
        writer.close()
        await writer.wait_closed()
        await tunnel.close()


async def test_browser_timing_brackets_network_send_without_using_delivery():
    policy = experimental_policy("youtube", TARGET)
    probe = BrowserProbe(policy, AuthManager(policy))
    try:
        probe.request_started(
            {
                "type": "Document",
                "request": {"url": TARGET},
                "requestId": "id",
                "timestamp": 10,
                "wallTime": 1000,
            }
        )
        probe.document_released = {"lower_mono": 11, "lower_utc": 1001}
        probe.guard = SimpleNamespace(
            document_received={"network_id": "id", "upper_mono": 12, "upper_utc": 1002}
        )
        timing = probe.request_bounds()
        assert timing["started_lower_mono"] == 11 and timing["started_upper_mono"] == 12
        assert timing["started_lower_utc"] == 1001 and timing["started_upper_utc"] == 1002
        assert timing["request_start_observed"] is True
        probe.guard.document_received["network_id"] = "unmatched"
        with pytest.raises(MonitorError, match="browser_missing_request_timing"):
            probe.request_bounds()
    finally:
        await probe.close()


async def test_native_cookie_snapshot_preserves_scope_and_clears_removed_credentials():
    policy = experimental_policy("youtube", TARGET)
    events = []
    auth = AuthManager(policy, FakeClock())
    context = auth.create(1, "test")
    auth.import_cookies(
        context.auth_id,
        credentials(),
        backend_epoch=auth.backend_epoch,
        expected_revision=0,
        request_id="one",
    )
    lease = await auth.acquire(context.auth_id)
    probe = BrowserProbe(policy, auth, policy_event=events.append)

    class NativeContext:
        items: ClassVar[list[dict]] = [
            {
                "name": "LOGIN_INFO",
                "value": "NATIVE_SECRET",
                "domain": ".youtube.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "expires": -1,
                "sameSite": "None",
            },
            {
                "name": "SID",
                "value": "FORBIDDEN_SECRET",
                "domain": ".youtube.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "expires": -1,
                "sameSite": "None",
            },
        ]

        async def cookies(self):
            return self.items.copy()

        async def clear_cookies(self, **where):
            self.items = [c for c in self.items if not all(c[k] == v for k, v in where.items())]

    native = NativeContext()
    probe.context = native
    try:
        await probe.sync_auth(lease)
        assert auth.header(lease, TARGET) == "LOGIN_INFO=NATIVE_SECRET"
        assert events[-1]["cookie_count"] == 1
        assert "SECRET" not in repr(events)
        native.items = []
        with pytest.raises(MonitorError, match="auth_required"):
            await probe.sync_auth(lease)
        assert not len(context.jar) and context.state == "auth_required"
    finally:
        await probe.close()
