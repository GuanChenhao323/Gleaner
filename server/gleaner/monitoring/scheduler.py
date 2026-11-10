"""Single-process monitor scheduler with persisted deadlines and in-memory leases."""

from __future__ import annotations

import asyncio
from typing import Any

from .adapters.moodle import MoodleAdapter
from .handoff import Handoff
from .models import Clock, MonitorError, MonitorSource, RemoteTransport
from .registry import Registry


class Scheduler:
    def __init__(
        self,
        registry: Registry,
        transport: RemoteTransport,
        handoff: Handoff,
        adapter: MoodleAdapter | None = None,
        *,
        clock: Clock | None = None,
        max_pending: int = 100,
    ) -> None:
        self.registry, self.store, self.auth = registry, registry.store, registry.auth
        self.transport, self.handoff = transport, handoff
        self.adapter, self.clock = adapter or MoodleAdapter(), clock or Clock()
        self.max_pending = max_pending
        self._tick_lock = asyncio.Lock()
        self.observations: list[dict[str, Any]] = []
        for check in self.store.checks():
            if check["state"] == "running":
                # A crash before outbox commit may need a later refetch, within persisted rate limits.
                self.store.save_check({**check, "state": "cancelled", "error": "backend_restart"})

    def _runtime(self, source: MonitorSource) -> str:
        if not source.enabled:
            return "paused"
        if not self.auth.online(source.bridge_id):
            return "waiting_browser"
        if source.auth_id:
            context = self.auth.contexts.get(source.auth_id)
            if context is None or context.state not in ("valid", "unverified"):
                return "waiting_auth"
        if self.store.meta("host_not_before", 0) > self.clock.utc():
            return "backoff"
        return "ready"

    async def tick(self) -> int:
        if self._tick_lock.locked():
            return 0
        async with self._tick_lock:
            await self.handoff.drain()
            if len(self.store.pending()) >= self.max_pending:
                return 0
            now = self.clock.utc()
            pending_sources = {batch.source_id for batch in self.store.pending()}
            due = []
            for source in self.store.sources():
                source.runtime_status = self._runtime(source)
                self.store.save_source(source)
                if source.source_id in pending_sources:
                    continue
                for old in self.store.checks(source.source_id):
                    if old["state"] == "queued" and old["source_revision"] != source.revision:
                        self.store.save_check({**old, "state": "superseded"})
                queued = [c for c in self.store.checks(source.source_id) if c["state"] == "queued"]
                account_key = "round:" + (source.auth_id or source.bridge_id)
                allowed_at = max(source.next_due_at, self.store.meta(account_key, 0))
                if source.runtime_status == "ready" and now >= allowed_at:
                    due.append((source, account_key, queued[0] if queued else None))
            # Snapshot the due round before advancing account deadlines; co-due sources share the round.
            for source, account_key, existing in due:
                self.store.put_meta(
                    account_key, self.clock.utc() + self.registry.policy.min_interval_s
                )
                check = existing or self.registry.request_check(
                    source.source_id,
                    source.owner_id,
                    f"timer:{source.revision}:{source.next_due_at}",
                )
                await self._execute(source, check)
                await self.handoff.drain()
            return len(due)

    async def _execute(self, source: MonitorSource, check: dict[str, Any]) -> None:
        lock = self.auth.context(source.auth_id).network_lock if source.auth_id else asyncio.Lock()
        async with lock:
            if self._runtime(self.store.source(source.source_id)) != "ready":
                return
            generation = self.auth.context(source.auth_id).generation if source.auth_id else None
            check = {
                **check,
                "state": "running",
                "source_revision": source.revision,
                "auth_generation": generation,
                "last_checked_at": self.clock.utc(),
            }
            self.store.save_check(check)
            source.next_due_at = self.clock.utc() + source.interval_s
            self.store.save_source(source)
            try:
                lease = await self.auth.acquire(source.auth_id) if source.auth_id else None
                plan = self.adapter.plan(source, source.targets, check["check_id"], generation)
                response = await self.transport.fetch(plan, lease)
                if not self._generation_current(source, generation):
                    raise MonitorError("superseded")
                verdict = self.adapter.inspect(response)
                if verdict.state == "auth_required":
                    raise MonitorError("auth_required")
                if verdict.state == "forbidden":
                    raise MonitorError("forbidden")
                if verdict.state not in ("authenticated", "public"):
                    raise MonitorError("parse_failed")
                if lease:
                    self.auth.verify(lease, verdict.principal_key)
                batch = self.adapter.select(response, source, plan, self.clock.utc())
                if not self._generation_current(source, generation):
                    raise MonitorError("superseded")
                source.failures = 0
                self.store.save_source(source)
                self.store.enqueue(batch, check)
                self.observations.append(
                    {
                        "check_id": check["check_id"],
                        "observation_id": batch.observation_id,
                        "scheduled_at": check["created_at"],
                        "started_at": check["last_checked_at"],
                        "utc": batch.observed_at,
                        "mono": self.clock.mono(),
                        "authentication": verdict.state,
                        "evidence_code": verdict.evidence_code,
                        "representation_hash": batch.representation_hash,
                        "entries": [
                            {
                                "item_id": e.item_id,
                                "outcome": e.outcome,
                                "title_present": bool(e.title),
                                "text_length": len(e.text or ""),
                                "error": e.error,
                            }
                            for e in batch.entries
                        ],
                    }
                )
            except MonitorError as error:
                latest = self.store.source(source.source_id)
                if error.code == "superseded" or not self._generation_current(source, generation):
                    self.store.save_check(
                        {**check, "state": "superseded", "outcome": None, "error": error.code}
                    )
                    return
                if source.auth_id and error.code in (
                    "auth_required",
                    "account_mismatch",
                    "account_confirmation_required",
                ):
                    self.auth.require_auth(source.auth_id)
                if error.retryable:
                    latest.failures += 1
                    latest.next_due_at = max(
                        latest.next_due_at, self.clock.utc() + error.retry_after_s
                    )
                    if latest.failures >= 3:
                        latest.next_due_at = max(latest.next_due_at, self.clock.utc() + 1800)
                    latest.runtime_status = "backoff"
                else:
                    latest.runtime_status = (
                        "waiting_auth" if error.code.startswith("auth_") else "paused"
                    )
                    # Non-retryable network/policy/parse failures need an explicit operator retry.
                    if error.code not in (
                        "auth_required",
                        "account_mismatch",
                        "account_confirmation_required",
                    ):
                        latest.enabled = False
                self.store.save_source(latest)
                self.store.save_check(
                    {**check, "state": "failed", "outcome": "failed", "error": error.code}
                )
                self.observations.append(
                    {
                        "check_id": check["check_id"],
                        "utc": self.clock.utc(),
                        "mono": self.clock.mono(),
                        "error": error.code,
                    }
                )
            finally:
                if source.auth_id:
                    self.store.put_meta(
                        "auth:" + source.auth_id, self.auth.metadata(source.auth_id)
                    )

    def _generation_current(self, source: MonitorSource, generation: int | None) -> bool:
        latest = self.store.source(source.source_id)
        return bool(
            latest
            and latest.enabled
            and latest.revision == source.revision
            and (not source.auth_id or self.auth.context(source.auth_id).generation == generation)
        )
