"""Typed Moodle summary collections, never native assignments or generic fallbacks."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .monitors import ContractError, compact, raw_content, string, web_url
from .web_captures import WebCaptureContract


class TimelineCaptureContract(WebCaptureContract):
    capture_kind = "timeline_summary"
    endpoint = "/api/v1/timeline-captures"
    subtype = "timeline_summary"
    label = "活动摘要资料"

    def source_url(self, value: Any) -> str:
        url = web_url(value)
        parsed = urlsplit(url)
        local = parsed.hostname in ("localhost", "127.0.0.1")
        if not (
            (
                parsed.hostname == "moodle.must.edu.mo"
                and parsed.scheme == "https"
                and parsed.path == "/my/"
            )
            or (local and parsed.path in ("/my/", "/capture/moodle-dashboard"))
        ):
            raise ContractError("invalid_timeline_source")
        # Reuse the credential-parameter policy while allowing this explicit campus type.
        self.detail_url(url, url, action_allowed=False)
        return url

    def detail_url(self, value: Any, base: str, *, action_allowed: bool = False) -> str:
        from urllib.parse import parse_qsl

        url = web_url(value)
        parsed, origin = urlsplit(url), urlsplit(base)
        if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
            raise ContractError("cross_origin_target")
        if any(
            any(
                w in k.lower()
                for w in ("token", "ticket", "session", "password", "secret", "authorization")
            )
            or (not action_allowed and k.lower() == "action")
            for k, _ in parse_qsl(parsed.query)
        ):
            raise ContractError("invalid_url")
        return url

    def binding(self, value: Any, url: str) -> dict[str, str]:
        if not isinstance(value, dict) or set(value) != {"adapter", "origin", "account_key"}:
            raise ContractError("invalid_binding")
        if value["adapter"] != "moodle":
            raise ContractError("invalid_binding")
        key = string(value["account_key"], 200)
        if key in ("public", "unverified"):
            raise ContractError("account_required")
        origin = web_url(value["origin"])
        if origin.rstrip("/") != f"{urlsplit(url).scheme}://{urlsplit(url).netloc}":
            raise ContractError("invalid_binding")
        return dict(value)

    def validate(self, body: Any) -> dict[str, Any]:
        if (
            not isinstance(body, dict)
            or body.get("collection_type") != self.capture_kind
            or body.get("match_scope") != "content"
        ):
            raise ContractError("invalid_snapshot")
        return super().validate(body)

    def fragment(self, f: Any, url: str) -> dict[str, Any]:
        if not isinstance(f, dict) or set(f) != {
            "candidate_id",
            "title",
            "text",
            "url",
            "fields",
            "evidence",
            "context",
        }:
            raise ContractError("invalid_snapshot")
        raw = raw_content({"title": f["title"], "text": f["text"]})
        fields, evidence, context = f["fields"], f["evidence"], f["context"]
        if not isinstance(fields, dict) or set(fields) != {"course", "date_text", "datetime_text"}:
            raise ContractError("invalid_snapshot")
        for value in fields.values():
            string(value, 1000, empty=True)
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"channel", "locator", "text"}
            or evidence["channel"] != "dom"
        ):
            raise ContractError("invalid_evidence")
        string(evidence["locator"], 4000)
        text = string(evidence["text"], 22000)
        if raw["text"] not in text:
            raise ContractError("invalid_evidence")
        if context != {"frame_url": url, "region": "Timeline", "completeness": "summary"}:
            raise ContractError("invalid_context")
        return {
            **f,
            "title": raw["title"],
            "text": raw["text"],
            "url": self.detail_url(f["url"], url),
        }

    def fragment_text(self, f: dict[str, Any], number: int) -> str:
        fields = f["fields"]
        return f"【活动摘要 {number}】{f['title']}\n课程：{fields['course']}\n日期原文：{fields['date_text']}\n时间原文：{fields['datetime_text']}\n{f['text']}\n详情：{f['url']}"

    def identity(self, value: dict[str, Any]) -> list[Any]:
        return [self.capture_kind, *super().identity(value)]

    def collection_text(self, fragments: list[dict[str, Any]]) -> str:
        ordered = sorted(
            fragments, key=lambda f: compact([f["title"], f["text"], f["url"], f["fields"]])
        )
        return super().collection_text(ordered)

    def metadata(self, value: dict[str, Any], cid: str) -> dict[str, Any]:
        return {
            **super().metadata(value, cid),
            "collection_type": self.capture_kind,
            "account_state": "bound",
            "completeness": "summary",
        }
