"""Saved query sources and a single durable schedule. Browsers own website sessions."""

from __future__ import annotations

import copy
import secrets
import time
import uuid
from collections.abc import Callable
from typing import Any

from ..net.http import Request, Response, Router
from ..storage.db import Database, loads
from .monitors import BrowserMonitorService, ContractError, digest, string
from .reading_contract import FAILURES, INTERVALS, ReadingRecipe, semantic_snapshot
from .web_captures import WebCaptureService

MESSAGES = {
    "revision_conflict": "来源配置已变化，请刷新后重试。",
    "verification_required": "请先通过后台重读测试。",
    "account_unknown": "来源标签无法核对网站账号，请在原网页手动采集。",
    "source_deleted": "信息源已删除；资料与历史按删除时的选择保留。",
    "source_missing": "原资料已删除，不会自动重新创建。",
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
    ) -> None:
        self.db, self.web, self.native, self.timeline = db, web, native, timeline
        self.recipes = ReadingRecipe()
        self.change_state: Callable[..., Any] | None = None

    @staticmethod
    def envelope(**values: Any) -> dict[str, Any]:
        return {"schema_version": 1, "ok": True, **values}

    def register(self, router: Router, authed: Callable[..., Any]) -> None:
        operations = [
            ("GET", "/api/v1/reading-sources", "list_sources"),
            ("GET", "/api/v1/reading-sources/deleted", "deleted_sources"),
            ("POST", "/api/v1/reading-sources/{id}/restore", "restore"),
            ("PUT", "/api/v1/reading-sources/{id}", "configure"),
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
        baseline = {k: copy.deepcopy(v) for k, v in body.items() if k != "reading"}
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
        await self.link(sid, receipt["results"])
        return sid

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
            capability = (
                "account_unknown"
                if recipe["binding"]["account_key"] == "unverified"
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
                    "device_online": bool(device and device["last_seen_at"] > now - 150),
                    "active_job": job,
                }
            )
        return self.envelope(sources=values)

    @staticmethod
    def device_request(body: Any) -> str:
        if not isinstance(body, dict) or set(body) != {"device_id"}:
            raise ContractError("invalid_request")
        return string(body["device_id"], 100)

    async def heartbeat(self, uid: int, body: Any) -> dict[str, Any]:
        device = self.device_request(body)
        await self.db.execute(
            "INSERT INTO reading_devices (owner_id, device_id, last_seen_at) VALUES (?, ?, ?) ON CONFLICT(owner_id, device_id) DO UPDATE SET last_seen_at = excluded.last_seen_at",
            uid,
            device,
            time.time(),
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
            if not await self.has_items(sid):
                raise ContractError("source_missing", 409)
            if body["mode"] == "periodic" and not row["verified"]:
                raise ContractError("verification_required", 409)
            await self.revoke(sid)
            await self.db.execute(
                "UPDATE reading_sources SET mode = ?, paused = ?, interval_s = ?, revision = revision + 1, next_at = ?, pending = '' WHERE id = ?",
                body["mode"],
                body["paused"],
                body["interval_s"],
                time.time() + body["interval_s"],
                sid,
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
            if not await self.has_items(sid):
                raise ContractError("source_missing", 409)
            if loads(row["recipe"])["binding"]["account_key"] == "unverified":
                raise ContractError("account_unknown", 409)
            if body["purpose"] == "check" and not row["verified"]:
                raise ContractError("verification_required", 409)
            active = await self.db.fetchone(
                "SELECT id FROM reading_jobs WHERE reading_id = ? AND revision = ? AND finished_at IS NULL",
                sid,
                row["revision"],
            )
            await self.db.execute(
                "UPDATE reading_sources SET pending = ? WHERE id = ?", body["purpose"], sid
            )
            return self.envelope(
                status="queued", source_id=sid, job_id=active["id"] if active else None
            )

    async def claim(self, uid: int, body: Any) -> dict[str, Any]:
        device = self.device_request(body)
        now = time.time()
        async with self.db.transaction():
            active = await self.db.fetchone(
                "SELECT j.id FROM reading_jobs j JOIN reading_sources s ON s.id = j.reading_id WHERE j.owner_id = ? AND j.device_id = ? AND j.finished_at IS NULL AND j.expires_at > ? AND j.revision = s.revision AND s.deleted = 0",
                uid,
                device,
                now,
            )
            if active:
                return self.envelope(job=None)
            rows = await self.db.fetch(
                "SELECT * FROM reading_sources WHERE owner_id = ? AND device_id = ? AND deleted = 0 ORDER BY CASE WHEN pending != '' THEN 0 ELSE 1 END, next_at, id",
                uid,
                device,
            )
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
                    "SELECT * FROM reading_jobs WHERE reading_id = ? AND revision = ? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
                    row["id"],
                    row["revision"],
                )
                due = row["pending"] or (
                    row["mode"] == "periodic"
                    and not row["paused"]
                    and row["verified"]
                    and row["next_at"] <= now
                )
                if not previous and not due:
                    continue
                if previous and previous["attempts"] >= 3:
                    await self.finish(row, previous, "worker_interrupted", {}, now)
                    continue
                lease = secrets.token_urlsafe(24)
                if previous:
                    jid, purpose = previous["id"], previous["purpose"]
                    await self.db.execute(
                        "UPDATE reading_jobs SET lease = ?, expires_at = ?, claimed_at = ?, attempts = attempts + 1 WHERE id = ?",
                        lease,
                        now + 180,
                        now,
                        jid,
                    )
                else:
                    purpose = row["pending"] or "check"
                    jid = await self.db.insert(
                        "reading_jobs",
                        {
                            "reading_id": row["id"],
                            "owner_id": uid,
                            "device_id": device,
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
                return self.envelope(
                    job={
                        "id": jid,
                        "source_id": row["id"],
                        "device_id": device,
                        "revision": row["revision"],
                        "lease": lease,
                        "expires_at": now + 180,
                        "purpose": purpose,
                        "recipe": loads(row["recipe"]),
                    }
                )
            return self.envelope(job=None)

    def snapshot(self, row: dict[str, Any], snapshot: Any) -> dict[str, Any]:
        recipe, base = loads(row["recipe"]), loads(row["last_snapshot"])
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
        }
        await self.db.execute(
            "UPDATE reading_sources SET last_result = ?, error = ?, next_at = ?, pending = '', verified = ?, paused = ? WHERE id = ?",
            result,
            "" if result in {"verified", "changed", "unchanged"} else result,
            now + row["interval_s"],
            0 if invalidates else row["verified"],
            1 if invalidates else row["paused"],
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
        if (
            not isinstance(body, dict)
            or type(body.get("schema_version")) is not int
            or body.get("schema_version") != 1
        ):
            raise ContractError("schema_version")
        allowed = {"schema_version", "device_id", "lease", "revision", "status"}
        if body.get("status") == "success":
            allowed |= {"account_key", "snapshot"}
        if set(body) != allowed or type(body.get("revision")) is not int:
            raise ContractError("invalid_request")
        async with self.db.transaction():
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
                return loads(job["response"])
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
            result = body.get("status")
            if result != "success" and result not in FAILURES:
                raise ContractError("invalid_check_status")
            details: dict[str, Any] = {}
            if result == "success":
                if body.get("account_key") != loads(row["recipe"])["binding"]["account_key"]:
                    result = "account_mismatch"
                else:
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
                                    uid, value
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
