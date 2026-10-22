"""带虚拟节点的一致性哈希环。网关用它把用户映射到推送节点，调度用它把信息源分给采集节点。"""

from __future__ import annotations

import bisect
import hashlib
from collections.abc import Iterable


def _h(key: str) -> int:
    return int.from_bytes(hashlib.md5(key.encode()).digest()[:8], "big")


class HashRing:
    def __init__(self, nodes: Iterable[str] = (), vnodes: int = 160) -> None:
        self.vnodes = vnodes
        self._ring: list[tuple[int, str]] = []
        self._nodes: set[str] = set()
        for n in nodes:
            self.add(n)

    @property
    def nodes(self) -> set[str]:
        return set(self._nodes)

    def add(self, node: str) -> None:
        if node in self._nodes:
            return
        self._nodes.add(node)
        for i in range(self.vnodes):
            bisect.insort(self._ring, (_h(f"{node}#{i}"), node))

    def remove(self, node: str) -> None:
        if node not in self._nodes:
            return
        self._nodes.discard(node)
        self._ring = [(h, n) for h, n in self._ring if n != node]

    def get(self, key: str, exclude: set[str] | None = None) -> str | None:
        """顺时针找到第一个节点；``exclude`` 用于故障转移时跳过不健康节点。"""
        if not self._ring:
            return None
        h = _h(key)
        i = bisect.bisect(self._ring, (h, "￿"))
        seen: set[str] = set()
        for j in range(len(self._ring)):
            node = self._ring[(i + j) % len(self._ring)][1]
            if node in seen:
                continue
            seen.add(node)
            if not exclude or node not in exclude:
                return node
            if len(seen) == len(self._nodes):
                break
        return None

    def __len__(self) -> int:
        return len(self._nodes)
