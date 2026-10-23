"""Autobahn Testsuite 用的回显服务器：用自研 HTTP + WebSocket 栈回显所有消息。

python devtools/autobahn_echo.py                         # asyncio 版（网关等使用）：ws://0.0.0.0:9001
python devtools/autobahn_echo.py --impl reactor          # 手写反应器版（推送节点使用）：ws://0.0.0.0:9002
docker compose -f deploy/docker-compose.yml --profile conformance run --rm autobahn
报告：deploy/autobahn/reports/servers/index.html

反应器版只回显文本消息（推送节点只用文本帧），二进制回显类用例对它不适用。
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from gleaner.net.http import HTTPServer, Router, ServerConfig
from gleaner.net.websocket import Opcode, websocket_route
from gleaner.net.websocket.reactor_server import ReactorWSServer

# 生产默认单条消息上限 4 MB；Autobahn 9.x 用例最大发 16 MB，这里放宽到 32 MB 以测试实现本身
MAX_MESSAGE = 32 * 1024 * 1024


async def echo(ws: Any, req: Any) -> None:
    async for msg in ws:
        await ws.send(msg.text if msg.opcode == Opcode.TEXT else msg.data)


async def run_asyncio(port: int) -> None:
    r = Router()
    r.mount("/", websocket_route(echo, max_message=MAX_MESSAGE))
    srv = HTTPServer(r, ServerConfig(host="0.0.0.0", port=port))
    print(f"autobahn echo (asyncio) on ws://0.0.0.0:{port}", flush=True)
    await srv.serve_forever()


async def run_reactor(port: int) -> None:
    async def on_open(peer: Any, req: Any) -> None:
        while (text := await peer.inbox.get()) is not None:
            peer.send_text(text)

    # Autobahn 的用例连接都在根路径上；心跳放宽，避免长用例期间被服务端 ping 打断
    rs = ReactorWSServer(
        "0.0.0.0", port, on_open=on_open, path="/", heartbeat=(300, 600), max_message=MAX_MESSAGE
    )
    await rs.start()
    print(f"autobahn echo (reactor) on ws://0.0.0.0:{port}", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", choices=["asyncio", "reactor"], default="asyncio")
    ap.add_argument("--port", type=int)
    a = ap.parse_args()
    if a.impl == "asyncio":
        asyncio.run(run_asyncio(a.port or 9001))
    else:
        asyncio.run(run_reactor(a.port or 9002))
