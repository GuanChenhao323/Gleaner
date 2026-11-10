"""Persistent simulated receipts, only for an independent debug database."""

from collections.abc import Callable

from gleaner.monitoring.models import ApplyReceipt, ObservationBatch
from gleaner.monitoring.store import Store

from .extract_debug import content_digest


class DebugSink:
    def __init__(
        self, store: Store, fence: Callable[[ObservationBatch], bool] = lambda _: True
    ) -> None:
        self.store, self.fence = store, fence
        self.fail = False

    async def apply(self, batch: ObservationBatch) -> ApplyReceipt:
        old = self.store.meta("stub_receipt:" + batch.observation_id)
        if old:
            return ApplyReceipt(**old)
        if self.fail:
            raise RuntimeError("synthetic_sink_unavailable")
        if not self.fence(batch):
            return ApplyReceipt(
                batch.observation_id, batch.source_id, batch.source_revision, False, []
            )
        results, hashes = [], {}
        for entry in batch.entries:
            key = f"stub_hash:{batch.source_id}:{entry.item_id}"
            if entry.outcome == "content":
                digest = content_digest(entry)
                status = "unchanged" if self.store.meta(key) == digest else "changed"
                hashes[key] = digest
                error, success = None, batch.observed_at
            else:
                status, error, success = (
                    "failed",
                    entry.error or {"code": "missing_baseline"},
                    None,
                )
            results.append(
                {
                    "item_id": entry.item_id,
                    "status": status,
                    "last_success_at": success,
                    "error": error,
                }
            )
        receipt = ApplyReceipt(
            batch.observation_id, batch.source_id, batch.source_revision, True, results
        )
        # Atomic dedupe + simulated application. No await between fence and this transaction.
        import json
        from dataclasses import asdict

        with self.store.db:
            for key, value in hashes.items():
                self.store.db.execute(
                    "INSERT INTO monitor_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)),
                )
            self.store.db.execute(
                "INSERT INTO monitor_meta VALUES (?,?)",
                ("stub_receipt:" + batch.observation_id, json.dumps(asdict(receipt))),
            )
            self.store.db.execute(
                "INSERT OR IGNORE INTO monitor_receipts VALUES (?,?)",
                (batch.observation_id, json.dumps(asdict(receipt))),
            )
        return receipt
