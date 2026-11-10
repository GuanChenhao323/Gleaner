"""Opt-in public-address lookup for debug hosts using a system Fake-IP resolver.

Cloudflare JSON DoH: https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/
HTTPX Host/SNI pinning: https://www.python-httpx.org/advanced/extensions/#sni-hostname
This helper receives a hostname only; it has no access to authentication contexts.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
from urllib.parse import urlencode

import httpx
from gleaner.collector.fetcher import parse_retry_after
from gleaner.monitoring.models import Clock, MonitorError


class CloudflareDNS:
    host = "cloudflare-dns.com"
    bootstrap = "https://1.1.1.1/dns-query"

    def __init__(
        self,
        allowed_host: str,
        *,
        clock: Clock | None = None,
        engine: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.allowed_host = allowed_host
        self.clock = clock or Clock()
        self.engine = engine
        self.cached: tuple[float, list[str]] | None = None
        self.not_before = 0.0

    async def __call__(self, host: str, port: int) -> list[str]:
        if host != self.allowed_host:
            raise MonitorError("blocked")
        if self.not_before > self.clock.utc():
            raise MonitorError(
                "dns_rate_limited",
                retryable=True,
                retry_after_s=self.not_before - self.clock.utc(),
            )
        if self.cached and self.cached[0] > self.clock.mono():
            return self.cached[1].copy()
        request = httpx.Request(
            "GET",
            self.bootstrap + "?" + urlencode({"name": host, "type": "A"}),
            headers={
                "Host": self.host,
                "Accept": "application/dns-json",
                "Accept-Encoding": "identity",
            },
            extensions={
                "sni_hostname": self.host,
                "timeout": {"connect": 3, "read": 5, "write": 3, "pool": 3},
            },
        )
        try:
            async with (
                asyncio.timeout(5),
                httpx.AsyncClient(
                    transport=self.engine
                    or httpx.AsyncHTTPTransport(retries=0, trust_env=False),
                    trust_env=False,
                    follow_redirects=False,
                ) as client,
            ):
                response = await client.send(
                    request, stream=True, follow_redirects=False
                )
                try:
                    if response.status_code in (429, 503):
                        delay = parse_retry_after(
                            response.headers.get("retry-after"), self.clock.utc()
                        )
                        delay = 600 if delay is None else delay
                        self.not_before = self.clock.utc() + delay
                        raise MonitorError(
                            "dns_rate_limited", retryable=True, retry_after_s=delay
                        )
                    if response.status_code != 200 or response.headers.get(
                        "content-encoding", "identity"
                    ) not in ("", "identity"):
                        raise MonitorError("dns", retryable=True)
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise MonitorError("dns", retryable=True)
                    data = json.loads(body)
                finally:
                    await response.aclose()
            if (
                not isinstance(data, dict)
                or type(data.get("Status")) is not int
                or data["Status"] != 0
            ):
                raise MonitorError("dns", retryable=True)
            addresses, ttls = [], []
            for answer in data.get("Answer", []):
                if answer.get("type") != 1:
                    continue
                address = ipaddress.ip_address(answer["data"])
                ttl = float(answer["TTL"])
                if (
                    address.version != 4
                    or not address.is_global
                    or not math.isfinite(ttl)
                    or ttl < 0
                ):
                    raise MonitorError("blocked")
                addresses.append(str(address))
                ttls.append(ttl)
            if not addresses:
                raise MonitorError("dns", retryable=True)
            self.cached = (self.clock.mono() + min(300, *ttls), addresses)
            return addresses.copy()
        except MonitorError:
            raise
        except (
            httpx.HTTPError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ):
            raise MonitorError("dns", retryable=True) from None
