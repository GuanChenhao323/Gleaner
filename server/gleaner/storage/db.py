"""数据库访问：同一套 SQL 跑在 SQLite（开发、测试）与 PostgreSQL 16（部署）上。

SQL 一律用 ``?`` 占位，PostgreSQL 下由 ``to_pg`` 换成 ``%s``（跳过字符串字面量，字面量 ``%`` 转义）。
驱动是同步的，调用放到线程池。

连接池：PostgreSQL 默认 4 条连接（``GLEANER_DB_POOL``），语句各自借一条连接执行，互不排队；
SQLite 只有一个写者，固定 1 条连接（开发、测试用）。事务把一条连接固定在当前协程上下文里
（contextvar），事务内的语句都走这条连接；事务里不要再创建任务（任务会继承上下文，与本协程抢同一条连接）。

连接每条都设连接超时与语句超时（PostgreSQL ``statement_timeout``）；断开后在下一次借出时重连，
事务中途断开不重连（否则后半段语句会落在事务之外），失败的那条语句不自动重试（写操作可能已执行）。
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import os
import sqlite3
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any

from .migrations import run_migrations
from .schema import SCHEMA

log = logging.getLogger(__name__)

Row = dict[str, Any]

_SCHEMA_LOCK = 0x474C5343  # 建表与迁移用的 PostgreSQL 咨询锁编号（"GLSC"）
STATEMENT_TIMEOUT_MS = int(os.environ.get("GLEANER_DB_STATEMENT_TIMEOUT_MS", "15000"))

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
    "sessions",
    "schema_migrations",
}


def to_pg(sql: str) -> str:
    """``?`` → ``%s``，字面量 ``%`` → ``%%``；单引号字符串与双引号标识符里的 ``?`` 原样保留。"""
    out: list[str] = []
    quote = ""
    for ch in sql:
        if quote:
            if ch == quote:
                quote = ""
            out.append("%%" if ch == "%" else ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


def _adapt(v: Any) -> Any:
    if isinstance(v, dict | list):
        return json.dumps(v, ensure_ascii=False, default=str)
    if isinstance(v, bool):
        return int(v)
    return v


def is_unique_violation(exc: BaseException) -> bool:
    """是否为唯一约束冲突（SQLite 与 PostgreSQL 两种驱动的异常类型不同）。"""
    if isinstance(exc, sqlite3.IntegrityError):
        return "UNIQUE" in str(exc).upper() or "PRIMARY KEY" in str(exc).upper()
    return getattr(exc, "sqlstate", None) == "23505"  # psycopg: unique_violation


def loads(v: Any, default: Any = None) -> Any:
    if v is None or v == "":
        return default
    if isinstance(v, dict | list):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


class _Slot:
    """池里的一条连接（懒连接，断开后在下次借出时重连）。"""

    __slots__ = ("conn",)

    def __init__(self) -> None:
        self.conn: Any = None


# 当前上下文正在进行的事务：（所属 Database，固定的连接）
_TX: contextvars.ContextVar[tuple[Database, _Slot] | None] = contextvars.ContextVar(
    "_tx", default=None
)


class Database:
    def __init__(self, url: str, *, pool_size: int | None = None) -> None:
        """``sqlite:///path.db``、``sqlite://:memory:`` 或 ``postgresql://user:pw@host/db``。"""
        self.url = url
        self.kind = "postgres" if url.startswith(("postgres://", "postgresql://")) else "sqlite"
        if self.kind == "sqlite":
            self.pool_size = 1  # SQLite 只有一个写者；内存库也必须共用同一条连接
        else:
            self.pool_size = max(1, pool_size or int(os.environ.get("GLEANER_DB_POOL", "4")))
        self._slots = [_Slot() for _ in range(self.pool_size)]
        self._idle: asyncio.Queue[_Slot] | None = None

    # -- 连接 --------------------------------------------------------------------

    def _connect(self, *, statement_timeout: bool = True) -> Any:
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

        opts = f"-c statement_timeout={STATEMENT_TIMEOUT_MS if statement_timeout else 0}"
        return psycopg.connect(
            self.url,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=5,
            options=opts,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
        )

    def _ready(self, slot: _Slot, *, reconnect: bool) -> Any:
        if slot.conn is not None and getattr(slot.conn, "closed", False):
            if not reconnect:
                return slot.conn  # 事务中途断开：照常执行，让驱动报错
            log.warning("database connection lost, reconnecting")
            slot.conn = None
        if slot.conn is None:
            slot.conn = self._connect()
        return slot.conn

    def _queue(self) -> asyncio.Queue[_Slot]:
        if self._idle is None:
            self._idle = asyncio.Queue()
            for s in self._slots:
                self._idle.put_nowait(s)
        return self._idle

    async def _acquire(self) -> _Slot:
        return await self._queue().get()

    def _release(self, slot: _Slot) -> None:
        self._queue().put_nowait(slot)

    async def connect(self) -> Database:
        await asyncio.to_thread(self._init_sync)
        return self

    def _init_sync(self) -> None:
        """建表并执行迁移。用一条单独的连接（不设语句超时：大表迁移可能较慢）。"""
        conn = self._connect(statement_timeout=False)
        try:
            if self.kind == "postgres":
                # 多个服务同时启动时并发建表 / 迁移：会话级咨询锁串行化
                conn.execute("SELECT pg_advisory_lock(%s)", (_SCHEMA_LOCK,))
            try:
                for ddl in SCHEMA:
                    if self.kind == "postgres":
                        ddl = (
                            ddl.replace(
                                "INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY"
                            )
                            .replace("REAL", "DOUBLE PRECISION")
                            .replace("BLOB", "BYTEA")
                        )
                    conn.execute(ddl)
                run_migrations(conn, self.kind)
            finally:
                if self.kind == "postgres":
                    conn.execute("SELECT pg_advisory_unlock(%s)", (_SCHEMA_LOCK,))
        finally:
            conn.close()

    async def close(self) -> None:
        conns = [s.conn for s in self._slots if s.conn is not None]
        for s in self._slots:
            s.conn = None
        for c in conns:
            await asyncio.to_thread(c.close)

    # -- 执行 --------------------------------------------------------------------

    def _exec_sync(
        self, slot: _Slot, sql: str, params: Sequence[Any], fetch: str, reconnect: bool
    ) -> Any:
        conn = self._ready(slot, reconnect=reconnect)
        q = to_pg(sql) if self.kind == "postgres" else sql
        try:
            cur = conn.execute(q, tuple(params))
        except Exception:
            if (
                reconnect
                and fetch in ("all", "one")
                and sql.lstrip()[:6].upper() == "SELECT"
                and getattr(conn, "closed", False)
            ):
                # 池里的空闲连接在数据库重启后才被发现已断：只读语句可以安全地重连后重试一次
                log.warning("database connection lost during read, reconnecting")
                slot.conn = None
                cur = self._ready(slot, reconnect=True).execute(q, tuple(params))
            else:
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

    async def _run(self, sql: str, params: Sequence[Any], fetch: str) -> Any:
        params = [_adapt(p) for p in params]
        tx = _TX.get()
        if tx is not None and tx[0] is self:
            return await asyncio.to_thread(self._exec_sync, tx[1], sql, params, fetch, False)
        slot = await self._acquire()
        try:
            return await asyncio.to_thread(self._exec_sync, slot, sql, params, fetch, True)
        finally:
            self._release(slot)

    async def fetch(self, sql: str, *params: Any) -> list[Row]:
        return await self._run(sql, params, "all")

    async def fetchone(self, sql: str, *params: Any) -> Row | None:
        return await self._run(sql, params, "one")

    async def fetchval(self, sql: str, *params: Any) -> Any:
        row = await self.fetchone(sql, *params)
        return next(iter(row.values())) if row else None

    async def execute(self, sql: str, *params: Any) -> int:
        return await self._run(sql, params, "count")

    async def insert(self, table: str, values: dict[str, Any], *, on_conflict: str = "") -> int:
        cols = list(values)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) {on_conflict}"
        if self.kind == "postgres" and table not in _NO_ID:
            sql += " RETURNING id"
        return await self._run(sql, list(values.values()), "id")

    async def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        data = [tuple(_adapt(v) for v in r) for r in rows]

        def run(slot: _Slot, reconnect: bool) -> None:
            conn = self._ready(slot, reconnect=reconnect)
            if self.kind == "sqlite":
                conn.executemany(sql, data)
            else:
                with conn.cursor() as cur:
                    cur.executemany(to_pg(sql), data)

        tx = _TX.get()
        if tx is not None and tx[0] is self:
            await asyncio.to_thread(run, tx[1], False)
            return
        slot = await self._acquire()
        try:
            await asyncio.to_thread(run, slot, True)
        finally:
            self._release(slot)

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[Database]:
        """事务：固定一条连接，块内语句都在这条连接上执行；嵌套调用复用外层事务。"""
        outer = _TX.get()
        if outer is not None and outer[0] is self:
            yield self
            return
        slot = await self._acquire()
        token = _TX.set((self, slot))
        try:
            begin = "BEGIN IMMEDIATE" if self.kind == "sqlite" else "BEGIN"
            await asyncio.to_thread(self._exec_sync, slot, begin, (), "count", True)
            try:
                yield self
            except BaseException:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self._exec_sync, slot, "ROLLBACK", (), "count", False)
                raise
            await asyncio.to_thread(self._exec_sync, slot, "COMMIT", (), "count", False)
        finally:
            _TX.reset(token)
            self._release(slot)
