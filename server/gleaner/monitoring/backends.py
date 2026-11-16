"""Select a transport from a registered policy; HTTP stays the default."""

from __future__ import annotations

from importlib.util import find_spec
from typing import Any, Protocol

from .auth import AuthManager
from .models import MonitorError, RemoteTransport, SitePolicy
from .transport import CloudflareDNS, HTTPXTransport


class PageTransport(RemoteTransport, Protocol):
    async def close(self) -> None: ...


def create_page_transport(policy: SitePolicy, auth: AuthManager, **kwargs: Any) -> PageTransport:
    if auth.policy != policy:
        raise MonitorError("binding_denied")
    backend = getattr(policy, "backend_kind", "http")
    dns_strategy = getattr(policy, "dns_strategy", "compatible")
    if dns_strategy == "cloudflare":
        kwargs.setdefault(
            "resolver",
            CloudflareDNS(
                policy.host,
                clock=kwargs.get("clock"),
                event=kwargs.get("policy_event", lambda _: None),
            ),
        )
    elif dns_strategy != "compatible":
        raise MonitorError("unsupported_dns_strategy")
    if backend == "http":
        return HTTPXTransport(policy, auth, **kwargs)
    if backend == "playwright":
        if find_spec("playwright") is None:
            raise MonitorError("browser_unavailable")
        from .browser import PlaywrightTransport

        rules = getattr(policy, "browser_rules", None)
        if rules is None:
            raise MonitorError("unsupported_browser_scope")
        return PlaywrightTransport(policy, auth, rules=rules, **kwargs)
    raise MonitorError("unsupported_backend")
