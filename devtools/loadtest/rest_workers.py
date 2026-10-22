"""网关多 worker 吞吐（Linux）：对比 GLEANER_WORKERS=1 与 4，压测端开多个进程，避免单进程客户端先成为瓶颈。

    python devtools/loadtest/rest_workers.py
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "server"))
from cluster import Cluster  # noqa: E402
import experiments  # noqa: E402
from gleaner.net.http import HTTPClient  # noqa: E402

SECONDS, CONC, PROCS = 10.0, 16, 8


def client(url: str, q: "mp.Queue") -> None:
    async def run() -> tuple[int, list[float], int]:
        lat: list[float] = []
        bad = 0
        async with HTTPClient(per_host_limit=CONC, total_limit=CONC) as c:
            end = time.perf_counter() + SECONDS

            async def worker() -> None:
                nonlocal bad
                while time.perf_counter() < end:
                    ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
                    s = time.perf_counter()
                    r = await c.get(url, headers={"X-Forwarded-For": ip})
                    lat.append((time.perf_counter() - s) * 1000)
                    bad += r.status != 200

            await asyncio.gather(*(worker() for _ in range(CONC)))
        return len(lat), lat, bad

    q.put(asyncio.run(run()))


if __name__ == "__main__":
    rows = []
    for w in (1, 4):
        with Cluster(1, gateway_workers=w) as c:
            for path in ("/health", "/api/templates"):
                q: mp.Queue = mp.Queue()
                # 127.0.0.2 走真正的 lo；WSL 镜像网络下 127.0.0.1 会经 Windows 回环
                url = c.gateway_url.replace("127.0.0.1", "127.0.0.2") + path
                ps = [mp.Process(target=client, args=(url, q)) for _ in range(PROCS)]
                for p in ps:
                    p.start()
                res = [q.get() for _ in ps]
                for p in ps:
                    p.join()
                lat = [x for r in res for x in r[1]]
                rows.append(
                    {
                        "网关 worker": w,
                        "接口": path,
                        "并发": CONC * PROCS,
                        "请求数": len(lat),
                        "非 200": sum(r[2] for r in res),
                        "吞吐 req/s": round(len(lat) / SECONDS),
                        "P50 ms": experiments.q(lat, 50),
                        "P99 ms": experiments.q(lat, 99),
                    }
                )
    experiments.save(
        "rest_throughput_workers",
        rows,
        f"Linux；本机多进程集群（业务服务 1 进程）；压测端 {PROCS} 进程×{CONC} 并发，每个接口 {SECONDS:g} s；"
        "与服务同机；走 127.0.0.2",
    )
