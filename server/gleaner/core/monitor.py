"""事项级监测状态（产品定义第 4 节，决策 D23）。

插件采集的事项由插件重新获取：插件领取到期任务（租用一段时间，避免重复领取），在浏览器里重新读取页面，
再回报结果。成功时更新“最后成功检查时间”；失败只记录失败原因与时间，绝不显示成“无变化”。
订阅来源的事项沿用服务端采集，监测状态取自来源本身（``public`` 里推导）。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ..storage.db import Database, loads
from .validate import BadRequest

LEASE_S = 300.0
MAX_BACKOFF_S = 24 * 3600.0
ERROR_CODES = ("auth_expired", "forbidden", "network", "not_found", "parse_failed", "unsupported")


def interval_s() -> float:
    """检查间隔：默认 1 小时，最短 15 分钟（来源访问限速，产品定义 4.1 节不承诺实时）。"""
    try:
        v = float(os.environ.get("GLEANER_MONITOR_INTERVAL", "3600"))
    except ValueError:
        v = 3600.0
    return max(v, 900.0)


async def on_capture(db: Database, uid: int, item_id: int, supported: bool) -> str:
    """保存（或再次保存）后登记监测能力：插件声明支持时默认启用；不再支持时停用。返回对外状态。"""
    now = time.time()
    cur = await db.fetchone(
        "SELECT * FROM item_monitors WHERE user_id = ? AND item_id = ?", uid, item_id
    )
    if cur is None:
        await db.execute(
            "INSERT INTO item_monitors (user_id, item_id, supported, enabled, interval_s, next_check_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            uid,
            item_id,
            int(supported),
            int(supported),
            interval_s(),
            now + interval_s() if supported else None,
            now,
        )
    elif supported and not cur["supported"]:
        await db.execute(
            "UPDATE item_monitors SET supported = 1, enabled = 1, next_check_at = ?, updated_at = ? "
            "WHERE user_id = ? AND item_id = ?",
            now + float(cur["interval_s"]),
            now,
            uid,
            item_id,
        )
    elif not supported and cur["supported"]:
        await db.execute(
            "UPDATE item_monitors SET supported = 0, enabled = 0, next_check_at = NULL, lease_until = NULL, "
            "updated_at = ? WHERE user_id = ? AND item_id = ?",
            now,
            uid,
            item_id,
        )
    return "enabled" if supported else "unsupported"


async def set_enabled(db: Database, uid: int, item_id: int, enabled: bool) -> None:
    cur = await db.fetchone(
        "SELECT supported, interval_s FROM item_monitors WHERE user_id = ? AND item_id = ?",
        uid,
        item_id,
    )
    if not cur or not cur["supported"]:
        if enabled:
            raise BadRequest(409, "该事项的来源暂不支持监测", "unsupported")
        return
    now = time.time()
    await db.execute(
        "UPDATE item_monitors SET enabled = ?, next_check_at = ?, lease_until = NULL, updated_at = ? "
        "WHERE user_id = ? AND item_id = ?",
        int(enabled),
        now if enabled else None,  # 重新打开后尽快检查一次
        now,
        uid,
        item_id,
    )


async def lease_due(
    db: Database, uid: int, limit: int
) -> tuple[list[dict[str, Any]], float | None]:
    """领取到期任务并租用 LEASE_S 秒；返回 (任务, 没有任务时下一个到期时间)。"""
    now = time.time()
    rows = await db.fetch(
        "SELECT m.item_id, i.title, i.url, i.attrs FROM item_monitors m JOIN items i ON i.id = m.item_id "
        "WHERE m.user_id = ? AND m.enabled = 1 AND m.supported = 1 AND i.deleted = 0 "
        "AND m.next_check_at <= ? AND (m.lease_until IS NULL OR m.lease_until < ?) "
        "ORDER BY m.next_check_at LIMIT ?",
        uid,
        now,
        now,
        int(limit),
    )
    tasks = []
    for r in rows:
        # 条件里再判一次租期：两个插件实例同时领取时只有一个能拿到
        if await db.execute(
            "UPDATE item_monitors SET lease_until = ? WHERE user_id = ? AND item_id = ? "
            "AND (lease_until IS NULL OR lease_until < ?)",
            now + LEASE_S,
            uid,
            r["item_id"],
            now,
        ):
            attrs = loads(r["attrs"], {})
            tasks.append(
                {
                    "item_id": r["item_id"],
                    "page_url": attrs.get("page_url") or r["url"],
                    "locator": attrs.get("locator", ""),
                    "title": r["title"],
                }
            )
    nxt = None
    if not tasks:
        nxt = await db.fetchval(
            "SELECT MIN(CASE WHEN lease_until IS NOT NULL AND lease_until > next_check_at "
            "THEN lease_until ELSE next_check_at END) FROM item_monitors "
            "WHERE user_id = ? AND enabled = 1 AND supported = 1",
            uid,
        )
    return tasks, nxt


async def get(db: Database, uid: int, item_id: int) -> dict[str, Any] | None:
    return await db.fetchone(
        "SELECT * FROM item_monitors WHERE user_id = ? AND item_id = ?", uid, item_id
    )


async def record_success(db: Database, uid: int, item_id: int, result: str) -> float:
    now = time.time()
    await db.execute(
        "UPDATE item_monitors SET last_checked_at = ?, last_success_at = ?, last_result = ?, last_error = '', "
        "fail_count = 0, next_check_at = ? + interval_s, lease_until = NULL, updated_at = ? "
        "WHERE user_id = ? AND item_id = ?",
        now,
        now,
        result,
        now,
        now,
        uid,
        item_id,
    )
    return now


async def record_failure(
    db: Database, uid: int, item_id: int, code: str, message: str
) -> float | None:
    """失败：记录原因，按次数退避（间隔 × 2^(n-1)，最多 1 天）；最后成功时间保持不变。"""
    cur = await get(db, uid, item_id)
    if cur is None:
        return None
    now = time.time()
    fails = int(cur["fail_count"]) + 1
    delay = min(float(cur["interval_s"]) * 2 ** (fails - 1), MAX_BACKOFF_S)
    await db.execute(
        "UPDATE item_monitors SET last_checked_at = ?, last_result = 'failed', last_error = ?, fail_count = ?, "
        "next_check_at = ?, lease_until = NULL, updated_at = ? WHERE user_id = ? AND item_id = ?",
        now,
        json.dumps({"code": code, "message": message}, ensure_ascii=False),
        fails,
        now + delay,
        now,
        uid,
        item_id,
    )
    return cur["last_success_at"]


def public(
    mon: dict[str, Any] | None, origin: str, source: dict[str, Any] | None = None
) -> dict[str, Any]:
    """对外的监测状态（IC-002 4.2）。"""
    if origin == "source" and source is not None:
        # 订阅来源由服务端采集：来源的状态就是该事项的监测状态
        st = source.get("status") or "pending"
        last_ok = source.get("last_success_at")
        if st == "pending" or (st == "ok" and last_ok is None):
            status = "pending"
        elif st == "ok":
            changed_at = source.get("last_change_at")
            status = (
                "changed" if changed_at and last_ok and changed_at >= last_ok - 1 else "unchanged"
            )
        else:
            status = "failed"
        return {
            "status": status,
            "supported": True,
            "enabled": True,
            "last_checked_at": source.get("last_checked_at"),
            "last_success_at": last_ok,
            "error": {"code": st, "message": source.get("last_error") or ""}
            if status == "failed"
            else None,
            "next_check_at": source.get("next_fetch_at"),
        }
    if not mon or not mon.get("supported"):
        return {
            "status": "unsupported",
            "supported": False,
            "enabled": False,
            "last_checked_at": None,
            "last_success_at": None,
            "error": None,
            "next_check_at": None,
        }
    if not mon.get("enabled"):
        status = "disabled"
    elif not mon.get("last_checked_at"):
        status = "pending"
    else:
        status = mon.get("last_result") or "pending"
    err = loads(mon.get("last_error"), None) if mon.get("last_result") == "failed" else None
    return {
        "status": status,
        "supported": True,
        "enabled": bool(mon.get("enabled")),
        "last_checked_at": mon.get("last_checked_at"),
        "last_success_at": mon.get("last_success_at"),
        "error": err,
        "next_check_at": mon.get("next_check_at") if mon.get("enabled") else None,
    }


async def load(db: Database, uid: int, item_ids: list[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for i in range(0, len(item_ids), 500):
        chunk = item_ids[i : i + 500]
        marks = ",".join("?" * len(chunk))
        for r in await db.fetch(
            f"SELECT * FROM item_monitors WHERE user_id = ? AND item_id IN ({marks})", uid, *chunk
        ):
            out[r["item_id"]] = r
    return out
