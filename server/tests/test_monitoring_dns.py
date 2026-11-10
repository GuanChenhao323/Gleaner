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
