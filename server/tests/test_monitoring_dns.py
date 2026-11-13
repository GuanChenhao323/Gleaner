import asyncio
import json

import httpx
import pytest
from monitoring.dns import CloudflareDNS
from monitoring_helpers import FakeClock, Stream

from gleaner.monitoring.models import MonitorError


async def test_doh_pins_bootstrap_sni_has_no_credentials_and_honours_ttl():
    seen = []
    clock = FakeClock()

    async def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            stream=Stream(
                json.dumps(
                    {"Status": 0, "Answer": [{"type": 1, "data": "1.1.1.1", "TTL": 30}]}
                ).encode()
            ),
        )

    resolver = CloudflareDNS("moodle.must.edu.mo", clock=clock, engine=httpx.MockTransport(handler))
    assert await resolver("moodle.must.edu.mo", 443) == ["1.1.1.1"]
    assert await resolver("moodle.must.edu.mo", 443) == ["1.1.1.1"]
    assert len(seen) == 1
    request = seen[0]
    assert request.url.host == "1.1.1.1" and request.headers["host"] == "cloudflare-dns.com"
    assert request.extensions["sni_hostname"] == "cloudflare-dns.com"
    assert "cookie" not in request.headers and "authorization" not in request.headers
    clock.advance(31)
    await resolver("moodle.must.edu.mo", 443)
    assert len(seen) == 2
    with pytest.raises(MonitorError, match="blocked"):
        await resolver("another.example", 443)


async def test_doh_connect_timeout_uses_recorded_same_provider_fallback():
    seen, events = [], []

    async def handler(request):
        seen.append(request)
        if request.url.host == "1.1.1.1":
            raise httpx.ConnectTimeout("synthetic timeout", request=request)
        return httpx.Response(
            200,
            stream=Stream(
                json.dumps(
                    {"Status": 0, "Answer": [{"type": 1, "data": "1.1.1.1", "TTL": 30}]}
                ).encode()
            ),
        )

    resolver = CloudflareDNS(
        "moodle.must.edu.mo", engine=httpx.MockTransport(handler), event=events.append
    )
    assert await resolver("moodle.must.edu.mo", 443) == ["1.1.1.1"]
    assert [request.url.host for request in seen] == ["1.1.1.1", "1.0.0.1"]
    assert all(request.headers["host"] == "cloudflare-dns.com" for request in seen)
    assert all(request.extensions["sni_hostname"] == "cloudflare-dns.com" for request in seen)
    assert all(
        "cookie" not in request.headers and "authorization" not in request.headers
        for request in seen
    )
    assert events[0]["reason"] == "primary_connect_timeout"
    assert events[-1]["kind"] == "dns_resolved" and events[-1]["endpoint"] == "secondary"


async def test_doh_retries_within_budget_after_both_bootstraps_timeout():
    seen, events = [], []

    async def handler(request):
        seen.append(request.url.host)
        if len(seen) < 3:
            raise httpx.ConnectTimeout("synthetic timeout", request=request)
        return httpx.Response(
            200,
            stream=Stream(
                json.dumps(
                    {"Status": 0, "Answer": [{"type": 1, "data": "1.1.1.1", "TTL": 30}]}
                ).encode()
            ),
        )

    resolver = CloudflareDNS(
        "moodle.must.edu.mo", engine=httpx.MockTransport(handler), event=events.append
    )
    assert await resolver("moodle.must.edu.mo", 443) == ["1.1.1.1"]
    assert seen == ["1.1.1.1", "1.0.0.1", "1.1.1.1"]
    assert [event["reason"] for event in events if event["kind"] == "dns_fallback"] == [
        "primary_connect_timeout",
        "secondary_connect_timeout",
    ]


async def test_doh_whole_attempt_timeout_leaves_budget_for_the_other_endpoint():
    seen, events = [], []

    async def handler(request):
        seen.append(request.url.host)
        if request.url.host == "1.1.1.1":
            # A stalled TLS handshake or body must not consume the entire DNS budget.
            await asyncio.sleep(1)
        return httpx.Response(
            200,
            stream=Stream(
                json.dumps(
                    {"Status": 0, "Answer": [{"type": 1, "data": "8.8.8.8", "TTL": 0}]}
                ).encode()
            ),
        )

    resolver = CloudflareDNS(
        "moodle.must.edu.mo",
        engine=httpx.MockTransport(handler),
        event=events.append,
        attempt_timeout=0.05,
        total_timeout=0.3,
    )
    assert await resolver("moodle.must.edu.mo", 443) == ["8.8.8.8"]
    assert seen == ["1.1.1.1", "1.0.0.1"]
    # A fresh lookup starts with the last working endpoint, without extending TTL.
    assert await resolver("moodle.must.edu.mo", 443) == ["8.8.8.8"]
    assert seen[-1] == "1.0.0.1" and len(seen) == 3
    assert any(e["kind"] == "dns_fallback" for e in events)


async def test_doh_timeout_of_last_attempt_is_recorded_and_all_streams_close():
    streams, events = [], []

    async def handler(request):
        stream = Stream(b"{}", delay=1)
        streams.append(stream)
        return httpx.Response(200, stream=stream)

    resolver = CloudflareDNS(
        "moodle.must.edu.mo",
        engine=httpx.MockTransport(handler),
        event=events.append,
        attempt_timeout=0.02,
        total_timeout=0.2,
    )
    with pytest.raises(MonitorError, match="dns"):
        await resolver("moodle.must.edu.mo", 443)
    assert len(streams) == 3 and all(s.closed for s in streams)
    assert events[-1]["kind"] == "dns_failure"
    assert events[-1]["phase"] == "body"


async def test_doh_overall_deadline_cancels_and_records_terminal_phase():
    events = []

    async def handler(request):
        await request.extensions["trace"]("connection.start_tls.started", {})
        await asyncio.sleep(1)

    resolver = CloudflareDNS(
        "moodle.must.edu.mo",
        engine=httpx.MockTransport(handler),
        event=events.append,
        attempt_timeout=0.04,
        total_timeout=0.07,
    )
    with pytest.raises(MonitorError, match="dns"):
        await asyncio.wait_for(resolver("moodle.must.edu.mo", 443), timeout=0.5)
    assert events[-1]["kind"] == "dns_failure"
    assert events[-1]["reason"] == "budget_exhausted"
    assert events[-1]["phase"] == "tls"


async def test_doh_tls_failure_is_not_retryable_or_hidden_by_other_endpoint():
    seen = []

    async def handler(request):
        seen.append(request.url.host)
        raise httpx.ConnectError("CERTIFICATE_VERIFY_FAILED SYNTHETIC_SECRET")

    resolver = CloudflareDNS("moodle.must.edu.mo", engine=httpx.MockTransport(handler))
    with pytest.raises(MonitorError, match="dns_tls") as caught:
        await resolver("moodle.must.edu.mo", 443)
    assert not caught.value.retryable and seen == ["1.1.1.1"]
    assert "SYNTHETIC_SECRET" not in str(caught.value)


@pytest.mark.parametrize("failure", ["rate_limit", "certificate"])
async def test_doh_does_not_fallback_on_rate_limit_or_tls_error(failure):
    seen = []

    async def handler(request):
        seen.append(request.url.host)
        if failure == "rate_limit":
            return httpx.Response(429, headers={"retry-after": "600"}, stream=Stream(b""))
        raise httpx.ConnectError("CERTIFICATE_VERIFY_FAILED", request=request)

    resolver = CloudflareDNS("moodle.must.edu.mo", engine=httpx.MockTransport(handler))
    with pytest.raises(
        MonitorError, match="dns_rate_limited" if failure == "rate_limit" else "dns"
    ):
        await resolver("moodle.must.edu.mo", 443)
    assert seen == ["1.1.1.1"]


@pytest.mark.parametrize(
    "data",
    [
        {"Status": 3},
        {"Status": 0, "Answer": []},
        {"Status": 0, "Answer": [{"type": 1, "data": "198.18.0.1", "TTL": 30}]},
        {"Status": 0, "Answer": [{"type": 1, "data": "127.0.0.1", "TTL": 30}]},
        {"Status": 0, "Answer": [{"type": 1, "data": "1.1.1.1", "TTL": -1}]},
    ],
)
async def test_invalid_or_nonpublic_doh_answers_fail_closed(data):
    async def handler(request):
        return httpx.Response(200, stream=Stream(json.dumps(data).encode()))

    resolver = CloudflareDNS("moodle.must.edu.mo", engine=httpx.MockTransport(handler))
    with pytest.raises(MonitorError):
        await resolver("moodle.must.edu.mo", 443)


async def test_doh_redirect_and_large_body_are_rejected():
    for status, body in [(302, b""), (200, b" " * 65537)]:

        async def handler(request, status=status, body=body):
            return httpx.Response(
                status, headers={"location": "https://evil.example"}, stream=Stream(body)
            )

        resolver = CloudflareDNS("moodle.must.edu.mo", engine=httpx.MockTransport(handler))
        with pytest.raises(MonitorError, match="dns"):
            await resolver("moodle.must.edu.mo", 443)


@pytest.mark.parametrize(
    "addresses,fallback",
    [
        (["198.18.0.27", "2001:2::1d"], True),
        (["198.19.255.254"], True),
        (["1.1.1.1"], False),
        (["127.0.0.1"], False),
        (["198.18.0.27", "10.0.0.1"], False),
        ([], False),
    ],
)
async def test_proxy_dns_only_reresolves_fake_ip(addresses, fallback):
    from gleaner.monitoring.transport import ProxyCompatibleDNS

    calls = []

    async def system(host, port):
        return addresses

    async def public(host, port):
        calls.append((host, port))
        return ["8.8.8.8"]

    resolver = ProxyCompatibleDNS("moodle.must.edu.mo", system=system, public=public)
    result = await resolver("moodle.must.edu.mo", 443)
    assert result == (["8.8.8.8"] if fallback else addresses)
    assert bool(calls) == fallback
    with pytest.raises(MonitorError, match="blocked"):
        await resolver("other.example", 443)


async def test_default_transport_uses_fallback_and_still_rejects_private_doh(monkeypatch):
    import gleaner.monitoring.transport as module
    from gleaner.monitoring.auth import AuthManager
    from gleaner.monitoring.models import SitePolicy

    async def system(host, port):
        return ["198.18.0.27", "2001:2::1d"]

    async def public(self, host, port):
        return ["127.0.0.1"]

    monkeypatch.setattr(module.CloudflareDNS, "__call__", public)
    policy = SitePolicy()
    transport = module.HTTPXTransport(policy, AuthManager(policy))
    transport.resolver.system = system
    try:
        with pytest.raises(MonitorError, match="blocked"):
            await transport._ip("https://moodle.must.edu.mo/robots.txt")
    finally:
        await transport.close()
