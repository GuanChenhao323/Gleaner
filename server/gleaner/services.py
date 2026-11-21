"""各服务的启动函数。既供各自的进程入口使用，也供开发启动器与端到端测试在同一进程里组合。"""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from . import security
from .broker.broker import Broker
from .collector.engine import Scheduler
from .collector.fetcher import Fetcher
from .config import Config
from .core.agent_hub import AgentHub
from .core.api import API
from .core.maintenance import run_maintenance
from .core.pipeline import Pipeline
from .core.reading_schedule import ReadingSchedule
from .core.reminders import publish_digests, send_due_reminders
from .core.validate import BadRequest, as_int
from .gateway.app import Gateway
from .gateway.balancer import UpstreamPool
from .mailsvc.receiver import MailService
from .net.bus import BusClient, BusHub
from .net.http import HTTPClient, HTTPServer, Request, Response, Router, ServerConfig
from .net.websocket import websocket_route
from .net.websocket.reactor_server import ReactorWSServer
from .obs.metrics import REGISTRY, metrics_handler
from .push.node import PushNode
from .storage.db import Database
from .transfer.service import TransferService

log = logging.getLogger(__name__)

BUS_RX = REGISTRY.counter("gleaner_bus_frames_received_total", "总线接收帧数", ("node",))


@dataclass
class Running:
    name: str
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    async def close(self) -> None:
        for c in reversed(self.closers):
            try:
                await c()
            except Exception:
                log.exception("closing %s", self.name)


def _ssl(cfg: Config) -> ssl.SSLContext | None:
    if not (cfg.tls_cert and cfg.tls_key):
        return None
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cfg.tls_cert, cfg.tls_key)
    return ctx


async def _loop_every(seconds: float, fn: Callable[[], Awaitable[Any]]) -> None:
    while True:
        try:
            await fn()
        except Exception:
            log.exception("periodic task failed")
        await asyncio.sleep(seconds)


# ---- 业务服务（内嵌总线 Hub） --------------------------------------------------


async def start_core(cfg: Config, db: Database | None = None, *, host: str = "0.0.0.0") -> Running:
    db = db or await Database(cfg.db_url).connect()
    hub = BusHub(cfg.node_id or "core", secret=security.bus_secret())
    run = Running("core")

    async def route(topic: str, payload: dict[str, Any]) -> None:
        await hub.publish(topic, payload)

    pipe = Pipeline(db, route)
    api = API(
        db,
        pipe,
        route,
        data_dir=cfg.data_dir,
        reading_schedule=ReadingSchedule(cfg.fixture_reading_interval),
    )
    router = Router()
    api.register(router)

    async def notify(uid: int, payload: dict[str, Any]) -> None:
        await hub.publish(f"u.{uid}", payload)

    TransferService(db, cfg.data_dir, api.user_of, notify).register(router)
    agents = AgentHub(db, pipe)
    api.agent_hub = agents
    api.collectors_online = lambda: len(hub.live_nodes("collector"))
    router.add("GET", "/agent", websocket_route(agents.on_websocket))
    router.add("GET", "/metrics", metrics_handler())

    async def on_extract(topic: str, data: Any, src: str) -> None:
        counts = await pipe.ingest(data)
        if any(counts.values()):
            log.info("ingest source=%s %s", data.get("source_id"), counts)

    async def on_client_state(topic: str, data: Any, src: str) -> None:
        """推送节点转来的 WebSocket 状态操作：参数不合法时只记日志（对应 HTTP 的 422）。"""
        op = data.get("op") or {}
        try:
            await api.apply_state(
                as_int(data.get("uid"), "uid", lo=1),
                as_int(op.get("item_id"), "item_id", lo=1),
                op,
                op.get("op_id"),
            )
        except BadRequest as e:
            log.info("ignored invalid client.state from %s: %s", src, e.message)

    hub.subscribe("extract.result", on_extract)
    hub.subscribe("client.state", on_client_state)

    def on_members(m: dict[str, list[str]]) -> None:
        log.info("bus members: %s", m)
        if not m.get("collector"):
            from .mailsvc.sender import send_alert

            asyncio.get_running_loop().create_task(send_alert("采集节点全部下线", f"当前成员：{m}"))

    hub.membership_listeners.append(on_members)
    bus_port = await hub.start(host, cfg.bus_port)
    srv = HTTPServer(router, ServerConfig(host=host, port=cfg.core_port))
    await srv.start()
    page_host = None
    control_port = int(os.environ.get("GLEANER_LOCAL_PAGE_PORT", "0"))
    if control_port:
        from pathlib import Path

        from .monitoring.host import LocalPageHost

        page_host = LocalPageHost(
            api.reading,
            Path(cfg.data_dir),
            control_port,
            os.environ["GLEANER_LOCAL_EXTENSION_ID"],
        )
        router.add("POST", "/api/v1/page-control-ticket", api.authed(page_host.ticket))
        await page_host.start()
    tasks = [
        asyncio.get_running_loop().create_task(
            _loop_every(60, lambda: send_due_reminders(db, pipe))
        ),
        asyncio.get_running_loop().create_task(_loop_every(30, lambda: publish_digests(db, pipe))),
        # 数据保留与过期清理（core/maintenance.py），每小时一次
        asyncio.get_running_loop().create_task(
            _loop_every(3600, lambda: run_maintenance(db, cfg.data_dir))
        ),
    ]

    async def stop_tasks() -> None:
        for t in tasks:
            t.cancel()

    run.closers += [db.close, hub.close, srv.close, stop_tasks]
    if page_host:
        run.closers.append(page_host.close)
    run.info.update(port=srv.port, bus_port=bus_port, hub=hub, db=db, pipeline=pipe, api=api)
    return run


# ---- 推送节点 --------------------------------------------------------------------


async def start_push(
    cfg: Config, node_id: str, port: int, db: Database | None = None, *, host: str = "0.0.0.0"
) -> Running:
    db = db or await Database(cfg.db_url).connect()
    bus = BusClient(
        node_id,
        "push",
        cfg.bus_host,
        cfg.bus_port,
        meta={"port": port},
        secret=security.bus_secret(),
    )
    node = PushNode(db, bus, node_id)

    def status() -> dict[str, Any]:
        return {"status": "ok", "service": "push", "bus": bus.connected.is_set(), **node.status()}

    bus.start()
    if cfg.push_io == "reactor":
        # 手写反应器（epoll / select）负责全部客户端 socket；业务逻辑仍在 asyncio 线程
        def http(req: Request) -> Response:
            if req.path == "/health":
                return Response.json_body(
                    {**status(), "io": "reactor", "selector": rsrv.selector_name}
                )
            if req.path == "/metrics":
                return Response.text_body(
                    REGISTRY.render(), content_type="text/plain; version=0.0.4; charset=utf-8"
                )
            return Response.error(404)

        rsrv = ReactorWSServer(
            host, port, on_open=node.on_reactor_open, http_handler=http, selector=cfg.push_selector
        )
        bound = await rsrv.start()
        run = Running(node_id, [db.close, bus.close, rsrv.close])
        run.info.update(port=bound, node=node, bus=bus, server=rsrv)
        return run

    router = Router()
    router.add("GET", "/ws", websocket_route(node.on_websocket))

    async def health(req: Any) -> Response:
        return Response.json_body({**status(), "io": "asyncio"})

    router.add("GET", "/health", health)
    router.add("GET", "/metrics", metrics_handler())
    srv = HTTPServer(router, ServerConfig(host=host, port=port, keepalive_timeout=120))
    await srv.start()
    run = Running(node_id, [db.close, bus.close, srv.close])
    run.info.update(port=srv.port, node=node, bus=bus, server=srv)
    return run


# ---- MQTT Broker -------------------------------------------------------------------


def mqtt_auth(client_id: str, username: str | None, password: bytes | None) -> str | None:
    """用户名为用户 ID，口令由服务端派生（见 /api/me）；内部服务用 GLEANER_MQTT_ADMIN_PASS。"""
    if not username or password is None:
        return None
    pw = password.decode(errors="ignore")
    admin = os.environ.get("GLEANER_MQTT_ADMIN_PASS")
    if username == "admin" and admin and pw == admin:
        return "admin"
    if not username.isdigit():
        return None
    for tv in range(1, 50):  # token_version 递增后旧口令失效；Broker 不访问数据库，按版本试算
        if security.mqtt_password(int(username), tv) == pw:
            return username
    return None


def mqtt_acl(principal: str, topic: str, action: str) -> bool:
    """主题访问控制：每个客户端只能订阅自己 uid 下的主题，普通用户不能发布。"""
    if principal == "admin":
        return True
    if action == "pub":
        return False
    prefix = f"gleaner/u/{principal}/"
    return topic.startswith(prefix) or topic == f"gleaner/u/{principal}/#"


async def start_broker(cfg: Config, *, host: str = "0.0.0.0", port: int | None = None) -> Running:
    persist = os.path.join(cfg.data_dir, "mqtt-state.json")
    broker = Broker(authenticate=mqtt_auth, acl=mqtt_acl, persist_path=persist)
    REGISTRY.gauge(
        "gleaner_mqtt_clients", "MQTT 在线客户端", fn=lambda: broker.stats.clients_connected
    )
    REGISTRY.gauge(
        "gleaner_mqtt_messages_out", "MQTT 已发送消息", fn=lambda: broker.stats.messages_out
    )
    REGISTRY.gauge(
        "gleaner_mqtt_qos1_retries", "MQTT QoS1 重发次数", fn=lambda: broker.stats.qos1_retries
    )
    mport = await broker.start(host, cfg.mqtt_port if port is None else port)
    tls = _ssl(cfg)
    if tls and cfg.mqtt_tls_port:
        broker2_srv = await asyncio.start_server(broker._on_conn, host, cfg.mqtt_tls_port, ssl=tls)
    else:
        broker2_srv = None
    bus = BusClient(
        f"broker-{cfg.node_id}", "broker", cfg.bus_host, cfg.bus_port, secret=security.bus_secret()
    )

    def on_publish(topic: str, data: Any, src: str) -> None:
        import json as _json

        broker.publish(
            data["topic"],
            _json.dumps(data["payload"], ensure_ascii=False).encode(),
            qos=int(data.get("qos", 1)),
            retain=bool(data.get("retain")),
        )

    def on_forget(topic: str, data: Any, src: str) -> None:
        n = broker.forget_user(int(data["uid"]))
        log.info("mqtt: forgot user %s (%d sessions)", data["uid"], n)

    bus.subscribe("mqtt.publish", on_publish)
    bus.subscribe("mqtt.forget", on_forget)
    bus.start()

    async def save_loop() -> None:
        while True:
            await asyncio.sleep(30)
            broker.save()

    t = asyncio.get_running_loop().create_task(save_loop())

    async def stop() -> None:
        t.cancel()
        if broker2_srv:
            broker2_srv.close()

    run = Running("broker", [bus.close, broker.close, stop])
    run.info.update(port=mport, broker=broker)
    if cfg.metrics_port or cfg.mqtt_ws_port:
        from .broker.ws_transport import mqtt_ws_handler

        r = Router()
        r.add("GET", "/metrics", metrics_handler())
        r.add(
            "GET",
            "/mqtt",
            websocket_route(mqtt_ws_handler(broker), subprotocols=("mqtt", "mqttv3.1")),
        )

        async def health(req: Any) -> Response:
            return Response.json_body(
                {"status": "ok", "service": "broker", "clients": broker.stats.clients_connected}
            )

        r.add("GET", "/health", health)
        ms = HTTPServer(
            r,
            ServerConfig(
                host=host, port=cfg.mqtt_ws_port or cfg.metrics_port, keepalive_timeout=300
            ),
        )
        await ms.start()
        run.info["ws_port"] = ms.port
        run.closers.append(ms.close)
    return run


# ---- 采集与邮件 --------------------------------------------------------------------


def _make_fetcher(cfg: Config) -> Fetcher:
    resolver = None
    if cfg.use_dns:
        from .net.dns import Resolver

        resolver = Resolver()
    return Fetcher(
        HTTPClient(per_host_limit=4, total_limit=64, resolver=resolver, egress_guard=True),
        min_interval=float(os.environ.get("GLEANER_HOST_INTERVAL", "0.5")),
    )


async def start_collector(
    cfg: Config, node_id: str, db: Database | None = None, *, host: str = "0.0.0.0"
) -> Running:
    db = db or await Database(cfg.db_url).connect()
    bus = BusClient(node_id, "collector", cfg.bus_host, cfg.bus_port, secret=security.bus_secret())

    async def publish(msg: dict[str, Any]) -> None:
        await bus.publish("extract.result", msg)

    sched = Scheduler(db, publish, node_id, fetcher=_make_fetcher(cfg))

    def on_nodes(topic: str, data: Any, src: str) -> None:
        sched.set_nodes(list((data or {}).get("collector", [])))

    def on_fetch(topic: str, data: Any, src: str) -> None:
        sid = int(data.get("source_id", 0))
        if sched.mine(sid):
            sched.fetch_now(sid)

    bus.subscribe("$nodes", on_nodes)
    bus.subscribe("collector.fetch", on_fetch)
    bus.start()
    task = asyncio.get_running_loop().create_task(sched.run())

    async def stop() -> None:
        task.cancel()
        await sched.fetcher.close()

    run = Running(node_id, [db.close, bus.close, stop])
    run.info.update(scheduler=sched, bus=bus)
    if cfg.metrics_port:
        r = Router()
        r.add("GET", "/metrics", metrics_handler())

        async def health(req: Any) -> Response:
            return Response.json_body(
                {"status": "ok", "service": "collector", "breaker": sched.breaker.snapshot()}
            )

        r.add("GET", "/health", health)
        ms = HTTPServer(r, ServerConfig(host=host, port=cfg.metrics_port))
        await ms.start()
        run.closers.append(ms.close)
    return run


async def start_mailsvc(cfg: Config, node_id: str, db: Database | None = None) -> Running:
    db = db or await Database(cfg.db_url).connect()
    bus = BusClient(node_id, "mail", cfg.bus_host, cfg.bus_port, secret=security.bus_secret())

    async def publish(msg: dict[str, Any]) -> None:
        await bus.publish("extract.result", msg)

    svc = MailService(db, publish, node_id)

    def on_nodes(topic: str, data: Any, src: str) -> None:
        svc.set_nodes(list((data or {}).get("mail", [])))
        asyncio.get_running_loop().create_task(svc.reconcile())

    def on_sources(topic: str, data: Any, src: str) -> None:
        asyncio.get_running_loop().create_task(svc.reconcile())

    bus.subscribe("$nodes", on_nodes)
    bus.subscribe("mail.sources", on_sources)
    bus.start()
    task = asyncio.get_running_loop().create_task(_loop_every(30, svc.reconcile))

    async def stop() -> None:
        task.cancel()
        await svc.close()

    run = Running(node_id, [db.close, bus.close, stop])
    run.info.update(mail=svc)
    return run


# ---- 网关 ----------------------------------------------------------------------------


async def start_gateway(
    cfg: Config, *, host: str = "0.0.0.0", port: int | None = None, check_interval: float = 5.0
) -> Running:
    core = UpstreamPool.from_spec("core", cfg.core_upstreams, check_interval=check_interval)
    push = UpstreamPool.from_spec("push", cfg.push_upstreams, check_interval=check_interval)
    mqtt = (
        UpstreamPool.from_spec("mqtt", cfg.mqtt_ws_upstream, check_interval=check_interval)
        if cfg.mqtt_ws_upstream
        else None
    )
    gw = Gateway(
        core,
        push,
        static_dir=cfg.static_dir or None,
        trust_proxy=cfg.trust_proxy,
        mqtt=mqtt,
        cors_origins=tuple(o.strip() for o in cfg.cors_origins.split(",") if o.strip()),
        allowed_hosts=tuple(h.strip() for h in cfg.allowed_hosts.split(",") if h.strip()),
    )
    core.start()
    push.start()
    if mqtt:
        mqtt.start()
    sc = ServerConfig(
        host=host, port=cfg.gateway_port if port is None else port, reuse_port=cfg.workers > 1
    )
    srv = HTTPServer(gw, sc)
    await srv.start()
    run = Running("gateway", [srv.close, core.close, push.close, gw.client.close])
    if mqtt:
        run.closers.append(mqtt.close)
    REGISTRY.gauge(
        "gleaner_gateway_connections", "网关当前 TCP 连接", fn=lambda: srv.stats.connections_active
    )
    tls = _ssl(cfg)
    if tls and cfg.gateway_tls_port:
        tsrv = HTTPServer(
            gw,
            ServerConfig(
                host=host, port=cfg.gateway_tls_port, ssl_context=tls, reuse_port=cfg.workers > 1
            ),
        )
        await tsrv.start()
        run.closers.insert(0, tsrv.close)
    run.info.update(port=srv.port, gateway=gw, server=srv)
    return run


async def wait_forever(run: Running) -> None:
    log.info(
        "%s started %s", run.name, {k: v for k, v in run.info.items() if isinstance(v, (int, str))}
    )
    try:
        await asyncio.Event().wait()
    finally:
        await run.close()


def now() -> float:
    return time.time()
