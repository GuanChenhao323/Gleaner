"""推送压测：经网关建立 N 个 WebSocket 长连接，再从总线发布带时间戳的消息，测送达延迟与推送节点资源占用。

    python devtools/loadtest/push_bench.py capacity --users 5000            # 单推送节点容量 + 推送延迟
    python devtools/loadtest/push_bench.py selector --conns 100,200,400     # 实验 1（Windows：select 与 IOCP）
    python devtools/loadtest/push_bench.py scale --users 3000               # 实验 5：单节点与三节点

延迟口径：总线发布 → 客户端收到（不含业务服务写库），压测客户端与服务同机，时钟一致。
令牌直接用开发密钥签发（GLEANER_SECRET 未设置时的默认值），无需注册账号。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cluster import ROOT, Cluster  # noqa: E402
from experiments import q, save  # noqa: E402

sys.path.insert(0, str(ROOT / "server"))
from gleaner import security  # noqa: E402
from gleaner.net.bus import BusClient  # noqa: E402
from gleaner.net.websocket import ConnectionClosed, connect  # noqa: E402

UID0 = 1_000_000


class Clients:
    def __init__(self, url: str, direct_port: int | None = None) -> None:
        self.ws_url = url.replace("http", "ws", 1) + "/ws"
        # 直连推送节点时轮流使用 127.0.0.1–4：WSL 镜像网络把临时端口限制在 4096 个，
        # 每个目的地址各有一份端口空间，分散后单机才能建出 5000 条连接
        self.direct_port = direct_port
        self.conns: dict[int, Any] = {}
        self.lat: list[float] = []
        self.received = 0
        self.failed = 0
        self.errors: dict[str, int] = {}
        self.connect_ms: list[float] = []
        self.nodes: dict[str, int] = {}
        self._tasks: list[asyncio.Task[None]] = []

    async def open(self, n: int, ramp: int) -> float:
        t0 = time.perf_counter()

        async def one(i: int) -> None:
            uid = UID0 + i
            tok = security.sign_token({"uid": uid, "tv": 1})
            s = time.perf_counter()
            try:
                base = f"ws://127.0.0.{1 + i % 4}:{self.direct_port}/ws" if self.direct_port else self.ws_url
                ws = await connect(
                    f"{base}?token={tok}",
                    headers={"X-Forwarded-For": f"10.{i // 65536}.{i // 256 % 256}.{i % 256}"},
                    timeout=30,
                )
                await ws.send(json.dumps({"type": "hello", "token": tok, "last_seq": 10**9}))
                welcome = json.loads((await asyncio.wait_for(ws.recv(), 30)).text)
                self.nodes[welcome["node"]] = self.nodes.get(welcome["node"], 0) + 1
            except (OSError, TimeoutError, ConnectionClosed, Exception) as e:
                self.failed += 1
                key = f"{type(e).__name__}: {e}"[:80]
                self.errors[key] = self.errors.get(key, 0) + 1
                return
            self.connect_ms.append((time.perf_counter() - s) * 1000)
            self.conns[uid] = ws
            self._tasks.append(asyncio.create_task(self._read(ws)))

        for start in range(0, n, ramp):
            await asyncio.gather(*(one(i) for i in range(start, min(n, start + ramp))))
        if self.errors:
            print("建连失败原因:", self.errors, file=sys.stderr)
        return time.perf_counter() - t0

    async def _read(self, ws: Any) -> None:
        try:
            async for m in ws:
                d = json.loads(m.text)
                if d.get("type") == "bench":
                    self.lat.append((time.time() - d["t"]) * 1000)
                    self.received += 1
        except Exception:
            pass

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        for ws in self.conns.values():
            ws.writer.close()


async def publish(bus: BusClient, uids: list[int], rate: float, seconds: float) -> int:
    """按固定速率随机挑用户发布，模拟“新事项入库后推送”。"""
    sent = 0
    t0 = time.time()
    while time.time() - t0 < seconds:
        uid = random.choice(uids)
        await bus.publish(f"u.{uid}", {"type": "bench", "t": time.time(), "priority": "normal"})
        sent += 1
        await asyncio.sleep(max(0.0, t0 + sent / rate - time.time()))
    return sent


async def broadcast(bus: BusClient, uids: list[int]) -> None:
    t = time.time()
    for uid in uids:
        await bus.publish(f"u.{uid}", {"type": "bench", "t": t, "priority": "normal"})


async def measure(
    cluster: Cluster, users: int, ramp: int, rate: float, seconds: float, label: str, direct: bool = False
) -> dict[str, Any]:
    push_names = [n for n in cluster.procs if n.startswith("push")]
    cl = Clients(cluster.gateway_url, cluster.push_port(0) if direct else None)
    open_s = await cl.open(users, ramp)
    bus = BusClient("bench", "bench", *cluster.bus, secret=security.bus_secret())
    bus.start()
    await bus.wait_connected()
    await asyncio.sleep(2)
    u0 = cluster.usage(push_names)
    t0 = time.time()
    uids = list(cl.conns)
    sent = await publish(bus, uids, rate, seconds) if uids else 0
    await asyncio.sleep(2)
    steady = list(cl.lat)
    # 一次性向所有在线用户各推一条（扇出），看最后一条何时送达
    cl.lat.clear()
    before = cl.received
    bt = time.time()
    await broadcast(bus, uids)
    deadline = time.time() + 60
    while cl.received - before < len(uids) and time.time() < deadline:
        await asyncio.sleep(0.05)
    fan_s = time.time() - bt
    wall = time.time() - t0
    u1 = cluster.usage(push_names)
    cpu = sum(u1[n]["cpu_s"] - u0[n]["cpu_s"] for n in push_names)
    row = {
        "场景": label,
        "目标连接": users,
        "成功连接": len(cl.conns),
        "失败": cl.failed,
        "建连耗时 s": round(open_s, 1),
        "握手 P99 ms": q(cl.connect_ms, 99),
        "节点分布": " ".join(f"{k}:{v}" for k, v in sorted(cl.nodes.items())),
        "推送速率 msg/s": rate,
        "推送 P50 ms": q(steady, 50),
        "推送 P99 ms": q(steady, 99),
        "送达": f"{len(steady)}/{sent}",
        "全员扇出耗时 s": round(fan_s, 2),
        "推送节点 CPU %": round(100 * cpu / wall, 1),
        "推送节点内存 MB": round(sum(u1[n]["rss_mb"] for n in push_names), 1),
    }
    await bus.close()
    await cl.close()
    return row


async def capacity(users: int, ramp: int, rate: float, seconds: float, direct: bool) -> None:
    rows = []
    for io in ("asyncio", "reactor"):
        if io == "reactor" and sys.platform == "win32" and users > 450:
            # Windows 的 select 最多 512 个 socket；手写反应器在 Windows 上只测到这个规模，大规模留给 Linux epoll
            continue
        with Cluster(1, push_io=io) as c:
            rows.append(await measure(c, users, ramp, rate, seconds, f"单节点 {io}", direct))
    path = "直连推送节点（绕过网关）" if direct else "经网关建连"
    name = "push_capacity_direct" if direct else "push_capacity"
    save(name, rows, f"{sys.platform}；{path}；延迟口径为总线发布→客户端收到；客户端与服务同机")


async def selector_exp(conns: list[int], rate: float, seconds: float) -> None:
    rows = []
    modes = [("reactor", "select")] + ([("asyncio", "auto")] if sys.platform == "win32" else [("reactor", "epoll")])
    for n in conns:
        for io, sel in modes:
            if sel == "select" and sys.platform != "win32" and n > 900:
                continue  # 文件描述符超过 FD_SETSIZE=1024 后 select() 直接报错
            with Cluster(1, push_io=io, selector=sel) as c:
                name = "select（手写反应器）" if sel == "select" else ("IOCP（asyncio Proactor）" if io == "asyncio" else "epoll（手写反应器）")
                rows.append(await measure(c, n, 100, rate, seconds, name))
    if sys.platform == "win32":
        note = "Windows 上没有 epoll，先以 IOCP 作对照"
    else:
        note = "select 受 FD_SETSIZE=1024 限制，900 连接以上只测 epoll"
    save("exp1_selector", rows, f"{sys.platform}；{note}")


async def scale(users: int, rate: float, seconds: float, io: str) -> None:
    rows = []
    for n in (1, 3):
        with Cluster(n, push_io=io) as c:
            rows.append(await measure(c, users, 250, rate, seconds, f"{n} 个推送节点"))
    save("exp5_scale", rows, f"{sys.platform}；push_io={io}；同一台机器上的多进程，主要体现一致性哈希分布与单进程压力分摊")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capacity")
    c.add_argument("--users", type=int, default=5000)
    c.add_argument("--ramp", type=int, default=250)
    c.add_argument("--direct", action="store_true", help="绕过网关直连推送节点（WSL 临时端口只有 4096 个时使用）")
    s = sub.add_parser("selector")
    s.add_argument("--conns", default="100,200,400")
    sc = sub.add_parser("scale")
    sc.add_argument("--users", type=int, default=3000)
    sc.add_argument("--io", default="asyncio" if sys.platform == "win32" else "reactor")
    for p in (c, s, sc):
        p.add_argument("--rate", type=float, default=200)
        p.add_argument("--seconds", type=float, default=15)
    a = ap.parse_args()
    if a.cmd == "capacity":
        asyncio.run(capacity(a.users, a.ramp, a.rate, a.seconds, a.direct))
    elif a.cmd == "selector":
        asyncio.run(selector_exp([int(x) for x in a.conns.split(",")], a.rate, a.seconds))
    else:
        asyncio.run(scale(a.users, a.rate, a.seconds, a.io))


if __name__ == "__main__":
    main()
