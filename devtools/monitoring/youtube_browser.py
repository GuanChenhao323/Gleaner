"""Compatibility wrapper for the sealed YouTube experiment entry point.

The reusable browser implementation lives in gleaner.monitoring.browser.
"""

from gleaner.monitoring.browser import PinnedTunnel, PlaywrightTransport, ResponseGuard
from gleaner.monitoring.profiles import YOUTUBE_BROWSER_RULES
from gleaner.monitoring.transport import CloudflareDNS

__all__ = ["BrowserProbe", "PinnedTunnel", "ResponseGuard"]


class BrowserProbe(PlaywrightTransport):
    def __init__(self, policy, auth, **kwargs):
        kwargs.setdefault(
            "resolver",
            CloudflareDNS(
                policy.host,
                event=kwargs.get("policy_event", lambda _: None),
            ),
        )
        super().__init__(policy, auth, rules=YOUTUBE_BROWSER_RULES, **kwargs)
