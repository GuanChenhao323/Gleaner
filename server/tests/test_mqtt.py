import asyncio
import threading

import paho.mqtt.client as paho
import pytest

from gleaner.broker.broker import Broker
from gleaner.net.mqtt import (
    Connect,
    MQTTProtocolError,
    PacketId,
    PacketReader,
    PacketType,
    Publish,
    Simple,
    Subscribe,
    SubscriptionTree,
    decode_remaining_length,
    encode_remaining_length,
    matches,
    valid_filter,
)


@pytest.mark.parametrize("n", [0, 127, 128, 16383, 16384, 2097151, 2097152, 268435455])
def test_remaining_length(n):
    enc = encode_remaining_length(n)
    assert decode_remaining_length(b"\x30" + enc) == (n, len(enc))


def test_remaining_length_malformed():
    with pytest.raises(MQTTProtocolError):
        decode_remaining_length(b"\x30\xff\xff\xff\xff\x01")


@pytest.mark.parametrize(
    "f,t,ok",
    [
        ("sport/#", "sport", True),
        ("sport/#", "sport/tennis/player1", True),
        ("sport/+", "sport", False),
        ("sport/+", "sport/", True),
        ("+/+", "/finance", True),
        ("/+", "/finance", True),
        ("+", "/finance", False),
        ("a/+/b", "a//b", True),
        ("#", "$SYS/x", False),
        ("+/x", "$SYS/x", False),
        ("$SYS/#", "$SYS/x", True),
        ("gleaner/u/7/#", "gleaner/u/7/urgent", True),
        ("gleaner/u/7/#", "gleaner/u/70/urgent", False),
    ],
)
def test_topic_matching(f, t, ok):
    assert matches(f, t) is ok
    tree = SubscriptionTree()
    tree.add(f, "c", 1)
    assert ("c" in tree.match(t)) is ok


def test_filter_validation():
    assert valid_filter("a/#") and valid_filter("+/b/+") and valid_filter("#")
    assert (
        not valid_filter("a/#/b")
        and not valid_filter("a+")
        and not valid_filter("a/b#")
        and not valid_filter("")
    )


def test_packet_roundtrip_split_arrival():
    pkts = [
        Connect(
            "c1",
            clean_session=False,
            keepalive=30,
            username="u",
            password=b"p",
            will_topic="w",
            will_message=b"bye",
        ),
        Publish("a/b", b"x" * 300, qos=1, packet_id=7, retain=True),
        Subscribe(9, [("a/#", 1), ("b/+", 0)]),
        PacketId(PacketType.PUBACK, 7),
        Simple(PacketType.PINGREQ),
    ]
    data = b"".join(p.encode() for p in pkts)
    r = PacketReader()
    out = []
    for i in range(len(data)):
        out += r.feed(data[i : i + 1])
    assert out == pkts


@pytest.mark.parametrize(
    "raw",
    [
        b"\x30\x05\x00\x03a/#x",  # 发布主题含通配符
        b"\x36\x05\x00\x01a\x00\x01",  # QoS 3
        b"\x82\x02\x00\x01",  # SUBSCRIBE 没有主题
        b"\x80\x02\x00\x01",  # SUBSCRIBE 标志位错误
        b"\x10\x0c\x00\x04MQTT\x04\x01\x00\x3c\x00\x00",  # CONNECT 保留标志位
        b"\xf0\x00",  # 保留报文类型
    ],
)
def test_malformed_packets(raw):
    with pytest.raises(MQTTProtocolError):
        PacketReader().feed(raw)


# ---- 与 paho-mqtt 互通 -------------------------------------------------------


class PahoThread:
    def __init__(self, port, client_id, clean=True, user=None, pw=None):
        self.msgs = []
        self.event = threading.Event()
        self.connected = threading.Event()
        self.rc = None
        self.c = paho.Client(
            paho.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=clean
        )
        if user:
            self.c.username_pw_set(user, pw)
        self.c.on_message = self._on_msg
        self.c.on_connect = self._on_connect
        self.c.connect("127.0.0.1", port, keepalive=30)
        self.c.loop_start()

    def _on_connect(self, c, userdata, flags, rc, props=None):
        self.rc = rc
        self.session_present = flags.session_present
        self.connected.set()

    def _on_msg(self, c, userdata, msg):
        self.msgs.append((msg.topic, msg.payload, msg.qos, msg.retain))
        self.event.set()

    def stop(self):
        self.c.disconnect()
        self.c.loop_stop()


async def wait_for(cond, timeout=3.0):
    for _ in range(int(timeout / 0.02)):
        if cond():
            return True
        await asyncio.sleep(0.02)
    return False


async def test_paho_pubsub_qos_retained_and_acl():
    def auth(cid, user, pw):
        return user if pw == b"secret" else None

    def acl(principal, topic, action):
        return topic.startswith(f"gleaner/u/{principal}/") or principal == "admin"

    b = Broker(authenticate=auth, acl=acl)
    port = await b.start("127.0.0.1", 0)
    b.publish("gleaner/u/7/digest", b"daily", qos=1, retain=True)

    sub = await asyncio.to_thread(PahoThread, port, "sub7", True, "7", "secret")
    assert await wait_for(sub.connected.is_set)
    sub.c.subscribe([("gleaner/u/7/#", 1), ("gleaner/u/8/#", 1)])
    assert await wait_for(lambda: len(sub.msgs) >= 1)
    assert sub.msgs[0] == ("gleaner/u/7/digest", b"daily", 1, True)

    pub = await asyncio.to_thread(PahoThread, port, "admin1", True, "admin", "secret")
    assert await wait_for(pub.connected.is_set)
    pub.c.publish("gleaner/u/7/urgent", b"due soon", qos=1)
    pub.c.publish("gleaner/u/8/urgent", b"not for 7", qos=1)
    pub.c.publish("gleaner/u/7/normal", b"q0", qos=0)
    assert await wait_for(lambda: len(sub.msgs) >= 3)
    topics = [m[0] for m in sub.msgs]
    assert "gleaner/u/8/urgent" not in topics
    assert ("gleaner/u/7/urgent", b"due soon", 1, False) in sub.msgs

    bad = await asyncio.to_thread(PahoThread, port, "bad", True, "7", "wrong")
    assert await wait_for(bad.connected.is_set)
    assert bad.rc != 0
    for c in (sub, pub, bad):
        await asyncio.to_thread(c.stop)
    await b.close()


async def test_persistent_session_offline_queue():
    b = Broker()
    port = await b.start("127.0.0.1", 0)
    s = await asyncio.to_thread(PahoThread, port, "phone", False, "u", "p")
    assert await wait_for(s.connected.is_set)
    s.c.subscribe("gleaner/u/1/urgent", 1)
    await wait_for(lambda: "phone" in b.sessions and b.sessions["phone"].subscriptions)
    await asyncio.to_thread(s.stop)
    await wait_for(lambda: b.sessions["phone"].conn is None)
    # 设备离线期间到达的 QoS1 消息
    b.publish("gleaner/u/1/urgent", b"offline-1", qos=1)
    b.publish("gleaner/u/1/urgent", b"offline-2", qos=1)
    assert len(b.sessions["phone"].queue) == 2
    s2 = await asyncio.to_thread(PahoThread, port, "phone", False, "u", "p")
    assert await wait_for(lambda: len(s2.msgs) >= 2)
    assert s2.session_present
    assert [m[1] for m in s2.msgs] == [b"offline-1", b"offline-2"]
    await asyncio.to_thread(s2.stop)
    await b.close()


async def raw_connect(port, cid, keepalive=60, clean=True):
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(Connect(cid, clean_session=clean, keepalive=keepalive).encode())
    await w.drain()
    ack = await asyncio.wait_for(r.readexactly(4), 2)
    assert ack[0] == 0x20 and ack[3] == 0
    return r, w


async def test_qos1_retry_with_dup_and_keepalive_and_takeover():
    b = Broker(retry_interval=0.1)
    port = await b.start("127.0.0.1", 0)
    r, w = await raw_connect(port, "raw", keepalive=1)
    w.write(Subscribe(1, [("t/#", 1)]).encode())
    await w.drain()
    await asyncio.wait_for(r.readexactly(5), 2)  # SUBACK
    b.publish("t/x", b"hello", qos=1)
    reader = PacketReader()
    got = []
    async with asyncio.timeout(3):
        while len(got) < 2:
            got += reader.feed(await r.read(1024))
    assert got[0].packet_id == got[1].packet_id and got[1].dup and not got[0].dup
    w.write(PacketId(PacketType.PUBACK, got[0].packet_id).encode())
    await w.drain()
    await wait_for(lambda: not b.sessions["raw"].inflight)
    assert not b.sessions["raw"].inflight

    # 会话接管：同 ClientId 新连接踢掉旧连接
    r2, w2 = await raw_connect(port, "raw", keepalive=1)
    data = await asyncio.wait_for(r.read(), 2)
    assert data == b"" or isinstance(data, bytes)
    # keepalive=1：1.5 秒内不发任何报文即被断开
    async with asyncio.timeout(4):
        assert await r2.read() == b""
    w.close()
    w2.close()
    await b.close()


async def test_will_message_on_abnormal_disconnect(tmp_path):
    b = Broker(persist_path=str(tmp_path / "mqtt.json"))
    port = await b.start("127.0.0.1", 0)
    rs, ws = await raw_connect(port, "watcher")
    ws.write(Subscribe(1, [("status/#", 0)]).encode())
    await ws.drain()
    await rs.readexactly(5)
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(Connect("dev", will_topic="status/dev", will_message=b"offline").encode())
    await w.drain()
    await r.readexactly(4)
    w.transport.abort()
    data = await asyncio.wait_for(rs.read(100), 2)
    [pkt] = PacketReader().feed(data)
    assert pkt.topic == "status/dev" and pkt.payload == b"offline"
    ws.close()
    b.publish("keep/me", b"1", retain=True)
    await b.close()
    b2 = Broker(persist_path=str(tmp_path / "mqtt.json"))
    assert "keep/me" in b2.retained


async def test_mqtt_over_websocket_with_paho():
    from gleaner.broker.ws_transport import mqtt_ws_handler
    from gleaner.net.http import HTTPServer, Router, ServerConfig
    from gleaner.net.websocket import websocket_route

    b = Broker()
    await b.start("127.0.0.1", 0)
    r = Router()
    r.add("GET", "/mqtt", websocket_route(mqtt_ws_handler(b), subprotocols=("mqtt",)))
    srv = HTTPServer(r, ServerConfig(host="127.0.0.1", port=0))
    await srv.start()

    msgs = []
    connected = threading.Event()

    def run():
        c = paho.Client(
            paho.CallbackAPIVersion.VERSION2, client_id="browser", transport="websockets"
        )
        c.ws_set_options(path="/mqtt")
        c.on_connect = lambda cl, u, f, rc, p=None: (
            cl.subscribe("gleaner/u/1/#", 1),
            connected.set(),
        )
        c.on_message = lambda cl, u, m: msgs.append((m.topic, m.payload))
        c.connect("127.0.0.1", srv.port)
        c.loop_start()
        return c

    c = await asyncio.to_thread(run)
    assert await wait_for(connected.is_set)
    await wait_for(lambda: "browser" in b.sessions and b.sessions["browser"].subscriptions)
    b.publish("gleaner/u/1/urgent", "截止提前".encode(), qos=1)
    assert await wait_for(lambda: msgs)
    assert msgs[0] == ("gleaner/u/1/urgent", "截止提前".encode())
    await asyncio.to_thread(c.loop_stop)
    c.disconnect()
    await srv.close()
    await b.close()
