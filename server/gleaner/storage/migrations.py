"""带版本号的数据库迁移。

``schema_migrations`` 记录已执行的版本；启动时按版本号依次执行尚未执行的迁移，每个迁移一个事务
（SQLite 与 PostgreSQL 的 DDL 都支持事务），失败就回滚并中止启动——不再像以前那样把错误吞掉。
新库先由 ``SCHEMA`` 建出基础表，再从第 1 个迁移跑起，所以每个迁移都要能在新库上安全执行
（加列前先检查列是否已存在）。

新增迁移：在 ``MIGRATIONS`` 末尾追加 ``Migration(下一个版本号, 说明, [步骤…])``，不要修改已发布的迁移。
步骤是 SQL 字符串或 ``(conn, kind) -> None`` 函数。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

Step = str | Callable[[Any, str], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    steps: list[Step] = field(default_factory=list)


def _q(sql: str, kind: str) -> str:
    from .db import to_pg

    return to_pg(sql) if kind == "postgres" else sql


def _execute(conn: Any, kind: str, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return conn.execute(_q(sql, kind), params)


def _columns(conn: Any, kind: str, table: str) -> set[str]:
    if kind == "sqlite":
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
    ).fetchall()
    return {r["column_name"] for r in rows}


def add_column(table: str, column: str, decl: str) -> Callable[[Any, str], None]:
    def step(conn: Any, kind: str) -> None:
        if column not in _columns(conn, kind, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    return step


def _share_key(stype: str, endpoint: str, config: Any) -> str:
    cfg = config if isinstance(config, dict) else json.loads(config or "{}")
    return f"{stype}|{endpoint}|{cfg.get('mode') or ''}"


def _backfill_share_keys(conn: Any, kind: str) -> None:
    """公共来源按（类型，地址，模式）去重：先把重复的公共来源合并到 id 最小的一个，再写入 share_key。"""
    rows = _execute(
        conn,
        kind,
        "SELECT id, type, endpoint, config FROM sources WHERE owner_id IS NULL ORDER BY id",
    ).fetchall()
    keep: dict[str, int] = {}
    for r in rows:
        key = _share_key(r["type"], r["endpoint"], r["config"])
        if key not in keep:
            keep[key] = r["id"]
            _execute(conn, kind, "UPDATE sources SET share_key = ? WHERE id = ?", (key, r["id"]))
            continue
        winner = keep[key]
        log.warning("merging duplicate shared source %s into %s", r["id"], winner)
        _execute(
            conn,
            kind,
            "INSERT INTO subscriptions (user_id, source_id, weight, muted, created_at) "
            "SELECT user_id, ?, weight, muted, created_at FROM subscriptions WHERE source_id = ? "
            "ON CONFLICT DO NOTHING",
            (winner, r["id"]),
        )
        _execute(conn, kind, "DELETE FROM sources WHERE id = ?", (r["id"],))


def _dedupe_clip_sources(conn: Any, kind: str) -> None:
    """每人只能有一个“网页收藏”来源（并发保存时可能建出两个）：多余的事项并到最早的一个。"""
    rows = _execute(
        conn,
        kind,
        "SELECT owner_id, MIN(id) AS keep FROM sources WHERE type = 'clip' GROUP BY owner_id HAVING COUNT(*) > 1",
    ).fetchall()
    for r in rows:
        dupes = [
            x["id"]
            for x in _execute(
                conn,
                kind,
                "SELECT id FROM sources WHERE type = 'clip' AND owner_id = ? AND id != ?",
                (r["owner_id"], r["keep"]),
            ).fetchall()
        ]
        for d in dupes:
            _execute(
                conn, kind, "UPDATE items SET source_id = ? WHERE source_id = ?", (r["keep"], d)
            )
            _execute(conn, kind, "DELETE FROM sources WHERE id = ?", (d,))


MIGRATIONS: list[Migration] = [
    Migration(
        1, "users.digest_email", [add_column("users", "digest_email", "INTEGER NOT NULL DEFAULT 0")]
    ),
    # 个人来源的身份键与别名键加所有者前缀（pipeline._scope），已有数据补上
    Migration(
        2,
        "scope personal identity keys",
        [
            """UPDATE items SET identity_key = '@' || (SELECT s.owner_id FROM sources s WHERE s.id = items.source_id)
                   || '/' || identity_key
               WHERE identity_key NOT LIKE '@%'
                 AND source_id IN (SELECT id FROM sources WHERE owner_id IS NOT NULL)"""
        ],
    ),
    Migration(
        3,
        "scope personal alias keys",
        [
            """UPDATE item_aliases SET alias_key = '@' || (SELECT s.owner_id FROM sources s WHERE s.id = item_aliases.source_id)
                   || '/' || alias_key
               WHERE alias_key NOT LIKE '@%'
                 AND source_id IN (SELECT id FROM sources WHERE owner_id IS NOT NULL)"""
        ],
    ),
    # 热点查询与级联删除用到的索引（审查 DB-5/6/30）
    Migration(
        4,
        "indexes for feed, fanout and cleanup",
        [
            "CREATE INDEX IF NOT EXISTS ix_subs_source ON subscriptions(source_id)",
            "CREATE INDEX IF NOT EXISTS ix_items_source ON items(source_id, deleted)",
            "CREATE INDEX IF NOT EXISTS ix_items_updated ON items(updated_at)",
            "CREATE INDEX IF NOT EXISTS ix_items_kind ON items(kind)",
            "CREATE INDEX IF NOT EXISTS ix_aliases_item ON item_aliases(item_id)",
            "CREATE INDEX IF NOT EXISTS ix_aliases_source ON item_aliases(source_id)",
            "CREATE INDEX IF NOT EXISTS ix_state_item ON user_item_state(item_id)",
            "CREATE INDEX IF NOT EXISTS ix_credentials_source ON credentials(source_id)",
            "CREATE INDEX IF NOT EXISTS ix_sources_owner ON sources(owner_id)",
            "CREATE INDEX IF NOT EXISTS ix_sources_endpoint ON sources(endpoint, type)",
            "CREATE INDEX IF NOT EXISTS ix_transfer_files_transfer ON transfer_files(transfer_id)",
            "CREATE INDEX IF NOT EXISTS ix_transfers_expires ON transfers(expires_at)",
            "CREATE INDEX IF NOT EXISTS ix_events_user ON events(user_id)",
            "CREATE INDEX IF NOT EXISTS ix_events_kind ON events(kind, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_deliveries_item ON deliveries(item_id)",
            "CREATE INDEX IF NOT EXISTS ix_deliveries_created ON deliveries(created_at)",
            "CREATE INDEX IF NOT EXISTS ix_op_log_created ON op_log(created_at)",
            "CREATE INDEX IF NOT EXISTS ix_sent_mails_status ON sent_mails(status, created_at)",
        ],
    ),
    # 公共来源与网页收藏的唯一性由数据库保证（审查 DB-19：并发添加同一网址会建出两个公共来源）
    Migration(
        5,
        "unique shared sources and clip sources",
        [
            add_column("sources", "share_key", "TEXT"),
            _backfill_share_keys,
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_sources_share ON sources(share_key) WHERE share_key IS NOT NULL",
            _dedupe_clip_sources,
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_sources_clip ON sources(owner_id) WHERE type = 'clip'",
        ],
    ),
    # 调度器只取即将到期的来源；每日摘要只查当前分钟的用户（审查 DB-29/36）
    Migration(
        6,
        "indexes for scheduler and digests",
        [
            "CREATE INDEX IF NOT EXISTS ix_sources_due ON sources(via_agent, next_fetch_at)",
            "CREATE INDEX IF NOT EXISTS ix_users_digest ON users(digest_time)",
        ],
    ),
]


def share_key(stype: str, endpoint: str, config: dict[str, Any]) -> str:
    """公共来源的唯一键（添加来源时写入，迁移 5 补齐已有数据）。"""
    return _share_key(stype, endpoint, config)


def run_migrations(conn: Any, kind: str) -> list[int]:
    """在一条连接上执行尚未执行的迁移，返回本次执行的版本号。调用方负责并发互斥（PostgreSQL 用咨询锁）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at "
        + ("DOUBLE PRECISION" if kind == "postgres" else "REAL")
        + " NOT NULL)"
    )
    done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    applied = []
    for m in MIGRATIONS:
        if m.version in done:
            continue
        conn.execute("BEGIN IMMEDIATE" if kind == "sqlite" else "BEGIN")
        try:
            for step in m.steps:
                if callable(step):
                    step(conn, kind)
                else:
                    conn.execute(step)
            _execute(
                conn,
                kind,
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (m.version, m.name, time.time()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            log.exception("migration %s (%s) failed", m.version, m.name)
            raise
        applied.append(m.version)
        log.info("applied migration %s: %s", m.version, m.name)
    return applied
