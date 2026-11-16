"""At-least-once delivery with persisted receipts and generation fences."""

from __future__ import annotations

from .auth import AuthManager
from .models import MonitorError, ObservationBatch, ObservationSink
from .store import Store


class Handoff:
    def __init__(self, store: Store, auth: AuthManager, sink: ObservationSink) -> None:
        self.store, self.auth, self.sink = store, auth, sink

    def current(self, batch: ObservationBatch) -> bool:
        source = self.store.source(batch.source_id)
        if source is None or not source.enabled or source.revision != batch.source_revision:
            return False
        if source.auth_id:
            c = self.auth.contexts.get(source.auth_id)
            if c is None:
                return False
            return c.generation == batch.auth_generation and c.state == "valid"
        return True

    async def drain(self) -> int:
        completed = 0
        for batch in self.store.pending():
            source, check = self.store.source(batch.source_id), self.store.check(batch.check_id)
            if source is None or check is None:
                raise MonitorError("invalid_outbox")
            if not self.current(batch):
                self.store.finish(batch, {**check, "state": "superseded", "outcome": None}, source)
                continue
            try:
                receipt = await self.sink.apply(batch)
            except Exception:
                # Keep selected observation content durable; do not refetch upstream on sink failure.
                self.store.retry_delivery(batch.observation_id)
                continue
            # Sink implementations must enforce the same fence at their own commit point.
            if not self.current(batch):
                self.store.finish(
                    batch,
                    {**check, "state": "superseded", "outcome": None},
                    self.store.source(batch.source_id),
                )
                continue
            expected = {e.item_id for e in batch.entries}
            if (
                receipt.observation_id != batch.observation_id
                or receipt.source_id != batch.source_id
                or receipt.source_revision != batch.source_revision
                or not receipt.applied
                or len(receipt.results) != len(expected)
                or {r.get("item_id") for r in receipt.results} != expected
                or any(
                    r.get("status") not in ("changed", "unchanged", "failed", "superseded")
                    for r in receipt.results
                )
            ):
                self.store.retry_delivery(batch.observation_id)
                continue
            good = [r for r in receipt.results if r["status"] in ("changed", "unchanged")]
            if len(good) == len(receipt.results):
                source.last_success_at = batch.observed_at
                outcome = "changed" if any(r["status"] == "changed" for r in good) else "unchanged"
                state = "succeeded"
            elif good:
                outcome, state = "partial", "succeeded"
            else:
                outcome, state = "failed", "failed"
            self.store.finish(batch, {**check, "state": state, "outcome": outcome}, source, receipt)
            completed += 1
        return completed
