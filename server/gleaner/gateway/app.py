"""统一网关：HTTPS 入口、REST 反向代理、WebSocket 转发、静态文件、限流、/metrics。

路由（proposal 技术方案 1）：
- ``/api/*``  → 业务服务（轮询 + 健康检查）
- ``/ws``     → 按用户 ID 一致性哈希选推送节点，转发升级请求后双向拼接字节流
- 其余        → Flutter Web 构建产物（ETag、304、gzip）
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any

from .. import security
from ..net.http import (
    Headers,
    HTTPClient,
    HTTPError,
    HTTPParser,
    Request,
    Response,
    Router,
    StaticFiles,
)
from ..obs.metrics import REGISTRY, metrics_handler
from .balancer import Upstream, UpstreamPool
from .ratelimit import TokenBucket

log = logging.getLogger(__name__)

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
}

REQS = REGISTRY.counter("gleaner_gateway_requests_total", "网关请求数", ("route", "status"))
REQ_SECONDS = REGISTRY.histogram("gleaner_gateway_request_seconds", "网关请求耗时", ("route",))
WS_TUNNELS = REGISTRY.gauge("gleaner_gateway_ws_tunnels", "网关上正在转发的 WebSocket 连接")
RATE_LIMITED = REGISTRY.counter("gleaner_gateway_rate_limited_total", "被限流的请求数", ("dim",))


def _uid_from(req: Request) -> int | None:
    token = req.query.get("token") or req.cookies().get("gl_session")
    auth = req.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    claims = security.verify_token(token) if token else None
    return int(claims["uid"]) if claims else None


def client_ip(req: Request, trust_proxy: bool) -> str:
    if trust_proxy and req.headers.get("X-Forwarded-For"):
        return req.headers["X-Forwarded-For"].split(",")[0].strip()
    return req.peer[0] if req.peer else "?"


class Gateway:
    def __init__(
        self,
        core: UpstreamPool,
        push: UpstreamPool,
        *,
        static_dir: str | None = None,
        ip_rate: tuple[float, float] = (20.0, 60.0),
        user_rate: tuple[float, float] = (10.0, 40.0),
        trust_proxy: bool = False,
        mqtt: UpstreamPool | None = None,
        cors_origins: tuple[str, ...] = (),
    ) -> None:
        self.core = core
        self.push = push
        self.mqtt = mqtt
        self.cors_origins = cors_origins
        self.client = HTTPClient(
            connect_timeout=2.0, read_timeout=30.0, per_host_limit=64, total_limit=512
        )
        self.static = StaticFiles(static_dir) if static_dir else None
        self.ip_bucket = TokenBucket(*ip_rate)
        self.user_bucket = TokenBucket(*user_rate)
        self.trust_proxy = trust_proxy
        self.started = time.time()
        self.router = Router()
        self.router.add("GET", "/health", self.health)
        self.router.add("GET", "/metrics", metrics_handler())
        self.router.add("GET", "/gateway/status", self.status)
        self.router.add("GET", "/ws", self.websocket)
        self.router.add("GET", "/agent", self.agent_websocket)
        self.router.add("GET", "/mqtt", self.mqtt_websocket)
        self.router.mount("/api/", self.proxy_api)
        self.router.mount("/", self.serve_static)

    async def __call__(self, req: Request) -> Response:
        t0 = time.perf_counter()
        route = "api" if req.path.startswith("/api/") else "ws" if req.path == "/ws" else "static"
        origin = req.headers.get("Origin")
        allow_origin = (
            origin if origin and (origin in self.cors_origins or "*" in self.cors_origins) else None
        )
        if allow_origin and req.method == "OPTIONS":
            # CORS 预检：开发时 flutter run -d chrome 与网关不同源
            resp = Response(204)
        else:
            limited = self._limit(req, route)
            resp = limited or await self.router(req)
        if allow_origin:
            resp.headers["Access-Control-Allow-Origin"] = allow_origin
            resp.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, Idempotency-Key, X-Transfer-Token, Content-Range"
            )
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            resp.headers["Access-Control-Expose-Headers"] = "X-Request-Id, X-Upstream"
            resp.headers.add("Vary", "Origin")
        resp.headers.setdefault("X-Request-Id", req.context.get("rid", ""))
        if route != "static":
            resp.headers.setdefault("Cache-Control", "no-store")
        _security_headers(resp)
        REQS.inc(1, route, str(resp.status))
        REQ_SECONDS.observe(time.perf_counter() - t0, route)
        return resp

    def _limit(self, req: Request, route: str) -> Response | None:
        if route == "static" or req.path in ("/health", "/metrics"):
            return None
        req.context["rid"] = req.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        ok, wait = self.ip_bucket.allow(client_ip(req, self.trust_proxy))
        dim = "ip"
        if ok:
            uid = _uid_from(req)
            if uid is not None:
                ok, wait = self.user_bucket.allow(f"u{uid}")
                dim = "user"
        if ok:
            return None
        RATE_LIMITED.inc(1, dim)
        resp = Response.error(429, "请求太频繁，请稍后再试", "rate_limited")
        resp.headers["Retry-After"] = str(max(1, int(wait + 0.999)))
        return resp

    async def health(self, req: Request) -> Response:
        return Response.json_body(
            {"status": "ok", "service": "gateway", "uptime": round(time.time() - self.started)}
        )

    async def status(self, req: Request) -> Response:
        return Response.json_body(
            {
                "core": self.core.snapshot(),
                "push": self.push.snapshot(),
                "mqtt": self.mqtt.snapshot() if self.mqtt else [],
                "time": time.time(),
            }
        )

    async def serve_static(self, req: Request) -> Response:
        if self.static is None:
            return Response.text_body(
                "Gleaner gateway. Flutter Web build not configured (GLEANER_STATIC_DIR).", 404
            )
        return await self.static(req)

    async def proxy_api(self, req: Request) -> Response:
        """反向代理到业务服务。幂等方法失败时换一个节点重试一次（故障转移）。"""
        h = Headers(
            [(k, v) for k, v in req.headers if k.lower() not in HOP_BY_HOP and k.lower() != "host"]
        )
        ip = client_ip(req, self.trust_proxy)
        h["X-Forwarded-For"] = ip
        h["X-Forwarded-Proto"] = "https" if req.context.get("tls") else "http"
        h["X-Request-Id"] = req.context.get("rid", "")
        idempotent = (
            req.method in ("GET", "HEAD", "PUT", "DELETE") or "Idempotency-Key" in req.headers
        )
        tried: set[str] = set()
        for _ in range(2 if idempotent else 1):
            up = self.core.pick_rr()
            if up is None or up.name in tried:
                break
            tried.add(up.name)
            try:
                r = await self.client.request(
                    req.method,
                    f"http://{up.host}:{up.port}{req.target}",
                    headers=h,
                    body=req.body,
                    follow_redirects=False,
                )
            except HTTPError as e:
                self.core.report(up, False, str(e))
                continue
            self.core.report(up, r.status < 500, f"HTTP {r.status}")
            out = Headers(
                [
                    (k, v)
                    for k, v in r.headers
                    if k.lower() not in HOP_BY_HOP and k.lower() not in ("date", "server")
                ]
            )
            out["X-Upstream"] = up.name
            return Response(r.status, headers=out, body=r.body)
        return Response.error(503, "业务服务暂时不可用", "upstream_unavailable")

    async def websocket(self, req: Request) -> Response:
        """WebSocket 转发：校验令牌 → 选推送节点 → 把升级请求原样转发 → 双向拼接字节流。"""
        uid = _uid_from(req)
        if uid is None:
            return Response.error(401, "unauthorized")
        up = self.push.pick_hash(f"user:{uid}")
        if up is None:
            return Response.error(503, "没有可用的推送节点", "no_push_node")
        return await self._tunnel(req, self.push, up, uid)

    async def mqtt_websocket(self, req: Request) -> Response:
        """MQTT over WebSocket 转发到 Broker；鉴权由 MQTT CONNECT 完成。"""
        if self.mqtt is None:
            return Response.error(404, "mqtt over websocket disabled")
        up = self.mqtt.pick_rr()
        if up is None:
            return Response.error(503, "MQTT Broker 暂时不可用", "upstream_unavailable")
        return await self._tunnel(req, self.mqtt, up, 0)

    async def agent_websocket(self, req: Request) -> Response:
        """本地采集代理的长连接转发到业务服务。"""
        uid = _uid_from(req)
        if uid is None:
            return Response.error(401, "unauthorized")
        up = self.core.pick_rr()
        if up is None:
            return Response.error(503, "业务服务暂时不可用", "upstream_unavailable")
        return await self._tunnel(req, self.core, up, uid)

    async def _tunnel(self, req: Request, pool: UpstreamPool, up: Upstream, uid: int) -> Response:
        try:
            ur, uw = await asyncio.wait_for(asyncio.open_connection(up.host, up.port), 2.0)
        except (OSError, TimeoutError) as e:
            pool.report(up, False, str(e))
            return Response.error(502, "推送节点连接失败", "push_unreachable")
        fwd = Headers([(k, v) for k, v in req.headers if k.lower() not in ("host",)])
        fwd["Host"] = f"{up.host}:{up.port}"
        fwd["X-Forwarded-For"] = client_ip(req, self.trust_proxy)
        fwd["X-Gleaner-Uid"] = str(uid)
        uw.write(Request("GET", req.target, headers=fwd).encode_head())
        await uw.drain()
        parser = HTTPParser("response")
        parser.expect_response("GET")
        upstream_resp: Response | None = None
        try:
            async with asyncio.timeout(5):
                while upstream_resp is None:
                    data = await ur.read(65536)
                    if not data:
                        raise ConnectionError("push node closed")
                    msgs = parser.feed(data)
                    if msgs:
                        m = msgs[0]
                        assert isinstance(m, Response)
                        upstream_resp = m
        except (ConnectionError, TimeoutError, OSError) as e:
            uw.close()
            pool.report(up, False, str(e))
            return Response.error(502, "推送节点握手失败", "push_handshake")
        if upstream_resp.status != 101:
            uw.close()
            return Response(
                upstream_resp.status, headers=upstream_resp.headers, body=upstream_resp.body
            )
        pool.report(up, True)
        leftover = parser.take_buffer()

        async def tunnel(
            cr: asyncio.StreamReader, cw: asyncio.StreamWriter, client_leftover: bytes
        ) -> None:
            WS_TUNNELS.inc(1)
            try:
                if leftover:
                    cw.write(leftover)
                if client_leftover:
                    uw.write(client_leftover)
                await asyncio.gather(_pipe(cr, uw), _pipe(ur, cw), return_exceptions=True)
            finally:
                WS_TUNNELS.inc(-1)
                for w in (uw, cw):
                    with contextlib.suppress(Exception):
                        w.close()

        resp = Response(101, headers=Headers([(k, v) for k, v in upstream_resp.headers]))
        resp.headers["X-Push-Node"] = up.name
        resp.upgrade = tunnel
        return resp


async def _pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await r.read(65536)
            if not data:
                break
            w.write(data)
            await w.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            if w.can_write_eof():
                w.write_eof()
            else:
                w.close()


def _security_headers(resp: Response) -> None:
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("X-Frame-Options", "DENY")


def gateway_status(gw: Gateway) -> dict[str, Any]:
    return {"core": gw.core.snapshot(), "push": gw.push.snapshot()}
