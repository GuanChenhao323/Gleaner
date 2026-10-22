"""运行配置，全部来自环境变量（Docker Compose 中设置）。"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Config:
    db_url: str = field(default_factory=lambda: _env("GLEANER_DB", "sqlite:///gleaner-dev.db"))
    data_dir: str = field(default_factory=lambda: _env("GLEANER_DATA_DIR", "./data"))
    node_id: str = field(default_factory=lambda: _env("GLEANER_NODE_ID", socket.gethostname()))
    bus_host: str = field(default_factory=lambda: _env("GLEANER_BUS_HOST", "127.0.0.1"))
    bus_port: int = field(default_factory=lambda: int(_env("GLEANER_BUS_PORT", "7400")))
    core_port: int = field(default_factory=lambda: int(_env("GLEANER_CORE_PORT", "8081")))
    push_port: int = field(default_factory=lambda: int(_env("GLEANER_PUSH_PORT", "8100")))
    gateway_port: int = field(default_factory=lambda: int(_env("GLEANER_GATEWAY_PORT", "8080")))
    gateway_tls_port: int = field(
        default_factory=lambda: int(_env("GLEANER_GATEWAY_TLS_PORT", "0"))
    )
    tls_cert: str = field(default_factory=lambda: _env("GLEANER_TLS_CERT", ""))
    tls_key: str = field(default_factory=lambda: _env("GLEANER_TLS_KEY", ""))
    mqtt_port: int = field(default_factory=lambda: int(_env("GLEANER_MQTT_PORT", "1883")))
    mqtt_ws_port: int = field(default_factory=lambda: int(_env("GLEANER_MQTT_WS_PORT", "8083")))
    mqtt_ws_upstream: str = field(
        default_factory=lambda: _env("GLEANER_MQTT_WS_UPSTREAM", "broker=127.0.0.1:8083")
    )
    cors_origins: str = field(default_factory=lambda: _env("GLEANER_CORS_ORIGINS", ""))
    mqtt_tls_port: int = field(default_factory=lambda: int(_env("GLEANER_MQTT_TLS_PORT", "0")))
    core_upstreams: str = field(
        default_factory=lambda: _env("GLEANER_CORE_UPSTREAMS", "core-1=127.0.0.1:8081")
    )
    push_upstreams: str = field(
        default_factory=lambda: _env("GLEANER_PUSH_UPSTREAMS", "push-1=127.0.0.1:8100")
    )
    static_dir: str = field(default_factory=lambda: _env("GLEANER_STATIC_DIR", ""))
    workers: int = field(default_factory=lambda: int(_env("GLEANER_WORKERS", "1")))
    metrics_port: int = field(default_factory=lambda: int(_env("GLEANER_METRICS_PORT", "0")))
    trust_proxy: bool = field(default_factory=lambda: _env("GLEANER_TRUST_PROXY", "0") == "1")
    # 推送节点接入层：reactor（手写 selectors 反应器）或 asyncio；selector：auto / epoll / poll / select
    push_io: str = field(default_factory=lambda: _env("GLEANER_PUSH_IO", "reactor"))
    push_selector: str = field(default_factory=lambda: _env("GLEANER_PUSH_SELECTOR", "auto"))
    use_dns: bool = field(default_factory=lambda: _env("GLEANER_USE_OWN_DNS", "0") == "1")


def setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("GLEANER_LOG", "INFO"),
        format='{"t":"%(asctime)s","lvl":"%(levelname)s","mod":"%(name)s","msg":"%(message)s"}',
    )
