"""Independent SQLite state and transactional observation outbox (no credentials)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import Any

from .models import ApplyReceipt, MonitorSource, MonitorTarget, ObservationBatch, TargetObservation


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS monitor_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS saved_targets (
                item_id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, url TEXT NOT NULL, locator TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS monitor_sources (source_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS monitor_checks (check_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                state TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS monitor_outbox (observation_id TEXT PRIMARY KEY, check_id TEXT UNIQUE NOT NULL,
                source_id TEXT NOT NULL, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS monitor_receipts (observation_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS monitor_requests (request_key TEXT PRIMARY KEY, check_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS monitor_targets (source_id TEXT NOT NULL, item_id INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(source_id,item_id));
        """)

    def close(self) -> None:
        self.db.close()

    def meta(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM monitor_meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put_meta(self, key: str, value: Any) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO monitor_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def save_item(self, item_id: int, owner_id: int, url: str, locator: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO saved_targets VALUES (?,?,?,?)", (item_id, owner_id, url, locator)
            )

    def items(self, item_ids: list[int], owner_id: int) -> list[dict[str, Any]]:
        out = []
        for item_id in item_ids:
            row = self.db.execute(
                "SELECT * FROM saved_targets WHERE item_id=? AND owner_id=?", (item_id, owner_id)
            ).fetchone()
            if row:
                out.append(dict(row))
        return out

    def _write_source(self, source: MonitorSource) -> None:
        self.db.execute(
            "INSERT INTO monitor_sources VALUES (?,?) ON CONFLICT(source_id) DO UPDATE SET payload=excluded.payload",
            (source.source_id, json.dumps(asdict(source))),
        )

    def save_source(self, source: MonitorSource) -> None:
        with self.db:
            self._write_source(source)

    def sources(self) -> list[MonitorSource]:
        rows = self.db.execute("SELECT payload FROM monitor_sources ORDER BY source_id").fetchall()
        out = []
        for row in rows:
            data = json.loads(row[0])
            data["targets"] = [MonitorTarget(**t) for t in data["targets"]]
            out.append(MonitorSource(**data))
        return out

    def source(self, source_id: str) -> MonitorSource | None:
        return next((s for s in self.sources() if s.source_id == source_id), None)

    def check(self, check_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT payload FROM monitor_checks WHERE check_id=?", (check_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def checks(self, source_id: str | None = None) -> list[dict[str, Any]]:
        if source_id:
            rows = self.db.execute(
                "SELECT payload FROM monitor_checks WHERE source_id=? ORDER BY rowid", (source_id,)
            ).fetchall()
        else:
            rows = self.db.execute("SELECT payload FROM monitor_checks ORDER BY rowid").fetchall()
        return [json.loads(row[0]) for row in rows]

    def _write_check(self, check: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO monitor_checks VALUES (?,?,?,?) ON CONFLICT(check_id) DO UPDATE SET state=excluded.state,payload=excluded.payload",
            (check["check_id"], check["source_id"], check["state"], json.dumps(check)),
        )

    def save_check(self, check: dict[str, Any]) -> None:
        with self.db:
            self._write_check(check)

    def request(self, key: str) -> str | None:
        row = self.db.execute(
            "SELECT check_id FROM monitor_requests WHERE request_key=?", (key,)
        ).fetchone()
        return row[0] if row else None

    def save_request(self, key: str, check: dict[str, Any]) -> None:
        with self.db:
            self._write_check(check)
            self.db.execute("INSERT INTO monitor_requests VALUES (?,?)", (key, check["check_id"]))

    def enqueue(self, batch: ObservationBatch, check: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO monitor_outbox (observation_id,check_id,source_id,payload) VALUES (?,?,?,?)",
                (batch.observation_id, batch.check_id, batch.source_id, json.dumps(asdict(batch))),
            )
            self._write_check({**check, "state": "processing"})

    def pending(self) -> list[ObservationBatch]:
        out = []
        for row in self.db.execute("SELECT payload FROM monitor_outbox ORDER BY rowid"):
            data = json.loads(row[0])
            data["entries"] = [TargetObservation(**e) for e in data["entries"]]
            out.append(ObservationBatch(**data))
        return out

    def retry_delivery(self, observation_id: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE monitor_outbox SET attempts=attempts+1 WHERE observation_id=?",
                (observation_id,),
            )

    def receipt(self, observation_id: str) -> ApplyReceipt | None:
        row = self.db.execute(
            "SELECT payload FROM monitor_receipts WHERE observation_id=?", (observation_id,)
        ).fetchone()
        return ApplyReceipt(**json.loads(row[0])) if row else None

    def finish(
        self,
        batch: ObservationBatch,
        check: dict[str, Any],
        source: MonitorSource,
        receipt: ApplyReceipt | None = None,
    ) -> None:
        with self.db:
            if receipt:
                self.db.execute(
                    "INSERT OR IGNORE INTO monitor_receipts VALUES (?,?)",
                    (batch.observation_id, json.dumps(asdict(receipt))),
                )
                for result in receipt.results:
                    old = self.target(source.source_id, result["item_id"])
                    value = {**result}
                    if result["status"] not in ("changed", "unchanged"):
                        value["last_success_at"] = old.get("last_success_at") if old else None
                    self.db.execute(
                        "INSERT INTO monitor_targets VALUES (?,?,?) ON CONFLICT(source_id,item_id) DO UPDATE SET payload=excluded.payload",
                        (source.source_id, result["item_id"], json.dumps(value)),
                    )
            self.db.execute(
                "DELETE FROM monitor_outbox WHERE observation_id=?", (batch.observation_id,)
            )
            self._write_source(source)
            self._write_check(check)

    def target(self, source_id: str, item_id: int) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT payload FROM monitor_targets WHERE source_id=? AND item_id=?",
            (source_id, item_id),
        ).fetchone()
        return json.loads(row[0]) if row else None
