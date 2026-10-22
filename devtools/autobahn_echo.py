"""Autobahn Testsuite 用的回显服务器：用自研 HTTP + WebSocket 栈在 9001 端口回显所有消息。

python devtools/autobahn_echo.py
docker compose -f deploy/docker-compose.yml --profile conformance run --rm autobahn
报告：deploy/autobahn/reports/servers/index.html
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from gleaner.net.http import HTTPServer, Router, ServerConfig
from gleaner.net.websocket import Opcode, websocket_route


async def echo(ws, req):
    async for msg in ws:
        await ws.send(msg.text if msg.opcode == Opcode.TEXT else msg.data)


async def main() -> None:
    r = Router()
    ws_handler = websocket_route(echo)
    r.mount("/", ws_handler)
    srv = HTTPServer(r, ServerConfig(host="0.0.0.0", port=9001))
    print("autobahn echo on ws://0.0.0.0:9001")
    await srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
