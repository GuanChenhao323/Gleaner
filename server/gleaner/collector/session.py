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


def moodle_ws_url(base: str, token: str, function: str) -> str:
    """Moodle REST Web Service 地址。

    不能写成 ``urljoin(base, "/webservice/rest/server.php?") + query``：Python 3.12 的 urljoin
    会丢掉末尾空的“?”，拼出 ``server.phpwstoken=…``（3.14 不会），token 等于没传。
    """
    query = urlencode({"wstoken": token, "wsfunction": function, "moodlewsrestformat": "json"})
    return urljoin(base, "/webservice/rest/server.php") + "?" + query


_WS_KEY = re.compile(r"[0-9a-f]{32}")
# 采集用到的 Web Service 函数（见 connectors/moodle.py）
_REQUIRED_FUNCTIONS = ("mod_assign_get_assignments",)


def normalize_ws_key(raw: str) -> str | None:
    """Moodle 安全密钥是 32 位十六进制；去掉复制时带上的空白，格式不对返回 None。"""
    key = "".join(raw.split()).lower()
    return key if _WS_KEY.fullmatch(key) else None


async def moodle_token_session(fetcher: Fetcher, base: str, key: str) -> SourceSession:
    """用用户粘贴的安全密钥（偏好设置 → 安全密钥 → Moodle mobile web service）建立会话。

    适用于统一认证（CAS / SSO）的学校：账号密码不能直接换 token，拾课也不经手统一认证密码。
    用 core_webservice_get_site_info 校验密钥有效，并确认所属服务允许读取作业。
    """
    r = await fetcher.fetch(moodle_ws_url(base, key, "core_webservice_get_site_info"))
    try:
        data = r.json()
    except ValueError as e:
        raise FetchError("parse", f"Web Service 返回的不是 JSON（HTTP {r.status}）") from e
    if isinstance(data, dict) and data.get("errorcode"):
        if data["errorcode"] in ("invalidtoken", "accessexception"):
            raise FetchError("need_login", "密钥无效或已过期，请在 Moodle 安全密钥页面重新复制")
        raise FetchError("parse", str(data.get("message") or data["errorcode"]))
    if not isinstance(data, dict):
        raise FetchError("parse", "Web Service 返回格式异常")
    allowed = {f.get("name") for f in data.get("functions") or []}
    missing = [f for f in _REQUIRED_FUNCTIONS if allowed and f not in allowed]
    if missing:
        raise FetchError(
            "need_login",
            "这个密钥所属的服务不能读取作业，请复制“Moodle mobile web service”那一行的密钥",
        )
    return SourceSession(ws_token=key)
