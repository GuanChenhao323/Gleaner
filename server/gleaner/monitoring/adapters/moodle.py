"""Moodle assignment content only. No business field extraction or network calls."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from bs4 import BeautifulSoup, Tag

from ..models import (
    AccessVerdict,
    FetchPlan,
    MonitorSource,
    MonitorTarget,
    ObservationBatch,
    SafeResponse,
    TargetObservation,
)


class MoodleAdapter:
    version = "moodle-assignment/1"

    def __init__(self, principal_secret: bytes | None = None) -> None:
        self._secret = principal_secret or secrets.token_bytes(32)

    @staticmethod
    def plan(
        source: MonitorSource, targets: list[MonitorTarget], check_id: str, generation: int | None
    ) -> FetchPlan:
        return FetchPlan(
            source.source_id,
            source.revision,
            generation,
            check_id,
            source.canonical_url,
            tuple(t.item_id for t in targets if t.enabled),
        )

    @staticmethod
    def _html(response: SafeResponse) -> BeautifulSoup:
        return BeautifulSoup(response.body, "lxml")

    def inspect(self, response: SafeResponse) -> AccessVerdict:
        if response.status == 401:
            return AccessVerdict("auth_required", "http_401")
        soup = self._html(response)
        if soup.select_one(
            "form#login, form[action*='/login/index.php'], input[name='logintoken']"
        ):
            return AccessVerdict("auth_required", "login_form")
        if soup.select_one("body.notloggedin, body.pagelayout-login"):
            return AccessVerdict("auth_required", "logged_out_body")
        if response.status == 403:
            return AccessVerdict("forbidden", "http_403")
        if response.status != 200 or "html" not in response.content_type:
            return AccessVerdict("unknown", "unsupported_response")
        # Positive login evidence is mandatory; generic HTML/200 is insufficient.
        logout = soup.select_one("a[href*='/login/logout.php']")
        if logout and soup.select_one("#region-main"):
            principal = None
            profile = soup.select_one(
                ".usermenu a[href*='/user/profile.php'], .logininfo a[href*='/user/profile.php']"
            )
            if profile:
                uid = parse_qs(urlsplit(str(profile.get("href", ""))).query).get("id", [""])[0]
                if uid.isdigit():
                    principal = hmac.new(self._secret, uid.encode(), hashlib.sha256).hexdigest()
            return AccessVerdict("authenticated", "logout_and_main", principal)
        return AccessVerdict("unknown", "no_positive_login_evidence")

    @staticmethod
    def _text(node: Tag) -> str:
        # Never expose navigation, student submission data or executable content.
        for child in node.select(
            "script, style, noscript, form, .submissionstatustable, .submissionsummarytable"
        ):
            child.decompose()
        text = node.get_text("\n", strip=True)
        return "\n".join(
            re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines() if line.strip()
        )

    def select(
        self, response: SafeResponse, source: MonitorSource, plan: FetchPlan, observed_at: float
    ) -> ObservationBatch:
        soup = self._html(response)
        body = soup.body
        intro = soup.select_one("#intro .no-overflow, #intro")
        main = soup.select_one("#region-main")
        # Verified MUST structure: activity H2 is a direct child of the main landmark.
        # Nested intro headings and the course H1 must never substitute for a missing title.
        content = (
            main
            if main and main.get("role") == "main"
            else main.select_one('[role="main"]')
            if main
            else None
        )
        title = (
            content.find("h2", recursive=False)
            if content and content.get("id") != "intro" and not content.find_parent(id="intro")
            else None
        )
        assignment_id = parse_qs(urlsplit(source.canonical_url).query)["id"][0]
        expected_locator = f"moodle:assign:{assignment_id}"
        correct_type = (
            body is not None
            and body.get("id") == "page-mod-assign-view"
            and response.final_url == source.canonical_url
        )
        cmids = [c for c in (body.get("class", []) if body else []) if str(c).startswith("cmid-")]
        if f"cmid-{assignment_id}" not in cmids:
            correct_type = False
        # An authenticated but structurally unknown page is not an empty assignment.
        available = bool(correct_type and title and title.get_text(strip=True) and intro and main)
        entries = []
        for target in source.targets:
            if not target.enabled:
                continue
            if target.locator != expected_locator:
                entries.append(
                    TargetObservation(
                        target.item_id,
                        target.locator,
                        "missing",
                        source.canonical_url,
                        error={"code": "target_missing"},
                    )
                )
            elif not available:
                entries.append(
                    TargetObservation(
                        target.item_id,
                        target.locator,
                        "error",
                        source.canonical_url,
                        error={"code": "parse_failed"},
                    )
                )
            else:
                # Reparse the selected fragment so each target sees the same cleaned tree.
                selected = BeautifulSoup(str(intro), "lxml")
                entries.append(
                    TargetObservation(
                        target.item_id,
                        target.locator,
                        "content",
                        source.canonical_url,
                        title=title.get_text(" ", strip=True),
                        text=self._text(selected),
                        metadata={"content_kind": "assignment_intro"},
                    )
                )
        representation = json.dumps(
            [(e.item_id, e.outcome, e.title, e.text) for e in entries], ensure_ascii=False
        )
        return ObservationBatch(
            str(uuid4()),
            plan.check_id,
            source.source_id,
            source.revision,
            plan.auth_generation,
            observed_at,
            self.version,
            hashlib.sha256(representation.encode()).hexdigest(),
            entries,
        )
