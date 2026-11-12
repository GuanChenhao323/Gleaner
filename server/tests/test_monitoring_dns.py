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
    assert len(events) == 1 and events[0]["reason"] == "primary_connect_timeout"


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
    assert [event["reason"] for event in events] == [
        "primary_connect_timeout",
        "secondary_connect_timeout",
    ]


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
