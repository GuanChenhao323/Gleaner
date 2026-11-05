"""定时维护：数据保留期、过期清理（审查 DB-2/3/4/10/28）。

core 每小时运行一次 ``run_maintenance``。各项保留期可用环境变量调整（天）：

| 内容 | 默认 | 说明 |
| --- | --- | --- |
| 邮件正文 ``GLEANER_KEEP_MAIL_BODY_DAYS`` | 30 | proposal“数据最少化”：邮件只长期保存标题、发件人、摘要与链接 |
| 投递记录 ``GLEANER_KEEP_DELIVERIES_DAYS`` | 60 | 更早的离线补发改为全量刷新（/api/sync 返回 reset） |
| 幂等记录 op_log ``GLEANER_KEEP_OPLOG_DAYS`` | 30 | 客户端离线队列不会积压这么久 |
| 行为事件 events ``GLEANER_KEEP_EVENTS_DAYS`` | 180 | 运营统计用 |
| 发信记录 sent_mails ``GLEANER_KEEP_SENT_DAYS`` | 180 | 卡在 sending 超过 10 分钟的记录标记为失败 |
| 失效的来源会话 | 7 | 来源已“需要重新登录”超过 7 天：删除保存的 Cookie / Token（过期即删） |

另外：清理过期验证码、已吊销或 30 天未用的登录会话、截止已过 30 天的提醒记录、
过期一天以上的扫码传输（连同磁盘文件）、没有任何订阅者的公共来源。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from ..storage.db import Database

log = logging.getLogger(__name__)

DAY = 86400.0


def _days(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default)) * DAY
    except ValueError:
        return default * DAY


async def run_maintenance(
    db: Database, data_dir: str = "", now: float | None = None
) -> dict[str, int]:
    """执行一轮清理，返回每项删除 / 更新的行数（写日志与测试用）。"""
    now = time.time() if now is None else now
    out: dict[str, int] = {}

    async def run(name: str, sql: str, *params: Any) -> None:
        out[name] = await db.execute(sql, *params)

    await run(
        "mail_bodies",
        "UPDATE items SET body = '' WHERE kind = 'mail' AND body != '' AND first_seen_at < ?",
        now - _days("GLEANER_KEEP_MAIL_BODY_DAYS", 30),
    )
    await run(
        "deliveries",
        "DELETE FROM deliveries WHERE created_at < ?",
        now - _days("GLEANER_KEEP_DELIVERIES_DAYS", 60),
    )
    # 事项已被删除（私有来源删掉、来源级联）后留下的投递记录
    await run(
        "orphan_deliveries",
        "DELETE FROM deliveries WHERE item_id IS NOT NULL AND item_id NOT IN (SELECT id FROM items)",
    )
    await run(
        "op_log",
        "DELETE FROM op_log WHERE created_at < ?",
        now - _days("GLEANER_KEEP_OPLOG_DAYS", 30),
    )
    await run(
        "events",
        "DELETE FROM events WHERE created_at < ?",
        now - _days("GLEANER_KEEP_EVENTS_DAYS", 180),
    )
    await run("reminders_sent", "DELETE FROM reminders_sent WHERE deadline_at < ?", now - 30 * DAY)
    await run("email_codes", "DELETE FROM email_codes WHERE expires_at < ?", now)
    await run(
        "sessions",
        "DELETE FROM sessions WHERE revoked_at IS NOT NULL OR last_seen_at < ?",
        now - 30 * DAY,
    )
    await run(
        "stuck_mails",
        "UPDATE sent_mails SET status = 'failed', error = '发送中断（服务重启或超时）' WHERE status = 'sending' AND created_at < ?",
        now - 600,
    )
    await run(
        "sent_mails",
        "DELETE FROM sent_mails WHERE created_at < ?",
        now - _days("GLEANER_KEEP_SENT_DAYS", 180),
    )
    # 来源会话失效（需要重新登录）一周以上：会话凭据过期即删；邮箱的应用专用密码不在此列
    await run(
        "stale_sessions",
        "DELETE FROM credentials WHERE auth_type IN ('cookie', 'ws_token') AND updated_at < ? "
        "AND source_id IN (SELECT id FROM sources WHERE status = 'need_login')",
        now - 7 * DAY,
    )
    # 没有订阅者的公共来源：不再采集（事项随外键级联删除）
    await run(
        "orphan_sources",
        "DELETE FROM sources WHERE owner_id IS NULL AND type != 'clip' "
        "AND id NOT IN (SELECT source_id FROM subscriptions)",
    )
    # 过期一天以上的扫码传输：先删磁盘文件再删记录
    expired = await db.fetch("SELECT id FROM transfers WHERE expires_at < ?", now - DAY)
    if expired and data_dir:
        root = Path(data_dir) / "transfers"
        for r in expired:
            await asyncio.to_thread(shutil.rmtree, root / str(r["id"]), True)
    await run("transfers", "DELETE FROM transfers WHERE expires_at < ?", now - DAY)
    touched = {k: v for k, v in out.items() if v}
    if touched:
        log.info("maintenance: %s", touched)
    return out
