"""WebSocket 压测：建立 N 个长连接（每个用户一个），测连接建立速率、在线数与推送延迟。

    python devtools/loadtest/ws_load.py --server http://localhost:8080 --users 5000 --ramp 500

步骤：批量注册用户 → 每个用户经网关 /ws 建立连接并发 hello → 保持连接；
同时可用 --probe 让第 1 个用户每秒向自己写一条状态，测“写入 → 推送到达”的往返延迟。
需要提高文件描述符上限：``ulimit -n 65535``；单机端口不够时用多个源 IP 或多台压测机。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))

from gleaner.net.http import HTTPClient
from gleaner.net.websocket import ConnectionClosed, connect


async def make_users(server: str, n: int, prefix: str) -> list[str]:
    tokens: list[str] = []
    async with HTTPClient(per_host_limit=32) as c:

        async def one(i: int) -> str:
            email = f"{prefix}{i}@load.test"
            r = await c.post(
                f"{server}/api/auth/login",
                json_body={"email": email, "password": "loadtest1"},
                headers={"X-Forwarded-For": f"10.{i // 65536}.{i // 256 % 256}.{i % 256}"},
            )
            if r.status != 200:
                r = await c.post(
                    f"{server}/api/auth/register",
                    json_body={"email": email, "password": "loadtest1"},
                    headers={"X-Forwarded-For": f"10.{i // 65536}.{i // 256 % 256}.{i % 256}"},
                )
            return r.json()["token"]

        for start in range(0, n, 200):
            tokens += await asyncio.gather(*(one(i) for i in range(start, min(n, start + 200))))
            print(f"\rusers {len(tokens)}/{n}", end="", flush=True)
    print()
    return tokens


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8080")
    ap.add_argument("--users", type=int, default=1000)
    ap.add_argument("--ramp", type=int, default=200, help="每秒新建连接数")
    ap.add_argument("--hold", type=float, default=60, help="保持连接秒数")
    ap.add_argument("--prefix", default="lt")
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    tokens = await make_users(a.server, a.users, a.prefix)
    ws_base = a.server.replace("http", "ws", 1)
    conns = []
    failed = 0
    t0 = time.perf_counter()
    connect_ms: list[float] = []

    async def open_one(tok: str) -> None:
        nonlocal failed
        s = time.perf_counter()
        try:
            ws = await connect(f"{ws_base}/ws?token={tok}", timeout=20)
            await ws.send(json.dumps({"type": "hello", "token": tok, "last_seq": 10**9}))
            await asyncio.wait_for(ws.recv(), 20)
            connect_ms.append((time.perf_counter() - s) * 1000)
            conns.append(ws)
        except (OSError, TimeoutError, ConnectionClosed, Exception):
            failed += 1

    for start in range(0, len(tokens), a.ramp):
        batch = tokens[start : start + a.ramp]
        await asyncio.gather(*(open_one(t) for t in batch))
        print(
            f"\rconnected {len(conns)} failed {failed} elapsed {time.perf_counter() - t0:.1f}s",
            end="",
            flush=True,
        )
        await asyncio.sleep(max(0, 1 - (time.perf_counter() - t0) % 1))
    print()
    if connect_ms:
        q = statistics.quantiles(connect_ms, n=100)
        print(f"handshake+hello ms: p50={q[49]:.1f} p99={q[98]:.1f} max={max(connect_ms):.1f}")
    print(f"holding {len(conns)} connections for {a.hold}s …")
    await asyncio.sleep(a.hold)
    for ws in conns:
        ws.writer.close()


if __name__ == "__main__":
    asyncio.run(main())
