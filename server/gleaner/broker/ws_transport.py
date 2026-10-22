"""MQTT over WebSocket：把 WebSocket 二进制帧适配成 Broker 使用的 StreamReader / Writer。

浏览器无法直接建立 TCP 连接，Flutter Web 版经网关 ``/mqtt``（子协议 ``mqtt``）连到这里。
每个 WebSocket 二进制消息可以包含任意数量的 MQTT 报文片段，粘包拆包仍由 PacketReader 处理。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from ..net.http import Request
from ..net.websocket import ConnectionClosed, WebSocket
from .broker import Broker


class _WSWriter:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self._closing = False
        self._loop = asyncio.get_running_loop()

    def write(self, data: bytes) -> None:
        if self._closing:
            return
        # 立即排队发送：Broker 在路由消息时只调用 write，不一定随后 drain
        self._loop.create_task(self._send(bytes(data)))

    async def _send(self, data: bytes) -> None:
        with contextlib.suppress(ConnectionClosed, ConnectionError, OSError):
            await self.ws.send(data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def is_closing(self) -> bool:
        return self._closing or self.ws.closed

    def close(self) -> None:
        if not self._closing:
            self._closing = True
            self._loop.create_task(self.ws.close())

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return self.ws.writer.get_extra_info(name, default)

    async def wait_closed(self) -> None:
        return None


def mqtt_ws_handler(broker: Broker):  # noqa: ANN201
    async def on_ws(ws: WebSocket, req: Request) -> None:
        reader = asyncio.StreamReader()
        writer = _WSWriter(ws)

        async def pump() -> None:
            try:
                async for msg in ws:
                    reader.feed_data(msg.data)
            finally:
                reader.feed_eof()

        t = asyncio.get_running_loop().create_task(pump())
        try:
            await broker._on_conn(reader, writer)  # type: ignore[arg-type]
        finally:
            t.cancel()

    return on_ws
