"""Typed in-process contracts and deliberately non-secret errors for monitoring."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class MonitorError(Exception):
    """Only controlled error codes may leave the network/authentication boundary."""

    def __init__(self, code: str, *, retryable: bool = False, retry_after_s: float = 0) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after_s = retry_after_s


class Clock:
    def utc(self) -> float:
        return time.time()

    def mono(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0, seconds))


@dataclass(frozen=True)
class SitePolicy:
    origin: str = "https://moodle.must.edu.mo"
    adapter_id: str = "must_moodle_assignment_v1"
    paths: tuple[str, ...] = ("/mod/assign/view.php", "/robots.txt")
    cookie_names: tuple[str, ...] = ("MoodleSession",)
    min_interval_s: float = 600
    host_gap_s: float = 2
    # Explicit loopback origin is required; global egress environment is never consulted.
    local_test: bool = False
    target_urls: tuple[str, ...] = ()

    @property
    def host(self) -> str:
        return urlsplit(self.origin).hostname or ""

    def canonical(self, url: str, *, target: bool = False) -> str:
        try:
            p, base = urlsplit(url), urlsplit(self.origin)
            port, base_port = (
                p.port or (443 if p.scheme == "https" else 80),
                base.port or (443 if base.scheme == "https" else 80),
            )
        except ValueError:
            raise MonitorError("blocked") from None
        if (
            any(ord(c) < 33 or ord(c) == 127 for c in url)
            or p.username is not None
            or p.password is not None
            or p.scheme != base.scheme
            or p.hostname != base.hostname
            or port != base_port
            or p.path not in self.paths
            or p.fragment
            or (p.scheme != "https" and not self.local_test)
        ):
            raise MonitorError("blocked")
        if self.local_test and self.host not in ("127.0.0.1", "::1", "localhost"):
            raise MonitorError("blocked")
        pairs = parse_qsl(p.query, keep_blank_values=True)
        if p.path == "/mod/assign/view.php":
            if (
                len(pairs) != 1
                or pairs[0][0] != "id"
                or not pairs[0][1].isascii()
                or not pairs[0][1].isdigit()
            ):
                raise MonitorError("unsupported")
            pairs = [("id", str(int(pairs[0][1])))]
        elif pairs:
            raise MonitorError("blocked")
        clean = urlunsplit((base.scheme, base.netloc, p.path, urlencode(pairs), ""))
        if target and (
            p.path != "/mod/assign/view.php" or (self.target_urls and clean not in self.target_urls)
        ):
            raise MonitorError("unsupported")
        return clean


@dataclass(frozen=True)
class MonitorTarget:
    item_id: int
    locator: str
    enabled: bool = True


@dataclass
class MonitorSource:
    source_id: str
    owner_id: int
    adapter_id: str
    canonical_url: str
    bridge_id: str
    auth_id: str | None
    interval_s: float = 600
    revision: int = 1
    enabled: bool = True
    next_due_at: float = 0
    runtime_status: str = "waiting_auth"
    failures: int = 0
    last_success_at: float | None = None
    targets: list[MonitorTarget] = field(default_factory=list)


@dataclass(frozen=True)
class FetchPlan:
    source_id: str
    source_revision: int
    auth_generation: int | None
    check_id: str
    canonical_url: str
    target_ids: tuple[int, ...]
    method: str = "GET"
    validators: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthLease:
    auth_id: str
    generation: int
    approved_origin: str
    opaque_handle: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class SafeResponse:
    status: int
    final_url: str
    content_type: str
    body: bytes = field(repr=False)
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class AccessVerdict:
    state: str
    evidence_code: str
    principal_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class TargetObservation:
    item_id: int
    locator: str
    outcome: str
    canonical_url: str
    title: str | None = None
    text: str | None = field(default=None, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None


@dataclass(frozen=True)
class ObservationBatch:
    observation_id: str
    check_id: str
    source_id: str
    source_revision: int
    auth_generation: int | None
    observed_at: float
    adapter_version: str
    representation_hash: str
    entries: list[TargetObservation]
    schema_version: str = "1"


@dataclass(frozen=True)
class ApplyReceipt:
    observation_id: str
    source_id: str
    source_revision: int
    applied: bool
    results: list[dict[str, Any]]


class ObservationSink(Protocol):
    async def apply(self, batch: ObservationBatch) -> ApplyReceipt: ...


class RemoteTransport(Protocol):
    async def fetch(self, plan: FetchPlan, auth: AuthLease | None) -> SafeResponse: ...
