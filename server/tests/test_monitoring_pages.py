import asyncio

import pytest
from monitoring_helpers import FakeClock, cookie

from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.models import MonitorError, SafeResponse
from gleaner.monitoring.pages import HTMLReceipt, PageMonitor
from gleaner.monitoring.profiles import SessionInspector, page_policy

URL = "https://www.youtube.com/@3blue1brown/videos"
BODY = (
    b'<html><script>ytcfg.set({"LOGGED_IN":true});</script><script>{"videos":["C"]}</script></html>'
)


@pytest.mark.parametrize(
    ("exported", "expected"),
    [(None, "unspecified"), ("None", "none"), ("Lax", "lax"), ("strict", "strict")],
)
def test_cookie_editor_same_site_values_are_normalized(exported, expected):
    from devtools.monitoring.page_run import normalize

    records = normalize([{"name": "SID", "sameSite": exported}], ("SID",))
    assert records[0]["same_site"] == expected


async def test_cookie_diagnostics_record_rotation_and_removal_without_values():
    from devtools.monitoring.page_run import DiagnosticAuthManager

    events = []
    auth = DiagnosticAuthManager(page_policy("youtube", URL), events.append)
    c = auth.create(1, "bridge")
    auth.import_cookies(
        c.auth_id,
        [cookie("PRIVATE_VALUE", name="SID", domain=".youtube.com", host_only=False)],
        backend_epoch=auth.backend_epoch,
        expected_revision=0,
        request_id="i",
    )
    lease = await auth.acquire(c.auth_id)
    auth.update_cookies(
        lease,
        [
            "SID=ROTATED_SECRET; Domain=.youtube.com; Path=/; Secure",
            "PRIVATE_COOKIE=OTHER_SECRET; Path=/; Secure",
        ],
        URL,
    )
    assert events[0]["changed_names"] == ["SID"]
    assert events[0]["received_count"] == 2
    assert events[0]["received_registered_names"] == ["SID"]
    auth.update_cookies(lease, ["SID=; Domain=youtube.com; Path=/; Secure; Max-Age=0"], URL)
    assert events[1]["removed_names"] == ["SID"]
    assert all(value not in repr(events) for value in ("SECRET", "PRIVATE", ".youtube.com"))


def test_bilibili_diagnostics_report_structure_without_page_contents():
    from devtools.monitoring.page_run import DiagnosticSessionInspector

    events = []
    inspector = DiagnosticSessionInspector("bilibili", events.append)
    body = b'<script>window.__INITIAL_STATE__={"videoData":{"title":"PRIVATE_TEXT"}};</script>'
    verdict = inspector.inspect(SafeResponse(200, URL, "text/html", body))
    assert verdict.state == "unknown"
    assert events[0]["initial_state_objects"] == 1
    assert events[0]["initial_state_login_info"] is False
    assert "PRIVATE_TEXT" not in repr(events)


def test_youtube_diagnostics_count_conflicting_flags_without_page_contents():
    from devtools.monitoring.page_run import DiagnosticSessionInspector

    events = []
    inspector = DiagnosticSessionInspector("youtube", events.append)
    body = (
        b'<script>ytcfg.set({"LOGGED_IN":false,"DATASYNC_ID":"PRIVATE_TEXT"});</script>'
        b'<script>ytcfg.set({"LOGGED_IN":true});</script>'
    )
    verdict = inspector.inspect(SafeResponse(200, URL, "text/html", body))
    assert verdict.state == "auth_required"
    assert events[0]["logged_in_true"] == events[0]["logged_in_false"] == 1
    assert "PRIVATE_TEXT" not in repr(events)


def setup(body=BODY):
    clock = FakeClock()
    policy = page_policy("youtube", URL)
    auth = AuthManager(policy, clock)
    c = auth.create(1, "bridge")
    auth.import_cookies(
        c.auth_id,
        [cookie(name="SID", domain=".youtube.com", host_only=False)],
        backend_epoch=auth.backend_epoch,
        expected_revision=0,
        request_id="i",
    )
    auth.presence("bridge", 1)
    requests = []

    async def fetch(plan, lease):
        requests.append((clock.mono(), plan, lease))
        return SafeResponse(200, URL, "text/html; charset=utf-8", body)

    class Transport:
        async def fetch(self, plan, lease):
            return await fetch(plan, lease)

    snapshots = []

    class Sink:
        fail = False

        async def accept(self, snapshot):
            snapshots.append(snapshot)
            if self.fail:
                raise RuntimeError("SYNTHETIC_SECRET")
            return HTMLReceipt(snapshot.snapshot_id, True)

    sink = Sink()
    monitor = PageMonitor(policy, auth, Transport(), SessionInspector("youtube"), sink, clock=clock)
    task = monitor.register(
        {
            "target_url": URL,
            "interval_s": 600,
            "auth_context_id": c.auth_id,
            "site_profile": "youtube",
        },
        owner_id=1,
        bridge_id="bridge",
    )
    return monitor, auth, c, clock, requests, snapshots, sink, task


async def test_upstream_task_delivers_full_html_without_item_identity():
    monitor, _, _, _, requests, snapshots, _, _ = setup()
    result = await monitor.tick()
    assert result["state"] == "delivered"
    assert len(requests) == 1 and snapshots[0].body == BODY
    assert not hasattr(snapshots[0], "item_id") and not hasattr(snapshots[0], "title")
    assert "SYNTHETIC_SECRET" not in repr(snapshots[0]) + repr(result)
    assert BODY.decode() not in repr(snapshots[0]) + repr(result)


async def test_failed_delivery_replays_same_snapshot_without_refetch():
    monitor, _, _, clock, requests, snapshots, sink, _ = setup()
    sink.fail = True
    assert (await monitor.tick())["state"] == "delivery_pending"
    first = snapshots[0]
    assert monitor.last_delivery_at is None
    clock.advance(61)
    sink.fail = False
    assert (await monitor.tick())["state"] == "delivered"
    assert len(requests) == 1 and snapshots == [first, first]


async def test_revoke_drops_pending_html():
    monitor, auth, c, clock, requests, snapshots, sink, _ = setup()
    sink.fail = True
    await monitor.tick()
    await auth.revoke(c.auth_id, c.revision)
    clock.advance(61)
    sink.fail = False
    assert (await monitor.tick())["state"] == "superseded"
    assert monitor.pending is None and len(snapshots) == 1 and len(requests) == 1


async def test_intervals_and_browser_presence_are_not_remote_keepalive():
    monitor, auth, _, clock, requests, _, _, _ = setup()
    await monitor.tick()
    clock.advance(100)
    assert await monitor.tick() is None
    clock.advance(501)
    assert (await monitor.tick())["state"] == "waiting_browser"
    auth.presence("bridge", 2)
    assert (await monitor.tick())["state"] == "delivered"
    assert len(requests) == 2 and requests[1][0] - requests[0][0] >= 600


@pytest.mark.parametrize(
    "body,code",
    [
        (b"<html>empty</html>", "auth_unverified"),
        (b'<script>ytcfg.set({"LOGGED_IN":false});</script>', "auth_required"),
    ],
)
async def test_http_200_alone_does_not_verify_authenticated_html(body, code):
    monitor, _, _, _, _, snapshots, _, _ = setup(body)
    result = await monitor.tick()
    assert result["error"] == code and not snapshots and monitor.last_fetch_at is None


def test_bad_task_parameters_and_owner_binding():
    monitor, _, c, _, _, _, _, _ = setup()
    base = {
        "target_url": URL,
        "interval_s": 600,
        "auth_context_id": c.auth_id,
        "site_profile": "youtube",
    }
    for change in [
        {"interval_s": 0},
        {"interval_s": True},
        {"interval_s": float("nan")},
        {"target_url": "https://evil.example/"},
        {"site_profile": "bilibili"},
        {"auth_context_id": "missing"},
        {"cookie": "secret"},
    ]:
        with pytest.raises(MonitorError):
            monitor.register({**base, **change}, owner_id=1, bridge_id="bridge")
    with pytest.raises(MonitorError, match="binding_denied"):
        monitor.register(base, owner_id=2, bridge_id="bridge")


async def test_overlapping_ticks_do_not_duplicate_request():
    monitor, _, _, _, requests, snapshots, _, _ = setup()
    await asyncio.gather(monitor.tick(), monitor.tick())
    assert len(requests) == len(snapshots) == 1


async def test_actual_transport_delivers_embedded_json_and_rotates_cookie():
    import httpx
    from monitoring_helpers import Stream

    from gleaner.monitoring.transport import HTTPXTransport

    monitor, auth, _c, clock, _, snapshots, _, _ = setup()
    requests = []

    async def handler(req):
        requests.append(req)
        if req.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                stream=Stream(b"User-agent: *\nAllow: /"),
            )
        return httpx.Response(
            200,
            headers={
                "content-type": "text/html",
                "set-cookie": "SID=ROTATED; Domain=youtube.com; Path=/; Secure",
            },
            stream=Stream(BODY),
        )

    async def resolver(host, port):
        return ["1.1.1.1"]

    transport = HTTPXTransport(
        monitor.policy, auth, clock=clock, resolver=resolver, engine=httpx.MockTransport(handler)
    )
    monitor.transport = transport
    try:
        assert (await monitor.tick())["state"] == "delivered"
        assert snapshots[0].body == BODY
        clock.advance(601)
        auth.presence("bridge", 2)
        assert (await monitor.tick())["state"] == "delivered"
        assert requests[-1].headers["cookie"] == "SID=ROTATED"
        assert requests[-1].headers["host"] == "www.youtube.com"
        assert requests[-1].extensions["sni_hostname"] == "www.youtube.com"
        assert not transport._client.cookies
    finally:
        await transport.close()


async def test_configuration_change_discards_inflight_response():
    monitor, _, _, _, _, snapshots, _, _task = setup()
    entered, release = asyncio.Event(), asyncio.Event()

    class Delayed:
        async def fetch(self, plan, lease):
            entered.set()
            await release.wait()
            return SafeResponse(200, URL, "text/html", BODY)

    monitor.transport = Delayed()
    pending = asyncio.create_task(monitor.tick())
    await entered.wait()
    monitor.pause()
    release.set()
    assert (await pending)["state"] == "superseded"
    assert not snapshots


async def test_debug_upstream_only_accepts_loopback_origin_and_reports_no_secret(tmp_path):
    from argparse import Namespace

    import httpx
    from devtools.monitoring.page_run import Harness

    harness = Harness(
        Namespace(
            site="youtube",
            target=URL,
            interval=600,
            duration=0,
            port=0,
            report=str(tmp_path / "run.jsonl"),
            robots_fallback="strict",
        )
    )
    await harness.setup()
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            rejected = await client.post(
                harness.origin + "/control",
                headers={"Origin": "https://evil.example"},
                json={"action": "start"},
            )
            assert rejected.status_code == 403
            record = {
                "name": "SID",
                "value": "SYNTHETIC_SECRET",
                "domain": ".youtube.com",
                "path": "/",
                "hostOnly": False,
                "secure": True,
                "httpOnly": True,
                "session": True,
                "sameSite": "lax",
            }
            response = await client.post(
                harness.origin + "/control",
                headers={"Origin": harness.origin, "X-Debug-Token": harness.token},
                json={"action": "start", "params": harness.params, "cookies": [record]},
            )
            assert response.status_code == 200
            harness.request_event({"kind": "content", "status": 200})
            state = await client.get(harness.origin + "/state")
            assert state.json()["cookie_count"] == 1 and "SYNTHETIC_SECRET" not in state.text
            report = (tmp_path / "run.jsonl").read_text()
            assert '"cookie_count": 1' in report and '"cookie_revision": 1' in report
            assert "SYNTHETIC_SECRET" not in report
    finally:
        await harness.close()
    assert len(harness.context.jar) == 0


async def test_recovery_rechecks_only_after_persisted_site_and_profile_budget():
    monitor, auth, ctx, clock, requests, _, _, task = setup()
    assert (await monitor.tick())["state"] == "delivered"
    budget = monitor.access_not_before
    assert budget == clock.utc() + monitor.policy.min_interval_s
    host_budget = budget + 120
    assert monitor.queue_recovery(host_budget) == host_budget
    clock.advance(host_budget - clock.utc() - 1)
    assert await monitor.tick(authorized_offline=True) is None
    clock.advance(1)
    assert (await monitor.tick(authorized_offline=True))["state"] == "delivered"
    await auth.revoke(ctx.auth_id, ctx.revision)
    clock.advance(task.interval_s)
    assert (await monitor.tick(authorized_offline=True))["state"] == "waiting_browser"
    assert len(requests) == 2
