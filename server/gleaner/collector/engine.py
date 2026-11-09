"""采集引擎：最小堆调度、自适应检查周期、按一致性哈希分片、熔断。"""

from __future__ import annotations

import asyncio
import heapq
import json
import logging
import os
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .. import security
from ..common.hashring import HashRing
from ..obs.metrics import REGISTRY
from ..storage.db import Database, loads
from .connectors import CONNECTORS, Context, FetchResult, SourceInfo, content_hash
from .fetcher import CircuitBreaker, Fetcher, FetchError
from .session import SourceSession

log = logging.getLogger(__name__)

SOURCES_CHECKED = REGISTRY.counter("gleaner_source_checks_total", "来源检查次数", ("result",))
SCHEDULED = REGISTRY.gauge("gleaner_collector_sources", "本节点负责的来源数")

MIN_INTERVAL = float(os.environ.get("GLEANER_MIN_INTERVAL", "120"))
MAX_INTERVAL = float(os.environ.get("GLEANER_MAX_INTERVAL", "3600"))

Publish = Callable[[dict[str, Any]], Awaitable[None]]


def next_interval(current: float, *, changed: bool, failed: bool) -> float:
    """常更新的源检查得更勤，冷门源逐渐放慢；失败时退避。"""
    if failed:
        nxt = current * 2
    elif changed:
        nxt = current * 0.6
    else:
        nxt = current * 1.25
    return max(MIN_INTERVAL, min(MAX_INTERVAL, nxt))


async def load_session(
    db: Database, source_id: int, owner_id: int | None
) -> tuple[SourceSession | None, int | None]:
    row = await db.fetchone(
        "SELECT id, user_id, secret_encrypted FROM credentials WHERE source_id = ? ORDER BY updated_at DESC LIMIT 1",
        source_id,
    )
    if not row:
        return None, None
    try:
        secret = security.decrypt(
            row["secret_encrypted"], aad=f"{row['user_id']}:{source_id}".encode()
        )
    except Exception:
        log.warning("credential for source %s cannot be decrypted", source_id)
        return None, None
    return SourceSession.from_secret(secret), row["user_id"]


async def save_session(db: Database, source_id: int, user_id: int, sess: SourceSession) -> None:
    blob = security.encrypt(sess.to_secret(), aad=f"{user_id}:{source_id}".encode())
    await db.execute(
        "UPDATE credentials SET secret_encrypted = ?, updated_at = ? WHERE source_id = ? AND user_id = ?",
        blob,
        time.time(),
        source_id,
        user_id,
    )


async def check_source(db: Database, fetcher: Fetcher, row: dict[str, Any]) -> dict[str, Any]:
    """检查一个来源，更新抓取状态，返回发往业务服务的结果消息。

    内容哈希 ``sources.content_hash`` 由业务服务在入库成功后写入（见 ``Pipeline.ingest``），采集端只记
    “已发出的哈希” ``stats.published_hash``。两者不一致说明上次的结果没有入库（core 宕机或入库失败），
    这次就不用 HTTP 条件请求缓存、也不按哈希跳过，保证这批事项会再发一次。
    """
    stats0 = loads(row.get("stats"), {})
    published = stats0.get("published_hash")
    unconfirmed = bool(published) and published != row.get("content_hash")
    src = SourceInfo(
        id=row["id"],
        type=row["type"],
        endpoint=row["endpoint"],
        config=loads(row["config"], {}),
        course=row.get("course") or "",
        etag=row.get("etag"),
        last_modified=row.get("last_modified"),
        content_hash=row.get("content_hash"),
        cache={} if unconfirmed else stats0.get("http_cache", {}),
    )
    conn = CONNECTORS.get(src.type)
    sess, cred_user = await load_session(db, src.id, row.get("owner_id"))
    ctx = Context(fetcher, src, sess)
    now = time.time()
    t0 = time.perf_counter()
    try:
        if conn is None:
            raise FetchError("parse", f"unsupported source type {src.type}")
        if src.type == "moodle" and sess is None:
            raise FetchError("need_login", "尚未登录该 Moodle 来源")
        res = await conn(ctx)
    except FetchError as e:
        res = FetchResult(
            "need_login" if e.kind == "need_login" else "failed",
            error=str(e),
            error_kind=e.kind,
            complete=False,
            retry_after=e.retry_after,
        )
    except Exception as e:  # 解析器异常不能拖垮引擎
        log.exception("connector crashed for source %s", src.id)
        res = FetchResult(
            "failed", error=f"{type(e).__name__}: {e}", error_kind="parse", complete=False
        )
    res.requests, res.not_modified, res.bytes = ctx.requests, ctx.not_modified, ctx.bytes
    elapsed = time.perf_counter() - t0
    if res.status == "ok":
        res.content_hash = content_hash(res.items)
        if res.content_hash == src.content_hash:
            res.status = "not_modified"
    changed = res.status == "ok"
    failed = res.status in ("failed", "need_login")
    interval = next_interval(
        float(row.get("interval_s") or MIN_INTERVAL), changed=changed, failed=failed
    )
    if res.status == "need_login":
        interval = MAX_INTERVAL  # 不再反复请求，等用户重新登录
    stats = stats0
    stats["http_cache"] = src.cache
    if res.content_hash is not None:  # 本次发出的（或与已确认相同、无需再发的）内容哈希
        stats["published_hash"] = res.content_hash
    stats["last"] = {
        "requests": res.requests,
        "not_modified": res.not_modified,
        "bytes": res.bytes,
        "elapsed": round(elapsed, 3),
    }
    totals = stats.setdefault("totals", {"requests": 0, "not_modified": 0, "bytes": 0, "checks": 0})
    totals["requests"] += res.requests
    totals["not_modified"] += res.not_modified
    totals["bytes"] += res.bytes
    totals["checks"] += 1
    status = {"ok": "ok", "not_modified": "ok", "failed": "failed", "need_login": "need_login"}[
        res.status
    ]
    jitter = random.uniform(0.9, 1.1)
    next_at = now + interval * jitter
    if res.retry_after:
        next_at = max(next_at, now + res.retry_after)  # 服务端的 Retry-After 不能被缩短
    await db.execute(
        """UPDATE sources SET status = ?, last_checked_at = ?, last_success_at = CASE WHEN ? = 1 THEN ? ELSE last_success_at END,
           last_change_at = CASE WHEN ? = 1 THEN ? ELSE last_change_at END, last_error = ?, fail_count = CASE WHEN ? = 1 THEN fail_count + 1 ELSE 0 END,
           interval_s = ?, next_fetch_at = ?, stats = ? WHERE id = ?""",
        status,
        now,
        int(not failed),
        now,
        int(changed),
        now,
        res.error or None,
        int(failed),
        interval,
        next_at,
        json.dumps(stats, ensure_ascii=False, default=str),
        src.id,
    )
    if sess is not None and cred_user is not None and res.status in ("ok", "not_modified"):
        await save_session(db, src.id, cred_user, sess)  # 服务端可能刷新了 Cookie
    SOURCES_CHECKED.inc(1, res.status)
    return {
        "source_id": src.id,
        "prev_status": row.get("status"),
        "status": res.status,
        "error": res.error,
        "error_kind": res.error_kind,
        "checked_at": now,
        "complete": res.complete,
        "content_hash": res.content_hash if changed else None,
        "items": [i.to_dict() for i in res.items] if changed else [],
        "stats": stats["last"],
    }


class Scheduler:
    """最小堆按“下次检查时间”排序；只调度一致性哈希分给本节点的来源。"""

    def __init__(
        self,
        db: Database,
        publish: Publish,
        node_id: str,
        *,
        concurrency: int = 32,
        fetcher: Fetcher | None = None,
    ) -> None:
        self.db = db
        self.publish = publish
        self.node_id = node_id
        self.fetcher = fetcher or Fetcher()
        self.sem = asyncio.Semaphore(concurrency)
        self.ring = HashRing([node_id])
        self.breaker = CircuitBreaker()
        self._heap: list[tuple[float, int]] = []
        self._known: dict[int, float] = {}
        self._wake = asyncio.Event()
        self._running: set[int] = set()
        self._tasks: set[asyncio.Task[Any]] = set()

    def set_nodes(self, nodes: list[str]) -> None:
        """采集节点成员变化（来自总线 $nodes）：重建哈希环，任务自动重新分配。"""
        nodes = sorted(set(nodes) | {self.node_id})
        if set(nodes) != self.ring.nodes:
            log.info("collector ring now %s", nodes)
            self.ring = HashRing(nodes)
            self._known.clear()
            self._heap.clear()
            self._wake.set()

    def mine(self, source_id: int) -> bool:
        return self.ring.get(f"source:{source_id}") == self.node_id

    async def refresh(self) -> None:
        # 只取 60 秒内到期的来源（索引 ix_sources_due），并跳过无人订阅的公共来源（不再采集）
        rows = await self.db.fetch(
            "SELECT id, next_fetch_at FROM sources WHERE via_agent = 0 AND next_fetch_at <= ? "
            "AND type IN ('moodle','web','rss','teacher') "
            "AND (owner_id IS NOT NULL OR EXISTS (SELECT 1 FROM subscriptions s WHERE s.source_id = sources.id))",
            time.time() + 60,
        )
        mine = 0
        for r in rows:
            if not self.mine(r["id"]):
                continue
            mine += 1
            nf = float(r["next_fetch_at"] or 0)
            if self._known.get(r["id"]) != nf:
                self._known[r["id"]] = nf
                heapq.heappush(self._heap, (nf, r["id"]))
        SCHEDULED.set(mine)

    def fetch_now(self, source_id: int) -> None:
        heapq.heappush(self._heap, (0.0, source_id))
        self._known[source_id] = 0.0
        self._wake.set()

    async def run(self) -> None:
        last_refresh = 0.0
        while True:
            if time.monotonic() - last_refresh > 5:
                await self.refresh()
                last_refresh = time.monotonic()
            now = time.time()
            while self._heap and self._heap[0][0] <= now:
                nf, sid = heapq.heappop(self._heap)
                if self._known.get(sid) != nf or sid in self._running:
                    continue  # 过期的堆条目
                self._known.pop(sid, None)
                if not self.mine(sid) or not self.breaker.allow(sid):
                    continue
                self._running.add(sid)
                t = asyncio.get_running_loop().create_task(self._one(sid))
                self._tasks.add(t)
                t.add_done_callback(self._tasks.discard)
            delay = min(5.0, max(0.05, (self._heap[0][0] - time.time()) if self._heap else 5.0))
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
            except TimeoutError:
                pass

    async def _one(self, sid: int) -> None:
        try:
            async with self.sem:
                row = await self.db.fetchone("SELECT * FROM sources WHERE id = ?", sid)
                if not row:
                    return
                msg = await check_source(self.db, self.fetcher, row)
                self.breaker.record(sid, msg["status"] in ("ok", "not_modified"))
                msg["node"] = self.node_id
                await self.publish(msg)
        except Exception:
            log.exception("source %s check failed", sid)
        finally:
            self._running.discard(sid)
            self._wake.set()
