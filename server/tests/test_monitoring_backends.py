import asyncio
import hashlib
import json
from argparse import Namespace
from dataclasses import replace

import pytest
from devtools.monitoring.page_run import Harness
from monitoring_helpers import FakeClock, cookie

from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.backends import create_page_transport
from gleaner.monitoring.browser import PlaywrightTransport
from gleaner.monitoring.models import MonitorError, SafeResponse, SitePolicy
from gleaner.monitoring.pages import PageMonitor
from gleaner.monitoring.profiles import SessionInspector, page_policy
from gleaner.monitoring.transport import CloudflareDNS, HTTPXTransport, ProxyCompatibleDNS

TARGET = "https://www.youtube.com/@3blue1brown/videos"
BODY = b'<html><script>ytcfg.set({"LOGGED_IN":true});</script><p>\xc3\xa9 raw HTML</p></html>'


def install(auth, context, value="PRIVATE_BOOTSTRAP", request_id="first"):
    return auth.import_cookies(
        context.auth_id,
        [cookie(value, name="__Secure-3PSID", domain=".youtube.com", host_only=False)],
        backend_epoch=auth.backend_epoch,
        expected_revision=context.revision,
        request_id=request_id,
        reason="manual_reauthorize",
    )


async def test_default_http_and_legacy_policy_are_preserved():
    for policy in (SitePolicy(), page_policy("youtube", TARGET)):
        transport = create_page_transport(policy, AuthManager(policy))
        try:
            assert type(transport) is HTTPXTransport
            assert isinstance(transport.resolver, ProxyCompatibleDNS)
        finally:
            await transport.close()
    assert "SID" in page_policy("youtube", TARGET).cookie_names


@pytest.mark.parametrize(
    "profile,backend",
    [("youtube_http_v2", HTTPXTransport), ("youtube_browser_v1", PlaywrightTransport)],
)
async def test_explicit_profile_selects_backend_and_separates_initial_credentials(profile, backend):
    policy = page_policy(profile, TARGET)
    auth = AuthManager(policy, FakeClock())
    c = auth.create(1, "bridge")
    with pytest.raises(MonitorError, match="cookie_scope_denied"):
        auth.import_cookies(
            c.auth_id,
            [cookie(name="LOGIN_INFO", domain=".youtube.com", host_only=False)],
            backend_epoch=auth.backend_epoch,
            expected_revision=0,
            request_id="bad",
        )
    install(auth, c)
    lease = await auth.acquire(c.auth_id)
    auth.update_cookies(
        lease, ["LOGIN_INFO=CLIENT_STATE; Domain=.youtube.com; Path=/; Secure"], TARGET
    )
    assert "LOGIN_INFO=CLIENT_STATE" in auth.header(lease, TARGET)
    transport = create_page_transport(policy, auth)
    try:
        assert type(transport) is backend
        resolver = transport.resolver if backend is HTTPXTransport else transport.http.resolver
        assert isinstance(resolver, CloudflareDNS)
        inspector = SessionInspector(profile)
        assert inspector.profile == profile and inspector.family == "youtube"
        assert (
            inspector.inspect(SafeResponse(200, TARGET, "text/html", BODY)).state == "authenticated"
        )
    finally:
        await transport.close()


class NativeResource:
    def __init__(self, *, delayed=False):
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not delayed:
            self.release.set()

    async def close(self):
        self.started.set()
        await self.release.wait()
        self.calls += 1

    async def stop(self):
        await self.close()


async def test_browser_revocation_waits_for_old_runtime_and_never_clears_replacement_jar():
    policy = page_policy("youtube_browser_v1", TARGET)
    auth = AuthManager(policy)
    c = auth.create(1, "bridge")
    install(auth, c)
    transport = create_page_transport(policy, auth)
    lease = await auth.acquire(c.auth_id)
    await transport._prepare_lease(lease)
    browser, runtime = NativeResource(delayed=True), NativeResource()
    transport.browser, transport.runtime = browser, runtime
    transport.active = True
    revoke = asyncio.create_task(auth.revoke(c.auth_id, c.revision))
    await browser.started.wait()
    assert not transport.active and transport.context is None and transport.browser is None
    assert not revoke.done()
    install(auth, c, "NEW_SECRET", "replacement")
    replacement = await auth.acquire(c.auth_id)
    opening = asyncio.create_task(transport._prepare_lease(replacement))
    await asyncio.sleep(0)
    assert not opening.done()
    browser.release.set()
    await asyncio.gather(revoke, opening)
    assert browser.calls == runtime.calls == 1
    assert auth.header(replacement, TARGET) == "__Secure-3PSID=NEW_SECRET"
    with pytest.raises(MonitorError, match="superseded"):
        await transport._prepare_lease(lease)
    other = auth.create(1, "bridge")
    install(auth, other, "OTHER_SECRET", "other")
    with pytest.raises(MonitorError, match="binding_denied"):
        await transport._prepare_lease(await auth.acquire(other.auth_id))
    await transport.close()
    assert c.auth_id not in auth._resources


async def test_cookie_rotation_keeps_runtime_but_manual_reauthorization_clears_it():
    policy = page_policy("youtube_browser_v1", TARGET)
    auth = AuthManager(policy)
    c = auth.create(1, "bridge")
    install(auth, c)
    transport = create_page_transport(policy, auth)
    lease = await auth.acquire(c.auth_id)
    await transport._prepare_lease(lease)
    browser = NativeResource()
    transport.browser = browser
    auth.update_cookies(lease, ["LOGIN_INFO=ROTATION; Domain=.youtube.com; Path=/; Secure"], TARGET)
    assert transport.browser is browser
    install(auth, c, "NEW", "new")
    assert transport.browser is None
    await transport._prepare_lease(await auth.acquire(c.auth_id))
    assert browser.calls == 1
    await transport.close()


async def test_cancelled_revocation_does_not_cancel_credential_cleanup():
    policy = page_policy("youtube_browser_v1", TARGET)
    auth = AuthManager(policy)
    c = auth.create(1, "bridge")
    install(auth, c)
    transport = create_page_transport(policy, auth)
    await transport._prepare_lease(await auth.acquire(c.auth_id))
    browser = NativeResource(delayed=True)
    transport.browser = browser
    revoke = asyncio.create_task(auth.revoke(c.auth_id, c.revision))
    await browser.started.wait()
    revoke.cancel()
    with pytest.raises(asyncio.CancelledError):
        await revoke
    assert c.state == "revoked" and not len(c.jar)
    assert not transport._cleanup_task.cancelled()
    browser.release.set()
    await transport.close()
    assert browser.calls == 1


async def test_open_race_with_revocation_disposes_late_runtime():
    policy = page_policy("youtube_browser_v1", TARGET)
    auth = AuthManager(policy)
    c = auth.create(1, "bridge")
    install(auth, c)
    entered, release = asyncio.Event(), asyncio.Event()
    late = NativeResource()

    class SlowOpen(PlaywrightTransport):
        async def _open(self, lease):
            entered.set()
            await release.wait()
            self.browser = late
            self.auth.current(lease)

    transport = SlowOpen(policy, auth, rules=policy.browser_rules)
    task = asyncio.create_task(transport.open(await auth.acquire(c.auth_id)))
    await entered.wait()
    await auth.revoke(c.auth_id, c.revision)
    release.set()
    with pytest.raises(MonitorError, match="superseded"):
        await task
    assert late.calls == 1 and transport.browser is None
    await transport.close()


def test_browser_scope_and_debug_logging_fail_closed(monkeypatch):
    policy = page_policy("youtube_browser_v1", TARGET)
    monkeypatch.setenv("DEBUG", "pw:protocol")
    with pytest.raises(MonitorError, match="unsafe_browser_debug"):
        create_page_transport(policy, AuthManager(policy))
    monkeypatch.delenv("DEBUG")
    many = replace(policy, target_urls=(TARGET, TARGET + "/extra"))
    with pytest.raises(MonitorError, match="unsupported_browser_scope"):
        create_page_transport(many, AuthManager(many))
    with pytest.raises(ValueError, match="TLS verification"):
        create_page_transport(policy, AuthManager(policy), verify=False)


async def test_parameterized_entry_uses_standard_monitor_and_records_sink_receipt(tmp_path):
    profile = "youtube_browser_v1"
    h = Harness(
        Namespace(
            site=profile,
            target=TARGET,
            interval=600,
            duration=0,
            port=0,
            report=str(tmp_path / "run.jsonl"),
            robots_fallback="strict",
        )
    )
    try:
        assert type(h.monitor) is PageMonitor
        assert type(h.transport) is PlaywrightTransport
        h.monitor.register(h.params, owner_id=1, bridge_id="debug-browser")
        install(h.auth, h.context)
        h.auth.presence("debug-browser", 1)

        class ResponseOnly:
            async def fetch(self, plan, lease):
                return SafeResponse(200, TARGET, "text/html", BODY)

        h.monitor.transport = ResponseOnly()
        result = await h.monitor.tick()
        records = [json.loads(line) for line in h.report.read_text().splitlines()]
        receipts = [r for r in records if r["record"] == "receipt"]
        assert result["state"] == "delivered" and len(receipts) == 1
        assert receipts[0]["snapshot_id"] == result["snapshot_id"]
        assert receipts[0]["received_bytes"] == len(BODY) == result["bytes"]
        assert receipts[0]["body_sha256"] == hashlib.sha256(BODY).hexdigest() == result["sha256"]
        assert (
            "<html>" not in h.report.read_text() and "PRIVATE_BOOTSTRAP" not in h.report.read_text()
        )
    finally:
        await h.close()
