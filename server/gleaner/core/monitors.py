"""IC-BROWSER-001: private browser captures, one authoritative schedule and leased results.

No browser cookies or school passwords cross this interface. Legacy collectors never own
these sources. Database access, identity, classification and versions stay in Core.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..net.http import Request, Response, Router
from ..storage.db import Database, loads
from .pipeline import Pipeline, owner_prefix

ERRORS = {
    "need_login",
    "selection_missing",
    "view_mismatch",
    "route_mismatch",
    "render_timeout",
    "permission_denied",
    "unsupported",
    "account_mismatch",
    "failed",
}
FIELDS = {
    "subtype",
    "course",
    "semester",
    "week",
    "weekday",
    "period",
    "datetime_text",
    "requirements",
    "department",
    "office",
    "email",
    "phone",
    "role",
    "published_text",
    "valid_until_text",
    "course_code",
    "class_group",
    "location",
    "date_text",
}


class ContractError(ValueError):
    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(compact(value).encode()).hexdigest()


def string(value: Any, maximum: int = 200, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ContractError("invalid_string")
    return value.strip()


def web_url(value: Any) -> str:
    value = string(value, 2048)
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError
        _ = parsed.port
    except ValueError as e:
        raise ContractError("invalid_url") from e
    return value  # Route fragments and query parameters are identity-relevant context.


def frame_identity(url: str, adapter: str) -> str:
    parsed = urlsplit(url)
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not (adapter == "fie" and k == "locale")
    )
    return urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path, urlencode(query), parsed.fragment)
    )


def raw_content(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ContractError("invalid_snapshot")
    title, text = string(raw.get("title"), 300), string(raw.get("text"), 20000)
    shell = r"(?i)(loading[.…\s]*|log in( to the site)?|sign in|登录|正在加载[.…\s]*)"
    if re.fullmatch(shell, title) or re.fullmatch(shell, text):
        raise ContractError("page_not_ready")
    fields = raw.get("fields", {})
    if not isinstance(fields, dict) or set(fields) - FIELDS:
        raise ContractError("invalid_raw_fields")
    return {
        "title": title,
        "text": text,
        "fields": {k: string(v, 2000, empty=True) for k, v in fields.items()},
    }


class BrowserMonitorService:
    def __init__(self, db: Database, pipeline: Pipeline) -> None:
        self.db, self.pipeline = db, pipeline

    @staticmethod
    def envelope(**value: Any) -> dict[str, Any]:
        return {"schema_version": 1, "ok": True, **value}

    def register(self, router: Router, authed: Callable[..., Any]) -> None:
        routes = [
            ("POST", "/api/v1/captures", self.capture),
            ("GET", "/api/v1/captures/{request_id}", self.request_result),
            ("GET", "/api/v1/monitors", self.monitors),
            ("PUT", "/api/v1/monitors/{id}", self.control),
            ("DELETE", "/api/v1/monitors/{id}", self.remove),
            ("POST", "/api/v1/monitors/{id}/check", self.check_now),
            ("GET", "/api/v1/monitors/{id}/checks", self.checks),
            ("POST", "/api/v1/monitor-jobs/claim", self.claim),
            ("POST", "/api/v1/monitor-jobs/{id}/result", self.result),
        ]
        for method, path, operation in routes:

            def wrap(
                fn: Callable[..., Awaitable[dict[str, Any]]], verb: str, route: str
            ) -> Callable[..., Any]:
                async def handle(req: Request, user: dict[str, Any]) -> Response:
                    try:
                        args: list[Any] = [user["id"]]
                        if "{id}" in route:
                            try:
                                args.append(int(req.params["id"]))
                            except ValueError as e:
                                raise ContractError("not_found", 404) from e
                        if "{request_id}" in route:
                            args.append(req.params["request_id"])
                        if verb in ("POST", "PUT"):
                            args.append(req.json())
                        data = await fn(*args)
                        return Response.json_body(data)
                    except ContractError as e:
                        return Response.json_body(
                            {"schema_version": 1, "ok": False, "error": e.code, "message": e.code},
                            e.status,
                        )
                    except (TypeError, KeyError, json.JSONDecodeError):
                        return Response.json_body(
                            {
                                "schema_version": 1,
                                "ok": False,
                                "error": "invalid_request",
                                "message": "请求格式错误",
                            },
                            422,
                        )

                return handle

            router.add(method, path, authed(wrap(operation, method, path)))

    def target(self, target: Any, binding: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(target, dict):
            raise ContractError("invalid_target")
        candidate = string(target.get("candidate_id"))
        entity = string(target.get("entity_id"))
        if not re.match(r"^(assignment|notice|person|timetable|manual):[^\s]+$", entity):
            raise ContractError("unstable_identity")
        loc, recipe = target.get("locator"), target.get("recipe")
        if not isinstance(loc, dict) or not isinstance(recipe, dict):
            raise ContractError("invalid_locator")
        url = web_url(loc.get("url"))
        if (
            urlsplit(url).netloc != urlsplit(binding["origin"]).netloc
            or urlsplit(url).scheme != urlsplit(binding["origin"]).scheme
        ):
            raise ContractError("cross_origin_target")
        if web_url(loc.get("frame_url")) != url:
            raise ContractError("frame_unsupported")
        view = loc.get("view")
        if (
            not isinstance(view, dict)
            or len(compact(view)) > 2000
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in view.items())
        ):
            raise ContractError("invalid_view")
        if (
            recipe.get("adapter") != binding["adapter"]
            or type(recipe.get("version")) is not int
            or recipe.get("version") not in (1, 2)
            or recipe.get("entity_id") != entity
            or recipe.get("url") != url
            or recipe.get("view") != view
        ):
            raise ContractError("recipe_mismatch")
        if recipe["version"] == 1:
            string(recipe.get("selector"), 1000)
        elif recipe.get("strategy") != "snapshot" or target.get("supported") is not False:
            # Current-page extraction is explicitly snapshot-only. Never schedule
            # an AX node ID / provisional selector as a durable re-entry recipe.
            raise ContractError("snapshot_monitor_unsupported")
        if type(target.get("supported")) is not bool or type(target.get("enabled")) is not bool:
            raise ContractError("invalid_capability")
        if target["enabled"] and not target["supported"]:
            raise ContractError("monitor_unsupported")
        return {
            **target,
            "candidate_id": candidate,
            "entity_id": entity,
            "raw": raw_content(target.get("raw")),
        }

    async def capture(self, uid: int, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or type(body.get("schema_version")) is not int
            or body.get("schema_version") != 1
        ):
            raise ContractError("schema_version")
        rid, device = string(body.get("request_id"), 100), string(body.get("device_id"), 100)
        binding = body.get("binding")
        if not isinstance(binding, dict) or binding.get("adapter") not in (
            "moodle",
            "student",
            "fie",
            "manual",
        ):
            raise ContractError("invalid_binding")
        binding = {
            "adapter": binding["adapter"],
            "origin": web_url(binding.get("origin")),
            "account_key": string(binding.get("account_key")),
        }
        if binding["adapter"] in ("moodle", "student") and binding["account_key"] == "public":
            raise ContractError("account_required")
        targets = body.get("targets")
        if not isinstance(targets, list) or not 1 <= len(targets) <= 30:
            raise ContractError("invalid_targets")
        ids = [t.get("candidate_id") for t in targets if isinstance(t, dict)]
        if (
            len(ids) != len(targets)
            or any(not isinstance(i, str) for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ContractError("duplicate_candidates")
        payload_hash = digest(body)
        async with self.db.transaction():
            prev = await self.db.fetchone(
                "SELECT * FROM browser_requests WHERE owner_id = ? AND request_id = ?", uid, rid
            )
            if prev:
                if prev["digest"] != payload_hash:
                    raise ContractError("idempotency_conflict", 409)
                return loads(prev["response"])
            results = []
            for target in targets:
                try:
                    t = self.target(target, binding)
                except ContractError as e:
                    results.append(
                        {
                            "candidate_id": target["candidate_id"],
                            "status": "failed",
                            "error": e.code,
                            "message": e.code,
                        }
                    )
                    continue
                identity = digest(
                    [
                        binding,
                        t["entity_id"],
                        frame_identity(t["locator"]["frame_url"], binding["adapter"]),
                        t["locator"]["view"],
                    ]
                )
                monitor = await self.db.fetchone(
                    "SELECT * FROM browser_monitors WHERE owner_id = ? AND identity_key = ?",
                    uid,
                    identity,
                )
                if monitor and (
                    loads(monitor["recipe"]) != t["recipe"]
                    or monitor["device_id"] != device
                    or monitor["deleted"]
                ):
                    results.append(
                        {
                            "candidate_id": t["candidate_id"],
                            "status": "failed",
                            "error": "binding_or_recipe_changed",
                            "message": "原绑定已改变，需明确重新建立来源",
                        }
                    )
                    continue
                now = time.time()
                if not monitor:
                    sid = await self.db.insert(
                        "sources",
                        {
                            "owner_id": uid,
                            "type": "browser",
                            "name": t["raw"]["title"],
                            "endpoint": t["locator"]["url"],
                            "config": {"runner": "chrome"},
                            "via_agent": 1,
                            "status": "pending"
                            if t["enabled"]
                            else "unsupported"
                            if not t["supported"]
                            else "paused",
                            "created_at": now,
                        },
                    )
                    await self.db.execute(
                        "INSERT INTO subscriptions (user_id, source_id, weight, created_at) VALUES (?, ?, 0.7, ?)",
                        uid,
                        sid,
                        now,
                    )
                    mid = await self.db.insert(
                        "browser_monitors",
                        {
                            "owner_id": uid,
                            "device_id": device,
                            "identity_key": identity,
                            "binding": binding,
                            "recipe": t["recipe"],
                            "source_id": sid,
                            "supported": t["supported"],
                            "enabled": t["enabled"],
                            "last_raw": t["raw"],
                            "created_at": now,
                        },
                    )
                    monitor = await self.own(uid, mid)
                elif t["enabled"] and not monitor["enabled"]:
                    # A new, previewed capture explicitly re-confirms the original binding.
                    # Ordinary control/resume cannot acknowledge an account switch.
                    await self.db.execute(
                        "UPDATE browser_monitors SET enabled = 1, revision = revision + 1, next_at = 0, last_result = 'not_executed', error = '' WHERE id = ?",
                        monitor["id"],
                    )
                    await self.db.execute(
                        "UPDATE sources SET status = 'pending', last_error = NULL WHERE id = ?",
                        monitor["source_id"],
                    )
                    monitor = await self.own(uid, monitor["id"])
                counts = await self.ingest(monitor, t["raw"])
                iid = await self.db.fetchval(
                    "SELECT id FROM items WHERE identity_key = ?",
                    owner_prefix(uid) + f"browser:{monitor['id']}",
                )
                await self.db.execute(
                    "UPDATE browser_monitors SET item_id = ?, last_raw = ? WHERE id = ?",
                    iid,
                    t["raw"],
                    monitor["id"],
                )
                results.append(
                    {
                        "candidate_id": t["candidate_id"],
                        "status": "new"
                        if counts["new"]
                        else "changed"
                        if counts["changed"]
                        else "unchanged",
                        "monitor_id": monitor["id"],
                        "item_id": iid,
                    }
                )
            response = self.envelope(request_id=rid, results=results)
            await self.db.execute(
                "INSERT INTO browser_requests (owner_id, request_id, digest, response, created_at) VALUES (?, ?, ?, ?, ?)",
                uid,
                rid,
                payload_hash,
                response,
                time.time(),
            )
            return response

    async def ingest(self, monitor: dict[str, Any], raw: dict[str, Any]) -> dict[str, int]:
        recipe = loads(monitor["recipe"])
        fields = raw["fields"]
        subtype = fields.get("subtype", "")
        kind = (
            "assignment"
            if recipe["entity_id"].startswith("assignment:")
            else "event"
            if subtype == "timetable"
            else "notice"
        )
        # Timetable week/period strings are context, never an inferred calendar date.
        attrs = {
            "raw_fields": fields,
            "product_type": "task"
            if kind == "assignment"
            else "event"
            if kind == "event"
            else "notice",
            "subtype": subtype,
            "suppress_deadline": kind == "event",
            "browser_monitor_id": monitor["id"],
        }
        return await self.pipeline.ingest(
            {
                "source_id": monitor["source_id"],
                "status": "ok",
                "prev_status": "ok",
                "items": [
                    {
                        "key": f"browser:{monitor['id']}",
                        "kind": kind,
                        "title": raw["title"],
                        "body": raw["text"],
                        "url": recipe["url"],
                        "course": fields.get("course", ""),
                        "requirements": fields.get("requirements", ""),
                        "attrs": attrs,
                    }
                ],
            }
        )

    async def own(self, uid: int, mid: int) -> dict[str, Any]:
        row = await self.db.fetchone(
            "SELECT * FROM browser_monitors WHERE owner_id = ? AND id = ?", uid, mid
        )
        if not row:
            raise ContractError("not_found", 404)
        return row

    async def request_result(self, uid: int, rid: str) -> dict[str, Any]:
        row = await self.db.fetchone(
            "SELECT response FROM browser_requests WHERE owner_id = ? AND request_id = ?", uid, rid
        )
        if not row:
            raise ContractError("not_found", 404)
        return loads(row["response"])

    async def monitors(self, uid: int) -> dict[str, Any]:
        rows = await self.db.fetch(
            "SELECT m.*, i.title AS title FROM browser_monitors m LEFT JOIN items i ON i.id = m.item_id WHERE m.owner_id = ? AND m.deleted = 0 ORDER BY m.id DESC",
            uid,
        )
        return self.envelope(
            monitors=[
                {
                    **{
                        k: r[k]
                        for k in (
                            "id",
                            "title",
                            "item_id",
                            "source_id",
                            "revision",
                            "last_result",
                            "last_attempt_at",
                            "last_success_at",
                            "error",
                            "next_at",
                        )
                    },
                    "enabled": bool(r["enabled"]),
                    "supported": bool(r["supported"]),
                    "recipe": loads(r["recipe"]),
                }
                for r in rows
            ]
        )

    async def control(self, uid: int, mid: int, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict) or type(body.get("enabled")) is not bool:
            raise ContractError("invalid_control")
        async with self.db.transaction():
            row = await self.own(uid, mid)
            if row["revision"] != body.get("revision") or row["deleted"]:
                raise ContractError("revision_conflict", 409)
            if body["enabled"] and row["last_result"] == "account_mismatch":
                raise ContractError("account_confirmation_required", 409)
            if body["enabled"] and not row["supported"]:
                raise ContractError("monitor_unsupported")
            await self.db.execute(
                "UPDATE browser_monitors SET enabled = ?, revision = revision + 1, next_at = 0 WHERE id = ?",
                body["enabled"],
                mid,
            )
            await self.db.execute(
                "UPDATE sources SET status = ? WHERE id = ?",
                "pending" if body["enabled"] else "paused",
                row["source_id"],
            )
            return self.envelope(revision=row["revision"] + 1)

    async def remove(self, uid: int, mid: int) -> dict[str, Any]:
        row = await self.own(uid, mid)
        await self.db.execute(
            "UPDATE browser_monitors SET deleted = 1, enabled = 0, revision = revision + 1 WHERE id = ?",
            mid,
        )
        await self.db.execute("UPDATE sources SET status = 'paused' WHERE id = ?", row["source_id"])
        return self.envelope()

    async def check_now(self, uid: int, mid: int, body: Any) -> dict[str, Any]:
        row = await self.own(uid, mid)
        if not row["enabled"] or row["deleted"]:
            raise ContractError("monitor_paused", 409)
        await self.db.execute("UPDATE browser_monitors SET next_at = 0 WHERE id = ?", mid)
        return self.envelope(status="queued")

    async def checks(self, uid: int, mid: int) -> dict[str, Any]:
        await self.own(uid, mid)
        return self.envelope(
            checks=await self.db.fetch(
                "SELECT status, error, checked_at, version FROM browser_checks WHERE monitor_id = ? ORDER BY id DESC LIMIT 50",
                mid,
            )
        )

    async def claim(self, uid: int, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ContractError("invalid_request")
        device = string(body.get("device_id"), 100)
        now = time.time()
        async with self.db.transaction():
            # Device executes only one leased tab, including after worker restart.
            if await self.db.fetchone(
                "SELECT id FROM browser_jobs WHERE owner_id = ? AND device_id = ? AND finished_at IS NULL AND expires_at > ? AND revision = (SELECT revision FROM browser_monitors m WHERE m.id = monitor_id)",
                uid,
                device,
                now,
            ):
                return self.envelope(job=None)
            rows = await self.db.fetch(
                "SELECT * FROM browser_monitors WHERE owner_id = ? AND device_id = ? AND enabled = 1 AND deleted = 0 AND next_at <= ? ORDER BY next_at, id",
                uid,
                device,
                now,
            )
            for row in rows:
                prev = await self.db.fetchone(
                    "SELECT * FROM browser_jobs WHERE monitor_id = ? AND finished_at IS NULL AND revision = ? ORDER BY id DESC LIMIT 1",
                    row["id"],
                    row["revision"],
                )
                recent = await self.db.fetchone(
                    "SELECT j.claimed_at, m.recipe FROM browser_jobs j JOIN browser_monitors m ON m.id = j.monitor_id WHERE j.owner_id = ? ORDER BY j.claimed_at DESC LIMIT 1",
                    uid,
                )
                if recent and now - recent["claimed_at"] < 2:
                    return self.envelope(job=None)
                if prev and prev["attempts"] >= 3:
                    await self.finish_failure(
                        row, prev["id"], "failed", "lease_attempts_exhausted", now
                    )
                    await self.db.execute(
                        "UPDATE browser_jobs SET finished_at = ? WHERE id = ?", now, prev["id"]
                    )
                    continue
                lease = secrets.token_urlsafe(24)
                if prev:
                    jid = prev["id"]
                    await self.db.execute(
                        "UPDATE browser_jobs SET lease = ?, expires_at = ?, claimed_at = ?, attempts = attempts + 1 WHERE id = ?",
                        lease,
                        now + 120,
                        now,
                        jid,
                    )
                else:
                    jid = await self.db.insert(
                        "browser_jobs",
                        {
                            "monitor_id": row["id"],
                            "owner_id": uid,
                            "device_id": device,
                            "revision": row["revision"],
                            "lease": lease,
                            "expires_at": now + 120,
                            "claimed_at": now,
                        },
                    )
                await self.db.execute(
                    "UPDATE browser_monitors SET last_attempt_at = ? WHERE id = ?", now, row["id"]
                )
                return self.envelope(
                    job={
                        "id": jid,
                        "monitor_id": row["id"],
                        "device_id": device,
                        "lease": lease,
                        "expires_at": now + 120,
                        "revision": row["revision"],
                        "binding": loads(row["binding"]),
                        "recipe": loads(row["recipe"]),
                    }
                )
        return self.envelope(job=None)

    async def finish_failure(
        self, row: dict[str, Any], jid: int, status: str, error: str, now: float
    ) -> None:
        await self.db.execute(
            "UPDATE browser_monitors SET last_result = ?, error = ?, next_at = ?, enabled = CASE WHEN ? = 1 THEN 0 ELSE enabled END WHERE id = ?",
            status,
            error,
            now + row["interval_s"],
            int(status == "account_mismatch"),
            row["id"],
        )
        await self.db.execute(
            "UPDATE sources SET status = ?, last_error = ?, last_checked_at = ? WHERE id = ?",
            "need_login" if status in ("need_login", "account_mismatch") else "failed",
            error,
            now,
            row["source_id"],
        )
        await self.db.insert(
            "browser_checks",
            {
                "monitor_id": row["id"],
                "job_id": jid,
                "status": status,
                "error": error,
                "checked_at": now,
            },
        )

    async def result(self, uid: int, jid: int, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or type(body.get("schema_version")) is not int
            or body.get("schema_version") != 1
        ):
            raise ContractError("schema_version")
        now = time.time()
        payload_hash = digest(body)
        async with self.db.transaction():
            job = await self.db.fetchone(
                "SELECT * FROM browser_jobs WHERE id = ? AND owner_id = ?", jid, uid
            )
            if not job:
                raise ContractError("not_found", 404)
            row = await self.own(uid, job["monitor_id"])
            if body.get("device_id") != job["device_id"] or body.get("lease") != job["lease"]:
                raise ContractError("stale_lease", 409)
            if job["response"]:
                if job["digest"] != payload_hash:
                    raise ContractError("idempotency_conflict", 409)
                return loads(job["response"])
            if (
                row["deleted"]
                or not row["enabled"]
                or body.get("revision") != row["revision"]
                or job["revision"] != row["revision"]
                or job["expires_at"] <= now
            ):
                raise ContractError("stale_lease", 409)
            status = body.get("status")
            if status != "success" and status not in ERRORS:
                raise ContractError("invalid_check_status")
            if (
                status == "success"
                and body.get("account_key") != loads(row["binding"])["account_key"]
            ):
                status = "account_mismatch"
            if status == "success":
                raw = raw_content(body.get("raw"))
                counts = await self.ingest(row, raw)
                status = "changed" if counts["changed"] else "unchanged"
                await self.db.execute(
                    "UPDATE browser_monitors SET last_raw = ?, last_result = ?, error = '', last_success_at = ?, next_at = ? WHERE id = ?",
                    raw,
                    status,
                    now,
                    now + row["interval_s"],
                    row["id"],
                )
                await self.db.execute(
                    "UPDATE sources SET status = 'ok', last_error = NULL, last_checked_at = ?, last_success_at = ? WHERE id = ?",
                    now,
                    now,
                    row["source_id"],
                )
                version = await self.db.fetchval(
                    "SELECT version FROM items WHERE id = ?", row["item_id"]
                )
                await self.db.insert(
                    "browser_checks",
                    {
                        "monitor_id": row["id"],
                        "job_id": jid,
                        "status": status,
                        "error": "",
                        "checked_at": now,
                        "version": version,
                    },
                )
            else:
                await self.finish_failure(row, jid, status, status, now)
            ack = self.envelope(
                status=status if status in ("changed", "unchanged") else "failed",
                result=status,
                job_id=jid,
            )
            await self.db.execute(
                "UPDATE browser_jobs SET digest = ?, response = ?, finished_at = ? WHERE id = ?",
                payload_hash,
                ack,
                now,
                jid,
            )
            return ack
