"""推送节点：维持 WebSocket 会话，心跳、断线补发与背压（proposal 技术方案 2）。

客户端协议（JSON 文本帧）：

    → {"type": "hello", "token": "…", "last_seq": 1287}
    ← {"type": "welcome", "cursor": 1291, "node": "push-1", "replayed": 4}
    ← {"type": "item" | "change" | "source_status" | "reminder" | "state" | "digest", "seq": …, …}
    → {"type": "ack", "seq": 1291}
    → {"type": "state", "op_id": "c7f3…", "item_id": 5521, "starred": true}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .. import security
from ..net.bus import BusClient
from ..net.http import Request
from ..net.websocket import CloseCode, ConnectionClosed, Opcode, WebSocket
from ..obs.metrics import REGISTRY
from ..storage.db import Database, loads

log = logging.getLogger(__name__)

ONLINE = REGISTRY.gauge("gleaner_ws_connections", "在线 WebSocket 连接数")
ONLINE_USERS = REGISTRY.gauge("gleaner_ws_users", "在线用户数")
SENT = REGISTRY.counter("gleaner_ws_messages_sent_total", "推送消息数", ("type",))
DROPPED = REGISTRY.counter("gleaner_ws_messages_dropped_total", "背压丢弃的低优先级消息数")
LATENCY = REGISTRY.histogram(
    "gleaner_push_latency_seconds",
    "入库到推送的延迟",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
REPLAYED = REGISTRY.counter("gleaner_ws_replayed_total", "断线补发的消息数")

HIGH_WATER = 256 * 1024  # 发送缓冲超过此值：丢弃低优先级消息，稍后让客户端增量同步
MAX_BUFFER = 2 * 1024 * 1024  # 仍然超过：断开慢客户端，保护整个节点
REPLAY_MAX = (
    500  # 断线期间积压超过此数：不在 WebSocket 上逐条补发，改让客户端走 REST 增量同步（可分页）
)


class Peer(Protocol):
    """推送会话依赖的传输接口：手写反应器（ReactorPeer）与 asyncio（AsyncioPeer）各实现一份。"""

    @property
    def buffered(self) -> int: ...

    def send_text(self, text: str) -> None: ...

    def close(self, code: int = CloseCode.NORMAL, reason: str = "") -> None: ...

    def abort(self) -> None: ...


class AsyncioPeer:
    """把 asyncio 版 WebSocket 适配成 Peer（GLEANER_PUSH_IO=asyncio 时使用，便于对比）。"""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def buffered(self) -> int:
        return self.ws.write_buffer_size

    def send_text(self, text: str) -> None:
        # 发送锁按 FIFO 排队，消息顺序与调用顺序一致
        t = asyncio.get_running_loop().create_task(self._send(text))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _send(self, text: str) -> None:
        with contextlib.suppress(ConnectionClosed, ConnectionError, OSError):
            await self.ws.send(text)

    def close(self, code: int = CloseCode.NORMAL, reason: str = "") -> None:
        asyncio.get_running_loop().create_task(self.ws.close(code, reason))

    def abort(self) -> None:
        with contextlib.suppress(Exception):
            self.ws.writer.transport.abort()


@dataclass(eq=False)
class ClientConn:
    peer: Peer
    uid: int
    sent_seq: int = 0
    connected_at: float = field(default_factory=time.time)
    needs_resync: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class PushNode:
    def __init__(
        self,
        db: Database,
        bus: BusClient,
        node_id: str,
        *,
        hello_timeout: float = 10.0,
        heartbeat: tuple[float, float] = (25.0, 60.0),
    ) -> None:
        self.db = db
        self.bus = bus
        self.node_id = node_id
        self.hello_timeout = hello_timeout
        self.heartbeat = heartbeat
        self.users: dict[int, set[ClientConn]] = {}
        self._ack_pending: dict[int, int] = {}
        self._ack_task: asyncio.Task[None] | None = None

    # -- 统计 --------------------------------------------------------------------

    def _gauges(self) -> None:
        ONLINE.set(sum(len(s) for s in self.users.values()))
        ONLINE_USERS.set(len(self.users))

    def status(self) -> dict[str, Any]:
        return {
            "node": self.node_id,
            "connections": sum(len(s) for s in self.users.values()),
            "users": len(self.users),
        }

    # -- WebSocket 会话 ------------------------------------------------------------

    async def on_websocket(self, ws: WebSocket, req: Request) -> None:
        """asyncio 接入方式：把 WebSocket 消息搬进收件队列，复用同一套会话逻辑。"""
        if self.heartbeat:
            ws.start_heartbeat(*self.heartbeat)
        inbox: asyncio.Queue[str | None] = asyncio.Queue()

        async def pump() -> None:
            try:
                async for msg in ws:
                    if msg.opcode == Opcode.TEXT:
                        inbox.put_nowait(msg.text)
            finally:
                inbox.put_nowait(None)

        t = asyncio.get_running_loop().create_task(pump())
        try:
            await self.session(AsyncioPeer(ws), inbox)
        finally:
            t.cancel()

    async def on_reactor_open(self, peer: Any, req: Request) -> None:
        """手写反应器接入方式：反应器线程已完成握手，消息经 peer.inbox 投递过来。"""
        assert peer.inbox is not None
        await self.session(peer, peer.inbox)

    async def session(self, peer: Peer, inbox: asyncio.Queue[str | None]) -> None:
        try:
            first = await asyncio.wait_for(inbox.get(), self.hello_timeout)
        except TimeoutError:
            peer.close(CloseCode.POLICY, "hello required")
            return
        if first is None:
            return
        try:
            data = json.loads(first)
        except ValueError:
            data = {}
        claims = (
            security.verify_token(str(data.get("token", "")))
            if isinstance(data, dict) and data.get("type") == "hello"
            else None
        )
        if not claims:
            peer.send_text(json.dumps({"type": "error", "error": "unauthorized"}))
            peer.close(4401, "unauthorized")
            return
        uid = int(claims["uid"])
        conn = ClientConn(peer, uid)
        first_conn = uid not in self.users
        self.users.setdefault(uid, set()).add(conn)
        self._gauges()
        if first_conn:
            self.bus.subscribe(f"u.{uid}", self._on_bus)
        try:
            # 先补发 last_seq 之后的投递，再进入实时推送；sent_seq 保证补发与实时消息不重复
            last = int(data.get("last_seq") or 0)
            replayed = await self._replay(conn, last)
            cursor = await self.db.fetchval("SELECT next_seq FROM users WHERE id = ?", uid) or 0
            await self._send(
                conn,
                {
                    "type": "welcome",
                    "cursor": cursor,
                    "node": self.node_id,
                    "replayed": replayed,
                    "server_time": time.time(),
                },
                force=True,
            )
            while True:
                text = await inbox.get()
                if text is None:
                    break
                try:
                    m = json.loads(text)
                except ValueError:
                    continue
                if isinstance(m, dict):
                    await self._on_client(conn, m)
        finally:
            s = self.users.get(uid)
            if s is not None:
                s.discard(conn)
                if not s:
                    del self.users[uid]
                    self.bus.unsubscribe(f"u.{uid}")
            self._gauges()

    async def _replay(self, conn: ClientConn, last: int) -> int:
        backlog = await self.db.fetchval(
            "SELECT COUNT(*) FROM deliveries WHERE user_id = ? AND seq > ?", conn.uid, last
        )
        if int(backlog or 0) > REPLAY_MAX:
            # 一次补发几千条会占满发送缓冲、拖慢同节点其他用户；REST 同步按页拉取，超出保留期还会返回 reset
            await self._send(conn, {"type": "resync_hint", "since": last}, force=True)
            return 0
        n = 0
        while True:
            rows = await self.db.fetch(
                "SELECT seq, payload FROM deliveries WHERE user_id = ? AND seq > ? ORDER BY seq LIMIT 200",
                conn.uid,
                last,
            )
            if not rows:
                return n
            for r in rows:
                p = loads(r["payload"], {})
                p["replay"] = True
                await self._send(conn, p, force=True)
                last = r["seq"]
                n += 1
            REPLAYED.inc(len(rows))

    async def _on_client(self, conn: ClientConn, m: dict[str, Any]) -> None:
        t = m.get("type")
        if t == "ack":
            seq = int(m.get("seq") or 0)
            self._ack_pending[conn.uid] = max(seq, self._ack_pending.get(conn.uid, 0))
            if self._ack_task is None or self._ack_task.done():
                self._ack_task = asyncio.get_running_loop().create_task(self._flush_acks())
        elif t == "state":
            # 交给业务服务按幂等键处理，结果经 u.<uid> 广播给该用户所有设备
            await self.bus.publish("client.state", {"uid": conn.uid, "op": m})
        elif t == "ping":
            await self._send(
                conn, {"type": "pong", "t": m.get("t"), "server_time": time.time()}, force=True
            )
        elif t == "resync":
            await self._replay(conn, int(m.get("last_seq") or 0))

    async def _flush_acks(self) -> None:
        await asyncio.sleep(0.5)  # 合并 ACK，减少写库次数
        pending, self._ack_pending = self._ack_pending, {}
        now = time.time()
        for uid, seq in pending.items():
            await self.db.execute(
                "UPDATE deliveries SET acked_at = ? WHERE user_id = ? AND seq <= ? AND acked_at IS NULL",
                now,
                uid,
                seq,
            )

    # -- 实时推送 ----------------------------------------------------------------

    async def _on_bus(self, topic: str, data: Any, src: str) -> None:
        uid = int(topic.split(".", 1)[1])
        conns = list(self.users.get(uid, ()))
        if not conns or not isinstance(data, dict):
            return
        created = data.get("created_at")
        if created:
            LATENCY.observe(max(0.0, time.time() - float(created)))
        await asyncio.gather(*(self._send(c, data) for c in conns), return_exceptions=True)
        if data.get("seq"):
            await self.db.execute(
                "UPDATE deliveries SET delivered_at = ? WHERE user_id = ? AND seq = ? AND delivered_at IS NULL",
                time.time(),
                uid,
                data["seq"],
            )

    async def _send(
        self, conn: ClientConn, payload: dict[str, Any], *, force: bool = False
    ) -> None:
        seq = payload.get("seq")
        async with conn.lock:
            if seq is not None and seq <= conn.sent_seq:
                return  # 已发送过（补发与实时推送的交叠部分）
            buf = conn.peer.buffered
            if not force and buf > MAX_BUFFER:
                log.info("closing slow client uid=%s buffer=%s", conn.uid, buf)
                conn.peer.abort()
                return
            if (
                not force
                and buf > HIGH_WATER
                and payload.get("priority") in ("low", "normal")
                and payload.get("type") != "state"
            ):
                # 背压：先丢弃低优先级消息，标记需要增量同步；数据仍在库里，不会丢
                conn.needs_resync = True
                DROPPED.inc()
                return
            conn.peer.send_text(json.dumps(payload, ensure_ascii=False, default=str))
            if seq is not None and not conn.needs_resync:
                conn.sent_seq = int(seq)
            SENT.inc(1, str(payload.get("type")))
            if conn.needs_resync and conn.peer.buffered < HIGH_WATER // 4:
                conn.needs_resync = False
                conn.peer.send_text(json.dumps({"type": "resync_hint", "since": conn.sent_seq}))
