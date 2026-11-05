"""MQTT 3.1.1 Broker 子集。

支持 QoS 0/1、持久会话（Clean Session = 0）、保留消息、``+``/``#`` 通配符、
会话接管、Keep Alive（1.5 倍）、遗嘱消息、主题访问控制（ACL）。
QoS 2 的 SUBSCRIBE 请求降级授予 QoS 1。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..net.mqtt import (
    Connack,
    ConnackCode,
    Connect,
    MQTTProtocolError,
    PacketId,
    PacketReader,
    PacketType,
    Publish,
    Simple,
    Suback,
    Subscribe,
    SubscriptionTree,
    Unsubscribe,
    matches,
    valid_filter,
)

log = logging.getLogger(__name__)

# authenticate(client_id, username, password) -> principal（None 表示拒绝）
Authenticator = Callable[[str, str | None, bytes | None], str | None]
# acl(principal, topic_or_filter, action: "sub" | "pub") -> bool
ACL = Callable[[str, str, str], bool]


def allow_all_auth(client_id: str, username: str | None, password: bytes | None) -> str:
    return username or client_id


def allow_all_acl(principal: str, topic: str, action: str) -> bool:
    return True


@dataclass
class _Inflight:
    msg: Publish
    sent_at: float
    attempts: int = 1


@dataclass
class Session:
    client_id: str
    principal: str = ""
    clean: bool = True
    subscriptions: dict[str, int] = field(default_factory=dict)
    inflight: dict[int, _Inflight] = field(default_factory=dict)
    queue: deque[Publish] = field(default_factory=deque)
    next_pid: int = 1
    conn: _Client | None = None
    disconnected_at: float | None = None

    def alloc_pid(self) -> int:
        for _ in range(65535):
            pid = self.next_pid
            self.next_pid = pid % 65535 + 1
            if pid not in self.inflight:
                return pid
        raise RuntimeError("no free packet id")


@dataclass
class BrokerStats:
    clients_connected: int = 0
    messages_in: int = 0
    messages_out: int = 0
    qos1_retries: int = 0
    dropped: int = 0


class _Client:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.session: Session | None = None
        self.keepalive = 0
        self.last_rx = time.monotonic()
        self.will: Publish | None = None
        self.closed = False

    def send(self, data: bytes) -> None:
        if not self.closed and not self.writer.is_closing():
            self.writer.write(data)

    def close(self) -> None:
        self.closed = True
        if not self.writer.is_closing():
            self.writer.close()


class Broker:
    def __init__(
        self,
        *,
        authenticate: Authenticator = allow_all_auth,
        acl: ACL = allow_all_acl,
        max_inflight: int = 20,
        max_queued: int = 1000,
        retry_interval: float = 5.0,
        session_expiry: float = 7 * 24 * 3600,
        persist_path: str | None = None,
    ) -> None:
        self.authenticate = authenticate
        self.acl = acl
        self.max_inflight = max_inflight
        self.max_queued = max_queued
        self.retry_interval = retry_interval
        self.session_expiry = session_expiry
        self.persist_path = Path(persist_path) if persist_path else None
        self.sessions: dict[str, Session] = {}
        self.retained: dict[str, Publish] = {}
        self.tree = SubscriptionTree()
        self.stats = BrokerStats()
        self._server: asyncio.base_events.Server | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._retry_task: asyncio.Task[None] | None = None
        self._load()

    # -- 生命周期 ----------------------------------------------------------------

    async def start(self, host: str = "0.0.0.0", port: int = 1883, ssl_ctx: object = None) -> int:
        self._server = await asyncio.start_server(self._on_conn, host, port, ssl=ssl_ctx)  # type: ignore[arg-type]
        self._retry_task = asyncio.get_running_loop().create_task(self._retry_loop())
        return self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        if self._retry_task:
            self._retry_task.cancel()
        if self._server:
            self._server.close()
        for s in self.sessions.values():
            if s.conn:
                s.conn.close()
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self.save()

    # -- 对内发布接口：总线把紧急通知交给这里 ------------------------------------

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        self._route(Publish(topic, payload, qos=qos, retain=retain))

    # -- 连接处理 ----------------------------------------------------------------

    async def _on_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task
        self._tasks.add(task)
        client = _Client(reader, writer)
        parser = PacketReader()
        try:
            # CONNECT 必须是第一个报文，且应在合理时间内到达（§3.1）
            first = True
            while not client.closed:
                timeout = 10.0 if first else (client.keepalive * 1.5 if client.keepalive else None)
                try:
                    data = await asyncio.wait_for(reader.read(65536), timeout)
                except TimeoutError:
                    log.info("keepalive timeout %s", client.session and client.session.client_id)
                    break  # Keep Alive 的 1.5 倍内没有任何报文（§3.1.2.10）
                if not data:
                    break
                client.last_rx = time.monotonic()
                for pkt in parser.feed(data):
                    if first:
                        if not isinstance(pkt, Connect):
                            raise MQTTProtocolError("first packet must be CONNECT")
                        first = False
                        if not self._on_connect(client, pkt):
                            return
                        continue
                    if isinstance(pkt, Connect):
                        raise MQTTProtocolError("second CONNECT")  # §3.1.0-2
                    if not self._on_packet(client, pkt):
                        client.will = None  # 正常 DISCONNECT 丢弃遗嘱（§3.14.4）
                        client.close()
                        break
                await writer.drain()
        except (MQTTProtocolError, ConnectionError, OSError) as e:
            log.info("mqtt connection error: %s", e)
        except asyncio.CancelledError:
            pass
        finally:
            self._on_disconnect(client)
            self._tasks.discard(task)

    def _on_connect(self, client: _Client, c: Connect) -> bool:
        if c.protocol_level != 4:
            client.send(Connack(False, ConnackCode.BAD_PROTOCOL).encode())
            client.close()
            return False
        if not c.client_id:
            if not c.clean_session:
                client.send(Connack(False, ConnackCode.ID_REJECTED).encode())
                client.close()
                return False
            c.client_id = f"auto-{id(client):x}"
        principal = self.authenticate(c.client_id, c.username, c.password)
        if principal is None:
            client.send(Connack(False, ConnackCode.BAD_CREDENTIALS).encode())
            client.close()
            return False
        old = self.sessions.get(c.client_id)
        if old and old.conn:
            # 会话接管：同一 ClientId 的旧连接被断开（§3.1.4 第 2 步）
            old.conn.will = None
            old.conn.close()
            old.conn = None
            self.stats.clients_connected -= 1
        if c.clean_session or old is None or old.principal != principal:
            if old:
                self._drop_session(old)
            sess = Session(client_id=c.client_id, principal=principal, clean=c.clean_session)
            self.sessions[c.client_id] = sess
            present = False
        else:
            sess = old
            sess.clean = False
            present = True
        sess.conn = client
        sess.disconnected_at = None
        client.session = sess
        client.keepalive = c.keepalive
        if c.will_topic:
            client.will = Publish(
                c.will_topic, c.will_message, qos=min(c.will_qos, 1), retain=c.will_retain
            )
        self.stats.clients_connected += 1
        client.send(Connack(present, ConnackCode.ACCEPTED).encode())
        if present:
            # 持久会话恢复：未确认的消息以 DUP=1 重发，再发送离线队列（§4.4）
            for inf in sess.inflight.values():
                inf.msg.dup = True
                inf.sent_at = time.monotonic()
                client.send(inf.msg.encode())
            self._drain_queue(sess)
        return True

    def _on_packet(self, client: _Client, pkt: object) -> bool:
        sess = client.session
        assert sess is not None
        if isinstance(pkt, Publish):
            self.stats.messages_in += 1
            if pkt.topic.startswith("$") or not self.acl(sess.principal, pkt.topic, "pub"):
                # 3.1.1 没有拒绝 PUBLISH 的方式：确认后静默丢弃
                if pkt.qos == 1 and pkt.packet_id:
                    client.send(PacketId(PacketType.PUBACK, pkt.packet_id).encode())
                return True
            if pkt.qos == 1 and pkt.packet_id:
                client.send(PacketId(PacketType.PUBACK, pkt.packet_id).encode())
            elif pkt.qos == 2 and pkt.packet_id:
                client.send(PacketId(PacketType.PUBREC, pkt.packet_id).encode())
            self._route(Publish(pkt.topic, pkt.payload, qos=min(pkt.qos, 1), retain=pkt.retain))
        elif isinstance(pkt, PacketId):
            if pkt.type == PacketType.PUBACK:
                sess.inflight.pop(pkt.packet_id, None)
                self._drain_queue(sess)
            elif pkt.type == PacketType.PUBREL:
                client.send(PacketId(PacketType.PUBCOMP, pkt.packet_id).encode())
        elif isinstance(pkt, Subscribe):
            codes: list[int] = []
            new_filters: list[tuple[str, int]] = []
            for filt, q in pkt.topics:
                if not valid_filter(filt) or not self.acl(sess.principal, filt, "sub"):
                    codes.append(0x80)
                    continue
                granted = min(q, 1)
                sess.subscriptions[filt] = granted
                self.tree.add(filt, sess.client_id, granted)
                codes.append(granted)
                new_filters.append((filt, granted))
            client.send(Suback(pkt.packet_id, codes).encode())
            # 新订阅立即收到匹配的保留消息，RETAIN 标志置 1（§3.3.1.3）
            for filt, granted in new_filters:
                for topic, msg in self.retained.items():
                    if matches(filt, topic):
                        self._deliver(
                            sess,
                            Publish(topic, msg.payload, qos=min(msg.qos, granted), retain=True),
                        )
        elif isinstance(pkt, Unsubscribe):
            for filt in pkt.topics:
                sess.subscriptions.pop(filt, None)
                self.tree.remove(filt, sess.client_id)
            client.send(PacketId(PacketType.UNSUBACK, pkt.packet_id).encode())
        elif isinstance(pkt, Simple):
            if pkt.type == PacketType.PINGREQ:
                client.send(Simple(PacketType.PINGRESP).encode())
            elif pkt.type == PacketType.DISCONNECT:
                return False
        return True

    def _on_disconnect(self, client: _Client) -> None:
        client.close()
        sess = client.session
        if sess is None or sess.conn is not client:
            return
        self.stats.clients_connected -= 1
        sess.conn = None
        sess.disconnected_at = time.time()
        if client.will:
            self._route(client.will)
        if sess.clean:
            self._drop_session(sess)

    def _drop_session(self, sess: Session) -> None:
        for filt in sess.subscriptions:
            self.tree.remove(filt, sess.client_id)
        self.sessions.pop(sess.client_id, None)

    def forget_user(self, uid: int) -> int:
        """删除账号时调用：断开并清掉该用户的全部持久会话（含离线队列）和其主题下的保留消息。"""
        principal = str(uid)
        n = 0
        for sess in [s for s in self.sessions.values() if s.principal == principal]:
            if sess.conn is not None:
                sess.conn.writer.close()
            self._drop_session(sess)
            n += 1
        prefix = f"gleaner/u/{uid}/"
        for topic in [t for t in self.retained if t.startswith(prefix)]:
            del self.retained[topic]
        return n

    # -- 路由与投递 --------------------------------------------------------------

    def _route(self, msg: Publish) -> None:
        if msg.retain:
            # 空负载的保留消息表示删除（§3.3.1.3）
            if msg.payload:
                self.retained[msg.topic] = Publish(msg.topic, msg.payload, qos=msg.qos, retain=True)
            else:
                self.retained.pop(msg.topic, None)
        for cid, granted in self.tree.match(msg.topic).items():
            sess = self.sessions.get(cid)
            if sess:
                # 正常转发时 RETAIN 置 0
                self._deliver(
                    sess, Publish(msg.topic, msg.payload, qos=min(msg.qos, granted), retain=False)
                )

    def _deliver(self, sess: Session, msg: Publish) -> None:
        if msg.qos == 0:
            if sess.conn:
                sess.conn.send(msg.encode())
                self.stats.messages_out += 1
            return
        if sess.conn is None or len(sess.inflight) >= self.max_inflight:
            if len(sess.queue) >= self.max_queued:
                sess.queue.popleft()
                self.stats.dropped += 1
            sess.queue.append(msg)
            return
        msg.packet_id = sess.alloc_pid()
        sess.inflight[msg.packet_id] = _Inflight(msg, time.monotonic())
        sess.conn.send(msg.encode())
        self.stats.messages_out += 1

    def _drain_queue(self, sess: Session) -> None:
        while sess.queue and sess.conn and len(sess.inflight) < self.max_inflight:
            self._deliver(sess, sess.queue.popleft())

    async def _retry_loop(self) -> None:
        """QoS 1 未收到 PUBACK 时按指数退避重发，DUP=1。"""
        while True:
            await asyncio.sleep(min(1.0, self.retry_interval))
            now = time.monotonic()
            for sess in list(self.sessions.values()):
                if sess.conn is None:
                    if (
                        not sess.clean
                        and sess.disconnected_at
                        and time.time() - sess.disconnected_at > self.session_expiry
                    ):
                        self._drop_session(sess)
                    continue
                for inf in sess.inflight.values():
                    backoff = self.retry_interval * (2 ** min(inf.attempts - 1, 5))
                    if now - inf.sent_at >= backoff:
                        inf.msg.dup = True
                        inf.sent_at = now
                        inf.attempts += 1
                        self.stats.qos1_retries += 1
                        sess.conn.send(inf.msg.encode())

    # -- 持久化：持久会话与保留消息在重启后保留 --------------------------------

    def save(self) -> None:
        if not self.persist_path:
            return
        data = {
            "retained": [
                {"t": m.topic, "p": m.payload.hex(), "q": m.qos} for m in self.retained.values()
            ],
            "sessions": [
                {
                    "id": s.client_id,
                    "principal": s.principal,
                    "subs": s.subscriptions,
                    "queue": [
                        {"t": m.topic, "p": m.payload.hex(), "q": m.qos}
                        for m in [i.msg for i in s.inflight.values()] + list(s.queue)
                    ],
                }
                for s in self.sessions.values()
                if not s.clean
            ],
        }
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.persist_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self.persist_path)

    def _load(self) -> None:
        if not self.persist_path or not self.persist_path.exists():
            return
        with contextlib.suppress(Exception):
            data = json.loads(self.persist_path.read_text())
            for r in data.get("retained", []):
                self.retained[r["t"]] = Publish(
                    r["t"], bytes.fromhex(r["p"]), qos=r["q"], retain=True
                )
            for s in data.get("sessions", []):
                sess = Session(
                    client_id=s["id"],
                    principal=s["principal"],
                    clean=False,
                    subscriptions=s["subs"],
                )
                sess.disconnected_at = time.time()
                for m in s["queue"]:
                    sess.queue.append(Publish(m["t"], bytes.fromhex(m["p"]), qos=m["q"]))
                for filt, q in sess.subscriptions.items():
                    self.tree.add(filt, sess.client_id, q)
                self.sessions[sess.client_id] = sess
