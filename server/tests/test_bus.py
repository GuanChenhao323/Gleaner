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
