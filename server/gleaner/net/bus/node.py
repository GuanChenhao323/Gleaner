"""总线的 Hub 与客户端节点。

- 拓扑：星型。业务服务内嵌 Hub，采集、邮件、推送、Broker 作为节点接入。
- 可靠性：逐跳至少一次。NEED_ACK 帧在 ``ack_timeout`` 内未收到 ACK 就重发；
  接收方按 (发送节点, Seq) 去重，因此重发不会重复投递。
- 心跳：每 5 秒 HEARTBEAT，15 秒没收到任何帧即视为对端下线；客户端指数退避重连。
- 成员：NODE_JOIN / NODE_LEAVE 变化时 Hub 在 ``$nodes`` 主题广播存活节点列表。
"""

from __future__ import annotations

import asyncio
import contextlib
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


async def _call(handler: Handler, topic: str, data: Any, src: str) -> None:
    try:
        r = handler(topic, data, src)
        if asyncio.iscoroutine(r):
            await r
    except Exception:
        log.exception("bus handler failed for %s", topic)


# ---- Hub ---------------------------------------------------------------------


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
    alive: bool = True
    dead_since: float = 0.0


class BusHub:
    def __init__(
        self,
        node_id: str = "hub",
        *,
        ack_timeout: float = 2.0,
        heartbeat_timeout: float = HEARTBEAT_TIMEOUT,
        retention: float = 60.0,
    ) -> None:
        # 节点下线后在 retention 秒内仍为其缓存消息，重连即补发
        self.retention = retention
        self.node_id = node_id
        self.epoch = os.urandom(4).hex()
        self.ack_timeout = ack_timeout
        self.heartbeat_timeout = heartbeat_timeout
        self.members: dict[str, Member] = {}
        self.local: list[tuple[str, Handler]] = []
        self.membership_listeners: list[Callable[[dict[str, list[str]]], None]] = []
        self.stats = BusStats()
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

    def _spawn(self, coro: Awaitable[Any]) -> None:
        t = asyncio.get_running_loop().create_task(coro)  # type: ignore[arg-type]
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

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
        for node_id, m in list(self.members.items()):
            if node_id == exclude or (not m.alive and now - m.dead_since > self.retention):
                continue
            if to is not None and node_id != to:
                continue
            if m.topics.matches(topic):
                self._send_reliable(
                    m,
                    FrameType.PUBLISH,
                    {"topic": topic, "data": data, "from": exclude or self.node_id},
                )
                n += 1
        if to is None:
            for pattern, h in self.local:
                if topic_matches(pattern, topic):
                    await _call(h, topic, data, exclude or self.node_id)
                    n += 1
        return n

    def _send_reliable(self, m: Member, ftype: FrameType, payload: Any) -> None:
        m.seq = (m.seq + 1) & 0xFFFFFFFF
        f = BusFrame(ftype, m.seq, payload, Flags.NEED_ACK)
        m.outbox[m.seq] = _Pending(f, time.monotonic())
        self._write(m, f)

    def _write(self, m: Member, f: BusFrame) -> None:
        if m.writer and not m.writer.is_closing():
            m.writer.write(f.encode())
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
                    member.last_seen = time.monotonic()
                    await self._on_frame(member, f)
                await writer.drain()
        except (ConnectionError, OSError, BusProtocolError):
            pass
        finally:
            writer.close()
            if member and member.writer is writer:
                member.writer = None
                self._mark_dead(member, "disconnected")

    async def _on_join(self, f: BusFrame, writer: asyncio.StreamWriter) -> Member:
        p = f.payload or {}
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
        m.alive = True
        m.last_seen = time.monotonic()
        m.topics = TopicSet(p.get("topics") or [])
        self._write(
            m, BusFrame(FrameType.NODE_JOIN, 0, {"node": self.node_id, "epoch": self.epoch})
        )
        if f.flags & Flags.NEED_ACK:
            self._write(m, BusFrame(FrameType.ACK, f.seq))
        # 重连后重发尚未确认的帧
        for pend in m.outbox.values():
            pend.sent_at = time.monotonic()
            self._write(m, pend.frame)
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
            self._write(m, BusFrame(FrameType.ACK, f.seq))
            if not m.dedup.check((m.node_id, f.seq)):
                self.stats.duplicates += 1
                return
        if f.type == FrameType.HEARTBEAT:
            self._write(m, BusFrame(FrameType.HEARTBEAT, 0, {"t": time.time()}))
        elif f.type == FrameType.SUBSCRIBE:
            m.topics.update(f.payload.get("topics", []))
        elif f.type == FrameType.UNSUBSCRIBE:
            m.topics.difference_update(f.payload.get("topics", []))
        elif f.type == FrameType.NODE_LEAVE:
            self._mark_dead(m, "leave")
        elif f.type == FrameType.PUBLISH:
            p = f.payload or {}
            await self.publish(
                str(p.get("topic")), p.get("data"), exclude=m.node_id, to=p.get("to")
            )

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
            now = time.monotonic()
            for m in list(self.members.values()):
                if m.alive and now - m.last_seen > self.heartbeat_timeout:
                    if m.writer:
                        m.writer.close()
                    self._mark_dead(m, "heartbeat timeout")
                if not m.alive:
                    if now - m.dead_since > self.retention:
                        del self.members[m.node_id]
                    continue
                for pend in m.outbox.values():
                    if now - pend.sent_at > self.ack_timeout * min(pend.attempts, 8):
                        pend.sent_at = now
                        pend.attempts += 1
                        self.stats.retransmits += 1
                        self._write(m, pend.frame)


# ---- 客户端节点 ----------------------------------------------------------------


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
    ) -> None:
        self.node_id = node_id
        self.role = role
        self.host = host
        self.port = port
        self.meta = meta or {}
        self.ack_timeout = ack_timeout
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        # 精确主题 → 处理器列表；带通配符的模式单独存放（见 TopicSet）
        self.handlers: dict[str, list[Handler]] = {}
        self.wild_handlers: list[tuple[str, Handler]] = []
        self.topics = TopicSet()
        self.stats = BusStats()
        self.connected = asyncio.Event()
        self._writer: asyncio.StreamWriter | None = None
        self._seq = 0
        self._outbox: dict[int, _Pending] = {}
        self._dedup = _Dedup()
        self._hub_epoch: str | None = None
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
        payload: dict[str, Any] = {"topic": topic, "data": data}
        if to:
            payload["to"] = to
        fut = self._send_reliable(FrameType.PUBLISH, payload)
        if wait:
            await fut

    def _send_reliable(self, ftype: FrameType, payload: Any) -> asyncio.Future[None]:
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        f = BusFrame(ftype, self._seq, payload, Flags.NEED_ACK)
        self._outbox[self._seq] = _Pending(f, time.monotonic(), fut)
        self._write(f)
        return fut

    def _write(self, f: BusFrame) -> None:
        w = self._writer
        if w and not w.is_closing():
            w.write(f.encode())
            self.stats.sent += 1

    def start(self) -> None:
        self._run_task = asyncio.get_running_loop().create_task(self._run())

    async def wait_connected(self, timeout: float = 10.0) -> None:
        await asyncio.wait_for(self.connected.wait(), timeout)

    async def close(self) -> None:
        self._closing = True
        if self._writer:
            with contextlib.suppress(Exception):
                self._write(BusFrame(FrameType.NODE_LEAVE, 0, {"node": self.node_id}))
                await self._writer.drain()
            self._writer.close()
        if self._run_task:
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._run_task

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
            backoff = 0.2
            self._writer = writer
            self._last_rx = time.monotonic()
            join = {
                "node": self.node_id,
                "role": self.role,
                "meta": self.meta,
                "topics": sorted(self.topics),
                "epoch_seen": self._hub_epoch,
            }
            writer.write(BusFrame(FrameType.NODE_JOIN, 0, join).encode())
            for pend in self._outbox.values():
                pend.sent_at = time.monotonic()
                self._write(pend.frame)
            hb = asyncio.get_running_loop().create_task(self._heartbeat())
            try:
                await self._read_loop(reader)
            except (ConnectionError, OSError, BusProtocolError) as e:
                log.info("bus connection lost: %s", e)
            finally:
                hb.cancel()
                self.connected.clear()
                self._writer = None
                writer.close()
            if not self._closing:
                self.reconnects += 1
                await asyncio.sleep(backoff)

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

    async def _on_frame(self, f: BusFrame) -> None:
        if f.type == FrameType.NODE_JOIN:
            epoch = (f.payload or {}).get("epoch")
            if epoch != self._hub_epoch:
                self._dedup.clear()  # Hub 重启后序号重新开始
                self._hub_epoch = epoch
            self.connected.set()
            return
        if f.type == FrameType.ACK:
            pend = self._outbox.pop(f.seq, None)
            if pend and pend.future and not pend.future.done():
                pend.future.set_result(None)
            return
        if f.flags & Flags.NEED_ACK:
            self._write(BusFrame(FrameType.ACK, f.seq))
            if not self._dedup.check(("hub", f.seq)):
                self.stats.duplicates += 1
                return
        if f.type == FrameType.PUBLISH:
            p = f.payload or {}
            topic = str(p.get("topic"))
            hs = list(self.handlers.get(topic, ()))
            hs += [h for pat, h in self.wild_handlers if topic_matches(pat, topic)]
            for h in hs:
                await _call(h, topic, p.get("data"), str(p.get("from", "")))

    async def _heartbeat(self) -> None:
        last_hb = 0.0
        while True:
            await asyncio.sleep(min(0.5, self.heartbeat_interval))
            now = time.monotonic()
            if now - last_hb >= self.heartbeat_interval:
                last_hb = now
                self._write(BusFrame(FrameType.HEARTBEAT, 0))
            for pend in self._outbox.values():
                if now - pend.sent_at > self.ack_timeout * min(pend.attempts, 8):
                    pend.sent_at = now
                    pend.attempts += 1
                    self.stats.retransmits += 1
                    self._write(pend.frame)
