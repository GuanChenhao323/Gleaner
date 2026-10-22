"""令牌桶限流：按 IP 与用户两个维度。"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBucket:
    def __init__(self, rate: float, burst: float, max_keys: int = 100_000) -> None:
        self.rate = rate
        self.burst = burst
        self.max_keys = max_keys
        self._b: dict[str, _Bucket] = {}

    def allow(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        """返回 (是否放行, 需要等待的秒数)。"""
        now = time.monotonic()
        b = self._b.get(key)
        if b is None:
            if len(self._b) >= self.max_keys:
                # 清理已经回满的桶，防止内存被大量 IP 撑爆
                self._b = {
                    k: v
                    for k, v in self._b.items()
                    if v.tokens + (now - v.updated) * self.rate < self.burst
                }
            b = self._b[key] = _Bucket(self.burst, now)
        b.tokens = min(self.burst, b.tokens + (now - b.updated) * self.rate)
        b.updated = now
        if b.tokens >= cost:
            b.tokens -= cost
            return True, 0.0
        return False, (cost - b.tokens) / self.rate
