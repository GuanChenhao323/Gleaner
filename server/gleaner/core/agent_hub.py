"""本地采集代理的云端入口（P2）。

只能在校园网内访问的来源（``via_agent = 1``）由用户电脑上的代理采集后上传。代理经网关
``/agent`` 建立 WebSocket 长连接：

    → {"type": "hello", "token": "…", "agent_id": "laptop-1", "version": "0.1"}
    ← {"type": "welcome", "sources": [...], "server_time": …}
    ← {"type": "fetch", "source_id": 12}                 用户在界面上点了“立即检查”
    → {"type": "result", "source_id": 12, "status": "ok", "items": [...], …}
    ← {"type": "ack", "source_id": 12, "counts": {...}}
    ↔ {"type": "ping"} / {"type": "pong"}                 应用层心跳（另有 WebSocket ping）
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .. import security
from ..net.http import Request
from ..net.websocket import CloseCode, ConnectionClosed, Opcode, WebSocket
from ..obs.metrics import REGISTRY
from ..storage.db import Database, loads
from .pipeline import Pipeline

log = logging.getLogger(__name__)

AGENTS = REGISTRY.gauge("gleaner_agents_connected", "在线的本地采集代理")


class AgentHub:
    def __init__(self, db: Database, pipeline: Pipeline) -> None:
        self.db = db
        self.pipeline = pipeline
        self.agents: dict[int, dict[str, WebSocket]] = {}

    async def sources_for(self, uid: int) -> list[dict[str, Any]]:
        rows = await self.db.fetch(
            "SELECT id, type, name, endpoint, config, course, interval_s FROM sources WHERE owner_id = ? AND via_agent = 1",
            uid,
        )
        return [{**r, "config": loads(r["config"], {})} for r in rows]

    async def request_fetch(self, uid: int, source_id: int) -> bool:
        sent = False
        for ws in list(self.agents.get(uid, {}).values()):
            try:
                await ws.send(json.dumps({"type": "fetch", "source_id": source_id}))
                sent = True
            except ConnectionClosed:
                continue
        return sent

    async def on_websocket(self, ws: WebSocket, req: Request) -> None:
        ws.start_heartbeat(20, 60)
        try:
            hello = json.loads((await ws.recv()).text)
        except (ValueError, ConnectionClosed):
            return
        claims = security.verify_token(str(hello.get("token", "")))
        if not claims or hello.get("type") != "hello":
            await ws.close(4401, "unauthorized")
            return
        uid = int(claims["uid"])
        agent_id = str(hello.get("agent_id") or "agent")[:40]
        self.agents.setdefault(uid, {})[agent_id] = ws
        AGENTS.set(sum(len(v) for v in self.agents.values()))
        log.info("agent %s connected for user %s", agent_id, uid)
        try:
            await ws.send(
                json.dumps(
                    {
                        "type": "welcome",
                        "sources": await self.sources_for(uid),
                        "server_time": time.time(),
                    },
                    ensure_ascii=False,
                )
            )
            async for msg in ws:
                if msg.opcode != Opcode.TEXT:
                    continue
                m = json.loads(msg.text)
                if m.get("type") == "ping":
                    await ws.send(json.dumps({"type": "pong", "t": m.get("t")}))
                elif m.get("type") == "result":
                    counts = await self._on_result(uid, m)
                    await ws.send(
                        json.dumps(
                            {"type": "ack", "source_id": m.get("source_id"), "counts": counts}
                        )
                    )
                elif m.get("type") == "list":
                    await ws.send(
                        json.dumps(
                            {"type": "sources", "sources": await self.sources_for(uid)},
                            ensure_ascii=False,
                        )
                    )
        except (ConnectionClosed, ValueError):
            pass
        finally:
            if self.agents.get(uid, {}).get(agent_id) is ws:
                del self.agents[uid][agent_id]
            AGENTS.set(sum(len(v) for v in self.agents.values()))
            if not ws.closed:
                await ws.close(CloseCode.GOING_AWAY)

    async def _on_result(self, uid: int, m: dict[str, Any]) -> dict[str, int]:
        sid = int(m.get("source_id", 0))
        src = await self.db.fetchone(
            "SELECT * FROM sources WHERE id = ? AND owner_id = ? AND via_agent = 1", sid, uid
        )
        if not src:
            return {}
        now = time.time()
        status = {
            "ok": "ok",
            "not_modified": "ok",
            "failed": "failed",
            "need_login": "need_login",
        }.get(m.get("status", ""), "failed")
        failed = status != "ok"
        await self.db.execute(
            """UPDATE sources SET status = ?, last_checked_at = ?, last_success_at = CASE WHEN ? = 1 THEN ? ELSE last_success_at END,
               last_error = ?, fail_count = CASE WHEN ? = 1 THEN fail_count + 1 ELSE 0 END WHERE id = ?""",
            status,
            now,
            int(not failed),
            now,
            m.get("error") or None,
            int(failed),
            sid,
        )
        msg = {**m, "prev_status": src["status"], "checked_at": now}
        return await self.pipeline.ingest(msg)
