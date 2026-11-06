"""总线的 Hub 与客户端节点。

- 拓扑：星型。业务服务内嵌 Hub，采集、邮件、推送、Broker 作为节点接入。
- 可靠性：逐跳至少一次。NEED_ACK 帧在 ``ack_timeout`` 内未收到 ACK 就重发；
  接收方按 (发送节点, Seq) 去重，因此重发不会重复投递。
- 心跳：每 5 秒 HEARTBEAT，15 秒没收到任何帧即视为对端下线；客户端指数退避重连。
- 成员：NODE_JOIN / NODE_LEAVE 变化时 Hub 在 ``$nodes`` 主题广播存活节点列表。
- 认证：NODE_JOIN 带 HMAC（密钥见 ``security.bus_secret``），Hub 回复同样带 HMAC，双向确认。
- 处理：Hub 收到的 PUBLISH 交给每个节点各自的工作协程按序处理，读循环只做解码、ACK 与判活。
- 背压：发件箱有上限；写缓冲区积压时客户端 publish 等待 drain，Hub 暂缓写入、稍后重发。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import logging
import os
import random
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .frame import BusFrame, BusProtocolError, Flags, FrameDecoder, FrameType

log = logging.getLogger(__name__)

Handler = Callable[[str, Any, str], Awaitable[None] | None]  # (topic, data, from_node)

HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_TIMEOUT = 15.0


def topic_matches(pattern: str, topic: str) -> bool:
    """``a.b`` 精确匹配；``a.*`` 前缀匹配；``*`` 匹配全部。"""
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return topic.startswith(pattern[:-1]) or topic == pattern[:-2]
    return pattern == topic


class TopicSet:
    """订阅模式集合：精确主题走哈希查找，只有带通配符的模式才逐个匹配。

    推送节点为每个在线用户订阅一个 ``u.<uid>``，5000 个在线用户时线性匹配是每条消息 5000 次比较；
    压测发现它是全员扇出的瓶颈，改成哈希后单条消息的路由代价与在线人数无关。
    """

    def __init__(self, patterns: Any = ()) -> None:
        self.exact: set[str] = set()
        self.wild: set[str] = set()
        self.update(patterns)

    def add(self, p: str) -> None:
        (self.wild if p == "*" or p.endswith(".*") else self.exact).add(p)

    def discard(self, p: str) -> None:
        self.exact.discard(p)
        self.wild.discard(p)

    def update(self, ps: Any) -> None:
        for p in ps:
            self.add(p)

    def difference_update(self, ps: Any) -> None:
        for p in ps:
            self.discard(p)

    def matches(self, topic: str) -> bool:
        return topic in self.exact or any(topic_matches(p, topic) for p in self.wild)

    def __contains__(self, p: object) -> bool:
        return p in self.exact or p in self.wild

    def __iter__(self) -> Any:
        yield from self.exact
        yield from self.wild

    def __len__(self) -> int:
        return len(self.exact) + len(self.wild)


class _Dedup:
    def __init__(self, size: int = 50000) -> None:
        self._seen: OrderedDict[tuple[str, int], None] = OrderedDict()
        self.size = size

    def check(self, key: tuple[str, int]) -> bool:
        """首次出现返回 True。"""
        if key in self._seen:
            return False
        self._seen[key] = None
        if len(self._seen) > self.size:
            self._seen.popitem(last=False)
        return True

    def clear(self) -> None:
        self._seen.clear()


@dataclass
class _Pending:
    frame: BusFrame
    data: bytes  # 编码后的帧：先编码再进发件箱，超大负载在这里就报错，不会卡死重发循环
    sent_at: float
    future: asyncio.Future[None] | None = None
    attempts: int = 1


@dataclass
class BusStats:
    sent: int = 0
    received: int = 0
    retransmits: int = 0
    duplicates: int = 0
    crc_errors: int = 0
    auth_failures: int = 0
    dropped: int = 0  # 发件箱满时丢弃的最旧帧
    deferred: int = 0  # 对端写缓冲区过高、留待稍后重发的帧
    encode_errors: int = 0


async def _call(handler: Handler, topic: str, data: Any, src: str) -> None:
    try:
        r = handler(topic, data, src)
        if asyncio.iscoroutine(r):
            await r
    except Exception:
        log.exception("bus handler failed for %s", topic)


# ---- 节点认证 ------------------------------------------------------------------
#
# NODE_JOIN 携带 ts、nonce 与 HMAC-SHA256(密钥, node|role|epoch|ts|nonce)。Hub 检查时间窗与 nonce 是否用过
# （防重放），回复里带上 HMAC(密钥, hub|epoch|session|客户端 nonce)，客户端据此确认连上的是真 Hub。
# 密钥为空时不认证（单元测试用原始帧直接接入）。

JOIN_WINDOW = 120.0


def _mac(secret: bytes, label: str, *parts: Any) -> str:
    msg = "|".join([label, *(str(p) for p in parts)]).encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def join_mac(secret: bytes, p: dict[str, Any]) -> str:
    return _mac(
        secret, "join", p.get("node"), p.get("role"), p.get("epoch"), p.get("ts"), p.get("nonce")
    )


def welcome_mac(secret: bytes, p: dict[str, Any], client_nonce: Any) -> str:
    return _mac(secret, "welcome", p.get("node"), p.get("epoch"), p.get("session"), client_nonce)


# ---- Hub ---------------------------------------------------------------------

INBOX_MAX = 1000  # 每个节点待处理的 PUBLISH 上限；满了就暂停读这个连接（TCP 背压）
OUTBOX_MAX = 20000  # 每个节点未确认帧的上限；满了丢最旧的（推送有投递记录兜底，客户端会补发）
HIGH_WATER = 4 * 1024 * 1024  # 写缓冲区超过这个值就不再写入可靠帧，留在发件箱稍后重发


@dataclass
class Member:
    node_id: str
    role: str
    meta: dict[str, Any]
    writer: asyncio.StreamWriter | None
    last_seen: float = field(default_factory=time.monotonic)
    topics: TopicSet = field(default_factory=TopicSet)
    seq: int = 0
    outbox: dict[int, _Pending] = field(default_factory=dict)
    dedup: _Dedup = field(default_factory=_Dedup)
    epoch: str | None = None  # 节点进程的随机标识；变化说明节点重启过，序号从头开始
    alive: bool = True
    dead_since: float = 0.0
    # Hub 为这个成员记录分配的标识：成员被删除后重建时序号从 0 重来，客户端看到 session 变化就清空去重表
    session: str = field(default_factory=lambda: os.urandom(4).hex())
    inbox: asyncio.Queue[tuple[str, Any, str | None]] = field(
        default_factory=lambda: asyncio.Queue(INBOX_MAX)
    )
    worker: asyncio.Task[None] | None = None


class BusHub:
    def __init__(
        self,
        node_id: str = "hub",
        *,
        ack_timeout: float = 2.0,
        heartbeat_timeout: float = HEARTBEAT_TIMEOUT,
        retention: float = 60.0,
        secret: bytes | None = None,
        outbox_max: int = OUTBOX_MAX,
    ) -> None:
        # 节点下线后在 retention 秒内仍为其缓存消息，重连即补发
        self.retention = retention
        self.node_id = node_id
        self.epoch = os.urandom(4).hex()
        self.ack_timeout = ack_timeout
        self.heartbeat_timeout = heartbeat_timeout
        self.secret = secret or b""
        self.outbox_max = outbox_max
        self.members: dict[str, Member] = {}
        self.local: list[tuple[str, Handler]] = []
        self.membership_listeners: list[Callable[[dict[str, list[str]]], None]] = []
        self.stats = BusStats()
        self._nonces: OrderedDict[str, float] = OrderedDict()
        self._server: asyncio.base_events.Server | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self, host: str = "0.0.0.0", port: int = 7400) -> int:
        self._server = await asyncio.start_server(self._on_conn, host, port)
        self._spawn(self._maintenance())
        return self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        if self._server:
            self._server.close()
        for m in self.members.values():
            if m.writer:
                m.writer.close()
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        t = asyncio.get_running_loop().create_task(coro)  # type: ignore[arg-type]
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    def subscribe(self, pattern: str, handler: Handler) -> None:
        """Hub 所在进程的本地订阅。"""
        self.local.append((pattern, handler))

    def live_nodes(self, role: str | None = None) -> list[str]:
        return sorted(
            n for n, m in self.members.items() if m.alive and (role is None or m.role == role)
        )

    def membership(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for n, m in self.members.items():
            if m.alive:
                out.setdefault(m.role, []).append(n)
        return {k: sorted(v) for k, v in out.items()}

    async def publish(
        self, topic: str, data: Any, *, exclude: str | None = None, to: str | None = None
    ) -> int:
        """路由到所有订阅了该主题的节点和本地处理器，返回投递目标数。"""
        n = 0
        now = time.monotonic()
        payload = {"topic": topic, "data": data, "from": exclude or self.node_id}
        for node_id, m in list(self.members.items()):
            if node_id == exclude or (not m.alive and now - m.dead_since > self.retention):
                continue
            if to is not None and node_id != to:
                continue
            if m.topics.matches(topic):
                if self._send_reliable(m, FrameType.PUBLISH, payload):
                    n += 1
        if to is None:
            for pattern, h in self.local:
                if topic_matches(pattern, topic):
                    await _call(h, topic, data, exclude or self.node_id)
                    n += 1
        return n

    def _send_reliable(self, m: Member, ftype: FrameType, payload: Any) -> bool:
        seq = (m.seq + 1) & 0xFFFFFFFF
        f = BusFrame(ftype, seq, payload, Flags.NEED_ACK)
        try:
            data = f.encode()
        except (BusProtocolError, TypeError, ValueError) as e:
            # 超过 16 MiB 或无法序列化：只丢这一条，不影响其他节点和后续消息
            self.stats.encode_errors += 1
            log.warning("bus: cannot encode %s for %s: %s", ftype.name, m.node_id, e)
            return False
        m.seq = seq
        if len(m.outbox) >= self.outbox_max:
            del m.outbox[next(iter(m.outbox))]
            self.stats.dropped += 1
            if self.stats.dropped % 1000 == 1:
                log.warning("bus: outbox of %s is full, dropping oldest frames", m.node_id)
        m.outbox[seq] = _Pending(f, data, time.monotonic())
        self._write(m, data, reliable=True)
        return True

    def _write(self, m: Member, data: bytes, *, reliable: bool = False) -> None:
        w = m.writer
        if not w or w.is_closing():
            return
        if reliable and w.transport.get_write_buffer_size() > HIGH_WATER:
            self.stats.deferred += 1  # 对端读得太慢：留在发件箱，由维护任务稍后重发
            return
        w.write(data)
        self.stats.sent += 1

    async def _on_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        dec = FrameDecoder()
        member: Member | None = None
        try:
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(65536), self.heartbeat_timeout)
                except TimeoutError:
                    break
                if not data:
                    break
                if member is not None:
                    member.last_seen = time.monotonic()  # 收到任何字节都算活着
                try:
                    frames = dec.feed(data)
                except BusProtocolError as e:
                    # 校验失败立即断开，由对端重连
                    self.stats.crc_errors += 1
                    log.warning("bus protocol error: %s", e)
                    break
                for f in frames:
                    self.stats.received += 1
                    if f.type == FrameType.NODE_JOIN:
                        member = await self._on_join(f, writer)
                        continue
                    if member is None:
                        raise BusProtocolError("frame before NODE_JOIN")
                    await self._on_frame(member, f)
                await writer.drain()
        except (ConnectionError, OSError, BusProtocolError) as e:
            if isinstance(e, BusProtocolError):
                log.warning("bus: closing connection: %s", e)
        finally:
            writer.close()
            if member and member.writer is writer:
                member.writer = None
                self._mark_dead(member, "disconnected")

    def _check_join(self, p: dict[str, Any]) -> None:
        if not self.secret:
            return
        try:
            ts = float(p.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        nonce = str(p.get("nonce") or "")
        mac = str(p.get("mac") or "")
        now = time.time()
        ok = (
            abs(now - ts) <= JOIN_WINDOW
            and 8 <= len(nonce) <= 64
            and nonce not in self._nonces
            and hmac.compare_digest(mac, join_mac(self.secret, p))
        )
        if not ok:
            self.stats.auth_failures += 1
            raise BusProtocolError(f"NODE_JOIN authentication failed for {p.get('node')!r}")
        self._nonces[nonce] = now
        while self._nonces and now - next(iter(self._nonces.values())) > 2 * JOIN_WINDOW:
            self._nonces.popitem(last=False)

    async def _on_join(self, f: BusFrame, writer: asyncio.StreamWriter) -> Member:
        p = f.payload if isinstance(f.payload, dict) else {}
        self._check_join(p)
        node_id = str(p.get("node"))
        m = self.members.get(node_id)
        was_alive = bool(m and m.alive)
        if m is None:
            m = Member(node_id, str(p.get("role", "")), dict(p.get("meta") or {}), writer)
            self.members[node_id] = m
        else:
            if m.writer and m.writer is not writer:
                m.writer.close()
            m.writer = writer
            m.role = str(p.get("role", m.role))
            m.meta = dict(p.get("meta") or m.meta)
            if p.get("epoch_seen") != self.epoch:
                m.outbox.clear()
            if p.get("epoch") != m.epoch:
                # 同名节点的新进程：它的序号从头开始，旧进程的去重窗口会把新帧（含 SUBSCRIBE）当成重复丢掉
                m.dedup.clear()
        if m.worker is None or m.worker.done():
            m.worker = self._spawn(self._worker(m))
        m.epoch = p.get("epoch")
        m.alive = True
        m.last_seen = time.monotonic()
        m.topics = TopicSet(p.get("topics") or [])
        welcome: dict[str, Any] = {"node": self.node_id, "epoch": self.epoch, "session": m.session}
        if self.secret:
            welcome["mac"] = welcome_mac(self.secret, welcome, p.get("nonce"))
        self._write(m, BusFrame(FrameType.NODE_JOIN, 0, welcome).encode())
        if f.flags & Flags.NEED_ACK:
            self._write(m, BusFrame(FrameType.ACK, f.seq).encode())
        # 重连后重发尚未确认的帧
        for pend in m.outbox.values():
            pend.sent_at = time.monotonic()
            self._write(m, pend.data, reliable=True)
        if not was_alive:
            log.info("node joined: %s (%s)", node_id, m.role)
            await self._broadcast_membership()
        return m

    async def _on_frame(self, m: Member, f: BusFrame) -> None:
        if f.type == FrameType.ACK:
            pend = m.outbox.pop(f.seq, None)
            if pend and pend.future and not pend.future.done():
                pend.future.set_result(None)
            return
        if f.flags & Flags.NEED_ACK:
            self._write(m, BusFrame(FrameType.ACK, f.seq).encode())
            if not m.dedup.check((m.node_id, f.seq)):
                self.stats.duplicates += 1
                return
        p = f.payload if isinstance(f.payload, dict) else {}
        if f.type == FrameType.HEARTBEAT:
            self._write(m, BusFrame(FrameType.HEARTBEAT, 0, {"t": time.time()}).encode())
        elif f.type == FrameType.SUBSCRIBE:
            m.topics.update(str(t) for t in p.get("topics") or [])
        elif f.type == FrameType.UNSUBSCRIBE:
            m.topics.difference_update(str(t) for t in p.get("topics") or [])
        elif f.type == FrameType.NODE_LEAVE:
            self._mark_dead(m, "leave")
        elif f.type == FrameType.PUBLISH:
            # 交给该节点的工作协程按顺序处理，读循环不等处理器（入库、大模型可能要几秒）；
            # 队列满时这里会等待，即暂停读这个连接，由 TCP 把背压传回发送方
            to = p.get("to")
            await m.inbox.put((str(p.get("topic")), p.get("data"), str(to) if to else None))

    async def _worker(self, m: Member) -> None:
        while True:
            topic, data, to = await m.inbox.get()
            try:
                await self.publish(topic, data, exclude=m.node_id, to=to)
            except Exception:
                log.exception("bus: routing %s from %s failed", topic, m.node_id)

    def _mark_dead(self, m: Member, why: str) -> None:
        if not m.alive:
            return
        m.alive = False
        m.dead_since = time.monotonic()
        log.info("node left: %s (%s)", m.node_id, why)
        self._spawn(self._broadcast_membership())

    async def _broadcast_membership(self) -> None:
        mem = self.membership()
        for cb in self.membership_listeners:
            with contextlib.suppress(Exception):
                cb(mem)
        await self.publish("$nodes", mem)

    async def _maintenance(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            try:
                self._maintain_once(time.monotonic())
            except Exception:  # 维护任务退出就再也不会重发与判活：只记日志
                log.exception("bus maintenance failed")

    def _maintain_once(self, now: float) -> None:
        for m in list(self.members.values()):
            # 队列满说明是 Hub 自己没处理完、暂停了读取，不是对端失联
            if m.alive and not m.inbox.full() and now - m.last_seen > self.heartbeat_timeout:
                if m.writer:
                    m.writer.close()
                self._mark_dead(m, "heartbeat timeout")
            if not m.alive:
                if now - m.dead_since > self.retention and m.inbox.empty():
                    if m.worker:
                        m.worker.cancel()
                    del self.members[m.node_id]
                continue
            for pend in m.outbox.values():
                if now - pend.sent_at > self.ack_timeout * min(pend.attempts, 8):
                    pend.sent_at = now
                    pend.attempts += 1
                    self.stats.retransmits += 1
                    self._write(m, pend.data, reliable=True)


# ---- 客户端节点 ----------------------------------------------------------------

CLIENT_OUTBOX_MAX = 10000  # 未确认帧上限；满了 publish 等待（采集、邮件节点随之放慢）


class BusClient:
    def __init__(
        self,
        node_id: str,
        role: str,
        host: str,
        port: int,
        *,
        meta: dict[str, Any] | None = None,
        ack_timeout: float = 2.0,
        heartbeat_interval: float = HEARTBEAT_INTERVAL,
        heartbeat_timeout: float = HEARTBEAT_TIMEOUT,
        secret: bytes | None = None,
        outbox_max: int = CLIENT_OUTBOX_MAX,
    ) -> None:
        self.node_id = node_id
        self.role = role
        self.host = host
        self.port = port
        self.meta = meta or {}
        self.ack_timeout = ack_timeout
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.secret = secret or b""
        self.outbox_max = outbox_max
        # 精确主题 → 处理器列表；带通配符的模式单独存放（见 TopicSet）
        self.handlers: dict[str, list[Handler]] = {}
        self.wild_handlers: list[tuple[str, Handler]] = []
        self.topics = TopicSet()
        self.stats = BusStats()
        self.connected = asyncio.Event()
        self._room = asyncio.Event()
        self._room.set()
        self._writer: asyncio.StreamWriter | None = None
        self._seq = 0
        self._outbox: dict[int, _Pending] = {}
        self._dedup = _Dedup()
        self.epoch = os.urandom(4).hex()  # 本进程标识，随 NODE_JOIN 发给 Hub
        self._hub_epoch: str | None = None
        self._hub_session: str | None = None
        self._join_nonce = ""
        self._welcomed = False
        self._last_rx = time.monotonic()
        self._run_task: asyncio.Task[None] | None = None
        self._closing = False
        self.reconnects = 0

    def subscribe(self, pattern: str, handler: Handler) -> None:
        if pattern == "*" or pattern.endswith(".*"):
            self.wild_handlers.append((pattern, handler))
        else:
            self.handlers.setdefault(pattern, []).append(handler)
        if pattern not in self.topics:
            self.topics.add(pattern)
            if self._writer:
                self._send_reliable(FrameType.SUBSCRIBE, {"topics": [pattern]})

    def unsubscribe(self, pattern: str) -> None:
        self.handlers.pop(pattern, None)
        self.wild_handlers = [(p, h) for p, h in self.wild_handlers if p != pattern]
        if pattern in self.topics:
            self.topics.discard(pattern)
            if self._writer:
                self._send_reliable(FrameType.UNSUBSCRIBE, {"topics": [pattern]})

    async def publish(
        self, topic: str, data: Any, *, wait: bool = False, to: str | None = None
    ) -> None:
        """可靠发布。负载过大（> 16 MiB）抛 BusProtocolError；发件箱满时等待 Hub 确认腾出空间。"""
        payload: dict[str, Any] = {"topic": topic, "data": data}
        if to:
            payload["to"] = to
        while len(self._outbox) >= self.outbox_max and not self._closing:
            self._room.clear()
            await self._room.wait()
        fut = self._send_reliable(FrameType.PUBLISH, payload)
        await self._drain()
        if wait:
            await fut

    def _send_reliable(self, ftype: FrameType, payload: Any) -> asyncio.Future[None]:
        seq = (self._seq + 1) & 0xFFFFFFFF
        f = BusFrame(ftype, seq, payload, Flags.NEED_ACK)
        data = f.encode()  # 先编码：失败直接抛给调用方，不进发件箱
        self._seq = seq
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._outbox[seq] = _Pending(f, data, time.monotonic(), fut)
        self._write(data)
        return fut

    def _write(self, data: bytes) -> None:
        w = self._writer
        if w and not w.is_closing():
            w.write(data)
            self.stats.sent += 1

    async def _drain(self) -> None:
        """写缓冲区积压时等对端读走；连接断了不报错（帧在发件箱里，重连后重发）。"""
        w = self._writer
        if w is None or w.is_closing() or w.transport.get_write_buffer_size() <= HIGH_WATER:
            return
        with contextlib.suppress(ConnectionError, OSError, TimeoutError):
            await asyncio.wait_for(w.drain(), self.heartbeat_timeout)

    def _acked(self, seq: int) -> None:
        pend = self._outbox.pop(seq, None)
        if pend and pend.future and not pend.future.done():
            pend.future.set_result(None)
        if len(self._outbox) < self.outbox_max:
            self._room.set()

    def start(self) -> None:
        self._run_task = asyncio.get_running_loop().create_task(self._run())

    async def wait_connected(self, timeout: float = 10.0) -> None:
        await asyncio.wait_for(self.connected.wait(), timeout)

    async def close(self) -> None:
        self._closing = True
        self._room.set()
        if self._writer:
            with contextlib.suppress(Exception):
                self._write(BusFrame(FrameType.NODE_LEAVE, 0, {"node": self.node_id}).encode())
                await self._writer.drain()
            self._writer.close()
        if self._run_task:
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._run_task

    def _join_payload(self) -> dict[str, Any]:
        self._join_nonce = os.urandom(12).hex()
        join: dict[str, Any] = {
            "node": self.node_id,
            "role": self.role,
            "meta": self.meta,
            "topics": sorted(self.topics),
            "epoch": self.epoch,
            "epoch_seen": self._hub_epoch,
            "ts": round(time.time(), 3),
            "nonce": self._join_nonce,
        }
        if self.secret:
            join["mac"] = join_mac(self.secret, join)
        return join

    def _resend_after_reconnect(self) -> None:
        # NODE_JOIN 已带上完整的当前订阅：还没确认的 SUBSCRIBE / UNSUBSCRIBE 不再重发，
        # 否则一个已经取消的订阅会被旧的 SUBSCRIBE 重新加回来
        for seq, pend in list(self._outbox.items()):
            if pend.frame.type in (FrameType.SUBSCRIBE, FrameType.UNSUBSCRIBE):
                self._acked(seq)
        for pend in self._outbox.values():
            pend.sent_at = time.monotonic()
            self._write(pend.data)

    async def _run(self) -> None:
        backoff = 0.2
        while not self._closing:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), 5
                )
            except (OSError, TimeoutError):
                await asyncio.sleep(backoff + random.random() * backoff)
                backoff = min(backoff * 2, 10.0)
                continue
            self._writer = writer
            self._welcomed = False
            self._last_rx = time.monotonic()
            hb = asyncio.get_running_loop().create_task(self._heartbeat())
            try:
                writer.write(BusFrame(FrameType.NODE_JOIN, 0, self._join_payload()).encode())
                self._resend_after_reconnect()
                await self._read_loop(reader)
            except (ConnectionError, OSError, BusProtocolError) as e:
                log.info("bus connection lost: %s", e)
            except Exception:
                log.exception("bus client error")
            finally:
                hb.cancel()
                self.connected.clear()
                self._writer = None
                writer.close()
            if self._welcomed:  # 握手成功过才重置退避；认证失败等情况继续加大退避
                backoff = 0.2
            if not self._closing:
                self.reconnects += 1
                await asyncio.sleep(backoff + random.random() * backoff)
                backoff = min(backoff * 2, 10.0)

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        dec = FrameDecoder()
        while True:
            try:
                data = await asyncio.wait_for(reader.read(65536), self.heartbeat_timeout)
            except TimeoutError:
                log.info("bus heartbeat timeout")
                return
            if not data:
                return
            self._last_rx = time.monotonic()
            for f in dec.feed(data):
                self.stats.received += 1
                await self._on_frame(f)

    def _on_welcome(self, p: dict[str, Any]) -> None:
        if self.secret and not hmac.compare_digest(
            str(p.get("mac") or ""), welcome_mac(self.secret, p, self._join_nonce)
        ):
            self.stats.auth_failures += 1
            raise BusProtocolError("hub authentication failed")
        epoch, session = p.get("epoch"), p.get("session")
        if (epoch, session) != (self._hub_epoch, self._hub_session):
            # Hub 重启，或 Hub 删除后重建了本节点的成员记录：它发来的序号从头开始
            self._dedup.clear()
            self._hub_epoch, self._hub_session = epoch, session
        self._welcomed = True
        self.connected.set()

    async def _on_frame(self, f: BusFrame) -> None:
        if f.type == FrameType.NODE_JOIN:
            self._on_welcome(f.payload if isinstance(f.payload, dict) else {})
            return
        if not self._welcomed and self.secret:
            raise BusProtocolError("frame before hub welcome")
        if f.type == FrameType.ACK:
            self._acked(f.seq)
            return
        if f.flags & Flags.NEED_ACK:
            self._write(BusFrame(FrameType.ACK, f.seq).encode())
            if not self._dedup.check(("hub", f.seq)):
                self.stats.duplicates += 1
                return
        if f.type == FrameType.PUBLISH:
            p = f.payload if isinstance(f.payload, dict) else {}
            topic = str(p.get("topic"))
            hs = list(self.handlers.get(topic, ()))
            hs += [h for pat, h in self.wild_handlers if topic_matches(pat, topic)]
            for h in hs:
                await _call(h, topic, p.get("data"), str(p.get("from", "")))

    async def _heartbeat(self) -> None:
        last_hb = 0.0
        while True:
            await asyncio.sleep(min(0.5, self.heartbeat_interval))
            try:
                now = time.monotonic()
                if now - last_hb >= self.heartbeat_interval:
                    last_hb = now
                    self._write(BusFrame(FrameType.HEARTBEAT, 0).encode())
                for pend in self._outbox.values():
                    if now - pend.sent_at > self.ack_timeout * min(pend.attempts, 8):
                        pend.sent_at = now
                        pend.attempts += 1
                        self.stats.retransmits += 1
                        self._write(pend.data)
            except Exception:  # 心跳任务退出就再也不会重发：只记日志
                log.exception("bus heartbeat failed")
