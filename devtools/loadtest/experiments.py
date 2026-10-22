"""对比实验运行器：结果写入 docs/evaluation/results/<实验>.json，并打印 Markdown 表格。

    python devtools/loadtest/experiments.py keepalive      # 实验 2：有无连接池与 keep-alive
    python devtools/loadtest/experiments.py conditional    # 实验 3：有无条件请求
    python devtools/loadtest/experiments.py mqtt           # 实验 4：MQTT QoS 0 与 QoS 1
    python devtools/loadtest/experiments.py rest --url http://localhost:8080   # 网关 REST 吞吐（需先启动服务）

实验 1（select / epoll）、5000 连接、丢包注入需要 Linux，见 README。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "devtools"))

from gleaner.net.http import HTTPClient  # noqa: E402

OUT = ROOT / "docs" / "evaluation" / "results"


def env_info() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def save(name: str, rows: list[dict[str, Any]], note: str = "") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("linux"):
        name += "_linux"  # 与 Windows 数据分开保存
    (OUT / f"{name}.json").write_text(
        json.dumps({"env": env_info(), "note": note, "rows": rows}, ensure_ascii=False, indent=2), "utf-8"
    )
    keys = list(rows[0])
    print("| " + " | ".join(keys) + " |")
    print("| " + " | ".join("---" for _ in keys) + " |")
    for r in rows:
        print("| " + " | ".join(str(r[k]) for k in keys) + " |")


def start_fake_moodle() -> tuple[str, Any]:
    from fake_moodle import app as fm

    fm.STATE.__dict__.update(fm.State().__dict__)
    srv = fm.serve(0, "127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", fm


def q(xs: list[float], p: int) -> float:
    if len(xs) < 2:
        return round(xs[0], 2) if xs else 0.0
    return round(statistics.quantiles(xs, n=100)[p - 1], 2)


# ---- 实验 2：连接池与 keep-alive ------------------------------------------------


async def keepalive(rounds: int) -> None:
    base, _ = start_fake_moodle()
    paths = ["/news/", "/news/rss.xml", "/faculty/"] + [f"/news/{i}.html" for i in range(1, 5)] + [
        f"/faculty/{i}.html" for i in range(1, 4)
    ]
    rows = []
    for ka in (True, False):
        async with HTTPClient(keep_alive=ka, per_host_limit=4) as c:
            lat: list[float] = []
            t0 = time.perf_counter()
            for _ in range(rounds):

                async def one(p: str, c: HTTPClient = c) -> None:
                    s = time.perf_counter()
                    r = await c.get(base + p)
                    assert r.status == 200
                    lat.append((time.perf_counter() - s) * 1000)

                await asyncio.gather(*(one(p) for p in paths))
            dt = time.perf_counter() - t0
            rows.append(
                {
                    "模式": "连接池 + keep-alive" if ka else "每次新建连接",
                    "请求数": c.stats.requests,
                    "TCP 握手次数": c.stats.connections_opened,
                    "连接复用次数": c.stats.connections_reused,
                    "总耗时 s": round(dt, 2),
                    "吞吐 req/s": round(c.stats.requests / dt, 1),
                    "P50 ms": q(lat, 50),
                    "P99 ms": q(lat, 99),
                }
            )
    save("exp2_keepalive", rows, f"fake_moodle 本机回环；{len(paths)} 个 URL × {rounds} 轮，每主机并发 4")


# ---- 实验 3：条件请求 --------------------------------------------------------------


async def conditional(rounds: int, change_every: int) -> None:
    rows = []
    for use_cond in (True, False):
        base, fm = start_fake_moodle()
        paths = ["/news/", "/news/rss.xml", "/faculty/"] + [f"/faculty/{i}.html" for i in range(1, 4)]
        cache: dict[str, dict[str, str]] = {}
        n304 = n200 = 0
        async with HTTPClient() as c:
            for r in range(rounds):
                if r and r % change_every == 0:
                    # 来源偶尔发布新通知：列表页、RSS 和新详情页都会变化
                    with fm.STATE.lock:
                        nid = max(n.id for n in fm.STATE.notices) + 1
                        fm.STATE.notices.append(fm.Notice(nid, f"实验通知 {nid}", "测试正文" * 20, time.time()))
                for p in list(paths) + [f"/news/{n.id}.html" for n in fm.STATE.notices]:
                    h = {}
                    if use_cond and p in cache:
                        if cache[p].get("etag"):
                            h["If-None-Match"] = cache[p]["etag"]
                        if cache[p].get("lm"):
                            h["If-Modified-Since"] = cache[p]["lm"]
                    resp = await c.get(base + p, headers=h)
                    if resp.status == 304:
                        n304 += 1
                    else:
                        n200 += 1
                        cache[p] = {"etag": resp.headers.get("ETag") or "", "lm": resp.headers.get("Last-Modified") or ""}
            rows.append(
                {
                    "模式": "条件请求（ETag / If-Modified-Since）" if use_cond else "无条件请求",
                    "检查轮数": rounds,
                    "请求数": n200 + n304,
                    "304 次数": n304,
                    "304 占比": f"{n304 / (n200 + n304):.1%}",
                    "接收字节 KB": round(c.stats.bytes_received / 1024, 1),
                }
            )
    saved = 1 - rows[0]["接收字节 KB"] / rows[1]["接收字节 KB"]
    for r in rows:
        r["节省流量"] = f"{saved:.1%}" if r is rows[0] else "—"
    save("exp3_conditional", rows, f"每 {change_every} 轮来源新增一条通知；字节数含响应头")


# ---- 实验 4：MQTT QoS 0 与 QoS 1 -----------------------------------------------------


# WSL 镜像网络会把发往 127.0.0.1 的 TCP/UDP 策略路由到 loopback0 经 Windows 回环，
# lo 上的 tc netem 对它无效；做丢包实验时设 GLEANER_BENCH_HOST=127.0.0.2 走真正的 lo
BENCH_HOST = os.environ.get("GLEANER_BENCH_HOST", "127.0.0.1")

BROKER_PROC = """
import asyncio, sys
sys.path.insert(0, sys.argv[1])
from gleaner.broker.broker import Broker
async def main():
    b = Broker()
    port = await b.start(sys.argv[2], 0)
    print(port, flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
"""


def mqtt(subs: int, messages: int, rate: float, netem: str = "") -> None:
    """Broker 独立进程；先突发发布测吞吐，再按固定速率发布测延迟。"""
    import subprocess

    import paho.mqtt.client as paho

    cmd = [sys.executable, "-c", BROKER_PROC, str(ROOT / "server"), BENCH_HOST]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    port = int(proc.stdout.readline())  # type: ignore[union-attr]
    rows = []
    try:
        for mode in ("突发", "限速"):
            for qos in (0, 1):
                got = [0]
                lat: list[float] = []
                lock = threading.Lock()

                def on_msg(c: Any, u: Any, m: Any) -> None:
                    with lock:
                        got[0] += 1
                        lat.append((time.time() - float(m.payload.decode().split(":")[1])) * 1000)

                clients = []
                for i in range(subs):
                    c = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=f"exp-{mode}-{qos}-{i}")
                    c.on_message = on_msg
                    c.connect(BENCH_HOST, port, 60)
                    c.subscribe("exp/load", qos)
                    c.loop_start()
                    clients.append(c)
                time.sleep(1.0)
                pub = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=f"exp-pub-{mode}-{qos}")
                pub.connect(BENCH_HOST, port, 60)
                pub.loop_start()
                n = messages if mode == "突发" else min(messages, int(rate * 10))
                t0 = time.time()
                for i in range(n):
                    pub.publish("exp/load", f"{i}:{time.time()}", qos=qos)
                    if mode == "限速":
                        time.sleep(max(0.0, t0 + (i + 1) / rate - time.time()))
                expected = subs * n
                while got[0] < expected and time.time() - t0 < 120:
                    time.sleep(0.05)
                dt = time.time() - t0
                rows.append(
                    {
                        "模式": mode if mode == "突发" else f"限速 {rate:g} 条/s",
                        "QoS": qos,
                        "订阅者": subs,
                        "发布条数": n,
                        "送达率": f"{got[0] / expected:.2%}",
                        "吞吐 msg/s": round(got[0] / dt),
                        "P50 ms": q(lat, 50),
                        "P99 ms": q(lat, 99),
                    }
                )
                for c in [*clients, pub]:
                    c.loop_stop()
                    c.disconnect()
                time.sleep(0.5)
    finally:
        proc.kill()
    cond = f"回环网卡 tc netem {netem}" if netem else "无丢包"
    note = f"Broker 独立进程，paho 客户端同机；突发=一次性发布测吞吐，限速=固定速率测端到端延迟；{cond}"
    save("exp4_mqtt_netem" if netem else "exp4_mqtt_qos", rows, note)


class ChaosProxy:
    """故障注入 TCP 代理（Windows 上代替 tc netem）：周期性掐断全部连接，并在 down 秒内拒绝新连接。"""

    def __init__(self, target_port: int, every: float, down: float) -> None:
        self.target_port = target_port
        self.every = every
        self.down = down
        self.writers: set[asyncio.StreamWriter] = set()
        self.outage_until = 0.0
        self.outages = 0
        self.loop = asyncio.new_event_loop()
        self.port = self.loop.run_until_complete(self._start())
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    async def _start(self) -> int:
        srv = await asyncio.start_server(self._on_conn, "127.0.0.1", 0)
        self.loop.create_task(self._chaos())
        return srv.sockets[0].getsockname()[1]

    async def _on_conn(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        if time.time() < self.outage_until:
            w.transport.abort()
            return
        try:
            ur, uw = await asyncio.open_connection("127.0.0.1", self.target_port)
        except OSError:
            w.transport.abort()
            return
        self.writers |= {w, uw}

        async def pipe(a: asyncio.StreamReader, b: asyncio.StreamWriter) -> None:
            try:
                while data := await a.read(65536):
                    b.write(data)
                    await b.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                b.transport.abort()

        await asyncio.gather(pipe(r, uw), pipe(ur, w))
        self.writers -= {w, uw}

    async def _chaos(self) -> None:
        while True:
            await asyncio.sleep(self.every)
            self.outage_until = time.time() + self.down
            self.outages += 1
            for w in list(self.writers):
                w.transport.abort()  # 不发 FIN，模拟网络突然中断


def mqtt_chaos(subs: int, rate: float, seconds: float, every: float, down: float) -> None:
    """网络中断场景：QoS 0 与 QoS 1（持久会话）的送达率。"""
    import subprocess

    import paho.mqtt.client as paho

    cmd = [sys.executable, "-c", BROKER_PROC, str(ROOT / "server"), "127.0.0.1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    port = int(proc.stdout.readline())  # type: ignore[union-attr]
    rows = []
    try:
        for qos in (0, 1):
            proxy = ChaosProxy(port, every, down)
            seen: list[set[int]] = [set() for _ in range(subs)]
            dup = [0]
            lock = threading.Lock()
            clients = []
            for i in range(subs):

                def on_msg(c: Any, u: Any, m: Any, i: int = i) -> None:
                    n = int(m.payload.decode().split(":")[0])
                    with lock:
                        if n in seen[i]:
                            dup[0] += 1
                        seen[i].add(n)

                c = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=f"chaos-{qos}-{i}", clean_session=False)
                c.on_message = on_msg
                c.on_connect = lambda cl, u, f, rc, p=None, qos=qos: cl.subscribe("exp/chaos", qos)
                c.reconnect_delay_set(min_delay=1, max_delay=2)
                c.connect("127.0.0.1", proxy.port, keepalive=5)
                c.loop_start()
                clients.append(c)
            time.sleep(1.5)
            pub = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=f"chaos-pub-{qos}")
            pub.connect("127.0.0.1", port, 60)  # 发布端直连 Broker，只让订阅端经历网络中断
            pub.loop_start()
            t0 = time.time()
            n = int(rate * seconds)
            for k in range(n):
                pub.publish("exp/chaos", f"{k}:{time.time()}", qos=qos)
                time.sleep(max(0.0, t0 + (k + 1) / rate - time.time()))
            time.sleep(down + 6)  # 网络恢复后留时间补发
            got = sum(len(x) for x in seen)
            rows.append(
                {
                    "QoS": f"{qos}" + ("（持久会话）" if qos else ""),
                    "订阅者": subs,
                    "发布条数": n,
                    "网络中断次数": proxy.outages,
                    "每次中断 s": down,
                    "送达（去重后）": f"{got}/{n * subs}",
                    "送达率": f"{got / (n * subs):.2%}",
                    "重复投递": dup[0],
                }
            )
            for c in [*clients, pub]:
                c.loop_stop()
                c.disconnect()
            proxy.loop.call_soon_threadsafe(proxy.loop.stop)
            time.sleep(0.5)
    finally:
        proc.kill()
    save(
        "exp4_mqtt_chaos",
        rows,
        f"故障注入代理每 {every} s 掐断订阅端全部连接并拒绝重连 {down} s；Windows 上代替 tc netem，丢包按 TCP 层断线体现",
    )


# ---- 网关 REST 吞吐 -----------------------------------------------------------------


async def rest(url: str, seconds: float, concurrency: int) -> None:
    rows = []
    for path in ("/health", "/api/templates"):
        lat: list[float] = []
        codes: dict[int, int] = {}
        async with HTTPClient(per_host_limit=concurrency, total_limit=concurrency) as c:
            end = time.perf_counter() + seconds

            async def worker(c: HTTPClient = c, path: str = path, end: float = end) -> None:
                while time.perf_counter() < end:
                    ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
                    s = time.perf_counter()
                    r = await c.get(url + path, headers={"X-Forwarded-For": ip})
                    lat.append((time.perf_counter() - s) * 1000)
                    codes[r.status] = codes.get(r.status, 0) + 1

            t0 = time.perf_counter()
            await asyncio.gather(*(worker() for _ in range(concurrency)))
            dt = time.perf_counter() - t0
        n = sum(codes.values())
        rows.append(
            {
                "接口": path,
                "并发": concurrency,
                "请求数": n,
                "状态码": " ".join(f"{k}×{v}" for k, v in sorted(codes.items())),
                "吞吐 req/s": round(n / dt),
                "P50 ms": q(lat, 50),
                "P99 ms": q(lat, 99),
            }
        )
    save("rest_throughput", rows, f"{url}；每个接口 {seconds} s；压测客户端与服务同机")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keepalive")
    k.add_argument("--rounds", type=int, default=30)
    c = sub.add_parser("conditional")
    c.add_argument("--rounds", type=int, default=100)
    c.add_argument("--change-every", type=int, default=20)
    m = sub.add_parser("mqtt")
    m.add_argument("--subs", type=int, default=20)
    m.add_argument("--messages", type=int, default=2000)
    m.add_argument("--rate", type=float, default=100, help="限速模式每秒发布条数")
    m.add_argument("--netem", default="", help="已在回环网卡上设置的 netem 参数，只用于结果标注")
    mc = sub.add_parser("mqtt-chaos")
    mc.add_argument("--subs", type=int, default=10)
    mc.add_argument("--rate", type=float, default=20)
    mc.add_argument("--seconds", type=float, default=30)
    mc.add_argument("--every", type=float, default=6)
    mc.add_argument("--down", type=float, default=2)
    r = sub.add_parser("rest")
    r.add_argument("--url", default="http://localhost:8080")
    r.add_argument("--seconds", type=float, default=10)
    r.add_argument("--concurrency", type=int, default=64)
    a = ap.parse_args()
    if a.cmd == "keepalive":
        asyncio.run(keepalive(a.rounds))
    elif a.cmd == "conditional":
        asyncio.run(conditional(a.rounds, a.change_every))
    elif a.cmd == "mqtt":
        mqtt(a.subs, a.messages, a.rate, a.netem)
    elif a.cmd == "mqtt-chaos":
        mqtt_chaos(a.subs, a.rate, a.seconds, a.every, a.down)
    else:
        asyncio.run(rest(a.url, a.seconds, a.concurrency))


if __name__ == "__main__":
    main()
