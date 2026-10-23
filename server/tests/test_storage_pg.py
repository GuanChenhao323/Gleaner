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
    db = await Database(PG).connect()
    try:
        assert await db.fetchval("SELECT 1") == 1
        await asyncio.to_thread(_kill_backends)
        with pytest.raises(psycopg.OperationalError):  # 断线时正在执行的这一条失败，不自动重试
            await db.fetchval("SELECT 1")
        assert await db.fetchval("SELECT 1") == 1

        # 事务中途断线：不能换新连接把后半段语句提交到事务之外
        with pytest.raises(psycopg.OperationalError):
            async with db.transaction():
                await db.execute("UPDATE users SET name = 'x' WHERE id = 0")
                await asyncio.to_thread(_kill_backends)
                await db.execute("UPDATE users SET name = 'y' WHERE id = 0")
        assert await db.fetchval("SELECT 1") == 1
    finally:
        await db.close()
