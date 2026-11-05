"""登录与验证码的防爆破计数（进程内）。

网关的令牌桶只按 IP 限总速率（每秒 20 次），挡不住慢速猜密码：这里按“邮箱”和“IP”分别统计失败次数，
超过阈值后按指数退避拒绝一段时间。core 是单进程（总线 Hub 也在这里），计数放在内存里即可；
重启会清零，可以接受。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _Entry:
    hits: list[float] = field(default_factory=list)
    blocked_until: float = 0.0
    strikes: int = 0


class Throttle:
    """滑动窗口内超过 ``limit`` 次就封禁 ``base_block`` 秒，连续触发时封禁时间翻倍（上限 ``max_block``）。"""

    def __init__(
        self,
        limit: int,
        window: float,
        base_block: float,
        max_block: float = 3600.0,
        max_keys: int = 50_000,
    ) -> None:
        self.limit = limit
        self.window = window
        self.base_block = base_block
        self.max_block = max_block
        self.max_keys = max_keys
        self._d: dict[str, _Entry] = {}

    def retry_after(self, key: str, now: float | None = None) -> float:
        """仍在封禁期内时返回剩余秒数，否则返回 0。"""
        e = self._d.get(key)
        now = time.time() if now is None else now
        return max(0.0, e.blocked_until - now) if e else 0.0

    def hit(self, key: str, now: float | None = None) -> float:
        """记一次（失败 / 发送），返回之后需要等待的秒数（0 表示未触发封禁）。"""
        now = time.time() if now is None else now
        if len(self._d) >= self.max_keys:
            self._prune(now)
        e = self._d.setdefault(key, _Entry())
        e.hits = [t for t in e.hits if now - t < self.window]
        e.hits.append(now)
        if len(e.hits) > self.limit:
            block = min(self.max_block, self.base_block * (2**e.strikes))
            e.strikes += 1
            e.blocked_until = now + block
            e.hits.clear()
            return block
        return 0.0

    def reset(self, key: str) -> None:
        self._d.pop(key, None)

    def _prune(self, now: float) -> None:
        stale = [
            k
            for k, e in self._d.items()
            if e.blocked_until < now and (not e.hits or now - e.hits[-1] > self.window)
        ]
        for k in stale:
            del self._d[k]
        if len(self._d) >= self.max_keys:  # 仍然太多：丢掉最早的一半，防止被刷爆内存
            for k in list(self._d)[: self.max_keys // 2]:
                del self._d[k]
