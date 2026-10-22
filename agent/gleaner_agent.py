"""拾课本地采集代理（P2）。

运行在用户电脑上，替云端采集只能在校园网内访问的来源，然后经 WebSocket 长连接上传。
校内账号登录得到的会话只保存在本机 ``~/.gleaner-agent.json``，不会上传到云端。

    python agent/gleaner_agent.py --server http://localhost:8080 --email me@x.edu --password ...
    python agent/gleaner_agent.py --server ... --token <令牌> --login 12 student moodle123

长连接：应用层 ping 每 20 秒一次，60 秒收不到任何数据视为断线；断线后指数退避（1s → 60s，带抖动）重连。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import socket
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from gleaner.collector.connectors import CONNECTORS, Context, SourceInfo, content_hash
from gleaner.collector.fetcher import Fetcher, FetchError
from gleaner.collector.session import SourceSession, moodle_login
from gleaner.net.http import HTTPClient
from gleaner.net.websocket import ConnectionClosed, connect

log = logging.getLogger("gleaner-agent")
STATE_FILE = Path(os.environ.get("GLEANER_AGENT_STATE", Path.home() / ".gleaner-agent.json"))


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {"sessions": {}, "cache": {}, "hashes": {}}


def save_state(st: dict[str, Any]) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False), "utf-8")
    os.replace(tmp, STATE_FILE)
    if os.name != "nt":
        os.chmod(STATE_FILE, 0o600)


class Agent:
    def __init__(self, server: str, token: str, agent_id: str) -> None:
        self.server = server.rstrip("/")
        self.token = token
        self.agent_id = agent_id
        self.state = load_state()
        self.fetcher = Fetcher(min_interval=1.0)
        self.sources: dict[int, dict[str, Any]] = {}
        self.next_at: dict[int, float] = {}
        self.reconnects = 0

    def ws_url(self) -> str:
        base = self.server.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}/agent?token={self.token}"

    async def run_forever(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self._session()
                backoff = 1.0
            except (OSError, ConnectionClosed, TimeoutError, ValueError) as e:
                log.warning("disconnected: %s", e)
            self.reconnects += 1
            delay = backoff * (0.5 + random.random())
            log.info("reconnecting in %.1fs", delay)
            await asyncio.sleep(delay)
            backoff = min(backoff * 2, 60.0)

    async def _session(self) -> None:
        ws = await connect(self.ws_url(), timeout=10)
        await ws.send(
            json.dumps(
                {"type": "hello", "token": self.token, "agent_id": self.agent_id, "version": "0.1"}
            )
        )
        welcome = json.loads((await asyncio.wait_for(ws.recv(), 10)).text)
        if welcome.get("type") != "welcome":
            raise ValueError(f"unexpected {welcome}")
        self._set_sources(welcome["sources"])
        log.info("connected, %d sources via agent", len(self.sources))
        last_rx = time.monotonic()

        async def reader() -> None:
            nonlocal last_rx
            async for msg in ws:
                last_rx = time.monotonic()
                m = json.loads(msg.text)
                if m["type"] == "fetch":
                    self.next_at[int(m["source_id"])] = 0
                elif m["type"] == "sources":
                    self._set_sources(m["sources"])
                elif m["type"] == "ack":
                    log.info("source %s ingested: %s", m.get("source_id"), m.get("counts"))

        async def ticker() -> None:
            last_ping = 0.0
            while True:
                now = time.monotonic()
                if now - last_rx > 60:
                    raise TimeoutError("no data from server for 60s")
                if now - last_ping > 20:
                    await ws.send(json.dumps({"type": "ping", "t": time.time()}))
                    last_ping = now
                for sid, src in list(self.sources.items()):
                    if self.next_at.get(sid, 0) <= time.time():
                        self.next_at[sid] = time.time() + float(src.get("interval_s") or 600)
                        await ws.send(
                            json.dumps(await self.check(src), ensure_ascii=False, default=str)
                        )
                await asyncio.sleep(1)

        tasks = [asyncio.create_task(reader()), asyncio.create_task(ticker())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for t in done:
                if t.exception():
                    raise t.exception()  # type: ignore[misc]
        finally:
            for t in tasks:
                t.cancel()
            await ws.close()

    def _set_sources(self, sources: list[dict[str, Any]]) -> None:
        self.sources = {int(s["id"]): s for s in sources}

    async def check(self, src: dict[str, Any]) -> dict[str, Any]:
        sid = str(src["id"])
        info = SourceInfo(
            int(src["id"]),
            src["type"],
            src["endpoint"],
            src.get("config") or {},
            src.get("course") or "",
            cache=self.state["cache"].get(sid, {}),
        )
        sess = (
            SourceSession.from_secret(self.state["sessions"].get(sid))
            if sid in self.state["sessions"]
            else None
        )
        ctx = Context(self.fetcher, info, sess)
        try:
            res = await CONNECTORS[src["type"]](ctx)
            status = res.status
            items = res.items
            h = content_hash(items)
            if status == "ok" and h == self.state["hashes"].get(sid):
                status = "not_modified"
            self.state["hashes"][sid] = h
            out = {
                "type": "result",
                "source_id": src["id"],
                "status": status,
                "complete": res.complete,
                "items": [i.to_dict() for i in items] if status == "ok" else [],
            }
        except FetchError as e:
            out = {
                "type": "result",
                "source_id": src["id"],
                "status": "need_login" if e.kind == "need_login" else "failed",
                "error": str(e),
                "items": [],
            }
        self.state["cache"][sid] = info.cache
        if sess:
            self.state["sessions"][sid] = sess.to_secret()
        save_state(self.state)
        log.info("checked source %s: %s (%d items)", sid, out["status"], len(out["items"]))
        return out

    async def login(self, source_id: int, endpoint: str, username: str, password: str) -> None:
        sess = await moodle_login(self.fetcher, endpoint, username, password)
        self.state["sessions"][str(source_id)] = sess.to_secret()
        save_state(self.state)


async def get_token(server: str, email: str, password: str) -> str:
    async with HTTPClient() as c:
        r = await c.post(
            f"{server.rstrip('/')}/api/auth/login", json_body={"email": email, "password": password}
        )
        if r.status != 200:
            raise SystemExit(f"登录失败：{r.text()}")
        return r.json()["token"]


def main() -> None:
    ap = argparse.ArgumentParser(description="拾课本地采集代理")
    ap.add_argument("--server", default=os.environ.get("GLEANER_SERVER", "http://localhost:8080"))
    ap.add_argument("--token", default=os.environ.get("GLEANER_TOKEN"))
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--agent-id", default=socket.gethostname())
    ap.add_argument(
        "--login",
        nargs=3,
        metavar=("SOURCE_ID", "USERNAME", "PASSWORD"),
        help="在本机登录某个来源（会话只存本机）",
    )
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    async def run() -> None:
        token = a.token or await get_token(a.server, a.email, a.password)
        agent = Agent(a.server, token, a.agent_id)
        if a.login:
            async with HTTPClient() as c:
                r = await c.get(
                    f"{a.server}/api/sources", headers={"Authorization": f"Bearer {token}"}
                )
                src = next((s for s in r.json()["sources"] if s["id"] == int(a.login[0])), None)
            if not src:
                raise SystemExit("来源不存在")
            await agent.login(int(a.login[0]), src["endpoint"], a.login[1], a.login[2])
            print("已在本机保存会话")
            return
        await agent.run_forever()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
