"""数据库访问：同一套 SQL 跑在 SQLite（开发、测试）与 PostgreSQL 16（部署）上。

SQL 一律用 ``?`` 占位，PostgreSQL 下自动换成 ``%s``。驱动是同步的，调用放到线程池；
每个进程一个连接，用 asyncio 锁串行化，事务通过 contextvar 识别——对课程规模足够，
瓶颈分析写入性能报告。
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import re
import sqlite3
import threading
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any

from .schema import MIGRATIONS, SCHEMA

log = logging.getLogger(__name__)

Row = dict[str, Any]

_IN_TX: contextvars.ContextVar[bool] = contextvars.ContextVar("_in_tx", default=False)

# 没有自增 id 列的表（PostgreSQL 下 INSERT 不加 RETURNING id）
_NO_ID = {
    "subscriptions",
    "user_item_state",
    "deliveries",
    "op_log",
    "item_aliases",
    "reminders_sent",
    "dashboards",
    "item_versions",
}


def _to_pg(sql: str) -> str:
    return re.sub(r"\?", "%s", sql)


def _adapt(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    if isinstance(v, bool):
        return int(v)
    return v


def loads(v: Any, default: Any = None) -> Any:
    if v is None or v == "":
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


class Database:
    def __init__(self, url: str) -> None:
        """``sqlite:///path.db``、``sqlite://:memory:`` 或 ``postgresql://user:pw@host/db``。"""
        self.url = url
        self.kind = "postgres" if url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self._tlock = threading.Lock()
        self._conn: Any = None
        self._alock: asyncio.Lock | None = None

    # -- 连接 --------------------------------------------------------------------

    def _connect(self) -> Any:
        if self.kind == "sqlite":
            path = (
                self.url[len("sqlite:///") :] if self.url.startswith("sqlite:///") else ":memory:"
            )
            conn = sqlite3.connect(
                path or ":memory:", check_same_thread=False, isolation_level=None, timeout=30
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            return conn
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.url, autocommit=True, row_factory=dict_row)

    def _get(self) -> Any:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    async def connect(self) -> Database:
        await asyncio.to_thread(self._init_sync)
        return self

    def _init_sync(self) -> None:
        with self._tlock:
            conn = self._get()
            for ddl in SCHEMA:
                if self.kind == "postgres":
                    ddl = (
                        ddl.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
                        .replace("REAL", "DOUBLE PRECISION")
                        .replace("BLOB", "BYTEA")
                    )
                conn.execute(ddl)
            for ddl in MIGRATIONS:
                try:
                    conn.execute(ddl)
                except Exception:  # 列已存在（两种驱动都是自动提交模式，失败不影响后续语句）
                    log.debug("migration skipped: %s", ddl)

    async def close(self) -> None:
        with self._tlock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # -- 执行 --------------------------------------------------------------------

    def _exec_sync(self, sql: str, params: Sequence[Any], fetch: str) -> Any:
        with self._tlock:
            conn = self._get()
            q = _to_pg(sql) if self.kind == "postgres" else sql
            try:
                cur = conn.execute(q, tuple(params))
            except Exception:
                log.error("SQL failed: %s", sql)
                raise
            if fetch == "all":
                return [dict(r) for r in cur.fetchall()]
            if fetch == "one":
                r = cur.fetchone()
                return dict(r) if r is not None else None
            if fetch == "id":
                if self.kind == "sqlite":
                    return cur.lastrowid
                r = cur.fetchone() if cur.description else None
                return (dict(r) if r else {}).get("id")
            return cur.rowcount

    def _lock(self) -> asyncio.Lock:
        if self._alock is None:
            self._alock = asyncio.Lock()
        return self._alock

    async def _run(self, sql: str, params: Sequence[Any], fetch: str) -> Any:
        if _IN_TX.get():
            return await asyncio.to_thread(self._exec_sync, sql, params, fetch)
        async with self._lock():
            return await asyncio.to_thread(self._exec_sync, sql, params, fetch)

    async def fetch(self, sql: str, *params: Any) -> list[Row]:
        return await self._run(sql, params, "all")

    async def fetchone(self, sql: str, *params: Any) -> Row | None:
        return await self._run(sql, params, "one")

    async def fetchval(self, sql: str, *params: Any) -> Any:
        row = await self.fetchone(sql, *params)
        return next(iter(row.values())) if row else None

    async def execute(self, sql: str, *params: Any) -> int:
        return await self._run(sql, [_adapt(p) for p in params], "count")

    async def insert(self, table: str, values: dict[str, Any], *, on_conflict: str = "") -> int:
        cols = list(values)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) {on_conflict}"
        if self.kind == "postgres" and table not in _NO_ID:
            sql += " RETURNING id"
        return await self._run(sql, [_adapt(v) for v in values.values()], "id")

    async def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        data = [tuple(_adapt(v) for v in r) for r in rows]

        def run() -> None:
            with self._tlock:
                conn = self._get()
                if self.kind == "sqlite":
                    conn.executemany(sql, data)
                else:
                    with conn.cursor() as cur:
                        cur.executemany(_to_pg(sql), data)

        async with self._lock():
            await asyncio.to_thread(run)

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[Database]:
        """串行事务，用于按用户分配 seq 这类需要原子性的操作。事务内不要再创建任务。"""
        if _IN_TX.get():
            yield self
            return
        async with self._lock():
            token = _IN_TX.set(True)
            try:
                await self._run(
                    "BEGIN IMMEDIATE" if self.kind == "sqlite" else "BEGIN", (), "count"
                )
                try:
                    yield self
                except BaseException:
                    await self._run("ROLLBACK", (), "count")
                    raise
                await self._run("COMMIT", (), "count")
            finally:
                _IN_TX.reset(token)
