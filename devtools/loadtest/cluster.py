"""本机多进程集群：业务服务（含总线 Hub）、N 个推送节点、网关各自是独立进程，结构与 docker compose 相同，
只是不在容器里。没有 Docker 时用它做压测与扩展性实验。

    python devtools/loadtest/cluster.py --pushes 3        # 手动启动，Ctrl+C 结束
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[2]

BASE = 18000  # 端口段，避开开发环境的 8080 等端口


class Cluster:
    def __init__(
        self,
        pushes: int = 1,
        *,
        push_io: str = "reactor",
        selector: str = "auto",
        gateway_workers: int = 1,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.pushes = pushes
        self.push_io = push_io
        self.selector = selector
        self.gateway_workers = gateway_workers
        self.extra_env = extra_env or {}
        self.procs: dict[str, subprocess.Popen[bytes]] = {}
        self.tmp = Path(tempfile.mkdtemp(prefix="gleaner-bench-"))
        self.gateway_url = f"http://127.0.0.1:{BASE + 80}"
        self.bus = ("127.0.0.1", BASE + 74)

    def _env(self, **kw: str) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "GLEANER_DB": f"sqlite:///{self.tmp / 'bench.db'}",
                "GLEANER_DATA_DIR": str(self.tmp),
                "GLEANER_BUS_HOST": "127.0.0.1",
                "GLEANER_BUS_PORT": str(BASE + 74),
                "GLEANER_CORE_PORT": str(BASE + 81),
                "GLEANER_GATEWAY_PORT": str(BASE + 80),
                "GLEANER_CORE_UPSTREAMS": f"core-1=127.0.0.1:{BASE + 81}",
                "GLEANER_PUSH_UPSTREAMS": ",".join(f"push-{i + 1}=127.0.0.1:{BASE + 100 + i}" for i in range(self.pushes)),
                "GLEANER_MQTT_WS_UPSTREAM": "",
                "GLEANER_TRUST_PROXY": "1",
                "GLEANER_REQUIRE_EMAIL_CODE": "0",
                "GLEANER_PUSH_IO": self.push_io,
                "GLEANER_PUSH_SELECTOR": self.selector,
                "GLEANER_WORKERS": str(self.gateway_workers),
                "GLEANER_LOG": "WARNING",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        env.update(self.extra_env)
        env.update(kw)
        return env

    def _spawn(self, name: str, service: str, **env: str) -> None:
        log = open(self.tmp / f"{name}.log", "wb")  # noqa: SIM115
        self.procs[name] = subprocess.Popen(
            [sys.executable, "-m", "gleaner", service], cwd=ROOT / "server", env=self._env(**env), stdout=log, stderr=log
        )

    def start(self) -> Cluster:
        self._spawn("core", "core", GLEANER_NODE_ID="core")
        self._wait(f"http://127.0.0.1:{BASE + 81}/health")
        for i in range(self.pushes):
            self._spawn(f"push-{i + 1}", "push", GLEANER_NODE_ID=f"push-{i + 1}", GLEANER_PUSH_PORT=str(BASE + 100 + i))
        for i in range(self.pushes):
            self._wait(f"http://127.0.0.1:{BASE + 100 + i}/health")
        self._spawn("gateway", "gateway")
        self._wait(self.gateway_url + "/health")
        time.sleep(1.0)  # 等网关第一轮主动健康检查
        return self

    def _wait(self, url: str, timeout: float = 30) -> None:
        import requests

        sess = requests.Session()
        sess.trust_env = False  # 不走系统代理
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if sess.get(url, timeout=1).status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.3)
        raise RuntimeError(f"{url} not healthy; logs in {self.tmp}")

    def pid(self, name: str) -> int:
        return self.procs[name].pid

    def usage(self, names: list[str]) -> dict[str, Any]:
        out = {}
        for n in names:
            p = psutil.Process(self.pid(n))
            out[n] = {"rss_mb": round(p.memory_info().rss / 2**20, 1), "cpu_s": round(sum(p.cpu_times()[:2]), 2)}
        return out

    def stop(self) -> None:
        for p in self.procs.values():
            p.kill()
        for p in self.procs.values():
            p.wait(timeout=10)

    def __enter__(self) -> Cluster:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pushes", type=int, default=2)
    ap.add_argument("--push-io", default="reactor")
    a = ap.parse_args()
    with Cluster(a.pushes, push_io=a.push_io) as c:
        print(f"gateway {c.gateway_url}  bus {c.bus}  logs {c.tmp}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
