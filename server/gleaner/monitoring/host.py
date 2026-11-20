"""Opt-in local control listener for a saved source and an explicitly supplied session."""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from pathlib import Path
from uuid import UUID, uuid4

from ..core.monitors import ContractError
from ..core.protocol_reading import BoundSession
from ..core.reading_sources import ReadingSourceService
from ..net.http import HTTPServer, Request, Response, ServerConfig
from ..storage.db import loads
from .auth import AuthManager
from .backends import create_page_transport
from .models import MonitorError
from .pages import HTMLReceipt, HTMLSnapshot, PageMonitor
from .profiles import SessionInspector, page_policy
from .store import Store
from .transport import OriginPacing


class LocalPageHost:
    def __init__(
        self,
        reading: ReadingSourceService,
        directory: Path,
        port: int,
        extension_id: str,
    ) -> None:
        if not re.fullmatch("[a-p]{32}", extension_id):
            raise ValueError("invalid extension id")
        self.origin = "chrome-extension://" + extension_id
        self.reading = reading
        self.tickets: dict[str, tuple[float, int, int, str]] = {}
        directory.mkdir(parents=True, exist_ok=True)
        self.store = Store(str(directory / "page-monitor.sqlite"))
        self.pacing: dict[str, OriginPacing] = {}
        self.epoch = str(uuid4())
        self.server = HTTPServer(
            self.handle, ServerConfig(host="127.0.0.1", port=port, max_body_bytes=262144)
        )
        self.worker: asyncio.Task | None = None

    async def accept(self, snapshot: HTMLSnapshot) -> HTMLReceipt:
        return HTMLReceipt(snapshot.snapshot_id, False)

    def build(self, row: dict, proof: str, grant: dict | None = None) -> BoundSession:
        recipe = loads(row["recipe"])
        policy = page_policy("moodle", recipe["url"])
        if recipe["source"] != "moodle" or not recipe.get("resident") or not row["verified"]:
            raise MonitorError("unsupported")
        auth = AuthManager(policy)
        auth.backend_epoch = self.epoch
        auth.persist_metadata = lambda meta: self.store.put_meta("auth:" + meta["auth_id"], meta)
        ctx = (
            auth.restore(self.store.meta("auth:" + grant["auth_id"]))
            if grant
            else auth.create(row["owner_id"], row["device_id"])
        )
        transport = create_page_transport(
            policy,
            auth,
            pacing=self.pacing.setdefault(policy.origin, OriginPacing()),
            get_not_before=lambda: self.store.meta("not-before:" + policy.origin, 0),
            set_not_before=lambda value: self.store.put_meta("not-before:" + policy.origin, value),
        )
        monitor = PageMonitor(
            policy, auth, transport, SessionInspector("moodle"), self, store=self.store
        )
        if grant:
            task = monitor.restore(
                grant["task_id"], owner_id=row["owner_id"], bridge_id=row["device_id"]
            )
        else:
            task = monitor.register(
                {
                    "target_url": recipe["url"],
                    "site_profile": "moodle",
                    "auth_context_id": ctx.auth_id,
                    "interval_s": row["interval_s"],
                },
                owner_id=row["owner_id"],
                bridge_id=row["device_id"],
            )
        bound = BoundSession(monitor, row, proof)
        self.store.put_meta(
            "grant:" + str(row["id"]),
            {
                "task_id": task.task_id,
                "auth_id": ctx.auth_id,
                "source": row["id"],
                "owner": row["owner_id"],
                "revision": row["revision"],
            },
        )
        self.reading.protocol.sessions[row["id"]] = bound
        return bound

    async def start(self) -> None:
        for (key,) in self.store.db.execute(
            "SELECT key FROM monitor_meta WHERE key LIKE 'grant:%'"
        ).fetchall():
            grant = self.store.meta(key)
            try:
                row = await self.reading.own(grant["owner"], grant["source"])
                if row["revision"] == grant["revision"]:
                    self.build(row, "", grant)
            except (ContractError, MonitorError):
                continue
        await self.server.start()
        self.worker = asyncio.create_task(self.run())

    async def detach(self, bound: BoundSession) -> None:
        self.reading.protocol.sessions.pop(bound.source, None)
        bound.monitor.pause()
        bound.monitor.auth.close()
        await bound.monitor.transport.close()
        with self.store.db:
            self.store.db.executemany(
                "DELETE FROM monitor_meta WHERE key=?",
                [
                    ("grant:" + str(bound.source),),
                    ("page:" + bound.task.task_id,),
                    ("auth:" + bound.task.auth_context_id,),
                ],
            )

    async def run(self) -> None:
        while True:
            try:
                for bound in tuple(self.reading.protocol.sessions.values()):
                    async with self.reading.db.transaction():
                        await self.reading.fence.lock(bound.task.owner_id)
                        row = await self.reading.db.fetchone(
                            "SELECT revision, deleted FROM reading_sources WHERE id=? AND owner_id=?",
                            bound.source,
                            bound.task.owner_id,
                        )
                        if (
                            not row or row["deleted"] or row["revision"] != bound.revision
                        ) and self.reading.protocol.sessions.get(bound.source) is bound:
                            await self.detach(bound)
                await self.reading.protocol.tick()
            except Exception:
                # No cookie, upstream HTML or URL is included in diagnostics.
                import logging

                logging.getLogger(__name__).error("local page check failed")
            await asyncio.sleep(5)

    async def close(self) -> None:
        await self.server.close()
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        for bound in self.reading.protocol.sessions.values():
            bound.monitor.auth.close()
            await bound.monitor.transport.close()
        self.reading.protocol.sessions.clear()
        self.store.close()

    async def ticket(self, req: Request, user: dict) -> Response:
        if req.headers.get("Origin") != self.origin or req.context.get("auth_via") != "bearer":
            return Response.error(403, "binding_denied")
        data = req.json()
        if (
            not isinstance(data, dict)
            or type(data.get("source_id")) is not int
            or data.get("action") not in ("status", "authorize", "supply", "revoke", "presence")
        ):
            return Response.error(422, "invalid")
        try:
            row = await self.reading.own(
                user["id"],
                data["source_id"],
                include_deleted=data["action"] in ("revoke", "status", "presence"),
            )
        except ContractError:
            bound = self.reading.protocol.sessions.get(data["source_id"])
            if (
                data["action"] not in ("revoke", "status", "presence")
                or not bound
                or bound.task.owner_id != user["id"]
            ):
                return Response.error(404, "未登记此来源", "source_missing")
            row = {"device_id": bound.task.bridge_id, "revision": bound.revision}
        now = time.monotonic()
        self.tickets = {k: v for k, v in self.tickets.items() if v[0] > now}
        if len(self.tickets) >= 512:
            return Response.error(429, "busy")
        token = secrets.token_urlsafe(32)
        self.tickets[token] = (now + 20, user["id"], data["source_id"], data["action"])
        response = Response.json_body(
            {
                "ok": True,
                "schema_version": 1,
                "ticket": token,
                "port": self.server.port,
                "device_id": row["device_id"],
                "revision": row["revision"],
                "epoch": self.epoch,
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    async def handle(self, req: Request) -> Response:
        if (
            req.headers.get("Host") != f"127.0.0.1:{self.server.port}"
            or req.headers.get("Origin") != self.origin
        ):
            return Response.error(403, "binding_denied")
        if (
            req.method != "POST"
            or req.path != "/api/monitor/v2/session"
            or req.headers.get("Content-Type", "").split(";")[0] != "application/json"
        ):
            return Response.error(404, "not_found")
        ticket = self.tickets.pop(req.headers.get("X-Gleaner-Page-Ticket", ""), None)
        if not ticket or ticket[0] <= time.monotonic():
            return Response.error(401, "unauthorized")
        _, uid, source_id, operation = ticket
        try:
            data = req.json()
            if (
                not isinstance(data, dict)
                or data.get("source_id") != source_id
                or data.get("action") != operation
            ):
                raise MonitorError("invalid")
            async with self.reading.db.transaction():
                await self.reading.fence.lock(uid)
                try:
                    row = await self.reading.own(
                        uid,
                        source_id,
                        include_deleted=operation in ("revoke", "status", "presence"),
                    )
                except ContractError:
                    bound = self.reading.protocol.sessions.get(source_id)
                    if (
                        not bound
                        or bound.task.owner_id != uid
                        or operation not in ("revoke", "status", "presence")
                    ):
                        raise
                    row = {
                        "id": source_id,
                        "device_id": bound.task.bridge_id,
                        "revision": bound.revision,
                        "deleted": True,
                    }
                if row.get("deleted") and operation in ("revoke", "status", "presence"):
                    bound = self.reading.protocol.sessions.get(source_id)
                    if bound and bound.task.owner_id == uid:
                        await self.detach(bound)
                    return Response.json_body(
                        {
                            "ok": True,
                            "schema_version": 1,
                            "state": "not_authorized",
                            "epoch": self.epoch,
                        }
                    )

                if (
                    data.get("device_id") != row["device_id"]
                    or data.get("revision") != row["revision"]
                ):
                    raise MonitorError("binding_denied")
                result = await self.session(row, data)
            response = Response.json_body({"ok": True, "schema_version": 1, **result})
        except (ContractError, MonitorError) as error:
            response = Response.error(409, error.code, error.code)
        except (ValueError, KeyError, TypeError):
            response = Response.error(422, "invalid")
        response.headers["Cache-Control"] = "no-store"
        return response

    async def session(self, row: dict, data: dict) -> dict:
        action = data.get("action")
        bound = self.reading.protocol.sessions.get(row["id"])
        if action == "authorize":
            proof = data["account_proof"]
            if (
                data.get("epoch") != self.epoch
                or not isinstance(proof, str)
                or not re.fullmatch(r"[a-f0-9]{64}", proof)
            ):
                raise MonitorError("binding_denied")
            if bound and bound.revision != row["revision"]:
                await self.detach(bound)
                bound = None
            if bound and bound.proof and bound.proof != proof:
                raise MonitorError("revision_conflict")
            if not bound:
                bound = self.build(row, proof)
            bound.monitor.auth.approve_reauthorization(bound.task.auth_context_id)
            bound.proof = proof
            if not bound.task.enabled:
                bound.monitor.resume(bound.task.revision)
        elif not bound:
            if action == "status":
                return {"state": "not_authorized", "epoch": self.epoch}
            raise MonitorError("not_found")
        if bound.revision != row["revision"] and action != "revoke":
            raise MonitorError("revision_conflict")
        auth = bound.monitor.auth
        ctx = auth.context(bound.task.auth_context_id)
        if action == "supply":
            if not bound.proof:
                raise MonitorError("account_confirmation_required")
            generation = ctx.generation
            auth.import_cookies(
                ctx.auth_id,
                data["cookies"],
                backend_epoch=data["epoch"],
                expected_revision=data["auth_revision"],
                request_id=str(UUID(data["request_id"])),
                reason=data["reason"],
                confirmed_same_account=data.get("confirmed_same_account") is True,
            )
            if ctx.generation != generation and bound.task.enabled and not row["paused"]:
                allowed = bound.monitor.queue_recovery(
                    self.store.meta("not-before:" + auth.policy.origin, 0)
                )
                await self.reading.db.execute(
                    "UPDATE reading_sources SET next_at=? WHERE id=? AND revision=? AND paused=0",
                    allowed,
                    row["id"],
                    row["revision"],
                )
        elif action == "revoke":
            if data["epoch"] != self.epoch:
                raise MonitorError("stale_backend")
            await auth.revoke(ctx.auth_id, data["auth_revision"])
            bound.proof = ""
        elif action == "presence":
            auth.presence(row["device_id"], data["sequence"])
        elif action not in ("status", "authorize"):
            raise MonitorError("invalid")
        return {
            "epoch": self.epoch,
            "state": (
                "account_confirmation_required"
                if not bound.proof and ctx.was_verified and ctx.state != "revoked"
                else ctx.state
            ),
            "auth_revision": ctx.revision,
            "task_id": bound.task.task_id,
            "next_allowed_at": max(
                bound.monitor.next_due_at, self.store.meta("not-before:" + auth.policy.origin, 0)
            ),
            "last_fetch_at": bound.monitor.last_fetch_at,
            "last_delivery_at": bound.monitor.last_delivery_at,
        }
