"""截止前 24 小时与 2 小时提醒；每日摘要以 MQTT 保留消息发布。"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

from ..mailsvc.sender import send_platform_mail
from ..storage.db import Database, loads
from .extract import TZ
from .pipeline import Pipeline, item_public

log = logging.getLogger(__name__)

WINDOWS = (("24h", 24 * 3600), ("2h", 2 * 3600))


async def send_due_reminders(db: Database, pipe: Pipeline, now: float | None = None) -> int:
    now = now or time.time()
    sent = 0
    rows = await db.fetch(
        """SELECT i.*, s.user_id AS uid, st.todo_status, st.deadline_override, st.hidden, e.value AS edited_deadline
           FROM items i
           JOIN subscriptions s ON s.source_id = i.source_id
           LEFT JOIN user_item_state st ON st.user_id = s.user_id AND st.item_id = i.id
           LEFT JOIN user_item_edits e ON e.user_id = s.user_id AND e.item_id = i.id AND e.field = 'deadline_at'
           WHERE i.deleted = 0 AND (e.value IS NOT NULL
                 OR (i.deadline_at IS NOT NULL AND i.deadline_at > ? AND i.deadline_at < ?))""",
        now,
        now + 24 * 3600 + 60,
    )
    for r in rows:
        if r.get("todo_status") == "done" or r.get("hidden"):
            continue
        # 用户改过截止时间以修改为准（决策 D22）；用户确认“没有截止时间”就不提醒
        if r.get("edited_deadline") is not None:
            edited = loads(r["edited_deadline"], None)
            if not isinstance(edited, int | float):
                continue
            deadline = float(edited)
        else:
            deadline = float(r.get("deadline_override") or r["deadline_at"])
        left = deadline - now
        for kind, window in WINDOWS:
            if left > window or left <= 0:
                continue
            exists = await db.fetchone(
                "SELECT 1 FROM reminders_sent WHERE user_id = ? AND item_id = ? AND kind = ? AND deadline_at = ?",
                r["uid"],
                r["id"],
                kind,
                deadline,
            )
            if exists:
                break
            await db.execute(
                "INSERT INTO reminders_sent (user_id, item_id, kind, deadline_at, sent_at) VALUES (?, ?, ?, ?, ?)",
                r["uid"],
                r["id"],
                kind,
                deadline,
                now,
            )
            hours = max(1, round(left / 3600))
            when = dt.datetime.fromtimestamp(deadline, TZ).strftime("%m-%d %H:%M")
            payload: dict[str, Any] = {
                "type": "reminder",
                "item_id": r["id"],
                "window": kind,
                "text": f"「{r['title']}」将在 {hours} 小时后截止（{when}）",
                "item": item_public(r),
            }
            await pipe._deliver(
                r["uid"],
                r["id"],
                r["version"],
                "reminder",
                90,
                "urgent",
                payload,
                mqtt_topic="urgent",
            )
            sent += 1
            break  # 同一时刻只发最近的窗口
    return sent


async def publish_digests(db: Database, pipe: Pipeline, now: float | None = None) -> int:
    """到达用户设置的摘要时间时，汇总过去 24 小时的事项，作为保留消息发布到 gleaner/u/{uid}/digest。"""
    now = now or time.time()
    local = dt.datetime.fromtimestamp(now, TZ)
    hhmm = local.strftime("%H:%M")
    today = local.strftime("%Y-%m-%d")
    # 只查摘要时间是这一分钟的用户（索引 ix_users_digest），不再每 30 秒扫描全部用户
    users = await db.fetch(
        "SELECT id, email, digest_time, digest_email FROM users WHERE digest_time = ?", hhmm
    )
    n = 0
    for u in users:
        key = f"digest:{today}"
        if await db.fetchone("SELECT 1 FROM op_log WHERE user_id = ? AND op_id = ?", u["id"], key):
            continue
        await db.execute(
            "INSERT INTO op_log (user_id, op_id, result, created_at) VALUES (?, ?, '{}', ?)",
            u["id"],
            key,
            now,
        )
        digest = await build_digest(db, u["id"], now)
        await pipe.route(
            "mqtt.publish",
            {"topic": f"gleaner/u/{u['id']}/digest", "qos": 1, "retain": True, "payload": digest},
        )
        await pipe.route(f"u.{u['id']}", {"type": "digest", "digest": digest})
        if u.get("digest_email"):
            # 可选的邮件版摘要（默认关闭，用户在设置里打开），经平台账号用自研 SMTP 发出
            await send_platform_mail(
                u["email"], f"拾课每日摘要 · {digest['date']}", digest_text(digest)
            )
        n += 1
    return n


def digest_text(d: dict[str, Any]) -> str:
    lines = [f"过去 24 小时有 {d['new_count']} 条新事项或变更。", ""]
    if d["upcoming"]:
        lines.append("未来 7 天截止：")
        for it in d["upcoming"]:
            when = dt.datetime.fromtimestamp(it["deadline_at"], TZ).strftime("%m-%d %H:%M")
            lines.append(f"  · {when}  {it['title']}")
        lines.append("")
    if d["items"]:
        lines.append("最近更新：")
        lines += [f"  · {it['title']}" for it in d["items"]]
        lines.append("")
    lines.append("可在拾课“设置 → 每日摘要邮件”中关闭这类邮件。")
    return "\n".join(lines)


async def build_digest(db: Database, uid: int, now: float) -> dict[str, Any]:
    rows = await db.fetch(
        """SELECT i.id, i.title, i.kind, i.deadline_at, st.priority FROM items i
           JOIN subscriptions s ON s.source_id = i.source_id AND s.user_id = ?
           LEFT JOIN user_item_state st ON st.user_id = ? AND st.item_id = i.id
           WHERE i.deleted = 0 AND i.updated_at > ? ORDER BY i.updated_at DESC LIMIT 30""",
        uid,
        uid,
        now - 86400,
    )
    upcoming = await db.fetch(
        """SELECT i.id, i.title, i.deadline_at FROM items i JOIN subscriptions s ON s.source_id = i.source_id AND s.user_id = ?
           LEFT JOIN user_item_state st ON st.user_id = ? AND st.item_id = i.id
           WHERE i.deleted = 0 AND i.deadline_at BETWEEN ? AND ? AND COALESCE(st.todo_status, '') != 'done' ORDER BY i.deadline_at LIMIT 10""",
        uid,
        uid,
        now,
        now + 7 * 86400,
    )
    return {
        "date": dt.datetime.fromtimestamp(now, TZ).strftime("%Y-%m-%d"),
        "new_count": len(rows),
        "items": [{"id": r["id"], "title": r["title"], "kind": r["kind"]} for r in rows[:10]],
        "upcoming": [
            {"id": r["id"], "title": r["title"], "deadline_at": r["deadline_at"]} for r in upcoming
        ],
    }
