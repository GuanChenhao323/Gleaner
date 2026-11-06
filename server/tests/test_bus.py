import asyncio
import random
import struct
import zlib

import pytest

from gleaner.net.bus import (
    BusClient,
    BusFrame,
    BusHub,
    BusProtocolError,
    Flags,
    FrameDecoder,
    FrameType,
    topic_matches,
)


def test_frame_roundtrip_and_layout():
    f = BusFrame(FrameType.PUBLISH, 42, {"topic": "a", "data": [1, "二"]}, Flags.NEED_ACK)
    raw = f.encode()
    magic, ver, typ, flags, seq, length = struct.unpack_from("!HBBBII", raw)
    assert (magic, ver, typ, flags, seq) == (0x474C, 1, 1, 2, 42)
    assert len(raw) == 13 + length + 4
    [g] = FrameDecoder().feed(raw)
    assert g.payload == f.payload and g.seq == 42


def test_compression_flag():
    f = BusFrame(FrameType.PUBLISH, 1, {"x": "a" * 10000})
    raw = f.encode()
    assert raw[4] & Flags.COMPRESSED
    assert FrameDecoder().feed(raw)[0].payload == {"x": "a" * 10000}


def test_split_arrival_fuzz():
    frames = [
        BusFrame(FrameType.PUBLISH, i, {"i": i, "pad": "x" * random.randint(0, 6000)})
        for i in range(50)
    ]
    data = b"".join(f.encode() for f in frames)
    dec = FrameDecoder()
    out = []
    pos = 0
    rnd = random.Random(1)
    while pos < len(data):
        n = rnd.randint(1, 300)
        out += dec.feed(data[pos : pos + n])
        pos += n
    assert [f.payload["i"] for f in out] == list(range(50))


def test_corruption_detected():
    raw = bytearray(BusFrame(FrameType.PUBLISH, 1, {"a": 1}).encode())
    raw[15] ^= 0xFF
    with pytest.raises(BusProtocolError, match="crc"):
        FrameDecoder().feed(bytes(raw))
    with pytest.raises(BusProtocolError, match="magic"):
        FrameDecoder().feed(b"XX" + bytes(raw[2:]))
    bad_len = bytearray(BusFrame(FrameType.ACK, 1).encode())
    struct.pack_into("!I", bad_len, 9, 1 << 30)
    with pytest.raises(BusProtocolError):
        FrameDecoder().feed(bytes(bad_len))


def test_random_truncation_never_crashes():
    raw = BusFrame(FrameType.PUBLISH, 7, {"k": "v"}).encode()
    for cut in range(len(raw)):
        assert FrameDecoder().feed(raw[:cut]) == []


def test_topic_patterns():
    assert topic_matches("*", "x") and topic_matches("a.*", "a.b") and topic_matches("a.*", "a")
    assert (
        not topic_matches("a.*", "ab.c")
        and topic_matches("a.b", "a.b")
        and not topic_matches("a.b", "a.c")
    )


async def test_pubsub_ack_membership_and_reconnect():
    hub = BusHub(ack_timeout=0.2, heartbeat_timeout=1.0)
    port = await hub.start("127.0.0.1", 0)
    got = []
    hub_got = []
    hub.subscribe("extract.*", lambda t, d, s: hub_got.append((t, d, s)))
    sub = BusClient(
        "push-1",
        "push",
        "127.0.0.1",
        port,
        ack_timeout=0.2,
        heartbeat_interval=0.2,
        heartbeat_timeout=1.0,
    )
    sub.subscribe("u.*", lambda t, d, s: got.append(d))
    pub = BusClient(
        "col-1",
        "collector",
        "127.0.0.1",
        port,
        ack_timeout=0.2,
        heartbeat_interval=0.2,
        heartbeat_timeout=1.0,
    )
    memberships = []
    pub.subscribe("$nodes", lambda t, d, s: memberships.append(d))
    sub.start()
    pub.start()
    await sub.wait_connected()
    await pub.wait_connected()
    await asyncio.sleep(0.1)
    await pub.publish("extract.moodle", {"n": 1}, wait=True)
    await hub.publish("u.7", {"seq": 1})
    for _ in range(50):
        if got and hub_got:
            break
        await asyncio.sleep(0.02)
    assert hub_got == [("extract.moodle", {"n": 1}, "col-1")]
    assert got == [{"seq": 1}]
    assert hub.live_nodes("push") == ["push-1"]
    assert any("push" in m for m in memberships)

    # 强行断开订阅者 TCP；断线期间发布的消息在重连后补发且只投递一次
    hub.members["push-1"].writer.transport.abort()
    await asyncio.sleep(0.05)
    await hub.publish("u.7", {"seq": 2})
    for _ in range(100):
        if len(got) >= 2:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.5)
    assert got == [{"seq": 1}, {"seq": 2}]
    assert sub.reconnects >= 1

    await sub.close()
    for _ in range(50):
        if hub.live_nodes("push") == []:
            break
        await asyncio.sleep(0.02)
    assert hub.live_nodes("push") == []
    await pub.close()
    await hub.close()


async def test_hub_detects_dead_node_by_heartbeat():
    hub = BusHub(heartbeat_timeout=0.5)
    port = await hub.start("127.0.0.1", 0)
    _r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(BusFrame(FrameType.NODE_JOIN, 0, {"node": "silent", "role": "collector"}).encode())
    await w.drain()
    await asyncio.sleep(0.1)
    assert hub.live_nodes() == ["silent"]
    await asyncio.sleep(1.2)
    assert hub.live_nodes() == []
    w.close()
    await hub.close()


async def test_dedup_on_retransmit():
    hub = BusHub()
    port = await hub.start("127.0.0.1", 0)
    got = []
    hub.subscribe("x", lambda t, d, s: got.append(d))
    _r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(BusFrame(FrameType.NODE_JOIN, 0, {"node": "n1", "role": "r"}).encode())
    f = BusFrame(FrameType.PUBLISH, 5, {"topic": "x", "data": 1}, Flags.NEED_ACK).encode()
    w.write(f + f + f)
    await w.drain()
    await asyncio.sleep(0.2)
    assert got == [1] and hub.stats.duplicates == 2
    w.close()
    await hub.close()


def test_crc_is_over_whole_frame():
    raw = BusFrame(FrameType.HEARTBEAT, 3).encode()
    assert struct.unpack("!I", raw[-4:])[0] == zlib.crc32(raw[:-4])


def test_topic_set_exact_and_wildcard():
    from gleaner.net.bus.node import TopicSet

    ts = TopicSet(["u.1", "u.2", "extract.*"])
    assert ts.matches("u.1") and not ts.matches("u.3")
    assert ts.matches("extract.moodle") and ts.matches("extract")
    ts.discard("u.1")
    ts.add("*")
    assert ts.matches("anything") and "u.1" not in ts and len(ts) == 3


async def test_restarted_node_is_not_deduplicated_as_old_incarnation():
    """推送节点重启（同名新进程，序号从头开始）后，Hub 不能把它的新帧当成旧进程的重复帧丢掉。

    compose 实测：重启后的推送节点 SUBSCRIBE u.<uid> 被吞掉，该用户收不到任何推送。
    """
    hub = BusHub()
    port = await hub.start("127.0.0.1", 0)
    got = []
    hub.subscribe("x", lambda t, d, s: got.append(d))

    async def incarnation(epoch: str, data: int) -> None:
        _r, w = await asyncio.open_connection("127.0.0.1", port)
        join = {"node": "push-1", "role": "push", "epoch": epoch}
        w.write(BusFrame(FrameType.NODE_JOIN, 0, join).encode())
        w.write(
            BusFrame(FrameType.PUBLISH, 1, {"topic": "x", "data": data}, Flags.NEED_ACK).encode()
        )
        await w.drain()
        await asyncio.sleep(0.1)
        w.transport.abort()  # 进程被杀：不发 NODE_LEAVE
        await asyncio.sleep(0.05)

    await incarnation("old", 1)
    await incarnation("new", 2)  # 新进程，同样从 seq 1 开始
    await incarnation("new", 2)  # 同一进程断线重连后重发：仍按重复帧丢弃
    assert got == [1, 2] and hub.stats.duplicates == 1

    # 端到端：同名 BusClient 重启后动态订阅的主题能收到消息
    recv = []
    for i in range(2):
        c = BusClient("push-2", "push", "127.0.0.1", port, heartbeat_interval=0.2)
        c.start()
        await c.wait_connected()
        c.subscribe(f"u.{i}", lambda t, d, s: recv.append(d))
        await asyncio.sleep(0.1)
        await hub.publish(f"u.{i}", i)
        for _ in range(50):
            if len(recv) > i:
                break
            await asyncio.sleep(0.02)
        c._writer.transport.abort()  # type: ignore[union-attr]
        c._closing = True
        await c.close()
    assert recv == [0, 1]
    await hub.close()


async def _until(cond, timeout: float = 3.0) -> bool:
    for _ in range(int(timeout / 0.02)):
        if cond():
            return True
        await asyncio.sleep(0.02)
    return cond()


async def test_slow_handler_does_not_eject_node():
    """BUS-1：Hub 的处理器慢（入库 + 大模型几秒）时，读循环照常判活，节点不会被当成掉线。"""
    hub = BusHub(heartbeat_timeout=0.6)
    port = await hub.start("127.0.0.1", 0)
    done = []

    async def slow(t, d, s):
        await asyncio.sleep(1.5)
        done.append(d)

    hub.subscribe("extract.result", slow)
    c = BusClient("collector-1", "collector", "127.0.0.1", port, heartbeat_interval=0.1)
    c.subscribe("ping", lambda t, d, s: done.append(d))
    c.start()
    await c.wait_connected()
    await c.publish("extract.result", "a", wait=True)
    await c.publish("extract.result", "b")
    await asyncio.sleep(0.2)
    await hub.publish("ping", "p")  # 处理器忙的时候，发往节点的消息照常送达
    assert await _until(lambda: "p" in done, 1.0)
    await asyncio.sleep(1.5)
    assert hub.live_nodes() == ["collector-1"] and c.reconnects == 0
    assert await _until(lambda: done == ["p", "a", "b"], 3.0), done  # 同一节点的消息按顺序处理
    await c.close()
    await hub.close()


async def test_member_recreated_after_retention_is_not_deduplicated():
    """BUS-2：节点离线超过保留期，Hub 删掉成员记录后序号从 0 重来；客户端要清空去重表。"""
    hub = BusHub(heartbeat_timeout=0.5, retention=0.2)
    port = await hub.start("127.0.0.1", 0)
    got = []
    c = BusClient("push-1", "push", "127.0.0.1", port, heartbeat_interval=0.1)
    c.subscribe("u.1", lambda t, d, s: got.append(d))
    c.start()
    await c.wait_connected()
    await hub.publish("u.1", 1)
    assert await _until(lambda: got == [1])
    c.port = 1  # 断开并且暂时连不上
    c._writer.transport.abort()  # type: ignore[union-attr]
    assert await _until(lambda: "push-1" not in hub.members, 3.0)
    c.port = port
    assert await _until(lambda: hub.live_nodes() == ["push-1"], 15.0)
    await c.wait_connected()
    await hub.publish("u.1", 2)  # 新成员记录的 seq 又是 1
    assert await _until(lambda: got == [1, 2]), got
    await c.close()
    await hub.close()


async def test_join_requires_hmac_and_rejects_replay():
    """BUS-6：设置密钥后，没有正确 HMAC 的节点接不进来；抓到的 NODE_JOIN 不能重放。"""
    hub = BusHub(secret=b"k" * 32)
    port = await hub.start("127.0.0.1", 0)
    bad = BusClient("evil", "push", "127.0.0.1", port, secret=b"x" * 32)
    bad.start()
    good = BusClient("push-1", "push", "127.0.0.1", port, secret=b"k" * 32)
    good.start()
    await good.wait_connected()
    await asyncio.sleep(0.3)
    assert hub.live_nodes() == ["push-1"] and not bad.connected.is_set()
    assert hub.stats.auth_failures >= 1
    # 不带密钥的原始帧
    _r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(BusFrame(FrameType.NODE_JOIN, 0, {"node": "raw", "role": "push"}).encode())
    await w.drain()
    # 重放 good 的 NODE_JOIN（同一个 nonce）
    _r2, w2 = await asyncio.open_connection("127.0.0.1", port)
    join = good._join_payload()
    w2.write(BusFrame(FrameType.NODE_JOIN, 0, join).encode())
    w3 = (await asyncio.open_connection("127.0.0.1", port))[1]
    await w2.drain()
    await asyncio.sleep(0.1)
    w3.write(BusFrame(FrameType.NODE_JOIN, 0, join).encode())
    await w3.drain()
    await asyncio.sleep(0.2)
    assert "raw" not in hub.members and hub.stats.auth_failures >= 3
    # 客户端也验证 Hub：密钥不对的 Hub 收不到确认
    fake = BusHub(secret=b"y" * 32)
    fport = await fake.start("127.0.0.1", 0)
    victim = BusClient("push-2", "push", "127.0.0.1", fport, secret=b"k" * 32)
    victim.start()
    await asyncio.sleep(0.3)
    assert not victim.connected.is_set()
    for x in (w, w2, w3):
        x.close()
    for cl in (bad, good, victim):
        await cl.close()
    await hub.close()
    await fake.close()


async def test_oversized_payload_is_rejected_without_breaking_the_link():
    """BUS-5：超过 16 MiB 的负载在发送端就报错，不进发件箱，心跳与后续消息不受影响。"""
    hub = BusHub(ack_timeout=0.2)
    port = await hub.start("127.0.0.1", 0)
    got = []
    hub.subscribe("x", lambda t, d, s: got.append(d))
    c = BusClient("n", "r", "127.0.0.1", port, heartbeat_interval=0.1, ack_timeout=0.2)
    c.subscribe("y", lambda t, d, s: got.append(d))
    c.start()
    await c.wait_connected()
    big = random.randbytes(17 * 1024 * 1024)  # 不可压缩
    with pytest.raises(BusProtocolError):
        await c.publish("x", big)
    assert not c._outbox
    assert await hub.publish("y", big) == 0 and hub.stats.encode_errors == 1
    await c.publish("x", "small", wait=True)
    await hub.publish("y", "back")
    assert await _until(lambda: got == ["small", "back"]), got
    await asyncio.sleep(0.5)
    assert c.reconnects == 0
    await c.close()
    await hub.close()


def test_decompression_bomb_rejected():
    """BUS-10：解压后的大小同样受 16 MiB 限制。"""
    import msgpack

    body = zlib.compress(msgpack.packb(b"\0" * (20 * 1024 * 1024)), 9)
    head = struct.pack(
        "!HBBBII", 0x474C, 1, int(FrameType.PUBLISH), int(Flags.COMPRESSED), 1, len(body)
    )
    raw = head + body
    raw += struct.pack("!I", zlib.crc32(raw))
    with pytest.raises(BusProtocolError, match="too large"):
        FrameDecoder().feed(raw)


async def test_outboxes_are_bounded():
    """BUS-4：客户端发件箱满了 publish 等待；Hub 给离线节点缓存的帧有上限。"""
    c = BusClient("n", "r", "127.0.0.1", 1, outbox_max=3)
    for i in range(3):
        await c.publish("x", i)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(c.publish("x", 3), 0.3)
    assert len(c._outbox) == 3
    c._acked(1)  # 收到确认就有空间
    await asyncio.wait_for(c.publish("x", 4), 0.3)

    hub = BusHub(outbox_max=3)
    from gleaner.net.bus.node import Member, TopicSet

    m = Member("p", "push", {}, None, topics=TopicSet(["u.1"]))
    m.alive, m.dead_since = False, __import__("time").monotonic()
    hub.members["p"] = m
    for i in range(5):
        await hub.publish("u.1", i)
    assert len(m.outbox) == 3 and hub.stats.dropped == 2
    assert [p.frame.payload["data"] for p in m.outbox.values()] == [2, 3, 4]


async def test_reconnect_does_not_resurrect_unsubscribed_topic():
    """BUS-12：断线期间未确认的 SUBSCRIBE / UNSUBSCRIBE 不重发，以 NODE_JOIN 里的当前订阅为准。"""
    hub = BusHub()
    port = await hub.start("127.0.0.1", 0)
    c = BusClient("push-1", "push", "127.0.0.1", port)
    c.subscribe("keep", lambda *a: None)
    # 模拟：断线前发出、还没确认的 SUBSCRIBE a，随后又取消了 a
    c._send_reliable(FrameType.SUBSCRIBE, {"topics": ["a"]})
    c.subscribe("a", lambda *a: None)
    c.unsubscribe("a")
    c.start()
    await c.wait_connected()
    await asyncio.sleep(0.3)
    topics = hub.members["push-1"].topics
    assert "keep" in topics and "a" not in topics and not c._outbox
    await c.close()
    await hub.close()
