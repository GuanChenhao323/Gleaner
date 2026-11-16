"""Account-wide capture epochs fence previews without retaining erased source identities."""

from typing import Any

from ..storage.db import Database
from .monitors import ContractError


class CaptureFence:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def generation(self, uid: int) -> int:
        return int(
            await self.db.fetchval("SELECT capture_generation FROM users WHERE id = ?", uid) or 0
        )

    async def lock(self, uid: int) -> None:
        # A writer lock also serializes separate PostgreSQL core processes.
        await self.db.execute(
            "UPDATE users SET capture_generation = capture_generation WHERE id = ?", uid
        )

    async def guard(self, uid: int, generation: Any) -> None:
        if type(generation) is not int or not 0 <= generation <= 2**53 - 1:
            raise ContractError("invalid_capture_generation")
        await self.lock(uid)
        if generation != await self.generation(uid):
            raise ContractError("capture_context_changed", 409)

    async def context(self, uid: int) -> dict[str, Any]:
        async with self.db.transaction():
            await self.lock(uid)
            pages = await self.db.fetch(
                "SELECT page_id FROM reading_pages WHERE owner_id = ? ORDER BY page_id", uid
            )
            return {
                "schema_version": 1,
                "ok": True,
                "generation": await self.generation(uid),
                "resident_pages": [r["page_id"] for r in pages],
                "reading_sources": await self.db.fetch(
                    "SELECT id, revision FROM reading_sources WHERE owner_id = ?", uid
                ),
                "monitors": await self.db.fetch(
                    "SELECT id, revision FROM browser_monitors WHERE owner_id = ?", uid
                ),
                "item_ids": [
                    r["id"]
                    for r in await self.db.fetch(
                        "SELECT DISTINCT i.id FROM items i JOIN subscriptions s ON s.source_id = i.source_id WHERE s.user_id = ?",
                        uid,
                    )
                ],
            }
