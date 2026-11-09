"""抓取器：条件请求、robots.txt（RFC 9309）、按主机限速、Retry-After（RFC 9110 §10.2.3）、
指数退避 + 抖动重试、逐跳重定向、熔断。"""

from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

from ..net.http import ClientResponse, CookieJar, HTTPClient, HTTPError
from ..net.http.message import parse_http_date
from ..obs.metrics import REGISTRY

FETCHES = REGISTRY.counter("gleaner_fetch_total", "采集请求数", ("status",))
FETCH_SECONDS = REGISTRY.histogram("gleaner_fetch_seconds", "单次采集请求耗时")
FETCH_BYTES = REGISTRY.counter("gleaner_fetch_bytes_total", "采集下载字节数")

REDIRECTS = (301, 302, 303, 307, 308)
MAX_REDIRECTS = 5
INLINE_RETRY_MAX = 30.0  # Retry-After 不超过这个秒数就在本次检查里等待重试；更长则推迟整个来源
ROBOTS_TTL = 3600.0
ROBOTS_UNREACHABLE_TTL = 300.0
_CREDENTIAL_HEADERS = ("authorization", "proxy-authorization", "cookie")


class FetchError(Exception):
    """kind: network / timeout / http / parse / need_login / robots / circuit_open / blocked

    ``retry_after``：服务端要求的最短等待秒数（429 / 503 的 Retry-After），调度器据此推迟下次检查。
    """

    def __init__(self, kind: str, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """RFC 9110 §10.2.3：delay-seconds 或 HTTP-date；无法解析返回 None，已过去的日期返回 0。"""
    if not value:
        return None
    v = value.strip()
    if v.isdigit():
        return float(int(v))
    t = parse_http_date(v)
    if t is None:
        return None
    return max(0.0, t - (now if now is not None else time.time()))


# ---- robots.txt（RFC 9309） -----------------------------------------------------


@dataclass
class RobotsRules:
    rules: list[tuple[bool, str, re.Pattern[str]]] = field(
        default_factory=list
    )  # (allow, 原文, 正则)
    crawl_delay: float = 0.0
    disallow_all: bool = False  # robots.txt 无法获取（5xx / 网络错误）：§2.3.1.4 视为全部禁止

    def allowed(self, path: str) -> bool:
        """§2.2.2：取最长匹配的规则；Allow 与 Disallow 一样长时 Allow 优先；没有规则匹配就允许。"""
        if path == "/robots.txt":
            return True
        if self.disallow_all:
            return False
        best: tuple[int, bool] | None = None
        for allow, raw, rx in self.rules:
            if rx.match(path):
                cand = (len(raw), allow)
                if best is None or cand > best:
                    best = cand
        return best is None or best[1]


def _robots_pattern(raw: str) -> re.Pattern[str]:
    """§2.2.3：* 匹配任意字符序列，结尾的 $ 表示路径到此结束；其余按字面前缀匹配。"""
    anchored = raw.endswith("$")
    body = raw[:-1] if anchored else raw
    rx = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(rx + ("$" if anchored else ""))


def parse_robots(text: str, agent: str = "gleaner") -> RobotsRules:
    """RFC 9309 §2.1–2.2：连续的 user-agent 行组成一组；有本程序的组就只用它（多组合并），否则用 * 组。

    Crawl-delay 不是标准字段，按常见约定读取，最多 10 秒。
    """
    groups: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if cur is None or not last_was_agent:
                cur = {"agents": [], "rules": [], "delay": None}
                groups.append(cur)
            cur["agents"].append(v.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if cur is None:
            continue  # 不在任何组里的规则忽略
        if k in ("allow", "disallow") and v:
            cur["rules"].append((k == "allow", v))  # 空的 Disallow 表示不限制
        elif k == "crawl-delay":
            try:
                cur["delay"] = min(max(float(v), 0.0), 10.0)
            except ValueError:
                pass
    agent = agent.lower()
    mine = [g for g in groups if any(a not in ("", "*") and a in agent for a in g["agents"])]
    chosen = mine or [g for g in groups if "*" in g["agents"]]
    out = RobotsRules()
    for g in chosen:
        out.rules += [(allow, r, _robots_pattern(r)) for allow, r in g["rules"]]
        if g["delay"] is not None:
            out.crawl_delay = max(out.crawl_delay, g["delay"])
    return out


@dataclass
class _HostState:
    next_allowed: float = 0.0  # monotonic：下一次请求最早的开始时间
    not_before: float = 0.0  # 墙钟时间：服务端 Retry-After 要求的最早时间
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    robots: RobotsRules | None = None
    robots_at: float = 0.0
    robots_ttl: float = ROBOTS_TTL

    @property
    def crawl_delay(self) -> float:
        return self.robots.crawl_delay if self.robots else 0.0


class Fetcher:
    """所有对外请求（robots.txt、每一跳重定向、每一次重试）都经过同一个按主机限速器。"""

    def __init__(
        self,
        client: HTTPClient | None = None,
        *,
        min_interval: float = 0.5,
        retries: int = 2,
        backoff: float = 0.5,
        respect_robots: bool = True,
        max_redirects: int = MAX_REDIRECTS,
        agent: str = "gleaner",
    ) -> None:
        # 采集与预览访问的都是用户可填的网址：默认只允许公网地址（防 SSRF）
        self.client = client or HTTPClient(per_host_limit=4, total_limit=64, egress_guard=True)
        self.min_interval = min_interval
        self.retries = retries
        self.backoff = backoff
        self.respect_robots = respect_robots
        self.max_redirects = max_redirects
        self.agent = agent
        self._hosts: dict[str, _HostState] = {}

    async def close(self) -> None:
        await self.client.close()

    def _host(self, url: str) -> tuple[str, _HostState]:
        p = urlsplit(url)
        key = f"{p.scheme.lower()}://{p.netloc.lower()}"
        return key, self._hosts.setdefault(key, _HostState())

    async def _pace(self, st: _HostState) -> None:
        """同一主机两次请求的开始时间至少间隔 min_interval / Crawl-delay。"""
        async with st.lock:
            wait = st.next_allowed - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            st.next_allowed = time.monotonic() + max(self.min_interval, st.crawl_delay)

    @staticmethod
    def _check_not_before(st: _HostState) -> None:
        left = st.not_before - time.time()
        if left > 0:
            raise FetchError("http", f"服务端要求 {left:.0f} 秒后再访问", retry_after=left)

    async def _robots(self, base: str, st: _HostState) -> RobotsRules:
        if st.robots is not None and time.time() - st.robots_at < st.robots_ttl:
            return st.robots
        await self._pace(st)
        r: ClientResponse | None
        try:
            r = await self.client.get(urljoin(base, "/robots.txt"), timeout=5)
        except HTTPError as e:
            if e.kind == "blocked":
                raise FetchError("blocked", str(e)) from e
            r = None
        if r is None or r.status >= 500:
            # §2.3.1.4：服务器或网络错误视为全部禁止，过几分钟再取
            st.robots, st.robots_ttl = RobotsRules(disallow_all=True), ROBOTS_UNREACHABLE_TTL
        elif r.status == 200:
            st.robots, st.robots_ttl = parse_robots(r.text(), self.agent), ROBOTS_TTL
        else:
            st.robots, st.robots_ttl = RobotsRules(), ROBOTS_TTL  # §2.3.1.3：4xx 视为没有限制
        st.robots_at = time.time()
        return st.robots

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
        """重定向在这里逐跳跟随：每一跳都重新检查 robots、限速与 Retry-After。"""
        h = dict(headers or {})
        if etag:
            h["If-None-Match"] = etag
        if last_modified:
            h["If-Modified-Since"] = last_modified
        history: list[str] = []
        while True:
            r = await self._fetch_once(url, method, h, body, cookies)
            location = r.headers.get("Location")
            if not (follow_redirects and r.status in REDIRECTS and location):
                r.url, r.history = url, history
                return r
            if len(history) >= self.max_redirects:
                raise FetchError("http", "too many redirects")
            history.append(url)
            nxt = urljoin(url, location)
            if r.status == 303 or (r.status in (301, 302) and method == "POST"):
                method, body = "GET", b""
            # 条件请求头只对原地址有效；跳到别的源时不带调用方给的凭证（RFC 9110 §15.4）
            h = {k: v for k, v in h.items() if k not in ("If-None-Match", "If-Modified-Since")}
            if _origin(nxt) != _origin(url):
                h = {k: v for k, v in h.items() if k.lower() not in _CREDENTIAL_HEADERS}
            url = nxt

    async def _fetch_once(
        self,
        url: str,
        method: str,
        h: dict[str, str],
        body: bytes,
        cookies: CookieJar | None,
    ) -> ClientResponse:
        base, st = self._host(url)
        self._check_not_before(st)
        if self.respect_robots:
            rules = await self._robots(base, st)
            p = urlsplit(url)
            path = (p.path or "/") + (f"?{p.query}" if p.query else "")
            if not rules.allowed(path):
                raise FetchError("robots", f"disallowed by robots.txt: {p.path or '/'}")
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            await self._pace(st)
            t0 = time.perf_counter()
            try:
                r = await self.client.request(
                    method, url, headers=h, body=body, cookies=cookies, follow_redirects=False
                )
            except HTTPError as e:
                FETCHES.inc(1, e.kind)
                last_err = e
                if e.kind == "blocked":  # 目标是内网地址，重试也没用
                    raise FetchError("blocked", str(e)) from e
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff * 2**attempt * (0.5 + random.random()))
                    continue
                raise FetchError("timeout" if e.kind == "timeout" else "network", str(e)) from e
            FETCH_SECONDS.observe(time.perf_counter() - t0)
            FETCH_BYTES.inc(len(r.body))
            FETCHES.inc(1, str(r.status))
            if r.status >= 500 or r.status == 429:
                last_err = FetchError("http", f"HTTP {r.status}")
                ra = parse_retry_after(r.headers.get("Retry-After"))
                if ra is not None and (ra > INLINE_RETRY_MAX or attempt >= self.retries):
                    # 不缩短服务端要求的等待：记下最早时间，交给调度器推迟整个来源
                    st.not_before = max(st.not_before, time.time() + ra)
                    raise FetchError("http", f"HTTP {r.status}", retry_after=ra)
                if attempt < self.retries:
                    delay = (
                        ra
                        if ra is not None
                        else self.backoff * 2**attempt * (0.5 + random.random())
                    )
                    await asyncio.sleep(delay)
                    continue
                raise FetchError("http", f"HTTP {r.status}")
            return r
        raise FetchError("network", str(last_err))


def _origin(url: str) -> tuple[str, str, int]:
    p = urlsplit(url)
    scheme = p.scheme.lower()
    return scheme, (p.hostname or "").lower(), p.port or (443 if scheme == "https" else 80)


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
