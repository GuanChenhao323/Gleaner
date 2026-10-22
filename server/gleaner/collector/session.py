"""信息源登录与会话：一次登录后只保存 Cookie / Token（加密），不保存统一认证密码。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

from ..net.http import CookieJar
from .fetcher import Fetcher, FetchError

_LOGIN_PATH = re.compile(r"/login(/index\.php)?|/cas/login|/sso/", re.I)


def looks_like_login(url: str, body: str = "") -> bool:
    """会话失效信号：被重定向到登录页，或页面里出现登录表单。"""
    if _LOGIN_PATH.search(urlsplit(url).path):
        return True
    return 'id="login"' in body and 'name="password"' in body


@dataclass
class SourceSession:
    cookies: CookieJar = field(default_factory=CookieJar)
    ws_token: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_secret(self) -> dict[str, Any]:
        return {"cookies": self.cookies.to_list(), "ws_token": self.ws_token, "extra": self.extra}

    @classmethod
    def from_secret(cls, d: dict[str, Any] | None) -> SourceSession:
        d = d or {}
        return cls(
            CookieJar.from_list(d.get("cookies") or []), d.get("ws_token"), d.get("extra") or {}
        )


async def moodle_login(fetcher: Fetcher, base: str, username: str, password: str) -> SourceSession:
    """Moodle 登录：优先换取 Web Service token（moodle_mobile_app），同时保存网页会话 Cookie。"""
    sess = SourceSession()
    # 1) Web Service token（与 Moodle 官方 App、moodle-dl 相同的方式）
    try:
        r = await fetcher.fetch(
            urljoin(base, "/login/token.php"),
            method="POST",
            body=urlencode(
                {"username": username, "password": password, "service": "moodle_mobile_app"}
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = r.json() if r.status == 200 else {}
        if isinstance(data, dict) and data.get("token"):
            sess.ws_token = data["token"]
        elif isinstance(data, dict) and data.get("errorcode") == "invalidlogin":
            raise FetchError("need_login", "用户名或密码错误")
    except FetchError as e:
        if e.kind == "need_login":
            raise
    # 2) 网页表单登录，拿到 MoodleSession
    r = await fetcher.fetch(urljoin(base, "/login/index.php"), cookies=sess.cookies)
    m = re.search(r'name="logintoken" value="([^"]+)"', r.text())
    form = {"username": username, "password": password, "logintoken": m.group(1) if m else ""}
    r = await fetcher.fetch(
        urljoin(base, "/login/index.php"),
        method="POST",
        body=urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        cookies=sess.cookies,
        follow_redirects=False,
    )
    if r.status not in (302, 303) or looks_like_login(r.headers.get("Location", "")):
        if sess.ws_token is None:
            raise FetchError("need_login", "用户名或密码错误")
    return sess
