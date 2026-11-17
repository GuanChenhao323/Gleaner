"""Explicit, signed erasure plans. No source tombstone or purge receipt is retained."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import TYPE_CHECKING, Any

from .. import security
from ..storage.db import Database, loads
from .capture_context import CaptureFence
from .monitors import ContractError, compact

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .reading_sources import ReadingSourceService


class SourcePurgeService:
    def __init__(self, db: Database, reading: ReadingSourceService) -> None:
        self.db, self.reading, self.fence = db, reading, CaptureFence(db)

    def sign(self, plan: dict[str, Any]) -> str:
        return hmac.new(
            security.secret(), ("source-purge-v1:" + compact(plan)).encode(), hashlib.sha256
        ).hexdigest()

    async def plan(self, uid: int, sid: int, expires: float) -> dict[str, Any]:
        row = await self.reading.own(uid, sid, include_deleted=True)
        if not row["deleted"]:
            raise ContractError("delete_first", 409)
        items = await self.db.fetch(
            "SELECT i.id, i.version, i.source_id, s.owner_id, s.type FROM reading_source_items l JOIN items i ON i.id = l.item_id JOIN sources s ON s.id = i.source_id WHERE l.reading_id = ? ORDER BY i.id",
            sid,
        )
        for item in items:
            if item["owner_id"] != uid or item["type"] != "browser":
                raise ContractError("shared_document", 409)
            if await self.db.fetchval(
                "SELECT COUNT(*) FROM subscriptions WHERE source_id = ? AND user_id != ?",
                item["source_id"],
                uid,
            ):
                raise ContractError("shared_document", 409)
            if await self.db.fetchval(
                "SELECT COUNT(*) FROM user_item_state WHERE item_id = ? AND user_id != ?",
                item["id"],
                uid,
            ):
                raise ContractError("shared_document", 409)
            if await self.db.fetchval(
                "SELECT COUNT(*) FROM reading_source_items l JOIN reading_sources r ON r.id = l.reading_id WHERE l.item_id = ? AND r.owner_id != ?",
                item["id"],
                uid,
            ):
                raise ContractError("shared_document", 409)
            if await self.db.fetchval(
                "SELECT COUNT(*) FROM deliveries WHERE item_id = ? AND user_id != ?",
                item["id"],
                uid,
            ):
                raise ContractError("shared_document", 409)
        ids = {i["id"] for i in items}
        affected = []
        for other in await self.db.fetch(
            "SELECT id, revision FROM reading_sources WHERE owner_id = ? AND id != ? ORDER BY id",
            uid,
            sid,
        ):
            links = await self.db.fetch(
                "SELECT item_id FROM reading_source_items WHERE reading_id = ?", other["id"]
            )
            linked = {i["item_id"] for i in links}
            if linked & ids:
                affected.append({**other, "remaining": len(linked - ids)})
        versions = sum(
            [
                await self.db.fetchval("SELECT COUNT(*) FROM item_versions WHERE item_id = ?", iid)
                for iid in ids
            ]
        )
        checks = sum(
            [
                await self.db.fetchval(
                    "SELECT COUNT(*) FROM reading_checks WHERE reading_id = ?", rid
                )
                for rid in [sid, *[r["id"] for r in affected]]
            ]
        )
        return {
            "owner_id": uid,
            "source_id": sid,
            "revision": row["revision"],
            "generation": await self.fence.generation(uid),
            "items": [{k: i[k] for k in ("id", "version", "source_id")} for i in items],
            "affected": affected,
            "version_count": versions,
            "check_count": checks,
            "expires_at": expires,
        }

    async def preview(self, uid: int, sid: int) -> dict[str, Any]:
        async with self.db.transaction():
            plan = await self.plan(uid, sid, int(time.time()) + 300)
            return self.reading.envelope(plan=plan, token=self.sign(plan))

    @staticmethod
    def references(value: Any, items: set[int], sources: set[int], readings: set[int]) -> bool:
        if isinstance(value, list):
            return any(SourcePurgeService.references(v, items, sources, readings) for v in value)
        if not isinstance(value, dict):
            return False
        if any(
            type(value.get(k)) is int and value[k] in ids
            for k, ids in (
                ("item_id", items),
                ("source_id", sources),
                ("reading_source_id", readings),
            )
        ):
            return True
        if (
            isinstance(value.get("item"), dict)
            and type(value["item"].get("id")) is int
            and value["item"]["id"] in items
        ):
            return True
        return any(
            SourcePurgeService.references(v, items, sources, readings)
            for v in value.values()
            if isinstance(v, (dict, list))
        )

    async def prune_records(
        self, uid: int, items: set[int], sources: set[int], readings: set[int]
    ) -> None:
        for table in ("web_capture_requests", "browser_requests"):
            for row in await self.db.fetch(
                f"SELECT request_id, response FROM {table} WHERE owner_id = ?", uid
            ):
                if self.references(loads(row["response"], {}), items, sources, readings):
                    await self.db.execute(
                        f"DELETE FROM {table} WHERE owner_id = ? AND request_id = ?",
                        uid,
                        row["request_id"],
                    )
        for row in await self.db.fetch("SELECT op_id, result FROM op_log WHERE user_id = ?", uid):
            if self.references(loads(row["result"], {}), items, sources, readings):
                await self.db.execute(
                    "DELETE FROM op_log WHERE user_id = ? AND op_id = ?", uid, row["op_id"]
                )
        for row in await self.db.fetch("SELECT id, data FROM events WHERE user_id = ?", uid):
            if self.references(loads(row["data"], {}), items, sources, readings):
                await self.db.execute("DELETE FROM events WHERE id = ?", row["id"])
        for row in await self.db.fetch(
            "SELECT seq, item_id, payload FROM deliveries WHERE user_id = ?", uid
        ):
            if row["item_id"] in items or self.references(
                loads(row["payload"], {}), items, sources, readings
            ):
                await self.db.execute(
                    "DELETE FROM deliveries WHERE user_id = ? AND seq = ?", uid, row["seq"]
                )
        for iid in items:
            await self.db.execute("DELETE FROM reminders_sent WHERE item_id = ?", iid)

    async def prune_bindings(self, uid: int) -> None:
        rows = await self.db.fetch(
            "SELECT device_id, recipe FROM reading_sources WHERE owner_id = ?", uid
        )
        keep = {
            (r["device_id"], loads(r["recipe"]).get("resident", {}).get("page_id")) for r in rows
        }
        for page in await self.db.fetch(
            "SELECT device_id, page_id FROM reading_pages WHERE owner_id = ?", uid
        ):
            if (page["device_id"], page["page_id"]) not in keep:
                await self.db.execute(
                    "DELETE FROM reading_pages WHERE owner_id = ? AND device_id = ? AND page_id = ?",
                    uid,
                    page["device_id"],
                    page["page_id"],
                )
        for session in await self.db.fetch(
            "SELECT device_id, origin FROM reading_sessions WHERE owner_id = ?", uid
        ):
            if not await self.db.fetchval(
                "SELECT COUNT(*) FROM reading_pages WHERE owner_id = ? AND device_id = ? AND origin = ?",
                uid,
                session["device_id"],
                session["origin"],
            ):
                await self.db.execute(
                    "DELETE FROM reading_sessions WHERE owner_id = ? AND device_id = ? AND origin = ?",
                    uid,
                    session["device_id"],
                    session["origin"],
                )

    def receipt(self, plan: dict[str, Any], generation: int, absent: bool) -> dict[str, Any]:
        return self.reading.envelope(
            source_id=plan["source_id"],
            purged=True,
            item_ids=[i["id"] for i in plan["items"]],
            purged_source_ids=[
                plan["source_id"],
                *[r["id"] for r in plan["affected"] if not r["remaining"]],
            ],
            paused_source_ids=[r["id"] for r in plan["affected"] if r["remaining"]],
            generation=generation,
            already_absent=absent,
        )

    async def purge(self, uid: int, sid: int, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or set(body) != {"plan", "token", "confirm"}
            or body["confirm"] is not True
            or not isinstance(body["plan"], dict)
            or not isinstance(body["token"], str)
        ):
            raise ContractError("invalid_request")
        plan = body["plan"]
        if not hmac.compare_digest(self.sign(plan), body["token"]):
            raise ContractError("invalid_purge_plan")
        if plan.get("owner_id") != uid or plan.get("source_id") != sid:
            raise ContractError("not_found", 404)
        if plan["expires_at"] <= time.time():
            raise ContractError("purge_plan_expired", 409)
        async with self.db.transaction():
            await self.fence.lock(uid)
            row = await self.db.fetchone(
                "SELECT id FROM reading_sources WHERE id = ? AND owner_id = ?", sid, uid
            )
            if not row:
                return self.receipt(plan, await self.fence.generation(uid), True)
            current = await self.plan(uid, sid, plan["expires_at"])
            if current != plan:
                raise ContractError("purge_plan_changed", 409)
            ids = {i["id"] for i in plan["items"]}
            removed = {sid, *[r["id"] for r in plan["affected"] if not r["remaining"]]}
            for rid in removed:
                await self.db.execute(
                    "DELETE FROM reading_sources WHERE id = ? AND owner_id = ?", rid, uid
                )
            for rule in plan["affected"]:
                if rule["remaining"]:
                    await self.reading.revoke(rule["id"])
                    await self.db.execute(
                        "DELETE FROM reading_jobs WHERE reading_id = ?", rule["id"]
                    )
                    await self.db.execute(
                        "DELETE FROM reading_checks WHERE reading_id = ?", rule["id"]
                    )
                    await self.db.execute(
                        "UPDATE reading_sources SET paused = 1, verified = 0, pending = '', last_snapshot = '{}', last_result = 'documents_purged', last_success_at = NULL, revision = revision + 1 WHERE id = ?",
                        rule["id"],
                    )
            for iid in ids:
                await self.db.execute("DELETE FROM items WHERE id = ?", iid)
            empty_sources = set()
            for source in {i["source_id"] for i in plan["items"]}:
                if not await self.db.fetchval(
                    "SELECT COUNT(*) FROM items WHERE source_id = ?", source
                ):
                    empty_sources.add(source)
            await self.prune_records(uid, ids, empty_sources, removed)
            for source in empty_sources:
                await self.db.execute(
                    "DELETE FROM sources WHERE id = ? AND owner_id = ?", source, uid
                )
            await self.prune_bindings(uid)
            await self.db.execute(
                "UPDATE users SET capture_generation = capture_generation + 1 WHERE id = ?", uid
            )
            generation = await self.fence.generation(uid)
            result = self.receipt(plan, generation, False)
        if self.reading.notify_purge:
            try:
                await self.reading.notify_purge(
                    f"u.{uid}",
                    {"type": "purged", "item_ids": result["item_ids"], "generation": generation},
                )
            except (OSError, RuntimeError):
                log.warning("Purge committed; live cache notification unavailable")
        return result
