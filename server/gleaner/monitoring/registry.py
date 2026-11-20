"""Saved-item registration and check coalescing. No arbitrary URL proxy."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .auth import AuthManager
from .models import Clock, MonitorError, MonitorSource, MonitorTarget, SitePolicy
from .store import Store


class Registry:
    def __init__(
        self, store: Store, auth: AuthManager, policy: SitePolicy, clock: Clock | None = None
    ) -> None:
        self.on_change: Callable[[], None] = lambda: None
        self.store, self.auth, self.policy, self.clock = store, auth, policy, clock or Clock()
        self.auth.persist_metadata = lambda meta: self.store.put_meta(
            "auth:" + meta["auth_id"], meta
        )
        for source in store.sources():
            if source.auth_id and source.auth_id not in auth.contexts:
                meta = store.meta("auth:" + source.auth_id)
                if meta:
                    generations = [
                        c.get("auth_generation") or 0 for c in store.checks(source.source_id)
                    ]
                    meta["generation"] = max([meta["generation"], *generations])
                    auth.restore(meta)

    def owned(self, source_id: str, owner_id: int) -> MonitorSource:
        source = self.store.source(source_id)
        if source is None or source.owner_id != owner_id:
            raise MonitorError("not_found")
        return source

    def register(
        self,
        owner_id: int,
        item_ids: list[int],
        bridge_id: str,
        auth_id: str | None,
        interval_s: float = 600,
    ) -> MonitorSource:
        if not item_ids or len(item_ids) > 100 or len(item_ids) != len(set(item_ids)):
            raise MonitorError("invalid")
        if not math.isfinite(interval_s) or interval_s < self.policy.min_interval_s:
            raise MonitorError("invalid")
        if auth_id:
            c = self.auth.context(auth_id)
            if c.owner_id != owner_id or c.bridge_id != bridge_id:
                raise MonitorError("binding_denied")
        elif not self.policy.local_test:
            raise MonitorError("binding_denied")
        items = self.store.items(item_ids, owner_id)
        if len(items) != len(item_ids):
            raise MonitorError("not_found")
        urls = {self.policy.canonical(i["url"], target=True) for i in items}
        if len(urls) != 1:
            raise MonitorError("invalid")
        url = urls.pop()
        locator = "moodle:assign:" + parse_qs(urlsplit(url).query)["id"][0]
        if any(i["locator"] != locator for i in items):
            raise MonitorError("unsupported")
        source = next(
            (
                s
                for s in self.store.sources()
                if (s.owner_id, s.adapter_id, s.canonical_url, s.auth_id)
                == (owner_id, self.policy.adapter_id, url, auth_id)
            ),
            None,
        )
        targets = [MonitorTarget(i["item_id"], i["locator"]) for i in items]
        if source:
            known = {t.item_id for t in source.targets}
            added = [t for t in targets if t.item_id not in known]
            if added:
                source.targets.extend(added)
                source.revision += 1
        else:
            source = MonitorSource(
                str(uuid4()),
                owner_id,
                self.policy.adapter_id,
                url,
                bridge_id,
                auth_id,
                interval_s=interval_s,
                next_due_at=self.clock.utc(),
                targets=targets,
            )
        self.store.save_source(source)
        if auth_id:
            self.store.put_meta("auth:" + auth_id, self.auth.metadata(auth_id))
        self.on_change()
        return source

    def configure(
        self,
        source_id: str,
        owner_id: int,
        expected_revision: int,
        *,
        enabled: bool | None = None,
        interval_s: float | None = None,
    ) -> MonitorSource:
        source = self.owned(source_id, owner_id)
        if source.revision != expected_revision:
            raise MonitorError("revision_conflict")
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise MonitorError("invalid")
            source.enabled = enabled
        if interval_s is not None:
            if not math.isfinite(interval_s) or interval_s < self.policy.min_interval_s:
                raise MonitorError("invalid")
            source.interval_s = interval_s
        source.revision += 1
        self.store.save_source(source)
        self.on_change()
        return source

    def request_check(self, source_id: str, owner_id: int, request_id: str) -> dict[str, Any]:
        source = self.owned(source_id, owner_id)
        if not request_id:
            raise MonitorError("invalid")
        key = f"{owner_id}:{source_id}:{request_id}"
        previous = self.store.request(key)
        if previous:
            return self.store.check(previous) or {}
        active = next(
            (
                c
                for c in self.store.checks(source_id)
                if c["state"] in ("queued", "running", "processing")
            ),
            None,
        )
        check = active or {
            "check_id": str(uuid4()),
            "source_id": source_id,
            "source_revision": source.revision,
            "auth_generation": None,
            "state": "queued",
            "outcome": None,
            "error": None,
            "created_at": self.clock.utc(),
            "last_checked_at": None,
        }
        self.store.save_request(key, check)
        if not request_id.startswith("timer:"):
            self.on_change()
        return check
