"""进程入口：``python -m gleaner <service>``。

gateway | core | push | broker | collector | mailsvc   各自独立进程（Docker Compose 使用）
dev                                                    同一进程内启动全部服务（本地开发）
"""

from __future__ import annotations

import argparse
import asyncio
import os

from .config import Config, setup_logging
from .services import (
    Running,
    start_broker,
    start_collector,
    start_core,
    start_gateway,
    start_mailsvc,
    start_push,
    wait_forever,
)


async def _dev(cfg: Config, pushes: int) -> None:
    """本地一键启动：业务 + 总线、N 个推送节点、网关、Broker、采集、邮件服务。"""
    runs: list[Running] = []
    core = await start_core(cfg)
    runs.append(core)
    specs = []
    for i in range(pushes):
        port = cfg.push_port + i
        runs.append(await start_push(cfg, f"push-{i + 1}", port))
        specs.append(f"push-{i + 1}=127.0.0.1:{port}")
    cfg.push_upstreams = ",".join(specs)
    cfg.core_upstreams = f"core-1=127.0.0.1:{core.info['port']}"
    runs.append(await start_gateway(cfg))
    runs.append(await start_broker(cfg))
    runs.append(await start_collector(cfg, "collector-1"))
    runs.append(await start_mailsvc(cfg, "mail-1"))
    print(
        f"\n  Gleaner dev stack ready\n  gateway  http://localhost:{cfg.gateway_port}\n  core     http://localhost:{core.info['port']}\n"
        f"  mqtt     tcp://localhost:{cfg.mqtt_port}\n  bus      tcp://localhost:{core.info['bus_port']}\n  push     {cfg.push_upstreams}\n",
        flush=True,
    )
    try:
        await asyncio.Event().wait()
    finally:
        for r in reversed(runs):
            await r.close()


def _fork_workers(n: int) -> None:
    """SO_REUSEPORT 多进程：父进程 fork 出 n-1 个子进程，内核在它们之间分发连接（仅 Linux）。"""
    if n <= 1 or not hasattr(os, "fork"):
        return
    for _ in range(n - 1):
        if os.fork() == 0:
            return


def main() -> None:
    ap = argparse.ArgumentParser(prog="gleaner")
    ap.add_argument(
        "service", choices=["gateway", "core", "push", "broker", "collector", "mailsvc", "dev"]
    )
    ap.add_argument("--pushes", type=int, default=2, help="dev 模式下的推送节点数")
    a = ap.parse_args()
    setup_logging()
    cfg = Config()
    os.makedirs(cfg.data_dir, exist_ok=True)

    async def run() -> None:
        if a.service == "dev":
            await _dev(cfg, a.pushes)
            return
        if a.service == "gateway":
            _fork_workers(cfg.workers)
            r = await start_gateway(cfg)
        elif a.service == "core":
            r = await start_core(cfg)
        elif a.service == "push":
            r = await start_push(cfg, cfg.node_id, cfg.push_port)
        elif a.service == "broker":
            r = await start_broker(cfg)
        elif a.service == "collector":
            r = await start_collector(cfg, cfg.node_id)
        else:
            r = await start_mailsvc(cfg, cfg.node_id)
        await wait_forever(r)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
