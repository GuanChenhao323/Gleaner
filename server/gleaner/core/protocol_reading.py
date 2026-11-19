"""Use pre-authorized local Moodle sessions for closed, account-bound reading sources."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..monitoring.models import MonitorError
from ..monitoring.pages import HTMLReceipt, HTMLSnapshot, PageMonitor
from ..monitoring.reading_projection import project_assignment
from ..storage.db import loads
from .monitors import ContractError

if TYPE_CHECKING:
    from .reading_sources import ReadingSourceService


@dataclass
class ActiveCheck:
    job: dict
    baseline: dict
    result: dict | None = None
    error: str = "unsupported"


class BoundSession:
    def __init__(self, monitor: PageMonitor, row: dict, proof: str) -> None:
        task = monitor.task
        if not task:
            raise MonitorError("not_found")
        recipe = loads(row["recipe"])
        if (
            (row["owner_id"], row["device_id"], recipe["url"], recipe["source"])
            != (task.owner_id, task.bridge_id, task.target_url, task.site_profile)
            or recipe["source"] != "moodle"
            or not recipe.get("resident")
        ):
            raise MonitorError("binding_denied")
        self.monitor, self.task, self.revision, self.proof = monitor, task, row["revision"], proof
        self.source = row["id"]
        self.active: ActiveCheck | None = None
        monitor.sink = self

    async def accept(self, snapshot: HTMLSnapshot) -> HTMLReceipt:
        active = self.active
        if active is None or snapshot.task_id != self.task.task_id:
            return HTMLReceipt(snapshot.snapshot_id, False)
        try:
            active.result = project_assignment(
                active.job["recipe"],
                active.baseline,
                snapshot,
                self.monitor.auth.backend_epoch + "|" + str(self.source),
                self.proof,
            )
        except MonitorError as error:
            active.error = error.code
        return HTMLReceipt(snapshot.snapshot_id, True)

    def available(self, row: dict) -> bool:
        context = self.monitor.auth.context(self.task.auth_context_id)
        return bool(
            self.proof
            and self.monitor.task is self.task
            and self.task.enabled
            and row["revision"] == self.revision
            and row["verified"]
            and not row["paused"]
            and not row["pending"]
            and context.state in ("valid", "unverified")
            and len(context.jar)
        )


class ProtocolReading:
    def __init__(self, reading: ReadingSourceService) -> None:
        self.reading = reading
        self.sessions: dict[int, BoundSession] = {}
        self._lock = asyncio.Lock()

    async def eligible(self, row: dict, now: float) -> bool:
        bound = self.sessions.get(row["id"])
        if not bound or not bound.available(row):
            return False
        recipe = loads(row["recipe"])
        presence = await self.reading.db.fetchone(
            "SELECT state, seen_at FROM reading_page_presence WHERE owner_id=? AND device_id=? AND page_id=?",
            row["owner_id"],
            row["device_id"],
            recipe["resident"]["page_id"],
        )
        if presence and presence["seen_at"] > now - 150:
            return presence["state"] == "absent"
        device = await self.reading.db.fetchval(
            "SELECT last_seen_at FROM reading_devices WHERE owner_id=? AND device_id=?",
            row["owner_id"],
            row["device_id"],
        )
        return bool(device and device <= now - 150)

    async def tick(self) -> None:
        if self._lock.locked():
            return
        async with self._lock:
            for bound in tuple(self.sessions.values()):
                await self.check(bound)

    async def check(self, bound: BoundSession) -> None:
        service = self.reading
        now = time.time()
        uid = bound.task.owner_id
        async with service.db.transaction():
            await service.fence.lock(uid)
            row = await service.db.fetchone(
                "SELECT * FROM reading_sources WHERE id=? AND owner_id=? AND deleted=0",
                bound.source,
                uid,
            )
            if (
                not row
                or self.sessions.get(bound.source) is not bound
                or not service.due(row, now)
                or not await self.eligible(row, now)
                or not await service.has_items(row["id"])
            ):
                return
            if bound.monitor.next_due_at > now:
                return
            job = await service.lease(row, now)
        if not job:
            return
        active = ActiveCheck(job, loads(row["last_snapshot"]))
        bound.active = active
        context = bound.monitor.auth.context(bound.task.auth_context_id)
        generation = context.generation
        payload = {
            "schema_version": 1,
            "revision": job["revision"],
            "lease": job["lease"],
            "device_id": row["device_id"],
            "status": "waiting_page",
        }
        try:
            outcome = await bound.monitor.tick(authorized_offline=True)
            if outcome and outcome["state"] == "delivered":
                if active.result:
                    payload.update(
                        status="success",
                        snapshot=active.result,
                        account_key=job["recipe"]["binding"]["account_key"],
                    )
                else:
                    payload["status"] = active.error
            elif outcome and outcome.get("error") in ("auth_required", "account_mismatch"):
                payload["status"] = "need_login"
            elif outcome and outcome["state"] == "failed":
                payload["status"] = "protocol_unavailable"
            async with service.db.transaction():
                await service.fence.lock(uid)
                if (
                    self.sessions.get(bound.source) is not bound
                    or context.generation != generation
                    or bound.monitor.task is not bound.task
                ):
                    return
                if payload["status"] == "success" and context.state != "valid":
                    return
                await service.result(uid, job["id"], payload)
        except ContractError as error:
            if error.code not in ("stale_lease", "source_deleted", "not_found"):
                raise
        finally:
            bound.active = None
            bound.monitor.pending = None
