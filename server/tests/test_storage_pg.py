"""PostgreSQL 路径（需要真实数据库，默认跳过）。

    GLEANER_TEST_PG=postgresql://gleaner:gleaner@localhost:5432/gleaner_test pytest tests/test_storage_pg.py

库会被清空重建，不要指向有数据的库。
"""

from __future__ import annotations

import asyncio
import os
import time

import psycopg
import pytest

from gleaner.storage.db import Database

PG = os.environ.get("GLEANER_TEST_PG", "")
pytestmark = pytest.mark.skipif(not PG, reason="未设置 GLEANER_TEST_PG")


def _reset() -> None:
    import psycopg

    with psycopg.connect(PG, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")


async def test_concurrent_schema_init() -> None:
    # compose 启动时多个服务同时建表，曾因 pg_type 唯一约束冲突导致推送节点崩溃重启
    await asyncio.to_thread(_reset)
    dbs = [Database(PG) for _ in range(6)]
    await asyncio.gather(*(asyncio.to_thread(d._init_sync) for d in dbs))
    try:
        uid = await dbs[0].insert(
            "users",
            {
                "email": "pg@test.local",
                "password_hash": "x",
                "name": "pg",
                "created_at": time.time(),
            },
        )
        row = await dbs[1].fetchone("SELECT digest_email FROM users WHERE id = ?", uid)
        assert row is not None and row["digest_email"] == 0
    finally:
        for d in dbs:
            await d.close()


def _kill_backends() -> None:
    import psycopg

    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )


async def test_reconnect_after_server_drops_connection() -> None:
    # 数据库重启后不重连，业务服务会一直报 "the connection is closed"（compose 实测发现）
    await asyncio.to_thread(_reset)
    db = await Database(PG, pool_size=1).connect()
    try:
        assert await db.fetchval("SELECT 1") == 1
        await asyncio.to_thread(_kill_backends)
        # 只读语句：发现连接已断就重连后重试一次，调用方无感
        assert await db.fetchval("SELECT 1") == 1
        await asyncio.to_thread(_kill_backends)
        # 写语句不自动重试（可能已经执行过），这一条失败，下一条恢复
        with pytest.raises(psycopg.OperationalError):
            await db.execute("UPDATE users SET name = 'x' WHERE id = 0")
        assert await db.execute("UPDATE users SET name = 'x' WHERE id = 0") == 0

        # 事务中途断线：不能换新连接把后半段语句提交到事务之外
        with pytest.raises(psycopg.OperationalError):
            async with db.transaction():
                await db.execute("UPDATE users SET name = 'x' WHERE id = 0")
                await asyncio.to_thread(_kill_backends)
                await db.execute("UPDATE users SET name = 'y' WHERE id = 0")
        assert await db.fetchval("SELECT 1") == 1
    finally:
        await db.close()


async def test_pool_runs_statements_concurrently() -> None:
    """连接池：4 条连接上 8 条各 0.3 秒的查询约 0.6 秒完成（单连接要 2.4 秒）。"""
    import time

    await asyncio.to_thread(_reset)
    db = await Database(PG, pool_size=4).connect()
    try:
        t0 = time.perf_counter()
        await asyncio.gather(*(db.fetchval("SELECT pg_sleep(0.3)") for _ in range(8)))
        assert time.perf_counter() - t0 < 1.5
        # 事务固定一条连接：事务内看得到自己未提交的写入，事务外看不到
        async with db.transaction():
            await db.insert(
                "users", {"email": "tx@test.local", "password_hash": "x", "created_at": 0}
            )
            assert (
                await db.fetchval("SELECT COUNT(*) FROM users WHERE email = 'tx@test.local'") == 1
            )
            other = await asyncio.create_task(_count_outside(db))
            assert other == 0
        assert await db.fetchval("SELECT COUNT(*) FROM users WHERE email = 'tx@test.local'") == 1
    finally:
        await db.close()


async def _count_outside(db: Database) -> int:
    from gleaner.storage import db as dbmod

    dbmod._TX.set(None)  # 新任务继承了上下文：显式退出事务，模拟另一个请求
    return await db.fetchval("SELECT COUNT(*) FROM users WHERE email = 'tx@test.local'")
