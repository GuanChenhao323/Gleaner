import asyncio
import gzip

import httpx
import pytest
from monitoring_helpers import FakeClock, Stream, cookie

from gleaner.monitoring.adapters.moodle import MoodleAdapter
from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.models import Clock, FetchPlan, MonitorError, SitePolicy
from gleaner.monitoring.transport import HTTPXTransport
from gleaner.net.http.message import http_date

URL = "https://moodle.must.edu.mo/mod/assign/view.php?id=7"


def plan():
    return FetchPlan("s", 1, None, "c", URL, (1,))


def setup(handler, **kwargs):
    clock = FakeClock()
    policy = kwargs.pop("policy", SitePolicy())
    auth = AuthManager(policy, clock)
    log, events = [], []
    state = {"not_before": 0}

    async def request(req):
        log.append((clock.mono(), req))
        status, headers, body = handler(req)
        return httpx.Response(
            status, headers=headers, stream=body if isinstance(body, Stream) else Stream(body)
        )

    async def resolver(host, port):
        return ["203.0.113.1"] if kwargs.pop("bad_ip", False) else ["1.1.1.1"]

    transport = HTTPXTransport(
        policy,
        auth,
        clock=clock,
        resolver=kwargs.pop("resolver", resolver),
        engine=httpx.MockTransport(request),
        event=events.append,
        get_not_before=lambda: state["not_before"],
        set_not_before=lambda t: state.update(not_before=t),
        **kwargs,
    )
    return transport, auth, clock, log, events, state


async def test_pinned_ip_sni_cookie_scope_and_all_hops_paced():
    def handler(req):
        if req.url.path == "/robots.txt":
            return 200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /"
        return 200, {"content-type": "text/html"}, b"<p>ok</p>"

    t, auth, _, log, events, _ = setup(handler)
    c = auth.create(1, "b")
    auth.import_cookies(
        c.auth_id, [cookie()], backend_epoch=auth.backend_epoch, expected_revision=0, request_id="i"
    )
    lease = await auth.acquire(c.auth_id)
    try:
        r = await t.fetch(plan(), lease)
        assert r.body == b"<p>ok</p>"
        assert len(log) == 2 and log[1][0] - log[0][0] >= 2
        assert all(req.url.host == "1.1.1.1" for _, req in log)
        assert all(req.headers["host"] == "moodle.must.edu.mo" for _, req in log)
        assert all(req.extensions["sni_hostname"] == "moodle.must.edu.mo" for _, req in log)
        assert log[0][1].headers["cookie"] == "MoodleSession=SYNTHETIC_SECRET"
        assert log[1][1].headers["cookie"] == "MoodleSession=SYNTHETIC_SECRET"
        assert "SYNTHETIC_SECRET" not in repr(events) and "id=7" not in repr(events)
        assert not t._client.cookies
    finally:
        await t.close()


@pytest.mark.parametrize(
    "location,code",
    [
        ("http://127.0.0.1/", "blocked"),
        ("https://login.must.edu.mo/login?ticket=SECRET", "auth_required"),
        ("/login/index.php", "auth_required"),
    ],
)
async def test_redirect_boundaries(location, code):
    t, _, _, log, _, _ = setup(
        lambda r: (
            (404, {}, b"") if r.url.path == "/robots.txt" else (302, {"location": location}, b"")
        )
    )
    try:
        with pytest.raises(MonitorError, match=code):
            await t.fetch(plan(), None)
        assert len(log) == 2
    finally:
        await t.close()


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::ffff:127.0.0.1", "224.0.0.1", "100.64.0.1"],
)
async def test_bad_dns_never_connects(address):
    async def resolver(host, port):
        return ["1.1.1.1", address]

    t, _, _, log, _, _ = setup(lambda r: (200, {}, b"ok"), resolver=resolver)
    try:
        with pytest.raises(MonitorError, match="blocked"):
            await t.fetch(plan(), None)
        assert log == []
    finally:
        await t.close()


async def test_rebinding_on_second_hop_is_blocked():
    calls = 0

    async def resolver(host, port):
        nonlocal calls
        calls += 1
        return ["1.1.1.1"] if calls < 3 else ["127.0.0.1"]

    def handler(r):
        return (404, {}, b"") if r.url.path == "/robots.txt" else (302, {"location": URL}, b"")

    t, _, _, log, _, _ = setup(handler, resolver=resolver)
    try:
        with pytest.raises(MonitorError, match="blocked"):
            await t.fetch(plan(), None)
        assert len(log) == 2
    finally:
        await t.close()


@pytest.mark.parametrize("date", [False, True])
async def test_retry_after_is_persisted_and_not_truncated(date):
    current = [0]

    def handler(r):
        if r.url.path == "/robots.txt":
            return 404, {}, b""
        return 429, {"retry-after": http_date(current[0] + 600) if date else "600"}, b"busy"

    t, _, clock, log, _, state = setup(handler)
    current[0] = clock.utc()
    try:
        with pytest.raises(MonitorError) as error:
            await t.fetch(plan(), None)
        assert error.value.code == "rate_limited" and error.value.retry_after_s >= 597
        assert state["not_before"] >= current[0] + 599
        with pytest.raises(MonitorError, match="rate_limited"):
            await t.fetch(plan(), None)
        assert len(log) == 2
    finally:
        await t.close()


@pytest.mark.parametrize(
    "body,headers,limits",
    [
        (b"x" * 101, {}, {"max_wire": 100}),
        (gzip.compress(b"x" * 1000), {"content-encoding": "gzip"}, {"max_decoded": 100}),
    ],
)
async def test_body_limits_close_response(body, headers, limits):
    stream = Stream(body)
    t, _, _, _, _, _ = setup(
        lambda r: (404, {}, b"") if r.url.path == "/robots.txt" else (200, headers, stream),
        **limits,
    )
    try:
        with pytest.raises(MonitorError, match="response_too_large"):
            await t.fetch(plan(), None)
        assert stream.closed
    finally:
        await t.close()


async def test_entire_request_deadline_and_cancel_cleanup():
    stream = Stream(b"late", delay=1)
    t, _, _, _, _, _ = setup(lambda r: (200, {}, stream), total_timeout=0.01)
    try:
        with pytest.raises(MonitorError, match="timeout"):
            await t.fetch(plan(), None)
        assert stream.closed
    finally:
        await t.close()


@pytest.mark.parametrize(
    "robot_status,robot_body,code",
    [
        (200, b"User-agent: *\nDisallow: /mod/", "robots_denied"),
        (503, b"unavailable", "upstream_5xx"),
    ],
)
async def test_robots_fail_closed(robot_status, robot_body, code):
    t, _, _, log, _, _ = setup(lambda r: (robot_status, {"content-type": "text/plain"}, robot_body))
    try:
        with pytest.raises(MonitorError, match=code):
            await t.fetch(plan(), None)
        assert len(log) == 1
    finally:
        await t.close()


async def test_missing_baseline_and_redirect_limit():
    for status, headers, code in [
        (304, {}, "missing_baseline"),
        (302, {"location": URL}, "redirect_limit"),
    ]:
        t, _, _, log, _, _ = setup(
            lambda r, status=status, headers=headers: (
                (404, {}, b"") if r.url.path == "/robots.txt" else (status, headers, b"")
            )
        )
        try:
            with pytest.raises(MonitorError, match=code):
                await t.fetch(plan(), None)
            assert len(log) <= 5
        finally:
            await t.close()


async def test_content_redirect_cannot_change_target_id():
    t, _, _, log, _, _ = setup(
        lambda r: (
            (404, {}, b"")
            if r.url.path == "/robots.txt"
            else (302, {"location": "/mod/assign/view.php?id=8"}, b"")
        )
    )
    try:
        with pytest.raises(MonitorError, match="blocked"):
            await t.fetch(plan(), None)
        assert len(log) == 2
    finally:
        await t.close()


async def test_dns_delay_cannot_shorten_actual_request_gap():
    calls = 0

    async def slow_first(host, port):
        nonlocal calls
        calls += 1
        if calls == 1:
            clock.advance(1.9)
        return ["1.1.1.1"]

    t, _, clock, log, events, _ = setup(
        lambda r: (404, {}, b"") if r.url.path == "/robots.txt" else (200, {}, b"ok"),
        resolver=slow_first,
    )
    try:
        await t.fetch(plan(), None)
        assert log[1][0] - log[0][0] >= 2
        assert [e["started_mono"] for e in events] == [at for at, _ in log]
    finally:
        await t.close()


@pytest.mark.parametrize("retry_after", [None, "3600"])
async def test_robots_rate_limit_persists_before_reading_body(retry_after):
    stream = Stream(b"late", delay=1)
    headers = {"retry-after": retry_after} if retry_after else {}
    t, _, clock, log, _, state = setup(lambda r: (429, headers, stream), total_timeout=0.05)
    try:
        with pytest.raises(MonitorError, match="rate_limited"):
            await t.fetch(plan(), None)
        assert state["not_before"] >= clock.utc() + (3600 if retry_after else 600)
        assert len(log) == 1 and stream.closed
    finally:
        await t.close()


async def test_pacing_does_not_spend_connection_budget():
    from dataclasses import replace

    t, _, _, log, _, _ = setup(
        lambda r: (404, {}, b"") if r.url.path == "/robots.txt" else (200, {}, b"ok"),
        connect_timeout=0.1,
        total_timeout=2,
    )
    t.clock = Clock()
    t.policy = replace(t.policy, host_gap_s=0.2)
    try:
        assert (await t.fetch(plan(), None)).status == 200
        assert len(log) == 2
    finally:
        await t.close()


async def test_dns_and_tcp_tls_have_separate_bounded_budgets():
    async def resolver(host, port):
        await asyncio.sleep(0.06)
        return ["1.1.1.1"]

    async def handler(request):
        await asyncio.sleep(0.06)
        return httpx.Response(200, stream=Stream(b"ok"))

    policy = SitePolicy()
    transport = HTTPXTransport(
        policy,
        AuthManager(policy),
        resolver=resolver,
        engine=httpx.MockTransport(handler),
        connect_timeout=0.1,
        total_timeout=1,
    )
    try:
        status, _, body = await transport._one(policy.origin + "/robots.txt", None, kind="robots")
        assert status == 200 and body == b"ok"
    finally:
        await transport.close()


async def test_request_evidence_uses_header_send_time_on_both_clocks():
    clock, events, sent = FakeClock(), [], []

    async def resolver(host, port):
        return ["1.1.1.1"]

    async def handler(request):
        clock.advance(0.5)
        await request.extensions["trace"]("http11.send_request_headers.started", {})
        sent.append((clock.mono(), clock.utc()))
        clock.advance(0.5)
        return httpx.Response(
            404 if request.url.path == "/robots.txt" else 200, stream=Stream(b"ok")
        )

    policy = SitePolicy()
    transport = HTTPXTransport(
        policy,
        AuthManager(policy),
        clock=clock,
        resolver=resolver,
        engine=httpx.MockTransport(handler),
        event=events.append,
    )
    try:
        await transport.fetch(plan(), None)
        assert all(e["request_start_observed"] for e in events)
        assert [(e["started_mono"], e["started_utc"]) for e in events] == sent
        assert all(e["finished_mono"] > e["started_mono"] for e in events)
    finally:
        await transport.close()


async def test_robots_uses_only_approved_session_and_cache_isolates_generations():
    def handler(r):
        if r.url.path == "/robots.txt":
            return (
                200,
                {
                    "set-cookie": "MoodleSession=ROTATED; Path=/; Secure; HttpOnly",
                    "content-type": "text/plain",
                },
                b"User-agent: *\nAllow: /",
            )
        return 200, {}, b"ok"

    t, auth, _, log, _, _ = setup(handler)
    c = auth.create(1, "b")
    auth.import_cookies(
        c.auth_id,
        [cookie()],
        backend_epoch=auth.backend_epoch,
        expected_revision=0,
        request_id="one",
    )
    try:
        await t.fetch(plan(), await auth.acquire(c.auth_id))
        assert log[1][1].headers["cookie"] == "MoodleSession=ROTATED"
        auth.import_cookies(
            c.auth_id,
            [cookie("SECOND")],
            backend_epoch=auth.backend_epoch,
            expected_revision=c.revision,
            request_id="two",
            reason="manual_reauthorize",
        )
        await t.fetch(plan(), await auth.acquire(c.auth_id))
        assert [r.url.path for _, r in log].count("/robots.txt") == 2
        assert log[2][1].headers["cookie"] == "MoodleSession=SECOND"
    finally:
        await t.close()


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (200, b'<form id="login"></form>', "auth_required"),
        (401, b"unauthorized", "auth_required"),
        (200, b"<html>Unknown page</html>", "robots_unavailable"),
    ],
)
async def test_robots_login_or_unknown_html_is_not_permission(status, body, expected):
    t, _, _, log, _, _ = setup(
        lambda r: (status, {"content-type": "text/html"}, body),
        inspect_access=MoodleAdapter().inspect,
    )
    try:
        with pytest.raises(MonitorError, match=expected):
            await t.fetch(plan(), None)
        assert len(log) == 1
    finally:
        await t.close()


@pytest.mark.parametrize(
    "location,expected",
    [("/my/?ticket=SYNTHETIC_SECRET", "/my/"), ("/SYNTHETIC_SECRET", "[unapproved_path]")],
)
async def test_redirect_diagnostics_do_not_log_parameters_or_unknown_paths(location, expected):
    t, _, _, _, events, _ = setup(lambda r: (303, {"location": location}, b"redirect"))
    try:
        with pytest.raises(MonitorError, match="blocked"):
            await t.fetch(plan(), None)
        assert events[0]["redirect_path"] == expected
        assert events[0]["redirect_same_origin"] is True
        assert "SYNTHETIC_SECRET" not in repr(events)
    finally:
        await t.close()


async def test_registered_target_fallback_is_explicit_bounded_and_logged():
    policy = SitePolicy(target_urls=(URL,))
    decisions = []

    def handler(r):
        return (
            (303, {"location": "/my/"}, b"redirect")
            if r.url.path == "/robots.txt"
            else (200, {}, b"ok")
        )

    t, auth, _, log, _, _ = setup(
        handler,
        policy=policy,
        registered_target_fallback=True,
        policy_event=decisions.append,
        inspect_access=MoodleAdapter().inspect,
    )
    c = auth.create(1, "b")
    auth.import_cookies(
        c.auth_id, [cookie()], backend_epoch=auth.backend_epoch, expected_revision=0, request_id="i"
    )
    try:
        assert (await t.fetch(plan(), await auth.acquire(c.auth_id))).status == 200
        assert [r.url.path for _, r in log] == ["/robots.txt", "/mod/assign/view.php"]
        assert decisions[0]["scope"] == "one_registered_target"
        assert t._robots[(c.auth_id, c.generation)][1].allowed("/mod/assign/view.php?id=7")
        assert not t._robots[(c.auth_id, c.generation)][1].allowed("/mod/assign/view.php?id=8")
        wrong = FetchPlan("s", 1, c.generation, "c2", URL.replace("id=7", "id=8"), (1,))
        with pytest.raises(MonitorError):
            await t.fetch(wrong, await auth.acquire(c.auth_id))
        assert len(log) == 2
    finally:
        await t.close()


@pytest.mark.parametrize(
    "status,headers,body,code",
    [
        (200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /", "robots_denied"),
        (200, {"content-type": "text/html"}, b'<form id="login"></form>', "auth_required"),
        (200, {"content-type": "text/html"}, b"<html>unknown</html>", "robots_unavailable"),
        (401, {}, b"denied", "auth_required"),
        (503, {}, b"unavailable", "upstream_5xx"),
        (303, {"location": "https://evil.example/my/"}, b"", "blocked"),
        (303, {"location": "/my/?ticket=secret"}, b"", "blocked"),
        (
            303,
            {"location": "/my/", "content-type": "text/html"},
            b'<form id="login"></form>',
            "auth_required",
        ),
    ],
)
async def test_registered_target_policy_does_not_override_rules_or_other_failures(
    status, headers, body, code
):
    t, auth, _, log, _, _ = setup(
        lambda r: (status, headers, body),
        policy=SitePolicy(target_urls=(URL,)),
        registered_target_fallback=True,
        inspect_access=MoodleAdapter().inspect,
    )
    c = auth.create(1, "b")
    auth.import_cookies(
        c.auth_id, [cookie()], backend_epoch=auth.backend_epoch, expected_revision=0, request_id="i"
    )
    try:
        with pytest.raises(MonitorError, match=code):
            await t.fetch(plan(), await auth.acquire(c.auth_id))
        assert len(log) == 1
    finally:
        await t.close()


def test_registered_target_policy_rejects_unbounded_configuration():
    with pytest.raises(ValueError, match="one explicit"):
        setup(lambda r: (200, {}, b""), registered_target_fallback=True)
    with pytest.raises(ValueError, match="authentication inspector"):
        setup(
            lambda r: (200, {}, b""),
            policy=SitePolicy(target_urls=(URL,)),
            registered_target_fallback=True,
        )


async def test_quota_group_rate_limit_blocks_other_transport_before_network():
    from gleaner.monitoring.transport import OriginPacing

    pacing = OriginPacing(2)
    a, _, _, _, _, _ = setup(lambda req: (429, {"retry-after": "60"}, b""), pacing=pacing)
    b, _, _, log, _, _ = setup(
        lambda req: (200, {"content-type": "text/plain"}, b""), pacing=pacing
    )
    try:
        with pytest.raises(MonitorError, match="rate_limited"):
            await a.fetch(plan(), None)
        with pytest.raises(MonitorError, match="rate_limited"):
            await b.fetch(plan(), None)
        assert not log
    finally:
        await a.close()
        await b.close()


async def test_revoked_session_stops_before_header_write():
    clock = FakeClock()
    policy = SitePolicy()
    auth = AuthManager(policy, clock)
    ctx = auth.create(1, "fixture")
    auth.import_cookies(
        ctx.auth_id,
        [cookie()],
        backend_epoch=auth.backend_epoch,
        expected_revision=0,
        request_id="setup",
    )
    sent = []

    async def resolver(host, port):
        return ["1.1.1.1"]

    async def send(req):
        await auth.revoke(ctx.auth_id, ctx.revision)
        await req.extensions["trace"]("http11.send_request_headers.started", {})
        sent.append(req.url.path)
        return httpx.Response(200, content=b"")

    transport = HTTPXTransport(
        policy, auth, clock=clock, resolver=resolver, engine=httpx.MockTransport(send)
    )
    try:
        with pytest.raises(MonitorError, match="superseded"):
            await transport.fetch(plan(), await auth.acquire(ctx.auth_id))
        assert not sent
    finally:
        await transport.close()


async def test_redirect_uses_robots_rules_for_originating_session_even_after_another_read():
    from gleaner.monitoring.profiles import PagePolicy
    from gleaner.monitoring.transport import OriginPacing

    origin = "https://moodle.must.edu.mo"
    first, second = origin + "/first", origin + "/second"
    policy = PagePolicy(
        origin=origin,
        target_urls=(first, second),
        cookie_domains=("moodle.must.edu.mo",),
        host_gap_s=0,
    )
    auth = AuthManager(policy)
    leases = []
    for value in ("A", "B"):
        ctx = auth.create(1, value)
        auth.import_cookies(
            ctx.auth_id,
            [cookie(value)],
            backend_epoch=auth.backend_epoch,
            expected_revision=0,
            request_id=value,
        )
        leases.append(await auth.acquire(ctx.auth_id))
    first_waiting, release = asyncio.Event(), asyncio.Event()
    called = []

    async def resolver(host, port):
        return ["1.1.1.1"]

    async def send(req):
        await req.extensions["trace"]("http11.send_request_headers.started", {})
        await req.extensions["trace"]("http11.send_request_headers.complete", {})
        a = req.headers["cookie"].endswith("=A")
        called.append((a, req.url.path))
        if req.url.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /second" if a else b"User-agent: *\nAllow: /"
            return httpx.Response(200, headers={"Content-Type": "text/plain"}, stream=Stream(body))
        if req.url.path == "/first":
            first_waiting.set()
            await release.wait()
            return httpx.Response(302, headers={"Location": second}, stream=Stream(b""))
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, stream=Stream(b"<p>ok</p>")
        )

    transport = HTTPXTransport(
        policy, auth, resolver=resolver, engine=httpx.MockTransport(send), pacing=OriginPacing(2)
    )
    task = asyncio.create_task(transport.fetch(FetchPlan("a", 1, 1, "a", first, ()), leases[0]))
    try:
        await asyncio.wait_for(first_waiting.wait(), 2)
        await asyncio.wait_for(transport.fetch(FetchPlan("b", 1, 1, "b", second, ()), leases[1]), 2)
        release.set()
        with pytest.raises(MonitorError, match="robots_denied"):
            await task
        assert (True, "/second") not in called
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await transport.close()
