"""Parameter-driven HTML fetch tasks with in-memory delivery; no business extraction.

This opt-in path reuses session and HTTP facilities. It does not alter IC-003 item
observations, persist authenticated HTML, or claim production inbox delivery.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from .auth import AuthManager
from .models import Clock, FetchPlan, MonitorError, RemoteTransport, SitePolicy
from .profiles import SessionInspector, page_policy
from .store import Store


@dataclass
class PageTask:
    task_id: str
    owner_id: int
    bridge_id: str
    target_url: str
    interval_s: float
    auth_context_id: str
    site_profile: str
    revision: int = 1
    enabled: bool = True


@dataclass(frozen=True)
class HTMLSnapshot:
    snapshot_id: str
    task_id: str
    task_revision: int
    auth_generation: int
    requested_url: str
    final_url: str
    fetched_at: float
    status: int
    content_type: str
    body: bytes = field(repr=False)


@dataclass(frozen=True)
class HTMLReceipt:
    snapshot_id: str
    accepted: bool


class HTMLSink(Protocol):
    async def accept(self, snapshot: HTMLSnapshot) -> HTMLReceipt: ...


class PageMonitor:
    """One task per transport/session; repeat callers share this instance and its lock."""

    def __init__(
        self,
        policy: SitePolicy,
        auth: AuthManager,
        transport: RemoteTransport,
        inspector: SessionInspector,
        sink: HTMLSink,
        *,
        clock: Clock | None = None,
        store: Store | None = None,
    ) -> None:
        self.policy, self.auth, self.transport, self.inspector, self.sink = (
            policy,
            auth,
            transport,
            inspector,
            sink,
        )
        self.store = store
        self.clock = clock or Clock()
        self.task: PageTask | None = None
        self.pending: HTMLSnapshot | None = None
        self.next_due_at = 0.0
        self.delivery_due_at = 0.0
        self.access_not_before = 0.0
        self.failures = 0
        self.last_fetch_at: float | None = None
        self.last_delivery_at: float | None = None
        self._lock = asyncio.Lock()
        self.evidence_code: str | None = None
        self._last_state: str | None = None

    def _persist(self) -> None:
        if self.store is None or self.task is None:
            return
        self.store.put_meta(
            "page:" + self.task.task_id,
            {
                "task": asdict(self.task),
                "next_due_at": self.next_due_at,
                "failures": self.failures,
                "access_not_before": self.access_not_before,
                "last_fetch_at": self.last_fetch_at,
                "last_delivery_at": self.last_delivery_at,
            },
        )

    def restore(self, task_id: str, *, owner_id: int, bridge_id: str) -> PageTask:
        saved = self.store.meta("page:" + task_id) if self.store is not None else None
        if not saved:
            raise MonitorError("not_found")
        task = PageTask(**saved["task"])
        if (task.task_id, task.owner_id, task.bridge_id) != (task_id, owner_id, bridge_id):
            raise MonitorError("binding_denied")
        params = {
            k: getattr(task, k)
            for k in ("target_url", "interval_s", "auth_context_id", "site_profile")
        }
        self._validate(params, owner_id, bridge_id)
        self.task = task
        self.pending = None
        self.next_due_at = saved["next_due_at"]
        self.access_not_before = saved.get("access_not_before", saved["next_due_at"])
        self.failures = saved["failures"]
        self.last_fetch_at = saved["last_fetch_at"]
        self.last_delivery_at = saved["last_delivery_at"]
        self._last_state = None
        self.delivery_due_at = 0
        return task

    def queue_recovery(self, host_not_before: float) -> float:
        if self.task is None or not self.task.enabled:
            raise MonitorError("paused")
        self.next_due_at = max(self.access_not_before, host_not_before)
        self._last_state = None
        self._persist()
        return self.next_due_at

    def resume(self, expected_revision: int) -> None:
        if self.task is None or self.task.revision != expected_revision:
            raise MonitorError("revision_conflict")
        if not self.task.enabled:
            self.task.enabled = True
            self.task.revision += 1
            self._persist()

    def _validate(self, params: dict[str, Any], owner_id: int, bridge_id: str) -> None:
        if set(params) != {"target_url", "interval_s", "auth_context_id", "site_profile"}:
            raise MonitorError("invalid")
        url, interval, auth_id, profile = (
            params[k] for k in ("target_url", "interval_s", "auth_context_id", "site_profile")
        )
        if not all(isinstance(v, str) for v in (url, auth_id, profile)) or type(interval) not in (
            int,
            float,
        ):
            raise MonitorError("invalid")
        if not math.isfinite(interval) or interval < self.policy.min_interval_s:
            raise MonitorError("invalid")
        registered = page_policy(profile, url)
        if registered != self.policy or profile != self.inspector.profile:
            raise MonitorError("binding_denied")
        c = self.auth.context(auth_id)
        if c.owner_id != owner_id or c.bridge_id != bridge_id or self.auth.policy != self.policy:
            raise MonitorError("binding_denied")

    def register(self, params: dict[str, Any], *, owner_id: int, bridge_id: str) -> PageTask:
        self._validate(params, owner_id, bridge_id)
        self.task = PageTask(
            str(uuid4()),
            owner_id,
            bridge_id,
            params["target_url"],
            float(params["interval_s"]),
            params["auth_context_id"],
            params["site_profile"],
        )
        self.pending = None
        self.next_due_at = self.delivery_due_at = 0.0
        self.failures = 0
        self.last_fetch_at = self.last_delivery_at = None
        self._persist()
        return self.task

    def pause(self) -> None:
        if self.task:
            self.task.enabled = False
            self.task.revision += 1
        self.pending = None
        self._persist()

    def _current(self, snapshot: HTMLSnapshot) -> bool:
        task = self.task
        if (
            not task
            or not task.enabled
            or (task.task_id, task.revision) != (snapshot.task_id, snapshot.task_revision)
        ):
            return False
        c = self.auth.contexts.get(task.auth_context_id)
        return bool(c and c.generation == snapshot.auth_generation and c.state == "valid")

    def _result(self, state: str, **extra: Any) -> dict[str, Any]:
        self._last_state = state
        self._persist()
        return {
            "state": state,
            "utc": self.clock.utc(),
            "mono": self.clock.mono(),
            "last_fetch_at": self.last_fetch_at,
            "last_delivery_at": self.last_delivery_at,
            **extra,
        }

    async def _deliver(self) -> dict[str, Any] | None:
        snapshot = self.pending
        if snapshot is None:
            return None
        if not self._current(snapshot):
            self.pending = None
            return self._result("superseded")
        if self.clock.utc() < self.delivery_due_at:
            return None
        try:
            receipt = await self.sink.accept(snapshot)
            accepted = receipt.snapshot_id == snapshot.snapshot_id and receipt.accepted is True
        except Exception:
            accepted = False
        if not self._current(snapshot):
            self.pending = None
            return self._result("superseded")
        if not accepted:
            self.delivery_due_at = self.clock.utc() + 60
            return self._result(
                "delivery_pending", snapshot_id=snapshot.snapshot_id, error="delivery_failed"
            )
        self.pending = None
        self.last_delivery_at = self.clock.utc()
        return self._result(
            "delivered",
            snapshot_id=snapshot.snapshot_id,
            bytes=len(snapshot.body),
            sha256=hashlib.sha256(snapshot.body).hexdigest(),
            authentication="authenticated",
            evidence_code=self.evidence_code,
            http_status=snapshot.status,
        )

    async def tick(self, *, authorized_offline: bool = False) -> dict[str, Any] | None:
        if self._lock.locked():
            return None
        async with self._lock:
            if self.pending:
                return await self._deliver()
            task = self.task
            if task is None or not task.enabled:
                return None
            c = self.auth.context(task.auth_context_id)
            if not self.auth.online(task.bridge_id) and not (
                authorized_offline and c.state in ("valid", "unverified") and len(c.jar)
            ):
                return (
                    self._result("waiting_browser")
                    if self._last_state != "waiting_browser"
                    else None
                )
            if c.state not in ("valid", "unverified"):
                return self._result("waiting_auth") if self._last_state != "waiting_auth" else None
            if self.clock.utc() < self.next_due_at:
                return None
            async with c.network_lock:
                if self.task is not task or not task.enabled:
                    return self._result("superseded")
                revision, generation = task.revision, c.generation
                self.access_not_before = self.clock.utc() + self.policy.min_interval_s
                self.next_due_at = self.clock.utc() + task.interval_s
                self._persist()
                try:
                    lease = await self.auth.acquire(task.auth_context_id)
                    plan = FetchPlan(
                        task.task_id, revision, generation, str(uuid4()), task.target_url, ()
                    )
                    response = await self.transport.fetch(plan, lease)
                    if (
                        self.task is not task
                        or not task.enabled
                        or task.revision != revision
                        or c.generation != generation
                    ):
                        raise MonitorError("superseded")
                    verdict = self.inspector.inspect(response)
                    if verdict.state != "authenticated":
                        raise MonitorError(
                            {"auth_required": "auth_required", "forbidden": "forbidden"}.get(
                                verdict.state, "auth_unverified"
                            )
                        )
                    self.auth.verify(lease, verdict.principal_key)
                    self.evidence_code = verdict.evidence_code
                    self.pending = HTMLSnapshot(
                        str(uuid4()),
                        task.task_id,
                        revision,
                        generation,
                        task.target_url,
                        response.final_url,
                        self.clock.utc(),
                        response.status,
                        response.content_type,
                        response.body,
                    )
                    self.failures = 0
                    self.last_fetch_at = self.clock.utc()
                    self.delivery_due_at = 0.0
                except MonitorError as error:
                    if error.code == "superseded":
                        return self._result("superseded")
                    if error.code in (
                        "auth_required",
                        "auth_unverified",
                        "account_mismatch",
                        "account_confirmation_required",
                    ):
                        self.auth.require_auth(task.auth_context_id)
                    elif not error.retryable:
                        task.enabled = False
                    self.failures += 1
                    delay = max(
                        task.interval_s,
                        error.retry_after_s,
                        1800 if error.retryable and self.failures >= 3 else 0,
                    )
                    self.access_not_before = max(
                        self.access_not_before,
                        self.clock.utc() + error.retry_after_s,
                        self.clock.utc() + 1800 if error.retryable and self.failures >= 3 else 0,
                    )
                    self.next_due_at = self.clock.utc() + delay
                    return self._result("failed", error=error.code, retryable=error.retryable)
                self.next_due_at = self.clock.utc() + task.interval_s
            return await self._deliver()
