import asyncio
import os
import struct

import pytest
import requests
import websockets

from gleaner.net.http import Response
from gleaner.net.reactor import Reactor
from gleaner.net.websocket import CloseCode, Opcode, encode_frame
from gleaner.net.websocket.reactor_server import ReactorWSServer

SELECTORS = ["select", "auto"]  # auto：Linux 上为 epoll


async def echo_server(kind, **kw):
    async def on_open(peer, req):
        while True:
            text = await peer.inbox.get()
            if text is None:
                return
            if text == "close":
                peer.close(CloseCode.NORMAL, "bye")
            else:
                peer.send_text(text)

    def http(req):
        return Response.json_body({"status": "ok", "path": req.path})

    srv = ReactorWSServer("127.0.0.1", 0, on_open=on_open, http_handler=http, selector=kind, **kw)
    await srv.start()
    return srv


def test_reactor_timers_and_threadsafe_calls():
    r = Reactor("select")
    order = []
    r.call_later(0.05, lambda: order.append("timer"))
    r.call_soon_threadsafe(lambda: order.append("soon"))
    r.call_later(0.1, lambda: setattr(r, "_running", False))  # 在反应器线程内结束循环
    r.run()
    assert order == ["soon", "timer"]


@pytest.mark.parametrize("kind", SELECTORS)
async def test_interop_with_websockets_library(kind):
    srv = await echo_server(kind)
    async with websockets.connect(f"ws://127.0.0.1:{srv.port}/ws", max_size=None) as c:
        await c.send("你好")
        assert await c.recv() == "你好"
        big = "x" * 200_000  # 64 位长度，且发送端需要多次 send 才能写完
        await c.send(big)
        assert await c.recv() == big
        await c.send(iter(["a", "b", "c"]))  # 分片消息
        assert await c.recv() == "abc"
        pong = await c.ping(b"p")
        await asyncio.wait_for(pong, 2)
        await c.send("close")
        with pytest.raises(websockets.ConnectionClosedOK):
            await c.recv()
        assert c.close_code == 1000
    await srv.close()


@pytest.mark.parametrize("kind", SELECTORS)
async def test_split_handshake_and_frames_byte_by_byte(kind):
    srv = await echo_server(kind)
    r, w = await asyncio.open_connection("127.0.0.1", srv.port)
    hs = (
        b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    frame = encode_frame(Opcode.TEXT, "拆包".encode(), mask=True)
    for b in hs + frame:  # 握手与帧逐字节到达
        w.write(bytes([b]))
        await w.drain()
    head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 2)
    assert b"101" in head and b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in head
    data = await asyncio.wait_for(r.readexactly(2 + len("拆包".encode())), 2)
    assert data[2:].decode() == "拆包"
    # 未掩码的客户端帧：协议错误，服务端回 1002 并断开
    w.write(encode_frame(Opcode.TEXT, b"bad", mask=False))
    await w.drain()
    close = await asyncio.wait_for(r.read(64), 2)
    assert close[0] == 0x88 and struct.unpack("!H", close[2:4])[0] == 1002
    w.close()
    await srv.close()


@pytest.mark.parametrize("kind", SELECTORS)
async def test_http_health_and_bad_request(kind):
    srv = await echo_server(kind)
    r = await asyncio.to_thread(requests.get, f"http://127.0.0.1:{srv.port}/health", timeout=3)
    assert r.json() == {"status": "ok", "path": "/health"}
    rd, w = await asyncio.open_connection("127.0.0.1", srv.port)
    w.write(b"NOT HTTP\r\n\r\n")
    await w.drain()
    assert b"400" in await asyncio.wait_for(rd.read(), 2)
    await srv.close()


async def test_heartbeat_and_handshake_timeout():
    srv = await echo_server("select", heartbeat=(0.2, 1.0), handshake_timeout=1.0)
    # 握手迟迟不完成：超时关闭
    r1, w1 = await asyncio.open_connection("127.0.0.1", srv.port)
    w1.write(b"GET /ws HTTP/1.1\r\n")
    await w1.drain()
    assert await asyncio.wait_for(r1.read(), 4) == b""
    # 握手成功但从不回 pong：先收到 ping，1 秒无数据后被断开
    r, w = await asyncio.open_connection("127.0.0.1", srv.port)
    w.write(
        b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        b"Sec-WebSocket-Key: "
        + os.urandom(16).hex()[:22].encode()
        + b"==\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    await w.drain()
    data = await asyncio.wait_for(r.read(), 5)
    assert b"101" in data and bytes([0x89]) in data  # 收到过 ping，然后连接关闭
    await srv.close()


async def test_many_connections():
    srv = await echo_server("auto")
    clients = [await websockets.connect(f"ws://127.0.0.1:{srv.port}/ws") for _ in range(200)]
    await asyncio.gather(*(c.send(f"m{i}") for i, c in enumerate(clients)))
    got = await asyncio.gather(*(c.recv() for c in clients))
    assert got == [f"m{i}" for i in range(200)]
    assert srv.accepted == 200
    for c in clients:
        await c.close()
    await srv.close()
