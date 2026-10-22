"""抓取器：条件请求、robots.txt、按主机限速、指数退避 + 抖动重试、熔断。"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

from ..net.http import ClientResponse, CookieJar, HTTPClient, HTTPError
from ..obs.metrics import REGISTRY

FETCHES = REGISTRY.counter("gleaner_fetch_total", "采集请求数", ("status",))
FETCH_SECONDS = REGISTRY.histogram("gleaner_fetch_seconds", "单次采集请求耗时")
FETCH_BYTES = REGISTRY.counter("gleaner_fetch_bytes_total", "采集下载字节数")


class FetchError(Exception):
    """kind: network / timeout / http / parse / need_login / robots / circuit_open"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class _HostState:
    next_allowed: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    robots: list[str] | None = None  # Disallow 前缀
    crawl_delay: float = 0.0
    robots_at: float = 0.0


class Fetcher:
    def __init__(
        self,
        client: HTTPClient | None = None,
        *,
        min_interval: float = 0.5,
        retries: int = 2,
        backoff: float = 0.5,
        respect_robots: bool = True,
    ) -> None:
        self.client = client or HTTPClient(per_host_limit=4, total_limit=64)
        self.min_interval = min_interval
        self.retries = retries
        self.backoff = backoff
        self.respect_robots = respect_robots
        self._hosts: dict[str, _HostState] = {}

    async def close(self) -> None:
        await self.client.close()

    def _host(self, url: str) -> tuple[str, _HostState]:
        p = urlsplit(url)
        key = f"{p.scheme}://{p.netloc}"
        return key, self._hosts.setdefault(key, _HostState())

    async def _robots(self, base: str, st: _HostState) -> None:
        if st.robots is not None and time.time() - st.robots_at < 3600:
            return
        st.robots, st.robots_at = [], time.time()
        try:
            r = await self.client.get(urljoin(base, "/robots.txt"), timeout=5)
        except HTTPError:
            return
        if r.status != 200:
            return
        applies = False
        for raw in r.text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                applies = v == "*" or "gleaner" in v.lower()
            elif applies and k == "disallow" and v:
                st.robots.append(v)
            elif applies and k == "crawl-delay":
                try:
                    st.crawl_delay = min(float(v), 10.0)
                except ValueError:
                    pass

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        etag: str | None = None,
        last_modified: str | None = None,
        cookies: CookieJar | None = None,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        follow_redirects: bool = True,
    ) -> ClientResponse:
        base, st = self._host(url)
        if self.respect_robots:
            await self._robots(base, st)
            path = urlsplit(url).path or "/"
            if any(path.startswith(d) for d in st.robots or []):
                raise FetchError("robots", f"disallowed by robots.txt: {path}")
        h = dict(headers or {})
        if etag:
            h["If-None-Match"] = etag
        if last_modified:
            h["If-Modified-Since"] = last_modified
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            # 按主机限速：同一主机两次请求之间至少间隔 min_interval / Crawl-delay
            async with st.lock:
                wait = st.next_allowed - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                st.next_allowed = time.monotonic() + max(self.min_interval, st.crawl_delay)
            t0 = time.perf_counter()
            try:
                r = await self.client.request(
                    method,
                    url,
                    headers=h,
                    body=body,
                    cookies=cookies,
                    follow_redirects=follow_redirects,
                )
            except HTTPError as e:
                FETCHES.inc(1, e.kind)
                last_err = e
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff * 2**attempt * (0.5 + random.random()))
                    continue
                raise FetchError("timeout" if e.kind == "timeout" else "network", str(e)) from e
            FETCH_SECONDS.observe(time.perf_counter() - t0)
            FETCH_BYTES.inc(len(r.body))
            FETCHES.inc(1, str(r.status))
            if r.status >= 500 or r.status == 429:
                last_err = FetchError("http", f"HTTP {r.status}")
                if attempt < self.retries:
                    ra = r.headers.get("Retry-After")
                    delay = (
                        float(ra)
                        if ra and ra.isdigit()
                        else self.backoff * 2**attempt * (0.5 + random.random())
                    )
                    await asyncio.sleep(min(delay, 30))
                    continue
                raise FetchError("http", f"HTTP {r.status}")
            return r
        raise FetchError("network", str(last_err))


@dataclass
class CircuitBreaker:
    """连续失败的源进入熔断，冷却期内直接跳过，不拖累其他源。"""

    threshold: int = 5
    cooldown: float = 600.0
    failures: dict[int, int] = field(default_factory=dict)
    opened_at: dict[int, float] = field(default_factory=dict)

    def allow(self, source_id: int) -> bool:
        t = self.opened_at.get(source_id)
        if t is None:
            return True
        if time.time() - t > self.cooldown:
            # 半开：允许一次试探
            del self.opened_at[source_id]
            return True
        return False

    def record(self, source_id: int, ok: bool) -> None:
        if ok:
            self.failures.pop(source_id, None)
            self.opened_at.pop(source_id, None)
            return
        n = self.failures.get(source_id, 0) + 1
        self.failures[source_id] = n
        if n >= self.threshold:
            self.opened_at[source_id] = time.time()

    def snapshot(self) -> dict[str, Any]:
        return {"open": sorted(self.opened_at), "failures": dict(self.failures)}
