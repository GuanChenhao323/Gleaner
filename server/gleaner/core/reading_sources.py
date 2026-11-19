"""Saved query sources and a single durable schedule. Browsers own website sessions."""

from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import Callable
from typing import Any

from ..net.http import Request, Response, Router
from ..storage.db import Database, loads
from .capture_context import CaptureFence
from .capture_snapshot import CaptureSnapshotProjector
from .monitors import BrowserMonitorService, ContractError, digest, string
from .protocol_reading import ProtocolReading
from .reading_contract import FAILURES, INTERVALS, ReadingRecipe, semantic_snapshot
from .reading_schedule import ReadingSchedule
from .resident_contract import ResidentContract
from .source_purge import SourcePurgeService
from .web_captures import WebCaptureService

MESSAGES = {
    "revision_conflict": "来源配置已变化，请刷新后重试。",
    "verification_required": "请先通过后台重读测试。",
    "account_unknown": "来源标签无法核对网站账号，请在原网页手动采集。",
    "source_deleted": "信息源已删除；资料与历史按删除时的选择保留。",
    "source_missing": "原资料已删除，不会自动重新创建。",
    "recapture_required": "关联资料已彻底删除，请在原网页重新提取并保存。",
    "result_rejected": "资料已保存；检查结果校验失败，监测已暂停。",
    "delete_first": "请先将来源移入已删除来源，再彻底删除。",
    "shared_document": "资料仍被其他账号或公共来源使用，不能物理删除。",
    "invalid_purge_plan": "删除确认无效，请重新查看删除范围。",
    "purge_plan_expired": "删除确认已过期，请重新查看删除范围。",
    "purge_plan_changed": "关联资料或来源状态已变化，请重新确认删除范围。",
    "stale_lease": "任务已过期或配置已改变，结果没有写入。",
    "not_found": "来源或任务不存在，或不属于当前账号。",
    "invalid_request": "来源检查请求格式异常。",
    "invalid_control": "检查配置格式异常，请刷新后重试。",
}


class ReadingSourceService:
    def __init__(
        self,
        db: Database,
        web: WebCaptureService,
        native: BrowserMonitorService,
        timeline: WebCaptureService | None = None,
        *,
        schedule: ReadingSchedule | None = None,
    ) -> None:
        self.db, self.web, self.native, self.timeline = db, web, native, timeline
        self.protocol = ProtocolReading(self)
        self.recipes = ReadingRecipe()
        self.snapshots = CaptureSnapshotProjector()
        self.fence = CaptureFence(db)
        self.purging = SourcePurgeService(db, self)
        self.notify_purge: Callable[..., Any] | None = None
        self.schedule = schedule or ReadingSchedule()
        self.change_state: Callable[..., Any] | None = None

    @staticmethod
    def envelope(**values: Any) -> dict[str, Any]:
        return {"schema_version": 1, "ok": True, **values}

    def register(self, router: Router, authed: Callable[..., Any]) -> None:
        operations = [
            ("GET", "/api/v1/reading-sources", "list_sources"),
            ("GET", "/api/v1/capture-context", "capture_context"),
            ("GET", "/api/v1/reading-sources/{id}/purge-preview", "purge_preview"),
            ("POST", "/api/v1/reading-sources/{id}/purge", "purge"),
            ("GET", "/api/v1/reading-sources/deleted", "deleted_sources"),
            ("POST", "/api/v1/reading-sources/{id}/restore", "restore"),
            ("PUT", "/api/v1/reading-sources/{id}", "configure"),
            ("POST", "/api/v1/reading-sources/{id}/activate", "activate"),
            ("DELETE", "/api/v1/reading-sources/{id}", "remove"),
            ("POST", "/api/v1/reading-sources/{id}/check", "enqueue"),
            ("GET", "/api/v1/reading-sources/{id}/checks", "checks"),
            ("POST", "/api/v1/reading-devices/heartbeat", "heartbeat"),
            ("POST", "/api/v1/reading-jobs/claim", "claim"),
            ("POST", "/api/v1/reading-jobs/{id}/result", "result"),
        ]

        def handler(operation: str) -> Callable[..., Any]:
            async def run(req: Request, user: dict[str, Any]) -> Response:
                try:
                    args: list[Any] = [user["id"]]
                    if "id" in req.params:
                        args.append(int(req.params["id"]))
                    if req.method != "GET":
                        args.append(req.json())
                    return Response.json_body(await getattr(self, operation)(*args))
                except ContractError as e:
                    return Response.json_body(
                        {
                            "schema_version": 1,
                            "ok": False,
                            "error": e.code,
                            "message": MESSAGES.get(e.code, "来源检查未完成：" + e.code),
                        },
                        e.status,
                    )
                except (TypeError, ValueError, KeyError):
                    return Response.json_body(
                        {"schema_version": 1, "ok": False, "error": "invalid_request"}, 422
                    )

            return run

        for method, path, operation in operations:
            router.add(method, path, authed(handler(operation)))

    async def capture_context(self, uid: int) -> dict[str, Any]:
        return await self.fence.context(uid)

    async def purge_preview(self, uid: int, sid: int) -> dict[str, Any]:
        return await self.purging.preview(uid, sid)

    async def purge(self, uid: int, sid: int, body: Any) -> dict[str, Any]:
        return await self.purging.purge(uid, sid, body)

    async def own(self, uid: int, sid: int, *, include_deleted: bool = False) -> dict[str, Any]:
        row = await self.db.fetchone(
            "SELECT * FROM reading_sources WHERE owner_id = ? AND id = ?", uid, sid
        )
        if not row:
            raise ContractError("not_found", 404)
        if row["deleted"] and not include_deleted:
            raise ContractError("source_deleted", 409)
        return row

    def validate_capture(self, body: dict[str, Any], kind: str) -> dict[str, Any]:
        recipe = self.recipes.validate(body["reading"])
        generic = kind == "generic"
        timeline = kind == "timeline_summary"
        if timeline != (recipe.get("representation") == "timeline_summary"):
            raise ContractError("invalid_reading_recipe")
        if (recipe["source"] == "generic") != generic:
            raise ContractError("invalid_reading_recipe")
        if generic or timeline:
            if (
                recipe["url"] != body["source"]["url"]
                or recipe["query"] != body["query"]
                or recipe["match_scope"] != body["match_scope"]
            ):
                raise ContractError("invalid_reading_recipe")
            if timeline:
                if recipe["binding"] != body["source_binding"]:
                    raise ContractError("invalid_binding")
                return recipe
            if recipe.get("source_label") != body["source_binding"]["label"]:
                raise ContractError("invalid_binding")
            identity = body["source_binding"].get("identity")
            expected = (
                "public"
                if body["source_binding"]["kind"] == "public"
                else identity["account_key"]
                if identity
                else "unverified"
            )
            if identity and recipe.get("account_probe") != {
                "version": 1,
                "kind": identity["probe"],
                "display": identity["display"],
            }:
                raise ContractError("invalid_account_proof")
            if not identity and "account_probe" in recipe:
                raise ContractError("invalid_account_proof")
            if recipe["binding"]["account_key"] != expected:
                raise ContractError("invalid_binding")
        elif recipe["binding"] != body["binding"]:
            raise ContractError("invalid_binding")
        return recipe

    async def attach(
        self, uid: int, body: dict[str, Any], receipt: dict[str, Any], kind: str
    ) -> int | None:
        recipe = self.validate_capture(body, kind)
        if any(r["status"] == "failed" for r in receipt["results"]):
            return None
        baseline = self.snapshots.project(body)
        identity = digest(self.recipes.identity(recipe))
        row = await self.db.fetchone(
            "SELECT * FROM reading_sources WHERE owner_id = ? AND identity_key = ?", uid, identity
        )
        if row and row["deleted"]:
            raise ContractError("source_deleted", 409)
        if row:
            changed_device = row["device_id"] != body["device_id"]
            await self.revoke(row["id"])
            await self.db.execute(
                "UPDATE reading_sources SET device_id = ?, recipe = ?, last_snapshot = ?, revision = revision + 1, verified = ?, mode = ?, paused = ?, pending = '' WHERE id = ?",
                body["device_id"],
                recipe,
                baseline,
                0 if changed_device else row["verified"],
                "manual" if changed_device else row["mode"],
                1 if changed_device else row["paused"],
                row["id"],
            )
            sid = row["id"]
        else:
            sid = await self.db.insert(
                "reading_sources",
                {
                    "owner_id": uid,
                    "device_id": body["device_id"],
                    "identity_key": identity,
                    "recipe": recipe,
                    "last_snapshot": baseline,
                    "created_at": time.time(),
                },
            )
        if "resident" in recipe:
            await self.register_page(uid, body["device_id"], recipe)
            current = await self.own(uid, sid)
            for peer in await self.peers(current):
                if peer["id"] != sid and peer["interval_s"] != recipe["resident"]["interval_s"]:
                    await self.revoke(peer["id"])
                    await self.db.execute(
                        "UPDATE reading_sources SET recipe = ?, interval_s = ?, next_at = ?, revision = revision + 1 WHERE id = ?",
                        ResidentContract.at_interval(
                            loads(peer["recipe"]), recipe["resident"]["interval_s"]
                        ),
                        recipe["resident"]["interval_s"],
                        time.time()
                        + self.schedule.interval(
                            {**peer, "interval_s": recipe["resident"]["interval_s"]}
                        ),
                        peer["id"],
                    )
            await self.db.execute(
                "UPDATE reading_sources SET mode = 'periodic', paused = 0, verified = 0, pending = 'activate', interval_s = ?, next_at = 0, failure_count = 0, last_result = 'starting', error = '' WHERE id = ?",
                recipe["resident"]["interval_s"],
                sid,
            )
            receipt["monitoring"] = {
                "state": "starting",
                "mode": "resident",
                "interval_s": recipe["resident"]["interval_s"],
            }
        await self.link(sid, receipt["results"])
        return sid

    async def register_page(self, uid: int, device: str, recipe: dict[str, Any]) -> None:
        resident = ResidentContract().validate(recipe["resident"])
        origin = ResidentContract.origin(recipe)
        session = await self.db.fetchone(
            "SELECT session_id FROM reading_sessions WHERE owner_id = ? AND device_id = ? AND origin = ?",
            uid,
            device,
            origin,
        )
        if session and session["session_id"] != resident["session_id"]:
            raise ContractError("single_account_conflict", 409)
        await self.db.execute(
            "INSERT INTO reading_sessions (owner_id, device_id, origin, session_id) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
            uid,
            device,
            origin,
            resident["session_id"],
        )
        view = digest(ResidentContract.page_view(recipe))
        page = await self.db.fetchone(
            "SELECT * FROM reading_pages WHERE owner_id = ? AND device_id = ? AND (page_id = ? OR (url = ? AND view = ?))",
            uid,
            device,
            resident["page_id"],
            recipe["url"],
            view,
        )
        if page and (page["page_id"], page["url"], page["view"], page["session_id"]) != (
            resident["page_id"],
            recipe["url"],
            view,
            resident["session_id"],
        ):
            raise ContractError("view_mismatch", 409)
        await self.db.execute(
            "INSERT INTO reading_pages (owner_id, device_id, page_id, origin, url, session_id, view) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            uid,
            device,
            resident["page_id"],
            origin,
            recipe["url"],
            resident["session_id"],
            view,
        )

    async def peers(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        recipe = loads(row["recipe"])
        page = ResidentContract.group(recipe)
        if not page:
            return [row]
        rows = await self.db.fetch(
            "SELECT * FROM reading_sources WHERE owner_id = ? AND device_id = ? AND deleted = 0 ORDER BY id",
            row["owner_id"],
            row["device_id"],
        )
        return [r for r in rows if ResidentContract.group(loads(r["recipe"])) == page]

    async def activate(self, uid: int, sid: int, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or set(body) != {"revision", "interval_s"}
            or type(body["revision"]) is not int
            or type(body["interval_s"]) is not int
            or body["interval_s"] not in INTERVALS
        ):
            raise ContractError("invalid_control")
        async with self.db.transaction():
            row = await self.own(uid, sid)
            if row["revision"] != body["revision"]:
                raise ContractError("revision_conflict", 409)
            if row["last_result"] == "documents_purged":
                raise ContractError("recapture_required", 409)
            if not await self.has_items(sid):
                raise ContractError("source_missing", 409)
            for peer in await self.peers(row):
                if not await self.has_items(peer["id"]):
                    continue
                await self.revoke(peer["id"])
                await self.db.execute(
                    "UPDATE reading_sources SET mode = 'periodic', paused = 0, verified = 0, pending = 'activate', recipe = ?, interval_s = ?, next_at = 0, failure_count = 0, last_result = 'starting', error = '', revision = revision + 1 WHERE id = ?",
                    ResidentContract.at_interval(loads(peer["recipe"]), body["interval_s"]),
                    body["interval_s"],
                    peer["id"],
                )
            return self.envelope(source_id=sid, status="queued")

    async def deleted_sources(self, uid: int) -> dict[str, Any]:
        rows = await self.db.fetch(
            "SELECT id, revision, recipe FROM reading_sources WHERE owner_id = ? AND deleted = 1 ORDER BY id DESC LIMIT 200",
            uid,
        )
        return self.envelope(sources=[{**row, "recipe": loads(row["recipe"])} for row in rows])

    async def restore(self, uid: int, sid: int, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or set(body) != {"revision"}
            or type(body["revision"]) is not int
        ):
            raise ContractError("invalid_request")
        async with self.db.transaction():
            row = await self.own(uid, sid, include_deleted=True)
            if not row["deleted"]:
                if (
                    row["revision"] == body["revision"] + 1
                    and row["paused"]
                    and loads(row["delete_result"], {}).get("restored_from") == body["revision"]
                ):
                    return self.envelope(
                        source_id=sid, restored=True, revision=row["revision"], paused=True
                    )
                raise ContractError("revision_conflict", 409)
            if row["revision"] != body["revision"]:
                raise ContractError("revision_conflict", 409)
            await self.revoke(sid)
            history = {**loads(row["delete_result"], {}), "restored_from": body["revision"]}
            await self.db.execute(
                "UPDATE reading_sources SET deleted = 0, delete_result = ?, paused = 1, verified = 0, mode = 'manual', pending = '', next_at = 0, last_result = 'restored', error = '', revision = revision + 1 WHERE id = ?",
                history,
                sid,
            )
            return self.envelope(
                source_id=sid, restored=True, revision=row["revision"] + 1, paused=True
            )

    async def guard_capture(self, uid: int, body: dict[str, Any], kind: str) -> None:
        recipe = self.validate_capture(body, kind)
        row = await self.db.fetchone(
            "SELECT deleted FROM reading_sources WHERE owner_id = ? AND identity_key = ?",
            uid,
            digest(self.recipes.identity(recipe)),
        )
        if row and row["deleted"]:
            raise ContractError("source_deleted", 409)
        if not row and "resident" in recipe:
            rows = await self.db.fetch(
                "SELECT recipe FROM reading_sources WHERE owner_id = ? AND device_id = ? AND deleted = 0",
                uid,
                body["device_id"],
            )
            if (
                sum(
                    ResidentContract.group(loads(r["recipe"])) == ResidentContract.group(recipe)
                    for r in rows
                )
                >= 10
            ):
                raise ContractError("source_limit", 409)

    async def pause_empty(self, uid: int, item_id: int) -> None:
        rows = await self.db.fetch(
            "SELECT r.id FROM reading_sources r JOIN reading_source_items link ON link.reading_id = r.id WHERE r.owner_id = ? AND r.deleted = 0 AND link.item_id = ?",
            uid,
            item_id,
        )
        for row in rows:
            if not await self.has_items(row["id"]):
                await self.revoke(row["id"])
                await self.db.execute(
                    "UPDATE reading_sources SET paused = 1, pending = '', revision = revision + 1, last_result = 'documents_trashed' WHERE id = ?",
                    row["id"],
                )

    async def mark_documents_visible(self, uid: int, item_id: int) -> None:
        rows = await self.db.fetch(
            "SELECT r.id FROM reading_sources r JOIN reading_source_items link ON link.reading_id = r.id WHERE r.owner_id = ? AND r.deleted = 0 AND r.last_result = 'documents_trashed' AND link.item_id = ?",
            uid,
            item_id,
        )
        for row in rows:
            if await self.has_items(row["id"]):
                await self.db.execute(
                    "UPDATE reading_sources SET last_result = 'documents_restored', paused = 1 WHERE id = ?",
                    row["id"],
                )

    async def remove(self, uid: int, sid: int, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or set(body) != {"revision", "trash_items"}
            or type(body["revision"]) is not int
            or type(body["trash_items"]) is not bool
        ):
            raise ContractError("invalid_request")
        async with self.db.transaction():
            row = await self.own(uid, sid, include_deleted=True)
            if row["deleted"]:
                previous = loads(row["delete_result"])
                if previous["trash_items"] != body["trash_items"]:
                    raise ContractError("idempotency_conflict", 409)
                return previous
            if row["revision"] != body["revision"]:
                raise ContractError("revision_conflict", 409)
            await self.revoke(sid)
            ids = await self.db.fetch(
                "SELECT item_id FROM reading_source_items WHERE reading_id = ?", sid
            )
            trashed = []
            if body["trash_items"]:
                if self.change_state is None:
                    raise ContractError("lifecycle_unavailable", 503)
                for item in ids:
                    status, _ = await self.change_state(
                        uid, item["item_id"], {"hidden": True}, None
                    )
                    if status != 200:
                        raise ContractError("lifecycle_failed", 409)
                    trashed.append(item["item_id"])
            response = self.envelope(
                source_id=sid,
                deleted=True,
                trash_items=body["trash_items"],
                trashed_item_ids=trashed,
            )
            await self.db.execute(
                "UPDATE reading_sources SET deleted = 1, paused = 1, verified = 0, pending = '', revision = revision + 1, delete_result = ? WHERE id = ?",
                response,
                sid,
            )
            # Retain subscriptions, documents and versions. Only this owner's browser tasks stop.
            for item in ids:
                await self.db.execute(
                    "UPDATE browser_monitors SET enabled = 0, revision = revision + 1 WHERE owner_id = ? AND item_id = ?",
                    uid,
                    item["item_id"],
                )
            return response

    async def link(self, sid: int, results: list[dict[str, Any]]) -> None:
        await self.db.execute("DELETE FROM reading_source_items WHERE reading_id = ?", sid)
        for iid in {r["item_id"] for r in results if r["status"] != "failed"}:
            await self.db.execute(
                "INSERT INTO reading_source_items (reading_id, item_id) VALUES (?, ?)", sid, iid
            )

    async def revoke(self, sid: int) -> None:
        await self.db.execute(
            "UPDATE reading_jobs SET finished_at = ? WHERE reading_id = ? AND finished_at IS NULL",
            time.time(),
            sid,
        )

    async def has_items(self, sid: int) -> bool:
        return bool(
            await self.db.fetchval(
                "SELECT COUNT(*) FROM reading_source_items r JOIN reading_sources s ON s.id = r.reading_id JOIN items i ON i.id = r.item_id LEFT JOIN user_item_state st ON st.item_id = i.id AND st.user_id = s.owner_id WHERE r.reading_id = ? AND i.deleted = 0 AND COALESCE(st.hidden, 0) = 0",
                sid,
            )
        )

    async def list_sources(self, uid: int) -> dict[str, Any]:
        rows = await self.db.fetch(
            "SELECT * FROM reading_sources WHERE owner_id = ? AND deleted = 0 ORDER BY id DESC LIMIT 200",
            uid,
        )
        values = []
        now = time.time()
        recent_presence = {
            (p["device_id"], p["page_id"]): p["state"]
            for p in await self.db.fetch(
                "SELECT device_id, page_id, state FROM reading_page_presence WHERE owner_id = ? AND seen_at > ?",
                uid,
                now - 150,
            )
        }
        for row in rows:
            recipe = loads(row["recipe"])
            baseline = loads(row["last_snapshot"])
            items = await self.db.fetch(
                "SELECT i.id, i.title, i.version, i.source_id, i.url FROM reading_source_items r JOIN items i ON i.id = r.item_id WHERE r.reading_id = ? AND i.deleted = 0 ORDER BY i.id",
                row["id"],
            )
            if not items:
                continue
            device = await self.db.fetchone(
                "SELECT last_seen_at FROM reading_devices WHERE owner_id = ? AND device_id = ?",
                uid,
                row["device_id"],
            )
            job = await self.db.fetchone(
                "SELECT id, purpose, expires_at, claimed_at FROM reading_jobs WHERE reading_id = ? AND revision = ? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
                row["id"],
                row["revision"],
            )
            expired = bool(job and job["expires_at"] <= now)
            capability = (
                "account_unknown"
                if recipe["binding"]["account_key"] == "unverified" and "resident" not in recipe
                else "ready"
                if row["verified"]
                else "unverified"
            )
            values.append(
                {
                    **{
                        k: row[k]
                        for k in (
                            "id",
                            "device_id",
                            "revision",
                            "mode",
                            "interval_s",
                            "last_result",
                            "last_attempt_at",
                            "last_success_at",
                            "next_at",
                            "error",
                            "pending",
                        )
                    },
                    "paused": bool(row["paused"]),
                    "verified": bool(row["verified"]),
                    "recipe": recipe,
                    "match_count": len(baseline.get("fragments", baseline.get("targets", []))),
                    "capability": capability,
                    "items": items,
                    "page_presence": recent_presence.get(
                        (row["device_id"], ResidentContract.group(recipe)), "unknown"
                    ),
                    "device_online": bool(device and device["last_seen_at"] > now - 150),
                    "effective_interval_s": self.schedule.interval(row),
                    "active_job": None if expired else job,
                    "execution_state": "expired"
                    if expired
                    else "running"
                    if job
                    else "queued"
                    if row["pending"]
                    else "idle",
                }
            )
        return self.envelope(sources=values)

    @staticmethod
    def device_request(body: Any) -> str:
        if not isinstance(body, dict) or set(body) != {"device_id"}:
            raise ContractError("invalid_request")
        return string(body["device_id"], 100)

    async def heartbeat(self, uid: int, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ContractError("invalid_request")
        device = self.device_request({k: v for k, v in body.items() if k != "pages"})
        pages = body.get("pages", {})
        if (
            not isinstance(pages, dict)
            or len(pages) > 2000
            or any(
                not isinstance(k, str) or len(k) != 36 or v not in ("present", "absent", "unknown")
                for k, v in pages.items()
            )
        ):
            raise ContractError("invalid_request")
        now = time.time()
        async with self.db.transaction():
            await self.fence.lock(uid)
            await self.db.execute(
                "INSERT INTO reading_devices (owner_id, device_id, last_seen_at) VALUES (?, ?, ?) ON CONFLICT(owner_id, device_id) DO UPDATE SET last_seen_at = excluded.last_seen_at",
                uid,
                device,
                now,
            )
            await self.db.execute(
                "DELETE FROM reading_page_presence WHERE owner_id = ? AND device_id = ?",
                uid,
                device,
            )
            for page, state in pages.items():
                await self.db.execute(
                    "INSERT INTO reading_page_presence (owner_id, device_id, page_id, state, seen_at) "
                    "SELECT owner_id, device_id, page_id, ?, ? FROM reading_pages WHERE owner_id = ? AND device_id = ? AND page_id = ?",
                    state,
                    now,
                    uid,
                    device,
                    page,
                )
        return self.envelope(device_id=device)

    async def configure(self, uid: int, sid: int, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or set(body) != {"revision", "mode", "paused", "interval_s"}
            or type(body["revision"]) is not int
            or body["mode"] not in ("manual", "periodic")
            or type(body["paused"]) is not bool
            or type(body["interval_s"]) is not int
            or body["interval_s"] not in INTERVALS
        ):
            raise ContractError("invalid_control")
        async with self.db.transaction():
            row = await self.own(uid, sid)
            if row["revision"] != body["revision"]:
                raise ContractError("revision_conflict", 409)
            if row["last_result"] == "documents_purged":
                raise ContractError("recapture_required", 409)
            if not await self.has_items(sid):
                raise ContractError("source_missing", 409)
            if body["mode"] == "periodic" and not body["paused"] and not row["verified"]:
                raise ContractError("verification_required", 409)
            for peer in await self.peers(row):
                if not await self.has_items(peer["id"]):
                    continue
                if body["mode"] == "periodic" and not body["paused"] and not peer["verified"]:
                    raise ContractError("verification_required", 409)
                await self.revoke(peer["id"])
                await self.db.execute(
                    "UPDATE reading_sources SET mode = ?, paused = ?, recipe = ?, interval_s = ?, revision = revision + 1, next_at = ?, pending = '' WHERE id = ?",
                    body["mode"],
                    body["paused"],
                    ResidentContract.at_interval(loads(peer["recipe"]), body["interval_s"]),
                    body["interval_s"],
                    time.time()
                    + self.schedule.interval({**peer, "interval_s": body["interval_s"]}),
                    peer["id"],
                )
            return self.envelope(revision=row["revision"] + 1)

    async def enqueue(self, uid: int, sid: int, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or set(body) != {"revision", "purpose"}
            or type(body["revision"]) is not int
            or body["purpose"] not in ("verify", "check")
        ):
            raise ContractError("invalid_request")
        async with self.db.transaction():
            row = await self.own(uid, sid)
            if row["revision"] != body["revision"]:
                raise ContractError("revision_conflict", 409)
            if row["last_result"] == "documents_purged":
                raise ContractError("recapture_required", 409)
            if not await self.has_items(sid):
                raise ContractError("source_missing", 409)
            if loads(row["recipe"])["binding"][
                "account_key"
            ] == "unverified" and "resident" not in loads(row["recipe"]):
                raise ContractError("account_unknown", 409)
            if body["purpose"] == "check" and not row["verified"]:
                raise ContractError("verification_required", 409)
            active = await self.db.fetchone(
                "SELECT id FROM reading_jobs WHERE reading_id = ? AND revision = ? AND finished_at IS NULL",
                sid,
                row["revision"],
            )
            for peer in await self.peers(row):
                if await self.has_items(peer["id"]) and (
                    body["purpose"] != "check" or peer["verified"]
                ):
                    await self.db.execute(
                        "UPDATE reading_sources SET pending = ? WHERE id = ?",
                        body["purpose"],
                        peer["id"],
                    )
            return self.envelope(
                status="queued", source_id=sid, job_id=active["id"] if active else None
            )

    @staticmethod
    def due(row: dict[str, Any], now: float) -> bool:
        return bool(
            row["pending"]
            or (
                row["mode"] == "periodic"
                and not row["paused"]
                and (row["verified"] or "resident" in loads(row["recipe"]))
                and row["next_at"] <= now
            )
        )

    async def lease(self, row: dict[str, Any], now: float) -> dict[str, Any] | None:
        previous = await self.db.fetchone(
            "SELECT * FROM reading_jobs WHERE reading_id = ? AND revision = ? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
            row["id"],
            row["revision"],
        )
        if previous and previous["expires_at"] > now:
            return None
        if previous and previous["attempts"] >= 3:
            await self.finish(row, previous, "worker_interrupted", {}, now)
            return None
        lease = secrets.token_urlsafe(24)
        purpose = (
            previous["purpose"]
            if previous
            else row["pending"] or ("check" if row["verified"] else "activate")
        )
        if previous:
            jid = previous["id"]
            await self.db.execute(
                "UPDATE reading_jobs SET lease = ?, expires_at = ?, claimed_at = ?, attempts = attempts + 1 WHERE id = ?",
                lease,
                now + 180,
                now,
                jid,
            )
        else:
            jid = await self.db.insert(
                "reading_jobs",
                {
                    "reading_id": row["id"],
                    "owner_id": row["owner_id"],
                    "device_id": row["device_id"],
                    "revision": row["revision"],
                    "purpose": purpose,
                    "lease": lease,
                    "expires_at": now + 180,
                    "claimed_at": now,
                },
            )
        await self.db.execute(
            "UPDATE reading_sources SET pending = '', last_attempt_at = ? WHERE id = ?",
            now,
            row["id"],
        )
        return {
            "id": jid,
            "source_id": row["id"],
            "device_id": row["device_id"],
            "revision": row["revision"],
            "lease": lease,
            "expires_at": now + 180,
            "purpose": purpose,
            "interval_s": row["interval_s"],
            "recipe": loads(row["recipe"]),
        }

    async def claim(self, uid: int, body: Any) -> dict[str, Any]:
        device = self.device_request(body)
        now = time.time()
        async with self.db.transaction():
            await self.fence.lock(uid)
            if await self.db.fetchone(
                "SELECT j.id FROM reading_jobs j JOIN reading_sources s ON s.id = j.reading_id WHERE j.owner_id = ? AND j.device_id = ? AND j.finished_at IS NULL AND j.expires_at > ? AND j.revision = s.revision AND s.deleted = 0",
                uid,
                device,
                now,
            ):
                return self.envelope(job=None)
            rows = await self.db.fetch(
                "SELECT * FROM reading_sources WHERE owner_id = ? AND device_id = ? AND deleted = 0 ORDER BY CASE WHEN pending != '' THEN 0 ELSE 1 END, next_at, id",
                uid,
                device,
            )
            eligible = []
            for row in rows:
                if not await self.has_items(row["id"]):
                    await self.revoke(row["id"])
                    available = await self.db.fetchval(
                        "SELECT COUNT(*) FROM reading_source_items link JOIN items i ON i.id = link.item_id WHERE link.reading_id = ? AND i.deleted = 0",
                        row["id"],
                    )
                    await self.db.execute(
                        "UPDATE reading_sources SET verified = ?, paused = 1, pending = '', last_result = ? WHERE id = ?",
                        row["verified"] if available else 0,
                        "documents_trashed" if available else "source_missing",
                        row["id"],
                    )
                    continue
                previous = await self.db.fetchone(
                    "SELECT id FROM reading_jobs WHERE reading_id = ? AND revision = ? AND finished_at IS NULL",
                    row["id"],
                    row["revision"],
                )
                if await self.protocol.eligible(row, now):
                    continue
                if self.due(row, now) or previous:
                    eligible.append(row)
            if not eligible:
                return self.envelope(job=None)
            first = eligible[0]
            page = ResidentContract.group(loads(first["recipe"]))
            peers = await self.peers(first) if page else [first]
            # All active rules on this page share its fetch cycle, including near-due rules.
            selected = [first] + [
                r
                for r in peers
                if r["id"] != first["id"]
                and not r["paused"]
                and not await self.protocol.eligible(r, now)
                and r["mode"] == "periodic"
                and await self.has_items(r["id"])
            ]
            jobs = []
            for row in selected[:10]:
                job = await self.lease(row, now)
                if job:
                    jobs.append(job)
            if not jobs:
                return self.envelope(job=None)
            if len(jobs) > 1:
                jobs[0]["companions"] = jobs[1:]
            return self.envelope(job=jobs[0])

    def snapshot(self, row: dict[str, Any], snapshot: Any) -> dict[str, Any]:
        recipe = loads(row["recipe"])
        # Existing 0.13 baselines may contain request-control metadata.
        base = self.snapshots.project(loads(row["last_snapshot"]))
        if not isinstance(snapshot, dict):
            raise ContractError("invalid_snapshot")
        generic = recipe["source"] == "generic"
        timeline = recipe.get("representation") == "timeline_summary"
        if generic or timeline:
            # Preserve the saved collection identity and title; changing text does not
            # authorize a new URL, label, query, owner or native target identity.
            value = {
                **base,
                "request_id": str(uuid.uuid4()),
                "observed_at": snapshot.get("observed_at"),
                "fragments": snapshot.get("fragments"),
            }
            if (
                not isinstance(snapshot.get("source"), dict)
                or snapshot["source"].get("url") != base["source"]["url"]
            ):
                raise ContractError("scope_mismatch")
            for key in ("query", "match_scope", "source_binding"):
                if snapshot.get(key) != base[key]:
                    raise ContractError("scope_mismatch")
            if timeline and snapshot.get("collection_type") != "timeline_summary":
                raise ContractError("scope_mismatch")
            service = self.timeline if timeline else self.web
            if service is None:
                raise ContractError("unsupported")
            service.contract.validate(value)
        else:
            if snapshot.get("binding") != base["binding"]:
                raise ContractError("account_mismatch")
            targets = snapshot.get("targets")
            if not isinstance(targets, list) or not 1 <= len(targets) <= 30:
                raise ContractError("invalid_targets")
            if len({t.get("entity_id") for t in targets}) != len(targets):
                raise ContractError("duplicate_candidates")
            for target in targets:
                self.native.target(target, base["binding"])
                if target["recipe"].get("version") != 2 or target.get("enabled") is not False:
                    raise ContractError("invalid_snapshot")
                if any(
                    target["locator"]["view"].get(k, target["raw"].get("fields", {}).get(k)) != v
                    for k, v in recipe["view"].items()
                ):
                    raise ContractError("view_mismatch")
            value = {**base, "targets": targets}
        return value

    async def finish(
        self,
        row: dict[str, Any],
        job: dict[str, Any],
        result: str,
        detail: dict[str, Any],
        now: float,
    ) -> dict[str, Any]:
        invalidates = result in {
            "need_login",
            "account_mismatch",
            "account_unknown",
            "route_mismatch",
            "view_mismatch",
            "permission_denied",
            "private_source_required",
            "unsupported",
            "tab_missing",
            "tab_rebind_required",
            "tab_ambiguous",
            "single_account_conflict",
            "result_rejected",
        }
        resident = "resident" in loads(row["recipe"]) or job["purpose"] == "activate"
        success = result in {"verified", "changed", "unchanged"}
        count = (
            0
            if success or result in {"user_busy", "waiting_page", "protocol_unavailable"}
            else row.get("failure_count", 0) + 1
        )
        pause = invalidates or (resident and count >= 3)
        next_at = now + (60 if result == "user_busy" else self.schedule.interval(row))
        if resident and success:
            peers = await self.peers(row)
            future = [
                r["next_at"]
                for r in peers
                if r["id"] != row["id"] and r["verified"] and r["next_at"] > now
            ]
            next_at = min(future) if future else job["claimed_at"] + self.schedule.interval(row)
        await self.db.execute(
            "UPDATE reading_sources SET failure_count = ? WHERE id = ?", count, row["id"]
        )
        await self.db.execute(
            "UPDATE reading_sources SET last_result = ?, error = ?, next_at = ?, pending = '', verified = ?, paused = ? WHERE id = ?",
            result,
            "" if result in {"verified", "changed", "unchanged"} else result,
            next_at,
            0 if invalidates else row["verified"],
            1 if pause else row["paused"],
            row["id"],
        )
        await self.db.insert(
            "reading_checks",
            {
                "reading_id": row["id"],
                "job_id": job["id"],
                "purpose": job["purpose"],
                "result": result,
                "detail": detail,
                "checked_at": now,
            },
        )
        ack = self.envelope(
            job_id=job["id"],
            status="changed"
            if result == "changed"
            else "unchanged"
            if result in {"verified", "unchanged"}
            else "failed",
            result=result,
        )
        await self.db.execute(
            "UPDATE reading_jobs SET finished_at = ?, response = ? WHERE id = ?",
            now,
            ack,
            job["id"],
        )
        return ack

    async def result(self, uid: int, jid: int, body: Any) -> dict[str, Any]:
        try:
            return await self.apply_result(uid, jid, body)
        except ContractError as error:
            if error.status == 422:
                await self.record_rejection(uid, jid, body, error.code)
            raise
        except (TypeError, ValueError, KeyError) as error:
            await self.record_rejection(uid, jid, body, "invalid_request")
            raise ContractError("invalid_request") from error

    async def record_rejection(self, uid: int, jid: int, body: Any, code: str) -> None:
        """A bad payload can finish only its own current lease, after content rollback."""
        if not isinstance(body, dict) or type(body.get("revision")) is not int:
            return
        async with self.db.transaction():
            await self.fence.lock(uid)
            job = await self.db.fetchone(
                "SELECT * FROM reading_jobs WHERE owner_id = ? AND id = ?", uid, jid
            )
            now = time.time()
            if (
                not job
                or job["finished_at"] is not None
                or job["expires_at"] <= now
                or body.get("device_id") != job["device_id"]
                or body.get("lease") != job["lease"]
                or body["revision"] != job["revision"]
            ):
                return
            row = await self.db.fetchone(
                "SELECT * FROM reading_sources WHERE owner_id = ? AND id = ? AND deleted = 0",
                uid,
                job["reading_id"],
            )
            if not row or row["revision"] != job["revision"] or not await self.has_items(row["id"]):
                return
            ack = await self.finish(row, job, "result_rejected", {"error": code}, now)
            await self.db.execute(
                "UPDATE reading_jobs SET digest = ?, response = ? WHERE id = ?",
                digest(body),
                {**ack, "error": code},
                jid,
            )

    async def apply_result(self, uid: int, jid: int, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or type(body.get("schema_version")) is not int
            or body.get("schema_version") != 1
        ):
            raise ContractError("schema_version")
        allowed = {"schema_version", "device_id", "lease", "revision", "status"}
        if body.get("status") == "success":
            allowed |= {"account_key", "snapshot"}
            if "resident" in body:
                allowed.add("resident")
        if set(body) != allowed or type(body.get("revision")) is not int:
            raise ContractError("invalid_request")
        async with self.db.transaction():
            await self.fence.lock(uid)
            job = await self.db.fetchone(
                "SELECT * FROM reading_jobs WHERE owner_id = ? AND id = ?", uid, jid
            )
            if not job:
                raise ContractError("not_found", 404)
            if body.get("device_id") != job["device_id"] or body.get("lease") != job["lease"]:
                raise ContractError("stale_lease", 409)
            signature = digest(body)
            if job["response"]:
                if job["digest"] != signature:
                    raise ContractError("idempotency_conflict", 409)
                previous = loads(job["response"])
                if previous.get("result") == "result_rejected":
                    raise ContractError(previous["error"], 422)
                return previous
            row = await self.own(uid, job["reading_id"])
            if not await self.has_items(row["id"]):
                raise ContractError("stale_lease", 409)
            now = time.time()
            if (
                body.get("revision") != row["revision"]
                or job["revision"] != row["revision"]
                or job["expires_at"] <= now
            ):
                raise ContractError("stale_lease", 409)
            if "resident" in body and job["purpose"] != "activate":
                raise ContractError("invalid_request")
            result = body.get("status")
            if result != "success" and result not in FAILURES:
                raise ContractError("invalid_check_status")
            details: dict[str, Any] = {}
            if result == "success":
                if body.get("account_key") != loads(row["recipe"])["binding"]["account_key"]:
                    result = "account_mismatch"
                else:
                    if job["purpose"] == "activate":
                        resident = ResidentContract().validate(body.get("resident"))
                        if resident["interval_s"] != row["interval_s"]:
                            raise ContractError("invalid_resident")
                        recipe = loads(row["recipe"])
                        if "resident" in recipe and (
                            resident["session_id"],
                            resident["page_id"],
                        ) != (recipe["resident"]["session_id"], recipe["resident"]["page_id"]):
                            raise ContractError("invalid_resident")
                        recipe["resident"] = resident
                        recipe = self.recipes.validate(recipe)
                        await self.register_page(uid, row["device_id"], recipe)
                        row["recipe"] = recipe
                        row["verified"] = 1
                        row["mode"], row["paused"] = "periodic", 0
                        await self.db.execute(
                            "UPDATE reading_sources SET recipe = ?, verified = 1, mode = 'periodic', paused = 0 WHERE id = ?",
                            recipe,
                            row["id"],
                        )
                    value = self.snapshot(row, body.get("snapshot"))
                    if job["purpose"] == "verify":
                        result = "verified"
                        row["verified"] = 1
                        await self.db.execute(
                            "UPDATE reading_sources SET verified = 1 WHERE id = ?", row["id"]
                        )
                    else:
                        recipe = loads(row["recipe"])
                        generic = recipe["source"] == "generic"
                        timeline = recipe.get("representation") == "timeline_summary"
                        changed = semantic_snapshot(
                            value, generic or timeline
                        ) != semantic_snapshot(loads(row["last_snapshot"]), generic or timeline)
                        result = "changed" if changed else "unchanged"
                        if changed:
                            value["request_id"] = str(
                                uuid.uuid5(uuid.NAMESPACE_URL, f"reading:{uid}:{jid}")
                            )
                            if timeline:
                                if self.timeline is None:
                                    raise ContractError("unsupported")
                                receipt = await self.timeline.capture(
                                    uid, value, from_reading_job=True
                                )
                            else:
                                receipt = await (self.web if generic else self.native).capture(
                                    uid, value, from_reading_job=True
                                )
                            if any(r["status"] == "failed" for r in receipt["results"]):
                                raise ContractError("capture_failed", 409)
                            await self.link(row["id"], receipt["results"])
                            details = {"results": receipt["results"]}
                            await self.db.execute(
                                "UPDATE reading_sources SET last_snapshot = ? WHERE id = ?",
                                value,
                                row["id"],
                            )
                        await self.db.execute(
                            "UPDATE reading_sources SET last_success_at = ? WHERE id = ?",
                            now,
                            row["id"],
                        )
            ack = await self.finish(row, job, result, details, now)
            await self.db.execute("UPDATE reading_jobs SET digest = ? WHERE id = ?", signature, jid)
            return ack

    async def checks(self, uid: int, sid: int) -> dict[str, Any]:
        await self.own(uid, sid)
        rows = await self.db.fetch(
            "SELECT job_id, purpose, result, detail, checked_at FROM reading_checks WHERE reading_id = ? ORDER BY id DESC LIMIT 50",
            sid,
        )
        return self.envelope(checks=[{**r, "detail": loads(r["detail"], {})} for r in rows])
