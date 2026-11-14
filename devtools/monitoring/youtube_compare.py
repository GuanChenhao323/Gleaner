"""Opt-in YouTube experiment; the production profiles and backend stay unchanged.

python -m devtools.monitoring.youtube_compare --backend http --report PATH
Install server's browser-validation extra before selecting --backend playwright.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import ipaddress
import json
import math
import re
import signal
from dataclasses import replace
from importlib.metadata import version
from uuid import uuid4

from bs4 import BeautifulSoup
from gleaner.monitoring.models import MonitorError
from gleaner.monitoring.pages import PageMonitor, PageTask
from gleaner.monitoring.profiles import page_policy
from gleaner.monitoring.transport import HTTPXTransport

from .page_run import DiagnosticSessionInspector, Harness

TARGET = "https://www.youtube.com/@3blue1brown/videos"
INITIAL_COOKIES = (
    "__Secure-3PSID",
    "__Secure-3PAPISID",
    "__Secure-3PSIDTS",
    "__Secure-3PSIDCC",
)


def experimental_policy(profile, url):
    if profile != "youtube" or url != TARGET:
        raise MonitorError("unsupported_experiment_target")
    return replace(
        page_policy(profile, url), cookie_names=(*INITIAL_COOKIES, "LOGIN_INFO")
    )


class ProbeMonitor(PageMonitor):
    """Only replace registration for this fixed, opt-in experiment policy."""

    def register(self, params, *, owner_id, bridge_id):
        if not isinstance(params, dict) or set(params) != {
            "target_url",
            "interval_s",
            "auth_context_id",
            "site_profile",
        }:
            raise MonitorError("invalid")
        interval = params["interval_s"]
        if (
            type(interval) not in (int, float)
            or not math.isfinite(interval)
            or interval < 600
        ):
            raise MonitorError("invalid")
        if (
            experimental_policy(params["site_profile"], params["target_url"])
            != self.policy
        ):
            raise MonitorError("binding_denied")
        c = self.auth.context(params["auth_context_id"])
        if (c.owner_id, c.bridge_id) != (
            owner_id,
            bridge_id,
        ) or self.auth.policy != self.policy:
            raise MonitorError("binding_denied")
        self.task = PageTask(str(uuid4()), owner_id, bridge_id, **params)
        return self.task


class NetworkInspector(DiagnosticSessionInspector):
    """Only booleans leave memory; no IP or stable network fingerprint is emitted."""

    def __init__(self, profile, emit):
        super().__init__(profile, emit)
        self.previous = None

    def inspect(self, response):
        verdict = super().inspect(response)
        keys = set()
        soup = BeautifulSoup(response.body, "lxml")
        for script in soup.find_all("script"):
            text = script.string or ""
            for match in re.finditer(r"ytcfg\.set\s*\(\s*", text):
                try:
                    data = json.JSONDecoder().raw_decode(text[match.end() :])[0]
                    raw = data["INNERTUBE_CONTEXT"]["client"]["remoteHost"]
                    address = ipaddress.ip_address(raw)
                    if address.is_global:
                        keys.add(
                            hmac.digest(
                                self._key, str(address).encode(), hashlib.sha256
                            )
                        )
                except (ValueError, TypeError, KeyError):
                    continue
        key = next(iter(keys)) if len(keys) == 1 else None
        self.emit(
            {
                "network_identity_observed": key is not None,
                "network_identity_changed": None
                if key is None or self.previous is None
                else key != self.previous,
            }
        )
        if key is not None:
            self.previous = key
        return verdict


def make_harness(args):
    transport = HTTPXTransport
    if args.backend == "playwright":
        from .youtube_browser import BrowserProbe

        transport = BrowserProbe
    return Harness(
        args,
        policy_factory=experimental_policy,
        transport_factory=transport,
        monitor_factory=ProbeMonitor,
        inspector_factory=NetworkInspector,
        import_names=INITIAL_COOKIES,
    )


async def main(args):
    harness = make_harness(args)
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, harness.stop.set)
    try:
        await harness.setup()
        harness.append(
            "experiment",
            {
                "backend": args.backend,
                "initial_cookie_names": list(INITIAL_COOKIES),
                "response_cookie_names": list(harness.policy.cookie_names),
                "egress": "direct_pinned_dns",
                "user_agent": "GleanerMonitor/1.0",
                "credential_persistence": "memory_only",
                "html_kind": "main_document_response",
                "default_profile_unchanged": True,
                "httpx_version": version("httpx"),
                "playwright_version": version("playwright")
                if args.backend == "playwright"
                else None,
            },
        )
        await harness.loop()
    finally:
        await harness.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("http", "playwright"), required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--interval", type=float, default=600)
    parser.add_argument("--duration", type=float, default=7200)
    parser.set_defaults(site="youtube", target=TARGET, robots_fallback="strict")
    args = parser.parse_args()
    if (
        not math.isfinite(args.interval)
        or args.interval < 600
        or not math.isfinite(args.duration)
        or args.duration < 0
    ):
        parser.error("interval >= 600 and duration >= 0 required")
    asyncio.run(main(args))
