"""Memory-only credentials, browser presence, and execution generation fences."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from ..net.http.cookies import Cookie, CookieJar, default_path
from .models import AuthLease, Clock, MonitorError, SitePolicy

SessionInvalidator = Callable[[], asyncio.Future[None] | None]


@dataclass
class AuthContext:
    auth_id: str
    owner_id: int
    bridge_id: str
    cookie_store_id: str
    state: str = "needs_credentials"
    revision: int = 0
    generation: int = 1
    principal_key: str | None = field(default=None, repr=False)
    confirmed_same_account: bool = False
    was_verified: bool = False
    jar: CookieJar = field(default_factory=CookieJar, repr=False)
    network_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    lease_handle: object = field(default_factory=object, repr=False)


class AuthManager:
    def __init__(self, policy: SitePolicy, clock: Clock | None = None) -> None:
        self.policy = policy
        self.clock = clock or Clock()
        self.backend_epoch = str(uuid4())
        self._key = secrets.token_bytes(32)
        self.contexts: dict[str, AuthContext] = {}
        self._presence: dict[str, tuple[int, float, bool]] = {}
        self._imports: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._resources: dict[str, tuple[object, SessionInvalidator]] = {}
        self.persist_metadata: Callable[[dict[str, Any]], None] = lambda _: None

    def attach_resource(self, auth_id: str, owner: object, invalidate: SessionInvalidator) -> None:
        """Bind one credential-owning runtime; invalidation must fence use synchronously.

        The callback may return an asynchronous cleanup future. Revocation awaits it;
        synchronous import/close callers also close their transport during shutdown.
        """
        self.context(auth_id)
        current = self._resources.get(auth_id)
        if current is not None and current[0] is not owner:
            raise MonitorError("binding_denied")
        self._resources[auth_id] = (owner, invalidate)

    def detach_resource(self, auth_id: str, owner: object) -> None:
        current = self._resources.get(auth_id)
        if current is not None and current[0] is owner:
            self._resources.pop(auth_id)

    def _invalidate_resource(self, auth_id: str) -> asyncio.Future[None] | None:
        current = self._resources.get(auth_id)
        if current is None:
            return None
        try:
            return current[1]()
        except Exception:
            raise MonitorError("session_cleanup_failed") from None

    def _save(self, auth_id: str) -> None:
        self.persist_metadata(self.metadata(auth_id))

    def create(self, owner_id: int, bridge_id: str, cookie_store_id: str = "0") -> AuthContext:
        if not bridge_id or not cookie_store_id:
            raise MonitorError("binding_denied")
        ctx = AuthContext(str(uuid4()), owner_id, bridge_id, cookie_store_id)
        self.contexts[ctx.auth_id] = ctx
        self._save(ctx.auth_id)
        return ctx

    def context(self, auth_id: str) -> AuthContext:
        if auth_id not in self.contexts:
            raise MonitorError("not_found")
        return self.contexts[auth_id]

    def presence(self, bridge_id: str, sequence: int, enabled: bool = True) -> float:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise MonitorError("invalid")
        previous = self._presence.get(bridge_id)
        if previous:
            if sequence < previous[0]:
                raise MonitorError("revision_conflict")
            if sequence == previous[0]:
                return previous[1]
        lease = self.clock.mono() + 180
        self._presence[bridge_id] = (sequence, lease, enabled)
        return lease

    def online(self, bridge_id: str) -> bool:
        p = self._presence.get(bridge_id)
        return bool(p and p[2] and p[1] > self.clock.mono())

    def metadata(self, auth_id: str) -> dict[str, Any]:
        c = self.context(auth_id)
        return {
            "auth_id": c.auth_id,
            "owner_id": c.owner_id,
            "bridge_id": c.bridge_id,
            "cookie_store_id": c.cookie_store_id,
            "state": c.state,
            "revision": c.revision,
            "generation": c.generation,
            "was_verified": c.was_verified,
        }

    def restore(self, metadata: dict[str, Any]) -> AuthContext:
        self._invalidate_resource(metadata["auth_id"])
        c = AuthContext(
            metadata["auth_id"],
            metadata["owner_id"],
            metadata["bridge_id"],
            metadata["cookie_store_id"],
            state="revoked" if metadata.get("state") == "revoked" else "needs_credentials",
            revision=metadata["revision"] + 1,
            generation=metadata["generation"] + 1,
            was_verified=metadata["was_verified"],
        )
        self.contexts[c.auth_id] = c
        self._save(c.auth_id)
        return c

    def import_cookies(
        self,
        auth_id: str,
        cookies: list[dict[str, Any]],
        *,
        backend_epoch: str,
        expected_revision: int,
        request_id: str,
        reason: str = "initial",
        confirmed_same_account: bool = False,
    ) -> dict[str, Any]:
        c = self.context(auth_id)
        if backend_epoch != self.backend_epoch:
            raise MonitorError("stale_backend")
        if c.state == "revoked" and reason != "manual_reauthorize":
            raise MonitorError("revoked")
        if not request_id or reason not in (
            "initial",
            "backend_restart",
            "auth_recovery",
            "manual_reauthorize",
        ):
            raise MonitorError("invalid")
        raw = json.dumps(
            [cookies, expected_revision, reason, confirmed_same_account], sort_keys=True
        ).encode()
        if len(raw) > 262144:
            raise MonitorError("too_large")
        digest = hmac.new(self._key, raw, hashlib.sha256).hexdigest()
        key = (auth_id, request_id)
        if key in self._imports:
            old, reply = self._imports[key]
            if old != digest:
                raise MonitorError("idempotency_conflict")
            return reply.copy()
        if expected_revision != c.revision:
            raise MonitorError("revision_conflict")
        if c.state == "valid" and reason != "manual_reauthorize":
            raise MonitorError("active_session")
        if c.was_verified and c.principal_key is None and not confirmed_same_account:
            raise MonitorError("account_confirmation_required")
        jar, seen = CookieJar(), set()
        if not isinstance(cookies, list) or not cookies:
            raise MonitorError("invalid")
        for record in cookies:
            try:
                name, value = record["name"], record["value"]
                domain, path = record["domain"], record["path"]
                host_only, secure = record["host_only"], record["secure"]
                session, expires = record["session"], record["expires_at"]
                if (
                    record.get("partitionKey") is not None
                    or record.get("partition_key") is not None
                    or record.get("partitioned")
                ):
                    raise MonitorError("partitioned_cookie_unsupported")
                if not all(isinstance(v, str) for v in (name, value, domain, path)):
                    raise MonitorError("invalid")
                if (
                    name not in self.policy.import_cookie_names
                    or not self.policy.cookie_allowed(name, domain, path, host_only, secure)
                    or record.get("same_site", "")
                    not in ("strict", "lax", "none", "unspecified", "no_restriction")
                    or any(ord(ch) < 32 or ord(ch) == 127 for ch in name + value + domain + path)
                    or any(ord(ch) < 33 or ord(ch) > 126 or ch in ';"\\,' for ch in value)
                    or len(name) + len(value) > 4096
                ):
                    raise MonitorError("cookie_scope_denied")
                if not isinstance(session, bool) or (session and expires is not None):
                    raise MonitorError("invalid")
                if not session and (
                    not isinstance(expires, (int, float))
                    or not math.isfinite(expires)
                    or expires <= self.clock.utc()
                ):
                    raise MonitorError("auth_required")
                domain = domain.lstrip(".").lower()
                ident = (domain, path, name)
                if ident in seen:
                    raise MonitorError("invalid")
                seen.add(ident)
                cookie = Cookie(
                    name,
                    value,
                    domain,
                    path,
                    expires,
                    secure=secure,
                    http_only=bool(record["http_only"]),
                    host_only=host_only,
                    same_site=record.get("same_site", ""),
                )
                jar = CookieJar([*map(lambda x: Cookie(**x), jar.to_list()), cookie])
            except (KeyError, TypeError, ValueError):
                raise MonitorError("invalid") from None
        c.jar.clear()
        c.jar, c.state = jar, "unverified"
        c.generation += 1
        c.lease_handle = object()
        c.revision += 1
        c.confirmed_same_account = confirmed_same_account
        try:
            self._invalidate_resource(auth_id)
        except MonitorError:
            c.jar.clear()
            c.state = "auth_required"
            self._save(auth_id)
            raise
        reply = self.metadata(auth_id)
        self._imports[key] = (digest, reply.copy())
        self._save(auth_id)
        return reply

    async def acquire(self, auth_id: str) -> AuthLease:
        c = self.context(auth_id)
        if c.state == "revoked":
            raise MonitorError("revoked")
        if c.state not in ("unverified", "valid") or not len(c.jar):
            c.state = "auth_required"
            self._save(auth_id)
            self._invalidate_resource(auth_id)
            raise MonitorError("auth_required")
        return AuthLease(auth_id, c.generation, self.policy.origin, c.lease_handle)

    def current(self, lease: AuthLease) -> AuthContext:
        c = self.context(lease.auth_id)
        if lease.opaque_handle is not c.lease_handle or c.generation != lease.generation:
            raise MonitorError("superseded")
        if c.state not in ("valid", "unverified"):
            raise MonitorError("auth_required")
        return c

    def header(self, lease: AuthLease, url: str) -> str:
        c, p = self.current(lease), urlsplit(url)
        if lease.approved_origin != self.policy.origin or p.hostname != self.policy.host:
            raise MonitorError("binding_denied")
        value = c.jar.header_for(
            self.policy.host, p.path, p.scheme == "https" or self.policy.local_test
        )
        if not value:
            c.state = "auth_required"
            self._save(c.auth_id)
            self._invalidate_resource(c.auth_id)
            raise MonitorError("auth_required")
        return value

    def update_cookies(self, lease: AuthLease, headers: list[str], url: str) -> None:
        c = self.current(lease)
        for header in headers:
            if any(ord(ch) < 32 or ord(ch) == 127 for ch in header):
                continue
            parts = header.split(";")
            name, separator, value = parts[0].strip().partition("=")
            attrs = {}
            duplicate = False
            for part in parts[1:]:
                key, _, val = part.strip().partition("=")
                key = key.lower()
                duplicate = duplicate or key in attrs
                attrs[key] = val.strip()
            # Validate scope before expiry processing; deletion cookies need the same checks.
            if (
                not separator
                or duplicate
                or "partitioned" in attrs
                or ("path" not in attrs and not self.policy.allow_default_cookie_path)
                or not self.policy.cookie_allowed(
                    name,
                    attrs.get("domain", self.policy.host),
                    attrs.get("path", default_path(urlsplit(url).path)),
                    "domain" not in attrs,
                    "secure" in attrs,
                )
                or any(ord(ch) < 33 or ord(ch) > 126 or ch in ';"\\,' for ch in value)
            ):
                continue
            if c.jar.set_from_header(header, self.policy.host, urlsplit(url).path, True):
                c.revision += 1
        if not len(c.jar):
            c.state = "auth_required"
            self._invalidate_resource(c.auth_id)
        self._save(c.auth_id)

    def verify(self, lease: AuthLease, principal_key: str | None) -> None:
        c = self.current(lease)
        if c.principal_key and principal_key and c.principal_key != principal_key:
            c.jar.clear()
            c.state = "auth_required"
            self._save(c.auth_id)
            self._invalidate_resource(c.auth_id)
            raise MonitorError("account_mismatch")
        if (
            c.state == "unverified"
            and c.was_verified
            and principal_key is None
            and not c.confirmed_same_account
        ):
            c.state = "auth_required"
            self._save(c.auth_id)
            self._invalidate_resource(c.auth_id)
            raise MonitorError("account_confirmation_required")
        c.principal_key = principal_key or c.principal_key
        c.was_verified, c.state = True, "valid"
        self._save(c.auth_id)

    def require_auth(self, auth_id: str) -> None:
        if self.context(auth_id).state == "revoked":
            return
        self.context(auth_id).state = "auth_required"
        self._save(auth_id)
        self._invalidate_resource(auth_id)

    def approve_reauthorization(self, auth_id: str) -> None:
        context = self.context(auth_id)
        if context.state == "revoked":
            context.state = "needs_credentials"
            context.revision += 1
            context.generation += 1
            context.lease_handle = object()
            self._save(auth_id)

    async def revoke(self, auth_id: str, expected_revision: int) -> None:
        c = self.context(auth_id)
        if c.state == "revoked":
            cleanup = self._invalidate_resource(auth_id)
            if cleanup is not None:
                await asyncio.shield(cleanup)
            return
        if c.revision != expected_revision:
            raise MonitorError("revision_conflict")
        c.jar.clear()
        c.generation += 1
        c.revision += 1
        c.state = "revoked"
        self._imports = {k: v for k, v in self._imports.items() if k[0] != auth_id}
        c.lease_handle = object()
        self._save(auth_id)
        cleanup = self._invalidate_resource(auth_id)
        if cleanup is not None:
            await asyncio.shield(cleanup)

    def close(self) -> None:
        cleanup_failed = False
        for c in self.contexts.values():
            c.jar.clear()
            if c.state != "revoked":
                c.state = "needs_credentials"
            c.generation += 1
            c.lease_handle = object()
            self._save(c.auth_id)
            try:
                self._invalidate_resource(c.auth_id)
            except MonitorError:
                cleanup_failed = True
        self._imports.clear()
        if cleanup_failed:
            raise MonitorError("session_cleanup_failed")
