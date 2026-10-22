"""上游节点池：一致性哈希 / 轮询、主动与被动健康检查（proposal 技术方案 7）。"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..common.hashring import HashRing
from ..net.http import HTTPClient, HTTPError
from ..obs.metrics import REGISTRY

log = logging.getLogger(__name__)

UPSTREAM_UP = REGISTRY.gauge("gleaner_upstream_up", "上游节点是否健康", ("pool", "node"))
UPSTREAM_EJECT = REGISTRY.counter(
    "gleaner_upstream_ejections_total", "节点被摘除次数", ("pool", "reason")
)


@dataclass
class Upstream:
    name: str
    host: str
    port: int
    healthy: bool = True
    consecutive_fail: int = 0
    consecutive_ok: int = 0
    passive_fail: int = 0
    ejected_until: float = 0.0
    last_check: float = 0.0
    last_error: str = ""
    latency_ms: float = 0.0
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.healthy and time.monotonic() >= self.ejected_until


class UpstreamPool:
    def __init__(
        self,
        name: str,
        upstreams: list[Upstream],
        *,
        check_interval: float = 5.0,
        fail_threshold: int = 3,
        passive_threshold: int = 5,
        passive_eject: float = 30.0,
        health_path: str = "/health",
    ) -> None:
        self.name = name
        self.nodes: dict[str, Upstream] = {u.name: u for u in upstreams}
        self.check_interval = check_interval
        self.fail_threshold = fail_threshold
        self.passive_threshold = passive_threshold
        self.passive_eject = passive_eject
        self.health_path = health_path
        self.ring = HashRing(self.nodes)
        self._rr = itertools.cycle(sorted(self.nodes))
        self._client = HTTPClient(connect_timeout=1.0, read_timeout=2.0, per_host_limit=2)
        self._task: asyncio.Task[None] | None = None
        for u in upstreams:
            UPSTREAM_UP.set(1, name, u.name)

    @classmethod
    def from_spec(cls, name: str, spec: str, **kw: Any) -> UpstreamPool:
        """``push-1=push1:8100,push-2=push2:8100`` 或 ``core:8081``。"""
        ups = []
        for i, part in enumerate(p.strip() for p in spec.split(",") if p.strip()):
            label, _, addr = part.rpartition("=")
            host, _, port = addr.rpartition(":")
            ups.append(Upstream(label or f"{name}-{i + 1}", host, int(port)))
        return cls(name, ups, **kw)

    def unavailable(self) -> set[str]:
        return {n for n, u in self.nodes.items() if not u.available}

    def pick_hash(self, key: str) -> Upstream | None:
        """一致性哈希：同一用户的多个连接落在同一节点；节点不可用时顺延到环上的下一个。"""
        n = self.ring.get(key, exclude=self.unavailable())
        return self.nodes.get(n) if n else None

    def pick_rr(self) -> Upstream | None:
        for _ in range(len(self.nodes)):
            u = self.nodes[next(self._rr)]
            if u.available:
                return u
        return None

    def report(self, u: Upstream, ok: bool, error: str = "") -> None:
        """被动健康检查：转发失败计数超过阈值时临时摘除。"""
        if ok:
            u.passive_fail = 0
            return
        u.passive_fail += 1
        u.last_error = error
        if u.passive_fail >= self.passive_threshold:
            u.ejected_until = time.monotonic() + self.passive_eject
            u.passive_fail = 0
            UPSTREAM_EJECT.inc(1, self.name, "passive")
            log.warning("%s: passively ejected %s (%s)", self.name, u.name, error)

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._loop())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
        await self._client.close()

    async def _loop(self) -> None:
        while True:
            await asyncio.gather(
                *(self.check(u) for u in self.nodes.values()), return_exceptions=True
            )
            await asyncio.sleep(self.check_interval)

    async def check(self, u: Upstream) -> None:
        """主动健康检查：TCP 连接 + GET /health；连续 3 次失败摘除，恢复后自动加回。"""
        t0 = time.perf_counter()
        ok = False
        try:
            r = await self._client.get(
                f"http://{u.host}:{u.port}{self.health_path}", headers={"Connection": "close"}
            )
            ok = r.status == 200
            if ok:
                try:
                    u.info = r.json() or {}
                except ValueError:
                    u.info = {}
            else:
                u.last_error = f"HTTP {r.status}"
        except HTTPError as e:
            u.last_error = str(e)
        u.last_check = time.time()
        u.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        if ok:
            u.consecutive_fail = 0
            u.consecutive_ok += 1
            if not u.healthy and u.consecutive_ok >= 1:
                log.info("%s: %s recovered", self.name, u.name)
                u.healthy = True
        else:
            u.consecutive_ok = 0
            u.consecutive_fail += 1
            if u.healthy and u.consecutive_fail >= self.fail_threshold:
                log.warning("%s: %s marked down (%s)", self.name, u.name, u.last_error)
                u.healthy = False
                UPSTREAM_EJECT.inc(1, self.name, "active")
        UPSTREAM_UP.set(1 if u.available else 0, self.name, u.name)

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "name": u.name,
                "addr": f"{u.host}:{u.port}",
                "healthy": u.healthy,
                "available": u.available,
                "latency_ms": u.latency_ms,
                "last_error": u.last_error,
                "info": u.info,
            }
            for u in self.nodes.values()
        ]
