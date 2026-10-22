"""docker-compose.yml 静态检查（没有 Docker 时的初步验证）。

    python devtools/check_compose.py

检查：构建上下文与 Dockerfile 存在、COPY 的源路径存在、depends_on 指向的服务存在、
各服务之间的上游地址（GLEANER_*_UPSTREAMS、BUS_HOST）主机名与端口对得上、
Prometheus 抓取目标与服务实际监听端口一致、挂载的配置文件存在。
它不能代替 `docker compose up`：镜像能否构建、进程能否启动仍需在有 Docker 的环境里验证。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"

# 服务进程默认监听端口（与 server/gleaner/config.py 的默认值一致；环境变量可覆盖）
DEFAULTS = {
    "GLEANER_GATEWAY_PORT": 8080,
    "GLEANER_CORE_PORT": 8081,
    "GLEANER_PUSH_PORT": 8100,
    "GLEANER_BUS_PORT": 7400,
    "GLEANER_MQTT_PORT": 1883,
    "GLEANER_MQTT_WS_PORT": 8083,
}
COMMAND_PORTS = {
    "gateway": ["GLEANER_GATEWAY_PORT"],
    "core": ["GLEANER_CORE_PORT", "GLEANER_BUS_PORT"],
    "push": ["GLEANER_PUSH_PORT"],
    "broker": ["GLEANER_MQTT_PORT", "GLEANER_MQTT_WS_PORT"],
}


def expand(v: Any) -> str:
    """把 ${VAR:-default} 展开成默认值。"""
    return re.sub(r"\$\{[^}:]+:-([^}]*)\}", r"\1", str(v)) if v is not None else ""


def main() -> int:
    doc = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text("utf-8"))
    services: dict[str, dict[str, Any]] = doc["services"]
    problems: list[str] = []
    ok: list[str] = []

    # 每个服务实际监听的端口
    listens: dict[str, set[int]] = {}
    for name, s in services.items():
        env = {k: expand(v) for k, v in (s.get("environment") or {}).items()}
        cmd = (s.get("command") or [""])[0]
        ports: set[int] = set()
        for key in COMMAND_PORTS.get(cmd, []):
            ports.add(int(env.get(key) or DEFAULTS[key]))
        if env.get("GLEANER_METRICS_PORT") and cmd in ("collector",):
            ports.add(int(env["GLEANER_METRICS_PORT"]))
        if cmd == "broker":
            # 见 services.start_broker：/metrics 与 /mqtt 共用一个 HTTP 端口（MQTT_WS_PORT 优先）
            ports.add(int(env.get("GLEANER_MQTT_WS_PORT") or DEFAULTS["GLEANER_MQTT_WS_PORT"]))
        listens[name] = ports
        s["_env"] = env

    for name, s in services.items():
        b = s.get("build")
        if b:
            ctx = (DEPLOY / b["context"]).resolve()
            df = ctx / b.get("dockerfile", "Dockerfile")
            if df.exists():
                ok.append(f"{name}: Dockerfile {df.relative_to(ROOT)}")
                for line in df.read_text("utf-8").splitlines():
                    m = re.match(r"\s*COPY\s+(?!--from)(\S+)\s+\S+", line)
                    if m and not any(ctx.glob(m.group(1))):
                        problems.append(f"{name}: Dockerfile 中 `{line.strip()}` 的源路径不存在（构建前需要先生成）")
            else:
                problems.append(f"{name}: 找不到 {df}")
        for dep in s.get("depends_on") or []:
            if dep not in services:
                problems.append(f"{name}: depends_on 指向不存在的服务 {dep}")
        for vol in s.get("volumes") or []:
            src = str(vol).split(":")[0]
            if src.startswith("./") and not (DEPLOY / src).exists():
                problems.append(f"{name}: 挂载源 {src} 不存在")
        env = s["_env"]
        for key in ("GLEANER_CORE_UPSTREAMS", "GLEANER_PUSH_UPSTREAMS", "GLEANER_MQTT_WS_UPSTREAM"):
            spec = env.get(key)
            if spec is None:
                if key == "GLEANER_MQTT_WS_UPSTREAM" and (s.get("command") or [""])[0] == "gateway":
                    problems.append(f"{name}: 未设置 {key}，容器里会使用默认值 127.0.0.1:8083（指向网关自己）")
                continue
            for part in filter(None, (p.strip() for p in spec.split(","))):
                host, _, port = part.rpartition("=")[2].rpartition(":")
                if host not in services:
                    problems.append(f"{name}: {key} 指向不存在的服务 {host}")
                elif int(port) not in listens[host]:
                    problems.append(f"{name}: {key} 指向 {host}:{port}，但 {host} 监听 {sorted(listens[host])}")
                else:
                    ok.append(f"{name}: {key} → {host}:{port}")
        bus = env.get("GLEANER_BUS_HOST")
        if bus and bus not in services:
            problems.append(f"{name}: GLEANER_BUS_HOST={bus} 不是服务名")

    prom = yaml.safe_load((DEPLOY / "prometheus" / "prometheus.yml").read_text("utf-8"))
    for job in prom["scrape_configs"]:
        for sc in job["static_configs"]:
            for t in sc["targets"]:
                host, port = t.split(":")
                if host not in services:
                    problems.append(f"prometheus {job['job_name']}: 目标 {t} 不是服务名")
                elif int(port) not in listens[host]:
                    problems.append(f"prometheus {job['job_name']}: 目标 {t}，但 {host} 监听 {sorted(listens[host])}")
                else:
                    ok.append(f"prometheus {job['job_name']} → {t}")

    for line in ok:
        print("  ok  ", line)
    for line in problems:
        print("  FAIL", line)
    print(f"\n{len(ok)} 项通过，{len(problems)} 个问题")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
