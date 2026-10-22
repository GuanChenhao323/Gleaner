import asyncio
import os
import struct

import pytest
import websockets

from gleaner.net.http import HTTPServer, Router, ServerConfig
from gleaner.net.websocket import (
    CloseCode,
    Closed,
    ConnectionClosed,
    Opcode,
    WSConnection,
    accept_key,
    connect,
    encode_frame,
    mask_bytes,
    websocket_route,
)


def test_accept_key_rfc_example():
    # RFC 6455 §1.3 的示例
    assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_mask_roundtrip():
    key = os.urandom(4)
    data = os.urandom(1001)
    assert mask_bytes(mask_bytes(data, key), key) == data


@pytest.mark.parametrize("n", [0, 125, 126, 65535, 65536, 200000])
def test_length_encodings_roundtrip(n):
    client = WSConnection(is_client=True)
    server = WSConnection(is_client=False)
    payload = os.urandom(n)
    events, _ = server.receive_data(client.send_binary(payload))
    assert events[0].data == payload


def test_fragmented_and_byte_by_byte_with_interleaved_ping():
    client = WSConnection(is_client=True)
    server = WSConnection()
    data = client.send_fragmented(Opcode.TEXT, "你好世界".encode(), 4)
    # 在第一个分片后插入一个 ping（控制帧允许夹在分片中间，§5.4）
    first_len = 2 + 4 + 4
    data = data[:first_len] + client.send_ping(b"p") + data[first_len:]
    events, replies = [], b""
    for i in range(len(data)):
        ev, r = server.receive_data(data[i : i + 1])
        events += ev
        replies += r
    kinds = [e.opcode for e in events]
    assert kinds == [Opcode.PING, Opcode.TEXT]
    assert events[1].text == "你好世界"
    # 服务端自动回复了 pong（不掩码）
    assert replies[0] == 0x80 | Opcode.PONG


@pytest.mark.parametrize(
    "frame,code",
    [
        (encode_frame(Opcode.TEXT, b"x", mask=False), CloseCode.PROTOCOL_ERROR),  # 客户端未掩码
        (encode_frame(Opcode.TEXT, b"x", mask=True, rsv=1), CloseCode.PROTOCOL_ERROR),
        (encode_frame(3, b"x", mask=True), CloseCode.PROTOCOL_ERROR),
        (encode_frame(Opcode.PING, b"x" * 126, mask=True), CloseCode.PROTOCOL_ERROR),
        (encode_frame(Opcode.PING, b"x", fin=False, mask=True), CloseCode.PROTOCOL_ERROR),
        (encode_frame(Opcode.CONT, b"x", mask=True), CloseCode.PROTOCOL_ERROR),
        (encode_frame(Opcode.TEXT, b"\xff\xfe", mask=True), CloseCode.INVALID_DATA),
        (encode_frame(Opcode.CLOSE, b"\x03", mask=True), CloseCode.PROTOCOL_ERROR),
        (encode_frame(Opcode.CLOSE, struct.pack("!H", 999), mask=True), CloseCode.PROTOCOL_ERROR),
    ],
)
def test_protocol_violations_close(frame, code):
    server = WSConnection()
    events, reply = server.receive_data(frame)
    assert isinstance(events[-1], Closed) and events[-1].code == code
    assert reply[0] == 0x80 | Opcode.CLOSE
    assert struct.unpack("!H", reply[2:4])[0] == code


def test_close_handshake_echo():
    client = WSConnection(is_client=True)
    server = WSConnection()
    events, reply = server.receive_data(client.send_close(1000, "bye"))
    assert events[0].code == 1000 and events[0].reason == "bye"
    ev2, _ = client.receive_data(reply)
    assert ev2[0].code == 1000


def test_too_big():
    server = WSConnection(max_message=10)
    events, _ = server.receive_data(encode_frame(Opcode.BINARY, b"x" * 11, mask=True))
    assert events[-1].code == CloseCode.TOO_BIG


async def _echo_server(**kw):
    async def on_ws(ws, req):
        async for msg in ws:
            await ws.send(msg.text if msg.opcode == Opcode.TEXT else msg.data)

    router = Router()
    router.add("GET", "/ws", websocket_route(on_ws, **kw))
    srv = HTTPServer(router, ServerConfig(host="127.0.0.1", port=0))
    await srv.start()
    return srv


async def test_self_client_against_self_server():
    srv = await _echo_server()
    ws = await connect(f"ws://127.0.0.1:{srv.port}/ws")
    await ws.send("hello")
    assert (await ws.recv()).text == "hello"
    await ws.send(b"\x00" * 70000)
    assert len((await ws.recv()).data) == 70000
    await ws.close()
    assert ws.conn.close_code == 1000
    await srv.close()


async def test_interop_with_websockets_library():
    srv = await _echo_server()
    async with websockets.connect(f"ws://127.0.0.1:{srv.port}/ws", max_size=None) as c:
        await c.send("互通测试")
        assert await c.recv() == "互通测试"
        await c.send(os.urandom(100000))
        assert len(await c.recv()) == 100000
        pong = await c.ping(b"abc")
        await asyncio.wait_for(pong, 2)
        # 分片消息
        await c.send(iter(["a", "b", "c"]))
        assert await c.recv() == "abc"
    await srv.close()


async def test_self_client_against_websockets_server():
    async def echo(c):
        async for m in c:
            await c.send(m)

    async with websockets.serve(echo, "127.0.0.1", 0) as s:
        port = s.sockets[0].getsockname()[1]
        ws = await connect(f"ws://127.0.0.1:{port}/")
        await ws.send("x" * 300)
        assert (await ws.recv()).text == "x" * 300
        await ws.close()


async def test_bad_handshake_rejected():
    srv = await _echo_server()
    r, w = await asyncio.open_connection("127.0.0.1", srv.port)
    w.write(b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
    await w.drain()
    data = await asyncio.wait_for(r.read(4096), 2)
    assert data.startswith(b"HTTP/1.1 400")
    w.close()
    await srv.close()


async def test_heartbeat_detects_dead_peer():
    done = asyncio.Event()

    async def on_ws(ws, req):
        try:
            await ws.recv()
        except ConnectionClosed:
            pass
        done.set()

    router = Router()
    router.add("GET", "/ws", websocket_route(on_ws, heartbeat=(0.05, 0.2)))
    srv = HTTPServer(router, ServerConfig(host="127.0.0.1", port=0))
    await srv.start()
    ws = await connect(f"ws://127.0.0.1:{srv.port}/ws")
    # 客户端不再读取，因此不会回 pong；服务端应在超时后断开
    await asyncio.wait_for(done.wait(), 3)
    ws.writer.close()
    await srv.close()
