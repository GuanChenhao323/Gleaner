"""Single-process monitor scheduler with persisted deadlines and in-memory leases."""

from __future__ import annotations

import asyncio
from collections import deque
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
        self.next_wake_at: float | None = None
        self.coordinator: SiteScheduler | None = None
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
        if self.store.meta("host_not_before", 0) > self.clock.utc() or (
            source.failures > 0 and source.next_due_at > self.clock.utc()
        ):
            return "backoff"
        return "ready"

    async def tick(self) -> int:
        if self.coordinator is not None:
            return await self.coordinator.tick()
        if self._tick_lock.locked():
            return 0
        async with self._tick_lock:
            await self.handoff.drain()
            if len(self.store.pending()) >= self.max_pending:
                return 0
            due = self.due_round()
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

    def due_round(self, *, include_cooling: bool = False) -> list:
        now = self.clock.utc()
        self.next_wake_at = None
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
            reserved = bool(queued and queued[0].get("scheduled_at") == source.next_due_at)
            allowed_at = (
                source.next_due_at
                if reserved
                else max(source.next_due_at, self.store.meta(account_key, 0))
            )
            if source.runtime_status in ("ready", "backoff") and allowed_at > now:
                self.next_wake_at = min(self.next_wake_at or allowed_at, allowed_at)
            eligible = source.runtime_status == "ready" or (
                include_cooling
                and source.runtime_status == "backoff"
                and self.store.meta("host_not_before", 0) > now
            )
            if eligible and now >= allowed_at:
                due.append((source, account_key, queued[0] if queued else None))
        return due

    async def _execute(self, source: MonitorSource, check: dict[str, Any]) -> None:
        lock = self.auth.context(source.auth_id).network_lock if source.auth_id else asyncio.Lock()
        async with lock:
            current = self.store.source(source.source_id)
            if not current or current.revision != source.revision:
                self.store.save_check({**check, "state": "superseded"})
                return
            if self._runtime(current) != "ready":
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
                        "scheduled_at": check.get("scheduled_at", check["created_at"]),
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


class SiteScheduler:
    """Dispatch across trusted single-origin schedulers, each with its own durable store."""

    def __init__(
        self,
        routes: list[Scheduler],
        *,
        concurrency: int = 8,
        max_pending: int = 100,
        round_robin: bool = True,
        quota_groups: dict[str, str] | None = None,
    ) -> None:
        if concurrency < 1 or max_pending < 1:
            raise ValueError("invalid dispatch budget")
        origins = {route.registry.policy.origin for route in routes}
        if len(origins) != len(routes) or len({id(r.store) for r in routes}) != len(routes):
            raise ValueError("each origin needs one scheduler and one dedicated store")
        if set(quota_groups or {}) - origins:
            raise ValueError("unknown quota origin")
        self.group = {
            r: (quota_groups or {}).get(r.registry.policy.origin, r.registry.policy.origin)
            for r in routes
        }
        self.round_robin = round_robin
        self.routes = routes
        self.concurrency, self.max_pending = concurrency, max_pending
        paths = [r.store.db.execute("PRAGMA database_list").fetchone()[2] for r in routes]
        files = [name for name in paths if name]
        if len(files) != len(set(files)) or any(
            r.coordinator or r._tick_lock.locked() for r in routes
        ):
            raise ValueError("route already has a dispatcher or shared database")
        self._running = asyncio.Lock()
        self._refresh = asyncio.Event()
        pacers = {}
        for route in routes:
            if hasattr(route.transport, "pacing"):
                route.transport.pacing = pacers.setdefault(
                    self.group[route], route.transport.pacing
                )
            route.coordinator = self
            route.registry.on_change = self._refresh.set

    async def tick(self) -> int:
        if self._running.locked():
            self._refresh.set()
            return 0
        async with self._running:
            return await self._run()

    async def _execute(
        self, route: Scheduler, source: MonitorSource, check: dict[str, Any]
    ) -> None:
        try:
            await route._execute(source, check)
        except asyncio.CancelledError:
            self._interrupt(route, check, "cancelled")
            raise
        except Exception:
            self._interrupt(route, check, "failed")

    @staticmethod
    def _interrupt(route: Scheduler, check: dict[str, Any], state: str) -> None:
        latest = route.store.check(check["check_id"])
        if latest and latest["state"] in ("running", "queued"):
            route.store.save_check({**latest, "state": state, "error": "execution_interrupted"})

    async def _run(self) -> int:
        queues = {r: deque() for r in self.routes}
        seen = set()
        order = deque(self.routes)
        active = {}
        sending = {}
        count = 0
        refresh = True
        delivery_requested = set(self.routes)
        wake = None
        try:
            while True:
                if refresh or self._refresh.is_set():
                    self._refresh.clear()
                    refresh = False
                    for route in self.routes:
                        for source, key, check in sorted(
                            route.due_round(include_cooling=True),
                            key=lambda it: (it[0].next_due_at, it[0].source_id),
                        ):
                            identity = (
                                route,
                                source.source_id,
                                source.revision,
                                source.next_due_at,
                            )
                            if identity in seen:
                                continue
                            seen.add(identity)
                            check = check or route.registry.request_check(
                                source.source_id,
                                source.owner_id,
                                f"timer:{source.revision}:{source.next_due_at}",
                            )
                            if "scheduled_at" not in check:
                                check = {**check, "scheduled_at": source.next_due_at}
                                route.store.save_check(check)
                            queues[route].append((source, key, check))

                for route in tuple(delivery_requested):
                    if route in sending.values():
                        continue
                    delivery_requested.remove(route)
                    if route.store.pending():
                        sending[asyncio.create_task(route.handoff.drain())] = route

                stores_pending = {r: len(r.store.pending()) for r in self.routes}
                delays = []
                if not self.round_robin:
                    order = deque(
                        sorted(
                            order,
                            key=lambda r: (
                                (queues[r][0][0].next_due_at, queues[r][0][0].source_id)
                                if queues[r]
                                else (float("inf"), "")
                            ),
                        )
                    )
                for _ in range(len(order)):
                    if (
                        len(active) >= self.concurrency
                        or sum(stores_pending.values()) + len(active) >= self.max_pending
                    ):
                        break
                    route = order.popleft()
                    order.append(route)
                    if (
                        any(self.group[r] == self.group[route] for r in active.values())
                        or not queues[route]
                        or stores_pending[route] >= route.max_pending
                    ):
                        continue
                    if quota_blocked := max(
                        (
                            r.store.meta("host_not_before", 0)
                            for r in self.routes
                            if self.group[r] == self.group[route]
                        ),
                        default=0,
                    ):
                        if quota_blocked > route.clock.utc():
                            delays.append(quota_blocked - route.clock.utc())
                            continue
                    delay = getattr(route.transport, "start_delay", lambda: 0.0)()
                    if delay > 0:
                        delays.append(delay)
                        continue
                    queue = queues[route]
                    entry = next(
                        (
                            entry
                            for entry in queue
                            if not entry[0].auth_id
                            or not route.auth.context(entry[0].auth_id).network_lock.locked()
                        ),
                        None,
                    )
                    if entry is None:
                        delays.append(0.1)
                        continue
                    queue.remove(entry)
                    source, key, check = entry
                    current = route.store.source(source.source_id)
                    if not current or current.revision != source.revision:
                        route.store.save_check({**check, "state": "superseded"})
                        continue
                    if route._runtime(current) != "ready":
                        continue
                    route.store.put_meta(
                        key, route.clock.utc() + route.registry.policy.min_interval_s
                    )
                    active[asyncio.create_task(self._execute(route, current, check))] = route
                    count += 1
                if not active and not sending and not delays:
                    break
                deadlines = [
                    route.next_wake_at - route.clock.utc()
                    for route in self.routes
                    if route.next_wake_at is not None
                ]
                if deadlines:
                    if min(deadlines) <= 0:
                        refresh = True
                        continue
                    delays.append(min(deadlines))
                wake = asyncio.create_task(self._refresh.wait())
                done, _ = await asyncio.wait(
                    [*active, *sending, wake],
                    timeout=min(delays) if delays else None,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                wake.cancel()
                await asyncio.gather(wake, return_exceptions=True)
                wake = None
                for task in done:
                    if task in active:
                        route = active.pop(task)
                        await task
                        delivery_requested.add(route)
                    elif task in sending:
                        sending.pop(task)
                        try:
                            await task
                        except MonitorError:
                            # Other origins can continue while this durable outbox is inspected.
                            import logging

                            logging.getLogger(__name__).error("site outbox could not be drained")
            return count
        finally:
            remaining = [*active, *sending]
            if wake is not None:
                remaining.append(wake)
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)
