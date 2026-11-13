"""Registered site rules for raw-HTML tasks; no item or video extraction."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..net.http.cookies import domain_match
from .adapters.moodle import MoodleAdapter
from .models import AccessVerdict, MonitorError, SafeResponse, SitePolicy

_YOUTUBE_COOKIES = (
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "LOGIN_INFO",
    "SIDCC",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
    "__Secure-1PSIDTS",
    "__Secure-3PSIDTS",
    "__Secure-1PSIDCC",
    "__Secure-3PSIDCC",
)
_BILIBILI_COOKIES = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "buvid3", "buvid4")


@dataclass(frozen=True)
class PagePolicy(SitePolicy):
    site_profile: str = "youtube"
    cookie_domains: tuple[str, ...] = ()
    allow_default_cookie_path: bool = True

    def canonical(self, url: str, *, target: bool = False) -> str:
        allowed = self.target_urls if target else (*self.target_urls, self.origin + "/robots.txt")
        if url not in allowed:
            raise MonitorError("blocked")
        return url

    def cookie_allowed(
        self, name: str, domain: str, path: str, host_only: bool, secure: bool
    ) -> bool:
        normalized = domain.lstrip(".").lower()
        return (
            type(host_only) is bool
            and type(secure) is bool
            and name in self.cookie_names
            and normalized in self.cookie_domains
            and path.startswith("/")
            and not any(ord(c) < 33 for c in path)
            and (domain == self.host if host_only else domain_match(self.host, normalized))
            and (not name.startswith("__Secure-") or secure)
            and (not name.startswith("__Host-") or (secure and host_only and path == "/"))
        )

    def allows_redirect(self, source: str, destination: str) -> bool:
        return source in self.target_urls and destination in self.target_urls

    def login_redirect(self, url: str) -> bool:
        p = urlsplit(url)
        return p.hostname in ("accounts.google.com", "passport.bilibili.com") or p.path.startswith(
            "/login"
        )


def page_policy(profile: str, target_url: str) -> SitePolicy:
    """Only trusted profiles are registered; the caller chooses an exact public target."""
    try:
        p = urlsplit(target_url)
        if (
            p.scheme != "https"
            or p.port not in (None, 443)
            or p.username is not None
            or p.password is not None
            or p.fragment
            or any(ord(c) < 33 or ord(c) == 127 for c in target_url)
            or p.netloc != p.hostname
        ):
            raise MonitorError("blocked")
    except ValueError:
        raise MonitorError("blocked") from None
    if profile == "moodle":
        policy = SitePolicy(target_urls=(target_url,))
        policy.canonical(target_url, target=True)
        return policy
    if profile == "youtube":
        if p.hostname != "www.youtube.com" or not (
            (
                not p.query
                and re.fullmatch(
                    r"/(?:@[\w.-]+|channel/UC[\w-]+)/(?:videos|shorts|streams)", p.path
                )
            )
            or (p.path == "/watch" and re.fullmatch(r"v=[\w-]{11}", p.query))
        ):
            raise MonitorError("unsupported")
        names, domains = _YOUTUBE_COOKIES, ("youtube.com", "www.youtube.com")
        targets = (target_url,)
    elif profile == "bilibili":
        if p.query or not (
            (
                p.hostname == "space.bilibili.com"
                and re.fullmatch(r"/(?:en/)?\d+/?(?:upload/video)?", p.path)
            )
            or (
                p.hostname == "www.bilibili.com"
                and re.fullmatch(r"/(?:en/)?video/BV[\w]{10}/?", p.path)
            )
        ):
            raise MonitorError("unsupported")
        names, domains = _BILIBILI_COOKIES, ("bilibili.com", p.hostname)
        # Some regions redirect to the same page under /en/. No unrelated destination is allowed.
        path = p.path.removeprefix("/en/") if p.path.startswith("/en/") else p.path.lstrip("/")
        root = "https://" + p.hostname
        targets = tuple(dict.fromkeys((target_url, root + "/" + path, root + "/en/" + path)))
    else:
        raise MonitorError("unsupported_profile")
    return PagePolicy(
        origin="https://" + p.hostname,
        adapter_id=profile + "_html_v1",
        cookie_names=names,
        cookie_domains=domains,
        target_urls=targets,
        site_profile=profile,
        request_headers=(("Accept-Language", "en-US,en;q=0.9"),),
    )


class SessionInspector:
    """Read only known session signals, never content or item identities."""

    def __init__(self, profile: str) -> None:
        self.profile = profile
        self._key = secrets.token_bytes(32)
        self._moodle = MoodleAdapter()

    def _principal(self, value: Any) -> str | None:
        if not isinstance(value, (str, int)) or not str(value):
            return None
        return hmac.new(self._key, str(value).encode(), hashlib.sha256).hexdigest()

    def inspect(self, response: SafeResponse) -> AccessVerdict:
        if response.status == 401:
            return AccessVerdict("auth_required", "http_401")
        if response.status == 403:
            return AccessVerdict("forbidden", "http_403")
        if response.status in (412, 429):
            return AccessVerdict("forbidden", "access_challenge")
        if self.profile == "moodle":
            return self._moodle.inspect(response)
        if response.status != 200 or response.content_type.split(";")[0].strip().lower() not in (
            "text/html",
            "application/xhtml+xml",
        ):
            return AccessVerdict("unknown", "unsupported_response")
        soup = BeautifulSoup(response.body, "lxml")
        for script in soup.find_all("script"):
            text = script.string or ""
            pattern = (
                r"ytcfg\.set\s*\(\s*"
                if self.profile == "youtube"
                else r"(?:window\.)?__INITIAL_STATE__\s*=\s*"
            )
            for match in re.finditer(pattern, text):
                try:
                    data = json.JSONDecoder().raw_decode(text[match.end() :])[0]
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                info = data if self.profile == "youtube" else data.get("loginInfo", {})
                if not isinstance(info, dict):
                    continue
                logged = info.get("LOGGED_IN" if self.profile == "youtube" else "isLogin")
                if type(logged) is bool:
                    principal = info.get("DATASYNC_ID" if self.profile == "youtube" else "mid")
                    return AccessVerdict(
                        "authenticated" if logged else "auth_required",
                        "explicit_login_flag",
                        self._principal(principal) if logged else None,
                    )
        return AccessVerdict("unknown", "no_positive_login_evidence")
