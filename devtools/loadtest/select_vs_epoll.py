"""对比实验 1：select 与 epoll。

用同一个基于 ``selectors`` 的回显服务器，分别指定 SelectSelector / EpollSelector，
连接数从 500 增加到 5000，每个连接每秒发一条小消息，记录 CPU 占用与往返延迟。

    python devtools/loadtest/select_vs_epoll.py --selector epoll --conns 500,1000,2000,5000
    python devtools/loadtest/select_vs_epoll.py --selector select --conns 500,1000     # select 受 FD_SETSIZE=1024 限制

结果以 CSV 打印，直接用于报告图表。Windows 上没有 epoll，请在 Linux / WSL / 容器中运行。
"""

from __future__ import annotations

import argparse
import asyncio
import multiprocessing as mp
import os
import selectors
import socket
import statistics
import time


def serve(kind: str, port: int, ready: mp.Event) -> None:  # type: ignore[valid-type]
    sel: selectors.BaseSelector = {
        "select": selectors.SelectSelector,
        "epoll": getattr(selectors, "EpollSelector", selectors.DefaultSelector),
        "poll": getattr(selectors, "PollSelector", selectors.DefaultSelector),
    }[kind]()
    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", port))
    ls.listen(4096)
    ls.setblocking(False)
    sel.register(ls, selectors.EVENT_READ)
    ready.set()
    while True:
        for key, _ in sel.select():
            s = key.fileobj
            if s is ls:
                c, _ = ls.accept()
                c.setblocking(False)
                sel.register(c, selectors.EVENT_READ)
                continue
            try:
                data = s.recv(4096)  # type: ignore[union-attr]
            except (BlockingIOError, ConnectionError):
                data = b""
            if data:
                s.send(data)  # type: ignore[union-attr]
            else:
                sel.unregister(s)
                s.close()  # type: ignore[union-attr]


async def client(port: int, n: int, duration: float) -> list[float]:
    lat: list[float] = []
    conns = []
    for _ in range(n):
        conns.append(await asyncio.open_connection("127.0.0.1", port))

    async def one(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        end = time.perf_counter() + duration
        while time.perf_counter() < end:
            t = time.perf_counter()
            w.write(b"ping\n")
            await w.drain()
            await r.readline()
            lat.append((time.perf_counter() - t) * 1000)
            await asyncio.sleep(1)

    await asyncio.gather(*(one(r, w) for r, w in conns))
    for _, w in conns:
        w.close()
    return lat


def cpu_of(pid: int) -> float:
    try:
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().split()
        return (int(parts[13]) + int(parts[14])) / os.sysconf("SC_CLK_TCK")
    except OSError:
        return float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selector", default="epoll", choices=["select", "poll", "epoll"])
    ap.add_argument("--conns", default="500,1000,2000,5000")
    ap.add_argument("--duration", type=float, default=10)
    a = ap.parse_args()
    print("selector,conns,cpu_seconds,p50_ms,p99_ms")
    for i, n in enumerate(int(x) for x in a.conns.split(",")):
        port = 19000 + i
        ready = mp.Event()
        p = mp.Process(target=serve, args=(a.selector, port, ready), daemon=True)
        p.start()
        ready.wait()
        c0 = cpu_of(p.pid)
        try:
            lat = asyncio.run(client(port, n, a.duration))
        except (OSError, ValueError) as e:
            print(f"{a.selector},{n},error,{e},")
            p.kill()
            continue
        c1 = cpu_of(p.pid)
        q = statistics.quantiles(lat, n=100) if len(lat) > 2 else [0] * 99
        print(f"{a.selector},{n},{c1 - c0:.3f},{q[49]:.3f},{q[98]:.3f}", flush=True)
        p.kill()


if __name__ == "__main__":
    main()
