"""IC-WEB-CAPTURE-001: explicit, labeled collections of generic DOM fragments.

This service does not fetch webpages or infer native identities/account ownership.
It owns collection identity; Pipeline owns item versions and user deliveries.
"""

from __future__ import annotations

import math
import time
import unicodedata
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from ..net.http import Request, Response, Router
from ..storage.db import Database, loads
from .monitors import ContractError, compact, digest, raw_content, string, web_url
from .pipeline import Pipeline, owner_prefix

CAMPUS_HOSTS = {
    "moodle.must.edu.mo",
    "student-wmweb.must.edu.mo",
    "infoportal-web.must.edu.mo",
    "classtimetable-coes-wmweb.must.edu.mo",
    "fie.must.edu.mo",
    "login.must.edu.mo",
}


def source_url(value: Any) -> str:
    url = web_url(value)
    keys = [k.lower() for k, _ in parse_qsl(urlsplit(url).query)]
    if any(
        any(
            word in k
            for word in ("token", "ticket", "session", "password", "secret", "authorization")
        )
        for k in keys
    ):
        raise ContractError("invalid_url")
    if urlsplit(url).hostname in CAMPUS_HOSTS:
        raise ContractError("specialized_source_required")
    return url


def binding_value(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"kind", "label"}:
        raise ContractError("source_label_required")
    kind, label = value["kind"], string(value["label"], 80)
    if kind not in ("public", "labeled") or (kind == "public" and label != "公开网页"):
        raise ContractError("source_label_required")
    return {"kind": kind, "label": unicodedata.normalize("NFKC", label)}


def normalized_query(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class WebCaptureContract:
    """Strict validation/projection, separate from persistence and transport."""

    def validate(self, body: Any) -> dict[str, Any]:
        allowed = {
            "schema_version",
            "request_id",
            "device_id",
            "source",
            "query",
            "match_scope",
            "observed_at",
            "source_binding",
            "fragments",
        }
        if not isinstance(body, dict) or set(body) != allowed:
            raise ContractError("invalid_request")
        if type(body["schema_version"]) is not int or body["schema_version"] != 1:
            raise ContractError("schema_version")
        rid = string(body["request_id"], 36)
        try:
            if str(uuid.UUID(rid)) != rid:
                raise ValueError
        except ValueError as e:
            raise ContractError("invalid_request") from e
        string(body["device_id"], 100)
        src = body["source"]
        if not isinstance(src, dict) or set(src) != {"url", "title"}:
            raise ContractError("invalid_request")
        url, title = source_url(src["url"]), string(src["title"], 300)
        query = string(body["query"], 200)
        if body["match_scope"] not in ("content", "title"):
            raise ContractError("invalid_request")
        at = body["observed_at"]
        if (
            type(at) not in (int, float)
            or not math.isfinite(at)
            or not 0 < at <= time.time() * 1000 + 300000
        ):
            raise ContractError("invalid_observation")
        binding = binding_value(body["source_binding"])
        fragments = body["fragments"]
        if not isinstance(fragments, list) or not 1 <= len(fragments) <= 30:
            raise ContractError("invalid_targets")
        ids, projected = set(), []
        for f in fragments:
            if not isinstance(f, dict) or set(f) != {
                "candidate_id",
                "title",
                "text",
                "evidence",
                "context",
            }:
                raise ContractError("invalid_snapshot")
            cid = string(f["candidate_id"], 100)
            if cid in ids:
                raise ContractError("duplicate_candidates")
            ids.add(cid)
            raw = raw_content({"title": f["title"], "text": f["text"]})
            evidence, ctx = f["evidence"], f["context"]
            if (
                not isinstance(evidence, dict)
                or set(evidence) != {"channel", "locator", "text"}
                or evidence["channel"] != "dom"
                or evidence["text"] != raw["text"]
            ):
                raise ContractError("invalid_evidence")
            string(evidence["locator"], 4000)
            if (
                not isinstance(ctx, dict)
                or set(ctx) != {"frame_url", "boundary", "completeness", "matched_by"}
                or ctx["frame_url"] != url
                or ctx["completeness"] != "fragment"
                or ctx["matched_by"] != "literal"
                or ctx["boundary"] not in ("paragraph", "list_row", "table_row", "section", "text")
            ):
                raise ContractError("invalid_context")
            projected.append({**f, "candidate_id": cid, "title": raw["title"], "text": raw["text"]})
        text = "\n\n".join(
            f"【片段 {i + 1}】{f['title']}\n{f['text']}" for i, f in enumerate(projected)
        )
        if len(text) > 20000:
            raise ContractError("content_too_large")
        return {
            **body,
            "source": {"url": url, "title": title},
            "query": query,
            "source_binding": binding,
            "fragments": projected,
            "text": text,
        }


class WebCaptureService:
    def __init__(
        self, db: Database, pipeline: Pipeline, contract: WebCaptureContract | None = None
    ) -> None:
        self.db, self.pipeline = db, pipeline
        self.contract = contract or WebCaptureContract()
        self.on_capture: Callable[..., Any] | None = None
        self.validate_reading: Callable[..., Any] | None = None

    def register(self, router: Router, authed: Callable[..., Any]) -> None:
        async def handle(req: Request, user: dict[str, Any]) -> Response:
            try:
                data = (
                    await self.capture(user["id"], req.json())
                    if req.method == "POST"
                    else await self.request_result(user["id"], req.params["request_id"])
                    if req.params.get("request_id")
                    else await self.collections(user["id"])
                )
                return Response.json_body(data)
            except ContractError as e:
                return Response.json_body(
                    {"schema_version": 1, "ok": False, "error": e.code}, e.status
                )
            except (TypeError, KeyError, ValueError):
                return Response.json_body(
                    {"schema_version": 1, "ok": False, "error": "invalid_request"}, 422
                )

        router.add("POST", "/api/v1/web-captures", authed(handle))
        router.add("GET", "/api/v1/web-captures/{request_id}", authed(handle))
        router.add("GET", "/api/v1/web-captures", authed(handle))

    async def collections(self, uid: int) -> dict[str, Any]:
        rows = await self.db.fetch(
            "SELECT i.id, i.title, i.url, i.version, i.updated_at, i.attrs FROM web_collections c JOIN sources s ON s.id = c.source_id JOIN subscriptions sub ON sub.source_id = s.id AND sub.user_id = ? JOIN items i ON i.source_id = s.id WHERE c.owner_id = ? AND i.deleted = 0 ORDER BY i.updated_at DESC LIMIT 100",
            uid,
            uid,
        )
        return {
            "schema_version": 1,
            "ok": True,
            "collections": [
                {k: v for k, v in r.items() if k != "attrs"}
                | {
                    "source_binding": loads(r["attrs"], {})
                    .get("web_capture", {})
                    .get("source_binding"),
                    "fragment_count": len(
                        loads(r["attrs"], {}).get("web_capture", {}).get("fragments", [])
                    ),
                }
                for r in rows
            ],
        }

    async def request_result(self, uid: int, rid: str) -> dict[str, Any]:
        row = await self.db.fetchone(
            "SELECT response FROM web_capture_requests WHERE owner_id = ? AND request_id = ?",
            uid,
            rid,
        )
        if not row:
            raise ContractError("not_found", 404)
        return loads(row["response"])

    async def capture(self, uid: int, body: Any) -> dict[str, Any]:
        value = self.contract.validate(
            {k: v for k, v in body.items() if k != "reading"} if isinstance(body, dict) else body
        )
        if isinstance(body, dict) and "reading" in body:
            if not self.validate_reading:
                raise ContractError("reading_unavailable")
            self.validate_reading(body, "generic")
        rid, signature = value["request_id"], digest(body)
        binding, source = value["source_binding"], value["source"]
        identity = digest(
            [binding, source["url"], normalized_query(value["query"]), value["match_scope"]]
        )
        async with self.db.transaction():
            previous = await self.db.fetchone(
                "SELECT * FROM web_capture_requests WHERE owner_id = ? AND request_id = ?", uid, rid
            )
            if previous:
                if previous["digest"] != signature:
                    raise ContractError("idempotency_conflict", 409)
                return loads(previous["response"])
            collection = await self.db.fetchone(
                "SELECT * FROM web_collections WHERE owner_id = ? AND identity_key = ?",
                uid,
                identity,
            )
            now = time.time()
            if not collection:
                sid = await self.db.insert(
                    "sources",
                    {
                        "owner_id": uid,
                        "type": "browser",
                        "name": f"网页资料：{value['query']}",
                        "endpoint": source["url"],
                        "config": {"runner": "snapshot", "source_binding": binding},
                        "via_agent": 1,
                        "status": "paused",
                        "created_at": now,
                    },
                )
                await self.db.execute(
                    "INSERT INTO subscriptions (user_id, source_id, weight, created_at) VALUES (?, ?, 0.7, ?)",
                    uid,
                    sid,
                    now,
                )
                cid = str(uuid.uuid4())
                await self.db.execute(
                    "INSERT INTO web_collections (id, owner_id, identity_key, source_id, created_at) VALUES (?, ?, ?, ?, ?)",
                    cid,
                    uid,
                    identity,
                    sid,
                    now,
                )
                collection = {"id": cid, "source_id": sid}
            cid, sid = collection["id"], collection["source_id"]
            metadata = {
                "capture_id": cid,
                "source": source,
                "query": value["query"],
                "match_scope": value["match_scope"],
                "source_binding": binding,
                "account_state": "unverified",
                "observed_at": value["observed_at"],
                "scope": "current_rendered_view",
                "completeness": "fragment",
                "monitoring": False,
                "fragments": value["fragments"],
            }
            counts = await self.pipeline.ingest(
                {
                    "source_id": sid,
                    "status": "ok",
                    "prev_status": "ok",
                    "items": [
                        {
                            "key": f"web:{cid}",
                            "kind": "clip",
                            "title": f"{value['query']} · {source['title']}"[:300],
                            "body": value["text"],
                            "url": source["url"],
                            "attrs": {
                                "web_capture": metadata,
                                "subtype": "web_reference",
                                "suppress_deadline": True,
                            },
                        }
                    ],
                }
            )
            item = await self.db.fetchone(
                "SELECT id, version, attrs FROM items WHERE identity_key = ?",
                owner_prefix(uid) + f"web:{cid}",
            )
            if not item:
                raise ContractError("capture_failed", 500)
            # A new confirmed observation can refresh evidence/time without inventing
            # a source-content version when the text is unchanged.
            attrs = loads(item["attrs"], {})
            attrs["web_capture"] = metadata
            await self.db.execute("UPDATE items SET attrs = ? WHERE id = ?", attrs, item["id"])
            await self.db.execute("UPDATE sources SET last_success_at = ? WHERE id = ?", now, sid)
            response = {
                "schema_version": 1,
                "ok": True,
                "request_id": rid,
                "candidate_ids": [f["candidate_id"] for f in value["fragments"]],
                "results": [
                    {
                        "candidate_id": "collection",
                        "capture_id": cid,
                        "item_id": item["id"],
                        "source_id": sid,
                        "status": "new"
                        if counts["new"]
                        else "changed"
                        if counts["changed"]
                        else "unchanged",
                        "fragment_count": len(value["fragments"]),
                        "version": item["version"],
                    }
                ],
            }
            if isinstance(body, dict) and "reading" in body:
                if not self.on_capture:
                    raise ContractError("reading_unavailable")
                response["reading_source_id"] = await self.on_capture(
                    uid, body, response, "generic"
                )
            await self.db.execute(
                "INSERT INTO web_capture_requests (owner_id, request_id, digest, response, created_at) VALUES (?, ?, ?, ?, ?)",
                uid,
                rid,
                signature,
                compact(response),
                now,
            )
            return response
