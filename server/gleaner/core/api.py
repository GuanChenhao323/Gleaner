"""REST API（proposal“REST API”一节）。所有路由在 ``/api`` 下，由网关转发到这里。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .. import security
from ..collector.connectors import CONNECTORS, Context, SourceInfo
from ..collector.connectors.base import normalize_url
from ..collector.fetcher import Fetcher, FetchError
from ..collector.session import (
    SourceSession,
    moodle_login,
    moodle_token_session,
    normalize_ws_key,
)
from ..mailsvc.sender import send_platform_mail, send_user_mail
from ..net.http import Request, Response, Router
from ..storage.db import Database, is_unique_violation, loads
from ..storage.migrations import share_key
from . import edits, monitor
from .itemtypes import ALL_STATUSES, ITEM_TYPES, status_of, status_sql
from .monitors import BrowserMonitorService
from .pipeline import Pipeline, item_public, owner_prefix
from .reading_schedule import ReadingSchedule
from .reading_sources import ReadingSourceService
from .templates import get_template, list_templates
from .throttle import Throttle
from .timeline_captures import TimelineCaptureContract
from .validate import (
    BadRequest,
    Handler,
    as_dict,
    as_float,
    as_int,
    as_list,
    as_str,
    body_of,
    guard,
    invalid,
    path_id,
)
from .web_captures import WebCaptureService

log = logging.getLogger(__name__)

Publish = Callable[[str, dict[str, Any]], Awaitable[None]]

COOKIE = "gl_session"
CODE_TTL = 600
CODE_RESEND = 60
CODE_MAX_ATTEMPTS = 5


def require_email_code() -> bool:
    return os.environ.get("GLEANER_REQUIRE_EMAIL_CODE", "1") == "1"


def _code_hash(email: str, code: str) -> str:
    return hmac.new(security.secret(), f"code:{email}:{code}".encode(), hashlib.sha256).hexdigest()


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SESSION_TTL = 30 * 86400
PASSWORD_MIN = 8
PASSWORD_MAX = 256
_HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def _client_ip(req: Request) -> str:
    """网关把真实客户端地址放在 X-Forwarded-For 第一段（core 只接受网关转发）。"""
    fwd = req.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return str(req.peer[0])[:64] if req.peer else ""


def _cookie(req: Request, token: str, max_age: int) -> str:
    """HttpOnly + SameSite=Lax；经 HTTPS 访问（网关标记 X-Forwarded-Proto）或强制配置时加 Secure。"""
    secure = (
        req.headers.get("X-Forwarded-Proto", "").lower() == "https"
        or os.environ.get("GLEANER_COOKIE_SECURE") == "1"
    )
    return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}" + (
        "; Secure" if secure else ""
    )


def _same_origin(req: Request) -> bool:
    """没有请求体的 Cookie 鉴权修改请求：Origin（或 Referer）必须与 Host 一致。"""
    origin = req.headers.get("Origin") or req.headers.get("Referer") or ""
    host = req.headers.get("X-Forwarded-Host") or req.headers.get("Host") or ""
    if not origin:
        return False
    netloc = origin.split("://", 1)[-1].split("/", 1)[0]
    return bool(host) and netloc.lower() == host.lower()


def _too_many(wait: float, message: str, code: str = "rate_limited") -> Response:
    resp = Response.error(429, message, code)
    resp.headers["Retry-After"] = str(int(wait) + 1)
    return resp


def _email_of(b: dict[str, Any]) -> str:
    email = as_str(b.get("email"), "email", max_len=254, default="").strip().lower()
    if not _EMAIL.match(email):
        raise BadRequest(422, "邮箱格式不正确", "bad_email")
    return email


def _password_of(b: dict[str, Any], key: str) -> str:
    pw = as_str(b.get(key), key, max_len=PASSWORD_MAX, default="")
    if len(pw) < PASSWORD_MIN:
        raise BadRequest(422, f"密码至少 {PASSWORD_MIN} 位", "weak_password")
    return pw


def _courses_of(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(c)[:60] for c in v if isinstance(c, str | int)][:50]


ITEM_KINDS = ("assignment", "notice", "mail", "rss", "teacher", "clip", "page")
FEED_FILTERS = ("unread", "starred", "todo", "important", "trash", "labeled")


def _like(text: str) -> str:
    """LIKE 模式（配合 ``ESCAPE '!'``）：转义用户输入里的 % _ !，统一小写（SQLite 与 PostgreSQL 的大小写行为不同）。"""
    esc = text.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{esc}%"


STATE_BATCH_MAX = 500


def _version_snapshot(raw: Any) -> dict[str, Any]:
    """版本快照的对外形状（IC-002 4.3）：来源内容，供工作台比较相邻版本。旧版本没有存正文时 body 为空。"""
    snap = loads(raw, {})
    attrs = snap.get("attrs") if isinstance(snap.get("attrs"), dict) else {}
    return {
        "title": snap.get("raw_title") or snap.get("title") or "",
        "summary": snap.get("summary") or "",
        "body": snap.get("body") or "",
        "type": snap.get("item_type") or "",
        "deadline_at": snap.get("deadline_at"),
        "requirements": attrs.get("requirements") or "",
        "start_at": attrs.get("start_at"),
        "end_at": attrs.get("end_at"),
        "location": attrs.get("location") or "",
        "url": snap.get("url") or "",
    }


def _effective_type_is(t: str) -> str:
    """生效类型（用户修改优先）等于 t 的 SQL 条件；修改值存为 JSON 字符串，如 "todo"。

    依赖 _items_for 的别名：i = items，s = subscriptions（s.user_id 即当前用户）。t 只能是 ITEM_TYPES 之一。
    """
    assert t in ITEM_TYPES
    return (
        "COALESCE((SELECT et.value FROM user_item_edits et WHERE et.user_id = s.user_id "
        "AND et.item_id = i.id AND et.field = 'type'), "
        "'\"' || COALESCE(NULLIF(i.item_type, ''), 'notice') || '\"') = "
        f"'\"{t}\"'"
    )


def _state_values(b: dict[str, Any]) -> dict[str, Any]:
    """从请求里取出要修改的个人状态字段（read_at 先放布尔值，由调用方换成操作时间）。"""
    vals: dict[str, Any] = {}
    if "read" in b:
        vals["read_at"] = bool(b["read"])
    if "starred" in b:
        vals["starred"] = int(bool(b["starred"]))
    if "todo" in b and "done" in b:
        raise BadRequest(422, "todo 与 done 不能同时提交", "invalid")
    if "todo" in b:
        if b["todo"] not in (None, "", "todo", "doing", "done"):
            raise BadRequest(422, "todo 只能是 todo / doing / done 或空", "invalid")
        vals["todo_status"] = b["todo"] or ""
    if "done" in b:
        if not isinstance(b["done"], bool):
            raise BadRequest(422, "done 应为布尔值", "invalid")
        vals["todo_status"] = "done" if b["done"] else "todo"
    if "archived" in b:
        if not isinstance(b["archived"], bool):
            raise BadRequest(422, "archived 应为布尔值", "invalid")
        vals["archived_at"] = b["archived"]
    if "hidden" in b:
        vals["hidden"] = int(bool(b["hidden"]))
    if "deadline_override" in b:
        vals["deadline_override"] = (
            as_float(b["deadline_override"], "deadline_override", lo=0, hi=4_102_444_800)
            if b["deadline_override"]
            else None
        )
    if "note" in b:
        vals["note"] = as_str(b["note"], "note", max_len=2000)
    return vals


MAX_SOURCES_PER_USER = 200
MAIL_MAX_RCPT = 20
# 每种来源允许的地址协议
SOURCE_SCHEMES = {
    "moodle": ("http", "https"),
    "web": ("http", "https"),
    "rss": ("http", "https"),
    "teacher": ("http", "https"),
    "imap": ("imap", "imaps"),
    "pop3": ("pop3", "pop3s"),
}
SMTP_PORTS = (25, 465, 587, 2525)
DASHBOARD_WIDGETS = frozenset(
    {"inbox", "deadlines", "calendar", "todo", "sources", "starred", "board", "course", "digest"}
)
_MIME = re.compile(r"[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*", re.I)


def _one_line(s: str) -> str:
    """邮件头里的字段不能带换行（否则可以注入额外的头或 SMTP 命令）。"""
    return " ".join(s.replace("\r", " ").replace("\n", " ").split())


def _addresses(v: Any, name: str) -> list[str]:
    out = []
    for x in as_list(v, name, max_len=MAIL_MAX_RCPT, default=[]):
        addr = _one_line(as_str(x, name, max_len=254))
        if not _EMAIL.match(addr):
            raise BadRequest(422, f"{name} 里有无效的邮箱地址", "bad_rcpt")
        out.append(addr)
    return out


def _smtp_of(v: Any) -> dict[str, Any]:
    """用户自填的发信服务器：只校验格式；连接时还会检查只能是公网地址（net/egress.py）。"""
    smtp = as_dict(v, "smtp", default={})
    if not smtp:
        return {}
    host = as_str(smtp.get("host"), "smtp.host", max_len=253, default="").strip()
    if not host:
        return {}
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise BadRequest(422, "SMTP 服务器地址不正确", "bad_smtp")
    port = as_int(smtp.get("port"), "smtp.port", default=587)
    if port not in SMTP_PORTS:
        raise BadRequest(422, "SMTP 端口只能是 25 / 465 / 587 / 2525", "bad_smtp")
    security_mode = as_str(smtp.get("security"), "smtp.security", max_len=10, default="starttls")
    if security_mode not in ("starttls", "tls", "none"):
        raise BadRequest(422, "SMTP 加密方式只能是 starttls / tls / none", "bad_smtp")
    return {"host": host, "port": port, "security": security_mode}


def _source_login_error(e: FetchError) -> Response:
    if e.kind == "need_login":
        return Response.error(401, str(e), "source_login_failed")
    if e.kind == "blocked":
        return Response.error(422, str(e), "blocked")
    return Response.error(502, f"连接信息源失败：{e}", f"fetch_{e.kind}")


DEFAULT_DASHBOARD = {
    "widgets": [
        {"id": "w1", "type": "deadlines", "title": "近期截止", "span": 1},
        {"id": "w2", "type": "inbox", "title": "未读通知", "span": 1, "filter": "unread"},
        {"id": "w3", "type": "calendar", "title": "本周任务分布", "span": 2},
        {"id": "w4", "type": "todo", "title": "待办", "span": 1},
        {"id": "w5", "type": "sources", "title": "来源状态", "span": 1},
    ]
}


def _user_public(u: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": u["id"],
        "email": u["email"],
        "name": u["name"],
        "grade": u["grade"],
        "major": u["major"],
        "courses": loads(u.get("courses"), []),
        "digest_time": u["digest_time"],
        "quiet_start": u["quiet_start"],
        "quiet_end": u["quiet_end"],
        "digest_email": bool(u.get("digest_email")),
        "mqtt": {
            "username": str(u["id"]),
            "password": security.mqtt_password(u["id"], u["token_version"]),
            "topics": [f"gleaner/u/{u['id']}/#"],
        },
        "created_at": u["created_at"],
    }


CLIP_MAX_TEXT = 100_000  # 插件上传正文上限（字符）
CAPTURE_MAX_ITEMS = 50


def _capture_snap(
    it: dict[str, Any], name: str, page_url: str, page_title: str, platform: str, locator: str
) -> dict[str, Any]:
    """把插件提交的一条事项（IC-001 3.1）校验并转成流水线的快照；不合法抛 422，只影响这一条。"""
    title = " ".join(as_str(it.get("title"), f"{name}.title", max_len=300).split())
    if not title:
        raise invalid(f"{name}.title", "不能为空")
    text = as_str(it.get("text"), f"{name}.text", max_len=CLIP_MAX_TEXT, default="").strip()
    url = as_str(it.get("url"), f"{name}.url", max_len=2048, default="").strip() or page_url
    if not re.match(r"^https?://", url, re.I):
        raise invalid(f"{name}.url", "只能是 http / https 链接")
    item_type = it.get("type")
    if item_type is not None and item_type not in ITEM_TYPES:
        raise invalid(f"{name}.type", "只能是 todo / event / notice")
    fields = as_dict(it.get("fields"), f"{name}.fields", default={})

    def ts(k: str) -> float | None:
        v = fields.get(k)
        return None if v is None else as_float(v, f"{name}.fields.{k}", lo=0, hi=4_102_444_800)

    return {
        "kind": "clip",
        "title": title,
        "url": url,
        "body": text,
        "item_type": item_type,
        "deadline_at": ts("deadline_at"),
        "start_at": ts("start_at"),
        "end_at": ts("end_at"),
        "location": as_str(
            fields.get("location"), f"{name}.fields.location", max_len=200, default=""
        ).strip(),
        "requirements": as_str(
            fields.get("requirements"), f"{name}.fields.requirements", max_len=4000, default=""
        ).strip(),
        "course": as_str(
            fields.get("course"), f"{name}.fields.course", max_len=100, default=""
        ).strip(),
        "attrs": {
            "saved_from": "browser-extension",
            "page_url": page_url,
            "page_title": page_title,
            "platform": platform,
            "locator": locator,
        },
    }


class API:
    def __init__(
        self,
        db: Database,
        pipeline: Pipeline,
        publish: Publish,
        *,
        fetcher: Fetcher | None = None,
        data_dir: str = "",
        reading_schedule: ReadingSchedule | None = None,
    ) -> None:
        self.db = db
        self.reading_schedule = reading_schedule
        self.pipeline = pipeline
        self.publish = publish
        self.fetcher = fetcher or Fetcher(min_interval=0.2)
        self.data_dir = data_dir
        self.agent_hub: Any = None
        # 在线采集节点数（core 内嵌 Hub 时由 services 注入）；None 表示不检查
        self.collectors_online: Callable[[], int] | None = None
        # 防爆破：同一邮箱 15 分钟内失败 5 次封 1 分钟起（翻倍）；同一 IP 15 分钟内失败 30 次封 5 分钟起
        self.login_by_email = Throttle(limit=5, window=900, base_block=60)
        self.login_by_ip = Throttle(limit=30, window=900, base_block=300)
        # 验证码：同一 IP 一小时最多发 10 封，防止被用来给任意邮箱发信
        self.codes_by_ip = Throttle(limit=10, window=3600, base_block=3600)
        self._dummy_hash = security.hash_password(secrets.token_hex(16))
        # “立即检查”冷却：公共来源大家共用，60 秒内只受理一次（私有来源不限，采集端已按主机限速）
        self.refresh_shared = Throttle(limit=0, window=60, base_block=60, max_block=60)
        self._stats_cache: tuple[float, dict[str, Any]] | None = None
        self.reading: ReadingSourceService | None = None

    # ---- 鉴权 ------------------------------------------------------------------

    async def user_of(self, req: Request) -> dict[str, Any] | None:
        if "user" in req.context:
            return req.context["user"]
        token = None
        auth = req.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            req.context["auth_via"] = "bearer"
        elif req.cookies().get(COOKIE):
            token = req.cookies()[COOKIE]
            req.context["auth_via"] = "cookie"
        claims = security.verify_token(token) if token else None
        user = None
        if claims and isinstance(claims.get("uid"), int):
            user = await self.db.fetchone("SELECT * FROM users WHERE id = ?", claims["uid"])
            if user and user["token_version"] != claims.get("tv"):
                user = None
            sid = claims.get("sid")
            if user and sid:
                sess = await self.db.fetchone(
                    "SELECT revoked_at, last_seen_at FROM sessions WHERE id = ? AND user_id = ?",
                    str(sid),
                    user["id"],
                )
                if not sess or sess["revoked_at"] is not None:
                    user = None
                else:
                    req.context["sid"] = str(sid)
                    if time.time() - sess["last_seen_at"] > 300:  # 最多 5 分钟写一次，减少写放大
                        await self.db.execute(
                            "UPDATE sessions SET last_seen_at = ? WHERE id = ?", time.time(), sid
                        )
        req.context["user"] = user
        return user

    def authed(
        self, fn: Callable[[Request, dict[str, Any]], Awaitable[Response]]
    ) -> Callable[[Request], Awaitable[Response]]:
        async def h(req: Request) -> Response:
            user = await self.user_of(req)
            if user is None:
                return Response.error(401, "请先登录", "unauthorized")
            if req.context.get("auth_via") == "cookie" and req.method not in ("GET", "HEAD"):
                # CSRF：只凭 Cookie 的修改请求必须是 JSON（跨站表单发不出 application/json，
                # 跨站脚本发 JSON 会触发 CORS 预检而被拦下）
                ctype = req.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if req.body and ctype != "application/json":
                    return Response.error(415, "请求体必须是 application/json", "bad_content_type")
                if not req.body and not _same_origin(req):
                    return Response.error(403, "跨站请求被拒绝", "csrf")
            return await fn(req, user)

        return h

    def register(self, r: Router) -> None:
        a = self.authed
        native = BrowserMonitorService(self.db, self.pipeline)
        web = WebCaptureService(self.db, self.pipeline)
        timeline = WebCaptureService(self.db, self.pipeline, TimelineCaptureContract())
        reading = ReadingSourceService(
            self.db, web, native, timeline, schedule=self.reading_schedule
        )
        self.reading = reading
        reading.change_state = self.apply_state
        reading.notify_purge = self.publish
        native.guard_reading = web.guard_reading = timeline.guard_reading = reading.guard_capture
        native.on_capture = web.on_capture = timeline.on_capture = reading.attach
        native.validate_reading = web.validate_reading = timeline.validate_reading = (
            reading.validate_capture
        )
        native.register(r, a)
        web.register(r, a)
        timeline.register(r, a)
        reading.register(r, a)

        def add(method: str, path: str, handler: Handler) -> None:
            r.add(method, path, guard(handler))

        add("GET", "/health", self.health)
        add("GET", "/api/health", self.health)
        add("POST", "/api/auth/code", self.send_code)
        add("POST", "/api/auth/register", self.register_user)
        add("POST", "/api/auth/login", self.login)
        add("POST", "/api/auth/logout", a(self.logout))
        add("POST", "/api/auth/reset/code", self.send_reset_code)
        add("POST", "/api/auth/reset", self.reset_password)
        add("GET", "/api/me", a(self.me))
        add("PUT", "/api/me", a(self.update_me))
        add("PUT", "/api/me/password", a(self.change_password))
        add("GET", "/api/me/sessions", a(self.list_sessions))
        add("DELETE", "/api/me/sessions/{id}", a(self.revoke_session))
        add("DELETE", "/api/account", a(self.delete_account))
        add("GET", "/api/feed", a(self.feed))
        add("GET", "/api/sync", a(self.sync))
        add("GET", "/api/items/{id}", a(self.get_item))
        add("GET", "/api/items/{id}/versions", a(self.versions))
        add("PUT", "/api/items/{id}/state", a(self.put_state))
        add("POST", "/api/items/{id}/feedback", a(self.feedback))
        add("POST", "/api/state/batch", a(self.state_batch))
        add("GET", "/api/deadlines", a(self.deadlines))
        add("GET", "/api/courses", a(self.courses))
        add("GET", "/api/templates", self.templates)
        add("GET", "/api/sources", a(self.list_sources))
        add("POST", "/api/sources", a(self.add_source))
        add("POST", "/api/clips", a(self.save_clip))
        add("POST", "/api/captures", a(self.save_captures))
        add("GET", "/api/monitor/due", a(self.monitor_due))
        add("POST", "/api/monitor/results", a(self.monitor_results))
        add("PATCH", "/api/items/{id}/fields", a(self.patch_fields))
        add("POST", "/api/items/{id}/fields/resolve", a(self.resolve_fields))
        add("PUT", "/api/items/{id}/monitor", a(self.put_monitor))
        add("POST", "/api/sources/preview", a(self.preview_source))
        add("PUT", "/api/sources/{id}", a(self.update_source))
        add("DELETE", "/api/sources/{id}", a(self.remove_source))
        add("POST", "/api/sources/{id}/login", a(self.source_login))
        add("POST", "/api/sources/{id}/refresh", a(self.refresh_source))
        add("POST", "/api/mail/send", a(self.mail_send))
        add("GET", "/api/mail/sent", a(self.mail_sent))
        add("GET", "/api/dashboard", a(self.get_dashboard))
        add("PUT", "/api/dashboard", a(self.put_dashboard))
        add("GET", "/api/rules", a(self.get_rules))
        add("PUT", "/api/rules", a(self.put_rules))
        add("GET", "/api/labels", a(self.list_labels))
        add("POST", "/api/labels", a(self.create_label))
        add("PUT", "/api/labels/{id}", a(self.update_label))
        add("DELETE", "/api/labels/{id}", a(self.delete_label))
        add("PUT", "/api/items/{id}/labels", a(self.put_item_labels))
        add("GET", "/api/stats", self.stats)

    # ---- 账号 ------------------------------------------------------------------

    async def health(self, req: Request) -> Response:
        await self.db.fetchval("SELECT 1")
        return Response.json_body({"status": "ok", "service": "core", "time": time.time()})

    async def _session_response(
        self, req: Request, user: dict[str, Any], status: int = 200
    ) -> Response:
        """新建一个登录会话并下发令牌（Bearer 与 HttpOnly Cookie 两种用法）。"""
        sid = secrets.token_urlsafe(16)
        now = time.time()
        await self.db.insert(
            "sessions",
            {
                "id": sid,
                "user_id": user["id"],
                "created_at": now,
                "last_seen_at": now,
                "user_agent": req.headers.get("User-Agent", "")[:200],
                "ip": _client_ip(req),
            },
        )
        token = security.sign_token({"uid": user["id"], "tv": user["token_version"], "sid": sid})
        resp = Response.json_body({"token": token, "user": _user_public(user)}, status)
        resp.headers.add("Set-Cookie", _cookie(req, token, SESSION_TTL))
        return resp

    async def _issue_code(
        self, req: Request, key: str, email: str, subject: str, text: str
    ) -> Response:
        """生成并发送 6 位验证码（注册与找回密码共用；key 区分用途）。"""
        ip = _client_ip(req)
        wait = self.codes_by_ip.retry_after(ip)
        if wait:
            return _too_many(wait, "验证码发送过于频繁，请稍后再试")
        now = time.time()
        prev = await self.db.fetchone("SELECT sent_at FROM email_codes WHERE email = ?", key)
        if prev and now - prev["sent_at"] < CODE_RESEND:
            return _too_many(
                CODE_RESEND - (now - prev["sent_at"]), "验证码已发送，请稍后再试", "too_soon"
            )
        self.codes_by_ip.hit(ip)
        code = f"{secrets.randbelow(1_000_000):06d}"
        await self.db.execute(
            """INSERT INTO email_codes (email, code_hash, expires_at, attempts, sent_at) VALUES (?, ?, ?, 0, ?)
               ON CONFLICT (email) DO UPDATE SET code_hash = excluded.code_hash, expires_at = excluded.expires_at,
               attempts = 0, sent_at = excluded.sent_at""",
            key,
            _code_hash(key, code),
            now + CODE_TTL,
            now,
        )
        ok = await send_platform_mail(email, subject.format(code=code), text.format(code=code))
        if not ok:
            await self.db.execute("DELETE FROM email_codes WHERE email = ?", key)
            return Response.error(502, "验证码邮件发送失败，请稍后重试", "mail_failed")
        return Response.json_body({"ok": True, "expires_in": CODE_TTL, "resend_after": CODE_RESEND})

    async def send_code(self, req: Request) -> Response:
        """注册验证码：6 位数字，经平台账号用自研 SMTP 发出；10 分钟有效，同一邮箱 60 秒内只发一次。"""
        email = _email_of(body_of(req))
        if await self.db.fetchone("SELECT id FROM users WHERE email = ?", email):
            # 注册时总要告诉用户邮箱已注册，这里不额外隐藏（注册接口同样会返回 409）
            return Response.error(409, "该邮箱已注册", "exists")
        return await self._issue_code(
            req,
            email,
            email,
            "拾课注册验证码：{code}",
            "你的拾课注册验证码是 {code}，10 分钟内有效。\n\n如果不是你本人操作，请忽略这封邮件。",
        )

    async def _check_code(self, key: str, code: str) -> str | None:
        """校验验证码，返回错误信息；最多尝试 5 次（先原子地占用一次尝试机会，再比较，防并发绕过）。"""
        row = await self.db.fetchone("SELECT * FROM email_codes WHERE email = ?", key)
        if not row or row["expires_at"] < time.time():
            return "验证码已过期，请重新获取"
        took = await self.db.execute(
            "UPDATE email_codes SET attempts = attempts + 1 WHERE email = ? AND attempts < ?",
            key,
            CODE_MAX_ATTEMPTS,
        )
        if not took:
            return "验证码错误次数过多，请重新获取"
        if not hmac.compare_digest(row["code_hash"], _code_hash(key, code)):
            return "验证码不正确"
        await self.db.execute("DELETE FROM email_codes WHERE email = ?", key)
        return None

    async def register_user(self, req: Request) -> Response:
        b = body_of(req)
        email = _email_of(b)
        pw = _password_of(b, "password")
        if b.get("agree_privacy") is not True:
            return Response.error(422, "请先阅读并同意隐私说明", "privacy")
        if await self.db.fetchone("SELECT id FROM users WHERE email = ?", email):
            return Response.error(409, "该邮箱已注册", "exists")
        if require_email_code():
            err = await self._check_code(
                email, as_str(b.get("code"), "code", max_len=12, default="").strip()
            )
            if err:
                return Response.error(422, err, "bad_code")
        try:
            async with self.db.transaction():
                uid = await self.db.insert(
                    "users",
                    {
                        "email": email,
                        "password_hash": security.hash_password(pw),
                        "name": as_str(b.get("name"), "name", max_len=200, default="").strip()[:40]
                        or email.split("@")[0][:40],
                        "grade": as_str(b.get("grade"), "grade", max_len=200, default="")[:20],
                        "major": as_str(b.get("major"), "major", max_len=200, default="")[:40],
                        "courses": _courses_of(b.get("courses")),
                        "created_at": time.time(),
                    },
                )
        except Exception as e:
            if is_unique_violation(e):  # 并发注册同一邮箱
                return Response.error(409, "该邮箱已注册", "exists")
            raise
        await self._event(uid, "register")
        user = await self.db.fetchone("SELECT * FROM users WHERE id = ?", uid)
        assert user
        return await self._session_response(req, user, 201)

    async def login(self, req: Request) -> Response:
        b = body_of(req)
        email = as_str(b.get("email"), "email", max_len=254, default="").strip().lower()
        pw = as_str(b.get("password"), "password", max_len=PASSWORD_MAX, default="")
        ip = _client_ip(req)
        wait = max(self.login_by_email.retry_after(email), self.login_by_ip.retry_after(ip))
        if wait:
            return _too_many(wait, "登录失败次数过多，请稍后再试")
        user = await self.db.fetchone("SELECT * FROM users WHERE email = ?", email)
        # 用户不存在时也做一次同样耗时的哈希校验，避免用响应时间判断邮箱是否注册
        ok = security.verify_password(user["password_hash"] if user else self._dummy_hash, pw)
        if not user or not ok:
            wait = max(self.login_by_email.hit(email), self.login_by_ip.hit(ip))
            if wait:
                return _too_many(wait, "登录失败次数过多，请稍后再试")
            return Response.error(401, "邮箱或密码错误", "bad_credentials")
        self.login_by_email.reset(email)
        await self.db.execute(
            "UPDATE users SET last_active_at = ? WHERE id = ?", time.time(), user["id"]
        )
        await self._event(user["id"], "login")
        return await self._session_response(req, user)

    async def logout(self, req: Request, user: dict[str, Any]) -> Response:
        """退出当前设备（吊销本会话）；``all_devices`` 时吊销全部会话与旧令牌。"""
        b = body_of(req)
        now = time.time()
        if b.get("all_devices"):
            await self.db.execute(
                "UPDATE users SET token_version = token_version + 1 WHERE id = ?", user["id"]
            )
            await self.db.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                now,
                user["id"],
            )
        elif req.context.get("sid"):
            await self.db.execute(
                "UPDATE sessions SET revoked_at = ? WHERE id = ?", now, req.context["sid"]
            )
        resp = Response.json_body({"ok": True})
        resp.headers.add("Set-Cookie", _cookie(req, "", 0))
        return resp

    async def send_reset_code(self, req: Request) -> Response:
        """找回密码第一步：向注册邮箱发验证码。邮箱未注册时同样返回成功，不泄露注册情况。"""
        email = _email_of(body_of(req))
        if not await self.db.fetchone("SELECT id FROM users WHERE email = ?", email):
            return Response.json_body(
                {"ok": True, "expires_in": CODE_TTL, "resend_after": CODE_RESEND}
            )
        return await self._issue_code(
            req,
            f"reset:{email}",
            email,
            "拾课重置密码验证码：{code}",
            "你正在重置拾课密码，验证码是 {code}，10 分钟内有效。\n\n"
            "如果不是你本人操作，请忽略这封邮件，你的密码不会改变。",
        )

    async def reset_password(self, req: Request) -> Response:
        """找回密码第二步：验证码正确后设置新密码，并让所有设备重新登录。"""
        b = body_of(req)
        email = _email_of(b)
        pw = _password_of(b, "new_password")
        code = as_str(b.get("code"), "code", max_len=12, default="").strip()
        user = await self.db.fetchone("SELECT * FROM users WHERE email = ?", email)
        err = await self._check_code(f"reset:{email}", code)
        if err or not user:
            return Response.error(422, err or "验证码已过期，请重新获取", "bad_code")
        await self._set_password(user["id"], pw)
        await self._event(user["id"], "password_reset")
        fresh = await self.db.fetchone("SELECT * FROM users WHERE id = ?", user["id"])
        assert fresh
        return await self._session_response(req, fresh)

    async def change_password(self, req: Request, user: dict[str, Any]) -> Response:
        """修改密码：校验旧密码；其他设备全部退出，当前设备换发新令牌。"""
        b = body_of(req)
        old = as_str(b.get("old_password"), "old_password", max_len=PASSWORD_MAX, default="")
        new = _password_of(b, "new_password")
        if not security.verify_password(user["password_hash"], old):
            return Response.error(403, "原密码不正确", "bad_credentials")
        await self._set_password(user["id"], new)
        await self._event(user["id"], "password_change")
        fresh = await self.db.fetchone("SELECT * FROM users WHERE id = ?", user["id"])
        assert fresh
        return await self._session_response(req, fresh)

    async def _set_password(self, uid: int, pw: str) -> None:
        async with self.db.transaction():
            await self.db.execute(
                "UPDATE users SET password_hash = ?, token_version = token_version + 1 WHERE id = ?",
                security.hash_password(pw),
                uid,
            )
            await self.db.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                time.time(),
                uid,
            )

    async def list_sessions(self, req: Request, user: dict[str, Any]) -> Response:
        rows = await self.db.fetch(
            "SELECT id, created_at, last_seen_at, user_agent, ip FROM sessions WHERE user_id = ? AND revoked_at IS NULL ORDER BY last_seen_at DESC LIMIT 50",
            user["id"],
        )
        cur = req.context.get("sid")
        return Response.json_body({"sessions": [{**r, "current": r["id"] == cur} for r in rows]})

    async def revoke_session(self, req: Request, user: dict[str, Any]) -> Response:
        sid = as_str(req.params.get("id"), "id", max_len=64)
        n = await self.db.execute(
            "UPDATE sessions SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
            time.time(),
            sid,
            user["id"],
        )
        if not n:
            return Response.error(404, "会话不存在", "not_found")
        return Response.json_body({"ok": True})

    async def me(self, req: Request, user: dict[str, Any]) -> Response:
        out = _user_public(user)
        out["cursor"] = user["next_seq"]
        return Response.json_body(out)

    async def update_me(self, req: Request, user: dict[str, Any]) -> Response:
        b = body_of(req)
        fields: dict[str, Any] = {}
        for k in ("name", "grade", "major"):
            if k in b:
                fields[k] = as_str(b[k], k, max_len=200)[:40]
        for k in ("digest_time", "quiet_start", "quiet_end"):
            if k in b:
                v = as_str(b[k], k, max_len=5)
                if not _HHMM.fullmatch(v):
                    return Response.error(422, f"{k} 应为 HH:MM（00:00–23:59）", "bad_time")
                fields[k] = v
        if "digest_email" in b:
            fields["digest_email"] = int(bool(b["digest_email"]))
        if "courses" in b:
            fields["courses"] = json.dumps(_courses_of(b["courses"]), ensure_ascii=False)
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            await self.db.execute(
                f"UPDATE users SET {sets} WHERE id = ?", *fields.values(), user["id"]
            )
        u = await self.db.fetchone("SELECT * FROM users WHERE id = ?", user["id"])
        assert u
        return Response.json_body(_user_public(u))

    async def delete_account(self, req: Request, user: dict[str, Any]) -> Response:
        """一键删除账号与全部数据（安全、隐私与合规）。需要再次输入密码，防止令牌被盗后被删号。

        私有来源及其事项、会话、传输记录随外键级联删除；磁盘上的传输文件在提交后删除。
        """
        b = body_of(req)
        pw = as_str(b.get("password"), "password", max_len=PASSWORD_MAX, default="")
        if not security.verify_password(user["password_hash"], pw):
            return Response.error(403, "密码不正确", "bad_credentials")
        uid = user["id"]
        transfer_ids = [
            r["id"] for r in await self.db.fetch("SELECT id FROM transfers WHERE user_id = ?", uid)
        ]
        private = [
            r["id"] for r in await self.db.fetch("SELECT id FROM sources WHERE owner_id = ?", uid)
        ]
        async with self.db.transaction():
            for sid in private:
                # 私有来源（如个人邮件）并进公共事项时，公共事项的 merged_from 里记着邮件标题：一并抹掉
                for it in await self.db.fetch(
                    "SELECT i.id, i.attrs FROM items i JOIN item_aliases a ON a.item_id = i.id "
                    "WHERE a.source_id = ? AND i.source_id != ?",
                    sid,
                    sid,
                ):
                    attrs = loads(it["attrs"], {})
                    merged = [m for m in attrs.get("merged_from", []) if m.get("source_id") != sid]
                    if len(merged) != len(attrs.get("merged_from", [])):
                        attrs["merged_from"] = merged
                        await self.db.execute(
                            "UPDATE items SET attrs = ? WHERE id = ?",
                            json.dumps(attrs, ensure_ascii=False),
                            it["id"],
                        )
                await self.db.execute("DELETE FROM item_aliases WHERE source_id = ?", sid)
            for t in (
                "deliveries",
                "user_item_state",
                "user_item_edits",
                "item_monitors",
                "item_labels",
                "labels",
                "op_log",
                "rules",
                "sent_mails",
                "dashboards",
                "credentials",
                "subscriptions",
                "reminders_sent",
                "transfers",
                "sessions",
                "events",
            ):
                await self.db.execute(f"DELETE FROM {t} WHERE user_id = ?", uid)
            await self.db.execute("DELETE FROM sources WHERE owner_id = ?", uid)
            for key in (user["email"], f"reset:{user['email']}"):
                await self.db.execute("DELETE FROM email_codes WHERE email = ?", key)
            await self.db.execute("DELETE FROM users WHERE id = ?", uid)
        if self.data_dir:
            root = Path(self.data_dir) / "transfers"
            for tid in transfer_ids:
                shutil.rmtree(root / str(tid), ignore_errors=True)
        await self.publish("mqtt.forget", {"uid": uid})  # Broker 清掉该用户的会话与保留消息
        resp = Response.json_body({"ok": True, "deleted": True})
        resp.headers.add("Set-Cookie", _cookie(req, "", 0))
        return resp

    # ---- 事项 ------------------------------------------------------------------

    async def _items_for(
        self,
        uid: int,
        where: str = "",
        params: tuple[Any, ...] = (),
        order: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = f"""SELECT i.*, st.read_at, st.starred, st.todo_status, st.hidden, st.not_important, st.deadline_override, st.note, st.score, st.priority, st.reasons, st.archived_at,
                    src.name AS src_name, src.type AS src_type, src.last_success_at AS src_last_success, src.status AS src_status,
                    src.last_checked_at AS src_last_checked, src.last_change_at AS src_last_change, src.last_error AS src_last_error, src.next_fetch_at AS src_next_fetch
                  FROM items i
                  JOIN subscriptions s ON s.source_id = i.source_id AND s.user_id = ?
                  JOIN sources src ON src.id = i.source_id
                  LEFT JOIN user_item_state st ON st.item_id = i.id AND st.user_id = ?
                  WHERE i.kind != 'teacher' {where} {order} LIMIT {int(limit)}"""
        rows = await self.db.fetch(sql, uid, uid, *params)
        ids = list(dict.fromkeys(r["id"] for r in rows))
        all_edits = await edits.load(self.db, uid, ids)
        all_mons = await monitor.load(self.db, uid, ids)
        label_map = await self._label_ids_for(uid, ids)
        out = []
        seen: set[int] = set()
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            src = {
                "id": r["source_id"],
                "name": r["src_name"],
                "type": r["src_type"],
                "last_success_at": r["src_last_success"],
                "status": r["src_status"],
            }
            state = {
                k: r.get(k)
                for k in (
                    "read_at",
                    "starred",
                    "todo_status",
                    "hidden",
                    "not_important",
                    "deadline_override",
                    "note",
                    "score",
                    "priority",
                    "reasons",
                )
            }
            state["score"] = state["score"] or 0
            state["priority"] = state["priority"] or "low"
            it = item_public(r, state, src)
            it["state"]["archived"] = r.get("archived_at") is not None
            it["label_ids"] = label_map.get(r["id"], [])
            self._decorate(it, r, all_edits.get(r["id"], {}), all_mons.get(r["id"]))
            out.append(it)
        return out

    async def _label_ids_for(self, uid: int, item_ids: list[int]) -> dict[int, list[int]]:
        if not item_ids:
            return {}
        marks = ",".join("?" * len(item_ids))
        rows = await self.db.fetch(
            f"SELECT item_id, label_id FROM item_labels WHERE user_id = ? AND item_id IN ({marks}) ORDER BY label_id",
            uid,
            *item_ids,
        )
        out: dict[int, list[int]] = {}
        for r in rows:
            out.setdefault(r["item_id"], []).append(r["label_id"])
        return out

    @staticmethod
    def _decorate(
        it: dict[str, Any],
        r: dict[str, Any],
        item_edits: dict[str, tuple[Any, Any]],
        mon: dict[str, Any] | None,
    ) -> None:
        """新基线的事项字段（IC-002 4.1）：生效值、修改明细与冲突、类型与状态、来源定位、监测状态。"""
        values, detail, conflicts = edits.effective(r, item_edits, r.get("deadline_override"))
        attrs = loads(r.get("attrs"), {})
        origin = "capture" if r.get("src_type") in ("clip", "browser") else "source"
        it.update(
            {
                "type": values["type"],
                "status": status_of(values["type"], r),
                "title": values["title"],
                "summary": values["summary"],
                "deadline_at": values["deadline_at"],
                "requirements": values["requirements"],
                "start_at": values["start_at"],
                "end_at": values["end_at"],
                "location": values["location"],
                "fields": detail,
                "conflicts": conflicts,
                "origin": origin,
                "page_url": attrs.get("page_url") or r.get("url", ""),
                "locator": attrs.get("locator", ""),
                "monitor": monitor.public(
                    mon,
                    origin,
                    {
                        "status": r.get("src_status"),
                        "last_success_at": r.get("src_last_success"),
                        "last_checked_at": r.get("src_last_checked"),
                        "last_change_at": r.get("src_last_change"),
                        "last_error": r.get("src_last_error"),
                        "next_fetch_at": r.get("src_next_fetch"),
                    },
                ),
            }
        )

    async def feed(self, req: Request, user: dict[str, Any]) -> Response:
        """分页收件箱。cursor = ``排序时间:id``（键集分页，翻页期间有新数据也不会重复或遗漏）。"""
        q = req.query
        where = " AND i.deleted = 0 AND COALESCE(st.hidden, 0) = " + (
            "1" if q.get("filter") == "trash" else "0"
        )
        params: list[Any] = []
        if q.get("kind"):
            if q["kind"] not in ITEM_KINDS:
                return Response.error(422, "kind 取值不正确", "invalid")
            where += " AND i.kind = ?"
            params.append(q["kind"])
        if q.get("type"):
            if q["type"] not in ITEM_TYPES:
                return Response.error(422, "type 只能是 todo / event / notice", "invalid")
            where += " AND " + _effective_type_is(q["type"])
        if q.get("status"):
            if q["status"] not in ALL_STATUSES:
                return Response.error(422, "status 取值不正确", "invalid")
            where += " AND " + status_sql(q["status"], _effective_type_is)
        if q.get("origin"):
            if q["origin"] not in ("capture", "source"):
                return Response.error(422, "origin 只能是 capture / source", "invalid")
            where += (
                " AND src.type IN ('clip', 'browser')"
                if q["origin"] == "capture"
                else " AND src.type NOT IN ('clip', 'browser')"
            )
        if q.get("course"):
            where += " AND LOWER(i.course) LIKE ? ESCAPE '!'"
            params.append(_like(as_str(q["course"], "course", max_len=100)))
        f = q.get("filter")
        if f and f not in FEED_FILTERS:
            return Response.error(422, "filter 取值不正确", "invalid")
        if f == "unread":
            where += " AND st.read_at IS NULL"
        elif f == "starred":
            where += " AND st.starred = 1"
        elif f == "todo":
            where += " AND COALESCE(st.todo_status, '') IN ('todo', 'doing')"
        elif f == "important":
            where += " AND COALESCE(st.priority, 'low') != 'low'"
        elif f == "labeled":
            try:
                label_id = int(q.get("label_id", ""))
            except (TypeError, ValueError):
                return Response.error(422, "labeled 筛选需要 label_id", "invalid")
            owns = await self.db.fetchval(
                "SELECT id FROM labels WHERE id = ? AND user_id = ?", label_id, user["id"]
            )
            if owns is None:
                return Response.error(404, "标签不存在", "not_found")
            where += (
                " AND EXISTS (SELECT 1 FROM item_labels il "
                "WHERE il.user_id = ? AND il.item_id = i.id AND il.label_id = ?)"
            )
            params += [user["id"], label_id]
        if q.get("q"):
            where += (
                " AND (LOWER(i.title) LIKE ? ESCAPE '!' OR LOWER(i.summary) LIKE ? ESCAPE '!'"
                " OR LOWER(i.course) LIKE ? ESCAPE '!')"
            )
            params += [_like(as_str(q["q"], "q", max_len=100))] * 3
        sort = "COALESCE(i.published_at, i.first_seen_at)"
        if q.get("cursor"):
            try:
                ts_s, id_s = q["cursor"].split(":")
                ts, last_id = float(ts_s), int(id_s)
            except ValueError:
                return Response.error(400, "游标格式不正确", "bad_cursor")
            where += f" AND ({sort} < ? OR ({sort} = ? AND i.id < ?))"
            params += [ts, ts, last_id]
        limit = as_int(q.get("limit"), "limit", default=30, lo=1, hi=100)
        items = await self._items_for(
            user["id"], where, tuple(params), f"ORDER BY {sort} DESC, i.id DESC", limit + 1
        )
        nxt = None
        if len(items) > limit:
            items = items[:limit]
            last = items[-1]
            # 与 SQL 的 COALESCE 一致：published_at 为 0 时也用它，而不是退到 first_seen_at
            ts = last["published_at"] if last["published_at"] is not None else last["first_seen_at"]
            nxt = f"{ts}:{last['id']}"
        unread = await self.db.fetchval(
            """SELECT COUNT(DISTINCT i.id) FROM items i JOIN subscriptions s ON s.source_id = i.source_id AND s.user_id = ?
               LEFT JOIN user_item_state st ON st.item_id = i.id AND st.user_id = ? WHERE i.deleted = 0 AND i.kind != 'teacher' AND st.read_at IS NULL AND COALESCE(st.hidden,0)=0""",
            user["id"],
            user["id"],
        )
        return Response.json_body(
            {"items": items, "next_cursor": nxt, "unread": unread, "sync_cursor": user["next_seq"]}
        )

    async def sync(self, req: Request, user: dict[str, Any]) -> Response:
        """离线恢复后的增量同步：返回 seq 大于 cursor 的投递（技术方案 9）。"""
        cursor = as_int(req.query.get("cursor"), "cursor", default=0, lo=0)
        rows = await self.db.fetch(
            "SELECT seq, payload FROM deliveries WHERE user_id = ? AND seq > ? ORDER BY seq LIMIT 501",
            user["id"],
            cursor,
        )
        more = len(rows) > 500
        rows = rows[:500]
        out = [loads(r["payload"], {}) for r in rows]
        new_cursor = rows[-1]["seq"] if rows else cursor
        # 需要全量刷新的情况：游标比服务端还新（换库 / 数据被重置），或者游标之后的投递已被
        # 保留期清理掉（第一条投递之前有空缺；或者一条都不剩但游标落后于最新序号）
        reset = (
            cursor > user["next_seq"]
            or (bool(rows) and rows[0]["seq"] > cursor + 1)
            or (not rows and cursor < user["next_seq"])
        )
        return Response.json_body(
            {"deliveries": out, "cursor": new_cursor, "has_more": more, "reset": reset}
        )

    async def get_item(self, req: Request, user: dict[str, Any]) -> Response:
        items = await self._items_for(user["id"], " AND i.id = ?", (path_id(req),))
        if not items:
            return Response.error(404, "事项不存在", "not_found")
        it = items[0]
        row = await self.db.fetchone("SELECT body FROM items WHERE id = ?", it["id"])
        it["body"] = row["body"] if row else ""
        it["browser_monitor"] = await self.db.fetchone(
            "SELECT id, enabled, supported, last_result, last_success_at, error FROM browser_monitors WHERE owner_id = ? AND item_id = ? AND deleted = 0",
            user["id"],
            it["id"],
        )
        if it["browser_monitor"]:
            for flag in ("enabled", "supported"):
                it["browser_monitor"][flag] = bool(it["browser_monitor"][flag])
        it["reading_source"] = await self.db.fetchone(
            "SELECT r.id, r.last_result, r.last_success_at FROM reading_sources r JOIN reading_source_items link ON link.reading_id = r.id WHERE r.owner_id = ? AND r.deleted = 0 AND link.item_id = ? ORDER BY r.id DESC LIMIT 1",
            user["id"],
            it["id"],
        )
        return Response.json_body(it)

    async def versions(self, req: Request, user: dict[str, Any]) -> Response:
        iid = path_id(req)
        if not await self._items_for(user["id"], " AND i.id = ?", (iid,)):
            return Response.error(404, "事项不存在")
        rows = await self.db.fetch(
            "SELECT version, snapshot, changed_fields, important, change_note, detected_at FROM item_versions WHERE item_id = ? ORDER BY version DESC",
            iid,
        )
        return Response.json_body(
            {
                "versions": [
                    {
                        **{k: v for k, v in r.items() if k != "snapshot"},
                        "snapshot": _version_snapshot(r["snapshot"]),
                        "changed_fields": loads(r["changed_fields"], {}),
                        "important": bool(r["important"]),
                    }
                    for r in rows
                ]
            }
        )

    async def apply_state(
        self, uid: int, item_id: int, b: dict[str, Any], op_id: str | None
    ) -> tuple[int, dict[str, Any]]:
        """修改个人状态；op_id 作为幂等键，重复提交直接返回第一次的结果（离线回放）。

        - 幂等键先占位再执行（同一事务内），WebSocket 与 HTTP 并发提交同一个 op_id 也只生效一次；
          客户端的键加 ``c:`` 前缀，与服务端内部键（如 ``digest:日期``）分开；同一个键换了内容返回 422。
        - 冲突处理“后写胜出”：以客户端操作时间 ts 为准（夹在 [现在 - 30 天, 现在 + 5 分钟]），无论是否带 op_id。
        """
        if "hidden" in b and type(b["hidden"]) is not bool:
            return 422, {"error": "invalid_state"}
        vals = _state_values(b)
        now = time.time()
        client_ts = as_float(b.get("ts"), "ts", default=now)
        client_ts = min(max(client_ts, now - 30 * 86400), now + 300)
        key = f"c:{as_str(op_id, 'op_id', max_len=100)}" if op_id else None
        digest = hashlib.sha256(
            json.dumps({"item": item_id, **vals}, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        if not await self.db.fetchone(
            "SELECT 1 FROM items i JOIN subscriptions s ON s.source_id = i.source_id AND s.user_id = ? WHERE i.id = ?",
            uid,
            item_id,
        ):
            return 404, {"error": "not_found", "message": "事项不存在"}
        async with self.db.transaction():
            if key:
                claimed = await self.db.execute(
                    "INSERT INTO op_log (user_id, op_id, result, created_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                    uid,
                    key,
                    json.dumps({"_h": digest, "pending": True}),
                    now,
                )
                if not claimed:
                    prev = loads(
                        await self.db.fetchval(
                            "SELECT result FROM op_log WHERE user_id = ? AND op_id = ?", uid, key
                        ),
                        {},
                    )
                    if prev.get("_h") not in (None, digest):
                        return 422, {
                            "error": "idempotency_mismatch",
                            "message": "同一个幂等键对应了不同的操作",
                        }
                    prev.pop("_h", None)
                    prev.pop("pending", None)
                    return 200, {**prev, "ok": True, "item_id": item_id, "duplicate": True}
            cur = await self.db.fetchone(
                "SELECT * FROM user_item_state WHERE user_id = ? AND item_id = ?", uid, item_id
            )
            if cur and cur["updated_at"] > client_ts:
                result: dict[str, Any] = {"ok": True, "stale": True, "item_id": item_id}
            else:
                if "read_at" in vals:
                    vals["read_at"] = client_ts if vals["read_at"] else None
                if "archived_at" in vals:
                    vals["archived_at"] = client_ts if vals["archived_at"] else None
                await self.db.execute(
                    "INSERT INTO user_item_state (user_id, item_id, updated_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                    uid,
                    item_id,
                    client_ts,
                )
                sets = "".join(f"{k} = ?, " for k in vals)
                await self.db.execute(
                    f"UPDATE user_item_state SET {sets}updated_at = ? WHERE user_id = ? AND item_id = ?",
                    *vals.values(),
                    max(client_ts, cur["updated_at"] if cur else 0),
                    uid,
                    item_id,
                )
                st = await self.db.fetchone(
                    "SELECT * FROM user_item_state WHERE user_id = ? AND item_id = ?", uid, item_id
                )
                assert st
                if "deadline_override" in vals:
                    # 旧接口改截止时间：同步为“截止时间”的用户修改（决策 D22）
                    row = await self.db.fetchone("SELECT * FROM items WHERE id = ?", item_id)
                    assert row
                    await edits.sync_deadline_override(self.db, uid, row, vals["deadline_override"])
                result = {
                    "ok": True,
                    "item_id": item_id,
                    "state": {
                        "read": st["read_at"] is not None,
                        "starred": bool(st["starred"]),
                        "todo": st["todo_status"],
                        "hidden": bool(st["hidden"]),
                        "archived": st.get("archived_at") is not None,
                        "deadline_override": st["deadline_override"],
                        "note": st["note"],
                    },
                }
                if "hidden" in vals and self.reading is not None:
                    if vals["hidden"]:
                        await self.reading.pause_empty(uid, item_id)
                    else:
                        await self.reading.mark_documents_visible(uid, item_id)
            if key:
                await self.db.execute(
                    "UPDATE op_log SET result = ? WHERE user_id = ? AND op_id = ?",
                    json.dumps({**result, "_h": digest}, ensure_ascii=False),
                    uid,
                    key,
                )
        if "state" in result:
            # 多设备同步：把状态变化推给该用户的其他在线设备（事务提交之后再推）
            await self.publish(
                f"u.{uid}",
                {"type": "state", "item_id": item_id, "state": result["state"], "op_id": op_id},
            )
        return 200, result

    async def put_state(self, req: Request, user: dict[str, Any]) -> Response:
        b = body_of(req)
        op = req.headers.get("Idempotency-Key") or b.get("op_id")
        status, res = await self.apply_state(user["id"], path_id(req), b, op)
        return Response.json_body(res, status)

    async def state_batch(self, req: Request, user: dict[str, Any]) -> Response:
        """离线操作队列按顺序回放。每条操作单独返回结果：一条坏操作不影响其他操作，也不会让整批失败。"""
        ops = as_list(body_of(req).get("ops"), "ops", max_len=10_000, default=[])
        results = []
        for op in ops[:STATE_BATCH_MAX]:
            if not isinstance(op, dict):
                results.append({"op_id": None, "status": 422, "error": "invalid"})
                continue
            op_id = op.get("op_id")
            try:
                item_id = as_int(op.get("item_id"), "item_id", lo=1)
                status, res = await self.apply_state(user["id"], item_id, op, op_id)
            except BadRequest as e:
                status, res = e.status, {"error": e.code, "message": e.message}
            results.append({"op_id": op_id, "status": status, **res})
        return Response.json_body({"results": results, "truncated": len(ops) > STATE_BATCH_MAX})

    async def feedback(self, req: Request, user: dict[str, Any]) -> Response:
        """“不重要”：降低该来源的权重，系统逐步贴合个人习惯。"""
        iid = path_id(req)
        item = await self.db.fetchone(
            "SELECT i.source_id FROM items i JOIN subscriptions s ON s.source_id = i.source_id AND s.user_id = ? WHERE i.id = ?",
            user["id"],
            iid,
        )
        if not item:
            return Response.error(404, "事项不存在", "not_found")
        await self.db.execute(
            "UPDATE subscriptions SET weight = CASE WHEN weight - 0.1 < 0.1 THEN 0.1 ELSE weight - 0.1 END WHERE user_id = ? AND source_id = ?",
            user["id"],
            item["source_id"],
        )
        now = time.time()
        await self.db.execute(
            "INSERT INTO user_item_state (user_id, item_id, not_important, updated_at) VALUES (?, ?, 1, ?) ON CONFLICT (user_id, item_id) DO UPDATE SET not_important = 1, updated_at = excluded.updated_at",
            user["id"],
            iid,
            now,
        )
        await self._event(user["id"], "not_important", {"item_id": iid})
        w = await self.db.fetchval(
            "SELECT weight FROM subscriptions WHERE user_id = ? AND source_id = ?",
            user["id"],
            item["source_id"],
        )
        return Response.json_body({"ok": True, "source_weight": w})

    async def deadlines(self, req: Request, user: dict[str, Any]) -> Response:
        now = time.time()
        frm = as_float(req.query.get("from"), "from", default=now - 7 * 86400)
        to = as_float(req.query.get("to"), "to", default=now + 60 * 86400)
        if to < frm or to - frm > 400 * 86400:
            return Response.error(422, "时间范围不正确（最长 400 天）", "invalid")
        items = await self._items_for(
            user["id"],
            " AND i.deleted = 0 AND COALESCE(st.hidden, 0) = 0 AND COALESCE(st.deadline_override, i.deadline_at) BETWEEN ? AND ?",
            (frm, to),
            "ORDER BY COALESCE(st.deadline_override, i.deadline_at)",
            500,
        )
        return Response.json_body({"items": items})

    async def courses(self, req: Request, user: dict[str, Any]) -> Response:
        """课程主页：未完成作业、近期通知、来自官网的教师信息（场景 6）。"""
        items = await self._items_for(
            user["id"],
            " AND i.deleted = 0 AND COALESCE(st.hidden, 0) = 0 AND i.course != ''",
            (),
            "ORDER BY i.deadline_at",
            500,
        )
        # 只看自己订阅的来源里的教师信息（自定义教师来源是私有的）
        teachers = await self.db.fetch(
            "SELECT i.title, i.url, i.attrs FROM items i JOIN subscriptions s ON s.source_id = i.source_id AND s.user_id = ? WHERE i.kind = 'teacher' AND i.deleted = 0",
            user["id"],
        )
        tinfo = [loads(t["attrs"], {}) | {"url": t["url"]} for t in teachers]
        courses: dict[str, dict[str, Any]] = {}
        for it in items:
            c = courses.setdefault(
                it["course"],
                {"name": it["course"], "assignments": [], "notices": [], "teachers": []},
            )
            (c["assignments"] if it["kind"] == "assignment" else c["notices"]).append(it)
        for name, c in courses.items():
            c["teachers"] = [
                t for t in tinfo if any(cn and cn in name for cn in t.get("courses", []))
            ]
            c["open"] = sum(
                1
                for a in c["assignments"]
                if a["state"]["todo"] != "done" and (a["deadline_at"] or 0) > time.time()
            )
        return Response.json_body({"courses": sorted(courses.values(), key=lambda c: c["name"])})

    # ---- 来源 ------------------------------------------------------------------

    async def templates(self, req: Request) -> Response:
        return Response.json_body({"templates": list_templates()})

    async def list_sources(self, req: Request, user: dict[str, Any]) -> Response:
        rows = await self.db.fetch(
            """SELECT src.*, s.weight, s.muted, (SELECT COUNT(*) FROM items i WHERE i.source_id = src.id AND i.deleted = 0) AS item_count,
               (SELECT COUNT(*) FROM credentials c WHERE c.source_id = src.id AND c.user_id = ?) AS has_login
               FROM sources src JOIN subscriptions s ON s.source_id = src.id AND s.user_id = ? ORDER BY src.id""",
            user["id"],
            user["id"],
        )
        out = []
        for r in rows:
            stats = loads(r.pop("stats"), {})
            totals = stats.get("totals", {})
            cfg = loads(r.pop("config"), {})
            r.pop("content_hash", None)
            out.append(
                {
                    **r,
                    "config": cfg,
                    "muted": bool(r["muted"]),
                    "has_login": bool(r["has_login"]),
                    "shared": r["owner_id"] is None,
                    "last": stats.get("last", {}),
                    "saved_ratio": round(totals.get("not_modified", 0) / totals["requests"], 3)
                    if totals.get("requests")
                    else None,
                }
            )
        return Response.json_body({"sources": out})

    def _source_input(
        self, b: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, str, dict[str, Any]]:
        """校验添加 / 预览来源的参数，返回（模板，类型，地址，配置）。"""
        tpl = None
        if b.get("template"):
            tpl = get_template(as_str(b["template"], "template", max_len=60))
            if not tpl:
                raise BadRequest(404, "模板不存在", "not_found")
        stype = (tpl or {}).get("type") or as_str(b.get("type"), "type", max_len=20, default="")
        if stype not in SOURCE_SCHEMES:
            raise BadRequest(422, "不支持的来源类型", "bad_type")
        endpoint = as_str(
            b.get("endpoint") or (tpl or {}).get("endpoint") or "", "endpoint", max_len=2048
        ).strip()
        scheme = endpoint.split("://", 1)[0].lower() if "://" in endpoint else ""
        if scheme not in SOURCE_SCHEMES[stype] or len(endpoint) <= len(scheme) + 3:
            raise BadRequest(422, "请输入完整网址", "bad_endpoint")
        user_cfg = as_dict(b.get("config"), "config", default={})
        if len(json.dumps(user_cfg, ensure_ascii=False, default=str)) > 4000:
            raise BadRequest(422, "config 过大", "invalid")
        return tpl, stype, endpoint, {**((tpl or {}).get("config") or {}), **user_cfg}

    async def add_source(self, req: Request, user: dict[str, Any]) -> Response:
        b = body_of(req)
        tpl, stype, endpoint, config = self._source_input(b)
        via_agent = bool(b.get("via_agent"))
        # 公共来源（无需登录的网页 / RSS）全员共享一份；交给本地代理采集的来源一律私有，
        # 否则公共来源会因为 via_agent 而永远不被云端采集
        shared = (
            bool((tpl or {}).get("shared"))
            if tpl
            else (stype in ("web", "rss") and not b.get("private") and not via_agent)
        )
        weight = as_float(
            b.get("weight") if b.get("weight") is not None else (tpl or {}).get("weight", 0.6),
            "weight",
            lo=0.0,
            hi=1.0,
            clamp=True,
        )
        name = as_str(b.get("name") or (tpl or {}).get("name") or endpoint, "name", max_len=2048)[
            :60
        ]
        course = as_str(b.get("course"), "course", max_len=200, default="")[:60]
        count = await self.db.fetchval(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id = ?", user["id"]
        )
        if count >= MAX_SOURCES_PER_USER:
            return Response.error(
                409, f"最多订阅 {MAX_SOURCES_PER_USER} 个信息源", "too_many_sources"
            )
        now = time.time()
        src = None
        values = {
            "owner_id": None if shared else user["id"],
            "type": stype,
            "name": name,
            "endpoint": endpoint,
            "template": (tpl or {}).get("id", ""),
            "config": config,
            "course": course,
            "via_agent": int(via_agent),
            "status": "pending"
            if not (tpl or {}).get("needs_login") and stype not in ("imap", "pop3")
            else "need_login",
            "created_at": now,
            "next_fetch_at": 0,
        }
        async with self.db.transaction():
            if shared:
                # 公共来源按（类型，地址，模式）唯一：同一网址可能既有“列表”订阅又有“整页监测”订阅（浏览器插件）。
                # 唯一索引保证并发添加也只有一份：插入冲突时读出已有的那一份
                key = share_key(stype, endpoint, config)
                cols = [*values, "share_key"]
                created = await self.db.execute(
                    f"INSERT INTO sources ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                    "ON CONFLICT (share_key) WHERE share_key IS NOT NULL DO NOTHING",
                    *values.values(),
                    key,
                )
                row = await self.db.fetchone("SELECT * FROM sources WHERE share_key = ?", key)
                assert row
                sid = row["id"]
                if not created:
                    src = row
            else:
                sid = await self.db.insert("sources", values)
            await self.db.execute(
                "INSERT INTO subscriptions (user_id, source_id, weight, created_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                user["id"],
                sid,
                weight,
                now,
            )
        if src is not None:
            # 公共来源已有事项：直接给新订阅者生成投递，让收件箱立即有内容
            for row in await self.db.fetch(
                "SELECT * FROM items WHERE source_id = ? AND deleted = 0 ORDER BY id DESC LIMIT 30",
                sid,
            ):
                if row["kind"] != "teacher":
                    await self.pipeline._fanout(src, row, kind="item", only_new_users=False)
        else:
            await self.publish("collector.fetch", {"source_id": sid})
            await self.publish("mail.sources", {"source_id": sid})
        await self._event(user["id"], "add_source", {"type": stype})
        row = await self.db.fetchone(
            "SELECT id, name, type, endpoint, status FROM sources WHERE id = ?", sid
        )
        return Response.json_body(
            {
                "source": row,
                "needs_login": bool((tpl or {}).get("needs_login")) or stype in ("imap", "pop3"),
                # 复用了已有的公共来源：名称与采集配置沿用最早添加者的，这次传入的不生效
                "reused": src is not None,
            },
            201,
        )

    async def preview_source(self, req: Request, user: dict[str, Any]) -> Response:
        """首次采集预览：不保存，直接运行一次连接器，让用户确认提取的字段对不对。"""
        _tpl, stype, endpoint, config = self._source_input(body_of(req))
        if stype not in ("web", "rss", "teacher"):
            return Response.error(422, "该类型需要先登录，无法预览", "need_login")
        info = SourceInfo(0, stype, endpoint, config)
        try:
            res = await CONNECTORS[stype](Context(self.fetcher, info, None))
        except FetchError as e:
            return Response.error(422, f"预览失败：{e}", f"fetch_{e.kind}")
        return Response.json_body(
            {"ok": True, "items": [i.to_dict() for i in res.items[:10]], "count": len(res.items)}
        )

    async def _own_sub(self, user: dict[str, Any], sid: int) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT src.* FROM sources src JOIN subscriptions s ON s.source_id = src.id AND s.user_id = ? WHERE src.id = ?",
            user["id"],
            sid,
        )

    async def update_source(self, req: Request, user: dict[str, Any]) -> Response:
        sid = path_id(req)
        if not await self._own_sub(user, sid):
            return Response.error(404, "来源不存在", "not_found")
        b = body_of(req)
        if "weight" in b:
            await self.db.execute(
                "UPDATE subscriptions SET weight = ? WHERE user_id = ? AND source_id = ?",
                as_float(b["weight"], "weight", lo=0.0, hi=1.0, clamp=True),
                user["id"],
                sid,
            )
        if "muted" in b:
            await self.db.execute(
                "UPDATE subscriptions SET muted = ? WHERE user_id = ? AND source_id = ?",
                int(bool(b["muted"])),
                user["id"],
                sid,
            )
        # 名称与课程只有私有来源的主人能改（公共来源是大家共用的）
        if "name" in b:
            await self.db.execute(
                "UPDATE sources SET name = ? WHERE id = ? AND owner_id = ?",
                as_str(b["name"], "name", max_len=200)[:60],
                sid,
                user["id"],
            )
        if "course" in b:
            await self.db.execute(
                "UPDATE sources SET course = ? WHERE id = ? AND owner_id = ?",
                as_str(b["course"], "course", max_len=200)[:60],
                sid,
                user["id"],
            )
        return Response.json_body({"ok": True})

    async def remove_source(self, req: Request, user: dict[str, Any]) -> Response:
        sid = path_id(req)
        src = await self._own_sub(user, sid)
        if not src:
            return Response.error(404, "来源不存在", "not_found")
        async with self.db.transaction():
            await self.db.execute(
                "DELETE FROM subscriptions WHERE user_id = ? AND source_id = ?", user["id"], sid
            )
            await self.db.execute(
                "DELETE FROM credentials WHERE user_id = ? AND source_id = ?", user["id"], sid
            )
            if src["owner_id"] == user["id"]:
                # 私有来源连同事项一起删除：先删掉这些事项的投递记录（deliveries 没有外键）
                await self.db.execute(
                    "DELETE FROM deliveries WHERE user_id = ? AND item_id IN (SELECT id FROM items WHERE source_id = ?)",
                    user["id"],
                    sid,
                )
                await self.db.execute("DELETE FROM item_aliases WHERE source_id = ?", sid)
                await self.db.execute("DELETE FROM sources WHERE id = ?", sid)
        return Response.json_body({"ok": True})

    # ---- 浏览器插件：保存当前页面 -----------------------------------------------

    async def save_clip(self, req: Request, user: dict[str, Any]) -> Response:
        """插件“保存到收件箱”：页面正文由插件在用户浏览器里读取后上传（登录后才能看的页面也能存）。

        每个用户一个个人来源“网页收藏”（类型 clip，不参与定时采集）；事项走正常流水线，
        同一网址再次保存会比较正文并记录新版本。不按链接与其他事项合并：
        否则保存一篇已在收件箱里的通知会被并进通知，用户保存的正文和之后的版本都会丢失。
        """
        b = body_of(req)
        url = str(b.get("url") or "").strip()
        if not re.match(r"^https?://", url, re.I) or len(url) > 2048:
            return Response.error(422, "只能保存 http / https 网页", "bad_url")
        title = " ".join(str(b.get("title") or "").split())[:300] or url
        text = str(b.get("text") or "").strip()[:CLIP_MAX_TEXT]
        src = await self._clip_source(user)
        key = "clip:" + normalize_url(url)
        snap = {
            "key": key,
            "kind": "clip",
            "title": title,
            "url": url,
            "body": text,
            "attrs": {"saved_from": "browser-extension"},
        }
        counts = await self.pipeline.ingest(
            {"source_id": src["id"], "status": "ok", "prev_status": "ok", "items": [snap]}
        )
        scoped = owner_prefix(user["id"]) + key
        item_id = await self.db.fetchval("SELECT id FROM items WHERE identity_key = ?", scoped)
        status = next((k for k in ("new", "changed") if counts.get(k)), "unchanged")
        return Response.json_body(
            {"ok": True, "item_id": item_id, "status": status}, 201 if status == "new" else 200
        )

    async def _clip_source(self, user: dict[str, Any]) -> dict[str, Any]:
        src = await self.db.fetchone(
            "SELECT * FROM sources WHERE owner_id = ? AND type = 'clip'", user["id"]
        )
        if src:
            return src

        now = time.time()
        # 每人一个（唯一索引 ux_sources_clip）：并发保存时第二个插入什么也不做，再读出来即可
        await self.db.execute(
            "INSERT INTO sources (owner_id, type, name, endpoint, template, config, status, created_at, next_fetch_at) "
            "VALUES (?, 'clip', '网页收藏', 'extension://clip', '', '{}', 'ok', ?, 0) "
            "ON CONFLICT (owner_id) WHERE type = 'clip' DO NOTHING",
            user["id"],
            now,
        )
        sid = await self.db.fetchval(
            "SELECT id FROM sources WHERE owner_id = ? AND type = 'clip'", user["id"]
        )
        await self.db.execute(
            "INSERT INTO subscriptions (user_id, source_id, weight, created_at) VALUES (?, ?, 0.6, ?) ON CONFLICT DO NOTHING",
            user["id"],
            sid,
            now,
        )
        src = await self.db.fetchone("SELECT * FROM sources WHERE id = ?", sid)
        assert src
        return src

    # ---- 插件：同页多条事项批量保存（IC-001，决策 D19、D20） -------------------------

    async def save_captures(self, req: Request, user: dict[str, Any]) -> Response:
        """批量保存用户勾选的候选事项，逐条返回结果。

        先校验整批（页面网址、条数、定位符），不合法就整批拒绝、什么都不保存；之后每条单独入库，
        一条失败不影响其他条，顶层 ok 只有全部成功才为 true（US02：不虚报保存成功）。
        """
        b = body_of(req)
        page = as_dict(b.get("page"), "page")
        page_url = str(page.get("url") or "").strip()
        if not re.match(r"^https?://", page_url, re.I) or len(page_url) > 2048:
            return Response.error(422, "只能保存 http / https 网页", "bad_url")
        page_title = " ".join(
            as_str(page.get("title"), "page.title", max_len=300, default="").split()
        )
        platform = as_str(page.get("platform"), "page.platform", max_len=20, default="")
        raw_items = as_list(b.get("items"), "items", max_len=CAPTURE_MAX_ITEMS)
        if not raw_items:
            raise invalid("items", "至少要有一条")
        locators: list[str] = []
        for i, it in enumerate(raw_items):
            if not isinstance(it, dict):
                raise invalid(f"items[{i}]", "应为对象")
            loc = as_str(it.get("locator"), f"items[{i}].locator", max_len=200).strip()
            if not loc:
                raise invalid(f"items[{i}].locator", "不能为空")
            locators.append(loc)
        if len(set(locators)) != len(locators):
            raise invalid("items", "locator 不能重复")
        src = await self._clip_source(user)
        page_key = normalize_url(page_url)
        results = []
        for i, (it, loc) in enumerate(zip(raw_items, locators, strict=True)):
            res: dict[str, Any] = {"index": i, "locator": loc, "item_id": None, "type": None}
            try:
                snap = _capture_snap(it, f"items[{i}]", page_url, page_title, platform, loc)
                snap["key"] = f"capture:{page_key}#{loc}"
                snap["dedupe_url"] = snap["key"]
                supported = (
                    bool((it.get("monitor") or {}).get("supported"))
                    if isinstance(it.get("monitor"), dict)
                    else False
                )
                counts = await self.pipeline.ingest(
                    {"source_id": src["id"], "status": "ok", "prev_status": "ok", "items": [snap]}
                )
                row = await self.db.fetchone(
                    "SELECT id, item_type FROM items WHERE identity_key = ?",
                    owner_prefix(user["id"]) + snap["key"],
                )
                if row is None:
                    raise RuntimeError("事项没有写入")
                res.update(
                    {
                        "status": next(
                            (k for k in ("new", "changed") if counts.get(k)), "unchanged"
                        ),
                        "item_id": row["id"],
                        "type": row["item_type"],
                        "monitor": await monitor.on_capture(
                            self.db, user["id"], row["id"], supported
                        ),
                        "error": None,
                    }
                )
            except BadRequest as e:
                res.update({"status": "error", "error": {"code": e.code, "message": e.message}})
            except Exception:
                log.exception("capture item %s failed", i)
                res.update(
                    {
                        "status": "error",
                        "error": {"code": "internal", "message": "保存失败，请稍后重试"},
                    }
                )
            res.setdefault("monitor", None)
            results.append(res)
        failed = sum(1 for r in results if r["status"] == "error")
        return Response.json_body(
            {
                "ok": failed == 0,
                "saved": len(results) - failed,
                "failed": failed,
                "results": results,
            }
        )

    # ---- 插件：事项级监测（IC-001 3.2、3.3，决策 D23） -------------------------------

    async def monitor_due(self, req: Request, user: dict[str, Any]) -> Response:
        limit = as_int(req.query.get("limit"), "limit", default=20, lo=1, hi=50)
        tasks, nxt = await monitor.lease_due(self.db, user["id"], limit)
        return Response.json_body({"tasks": tasks, "lease_s": monitor.LEASE_S, "next_due_at": nxt})

    async def monitor_results(self, req: Request, user: dict[str, Any]) -> Response:
        """插件回报重新获取的结果：成功的走流水线比较并记版本；失败只记原因，不更新最后成功时间。"""
        raw = as_list(body_of(req).get("results"), "results", max_len=50)
        if not raw:
            raise invalid("results", "至少要有一条")
        uid = user["id"]
        out = []
        for i, r in enumerate(raw):
            res: dict[str, Any] = {"item_id": None, "status": "error", "last_success_at": None}
            try:
                if not isinstance(r, dict):
                    raise invalid(f"results[{i}]", "应为对象")
                iid = as_int(r.get("item_id"), f"results[{i}].item_id", lo=1)
                res["item_id"] = iid
                mon = await monitor.get(self.db, uid, iid)
                row = await self.db.fetchone("SELECT * FROM items WHERE id = ?", iid)
                if not mon or not mon["supported"] or not mon["enabled"] or row is None:
                    raise BadRequest(404, "该事项没有启用监测", "not_monitored")
                if not isinstance(r.get("ok"), bool):
                    raise invalid(f"results[{i}].ok", "应为布尔值")
                if r["ok"]:
                    res.update(await self._monitor_success(user, row, r, i))
                else:
                    err = as_dict(r.get("error"), f"results[{i}].error")
                    code = err.get("code")
                    if code not in monitor.ERROR_CODES:
                        raise invalid(f"results[{i}].error.code", "取值不正确")
                    msg = as_str(err.get("message"), "message", max_len=300, default="")
                    last_ok = await monitor.record_failure(self.db, uid, iid, code, msg)
                    if code == "unsupported":
                        await monitor.on_capture(self.db, uid, iid, False)
                    res.update({"status": "failed", "last_success_at": last_ok})
                await self.publish(f"u.{uid}", {"type": "item_updated", "item_id": iid})
            except BadRequest as e:
                res["error"] = {"code": e.code, "message": e.message}
            except Exception:
                log.exception("monitor result %s failed", i)
                res["error"] = {"code": "internal", "message": "处理失败"}
            out.append(res)
        return Response.json_body({"results": out})

    async def _monitor_success(
        self, user: dict[str, Any], row: dict[str, Any], r: dict[str, Any], i: int
    ) -> dict[str, Any]:
        attrs = loads(row.get("attrs"), {})
        page_url = attrs.get("page_url") or row["url"]
        hint = dict(r)
        hint.setdefault("type", row.get("item_type") or None)  # 没给类型就沿用原类型，免得规则改判
        snap = _capture_snap(
            hint,
            f"results[{i}]",
            page_url,
            attrs.get("page_title", ""),
            attrs.get("platform", ""),
            attrs.get("locator", ""),
        )
        snap["key"] = row["identity_key"].removeprefix(owner_prefix(user["id"]))
        snap["dedupe_url"] = snap["key"]
        counts = await self.pipeline.ingest(
            {"source_id": row["source_id"], "status": "ok", "prev_status": "ok", "items": [snap]}
        )
        result = "changed" if counts.get("changed") else "unchanged"
        at = await monitor.record_success(self.db, user["id"], row["id"], result)
        return {"status": result, "last_success_at": at}

    # ---- 工作台：字段修改、冲突与监测开关（IC-002，决策 D22、D23） --------------------

    async def _own_item(self, req: Request, user: dict[str, Any]) -> dict[str, Any]:
        iid = path_id(req)
        if not await self._items_for(user["id"], " AND i.id = ?", (iid,)):
            raise BadRequest(404, "事项不存在", "not_found")
        row = await self.db.fetchone("SELECT * FROM items WHERE id = ?", iid)
        assert row
        return row

    async def _item_response(self, user: dict[str, Any], iid: int) -> Response:
        await self.publish(f"u.{user['id']}", {"type": "item_updated", "item_id": iid})
        items = await self._items_for(user["id"], " AND i.id = ?", (iid,))
        return Response.json_body(items[0])

    async def patch_fields(self, req: Request, user: dict[str, Any]) -> Response:
        row = await self._own_item(req, user)
        b = body_of(req)
        set_ = as_dict(b.get("set"), "set", default={})
        reset = as_list(b.get("reset"), "reset", max_len=len(edits.EDITABLE), default=[])
        await edits.apply(self.db, user["id"], row, set_, [str(f) for f in reset])
        return await self._item_response(user, row["id"])

    async def resolve_fields(self, req: Request, user: dict[str, Any]) -> Response:
        row = await self._own_item(req, user)
        b = body_of(req)
        field = as_str(b.get("field"), "field", max_len=40)
        keep = as_str(b.get("keep"), "keep", max_len=10)
        await edits.resolve(self.db, user["id"], row, field, keep)
        return await self._item_response(user, row["id"])

    async def put_monitor(self, req: Request, user: dict[str, Any]) -> Response:
        row = await self._own_item(req, user)
        enabled = body_of(req).get("enabled")
        if not isinstance(enabled, bool):
            raise invalid("enabled", "应为布尔值")
        await monitor.set_enabled(self.db, user["id"], row["id"], enabled)
        return await self._item_response(user, row["id"])

    async def source_login(self, req: Request, user: dict[str, Any]) -> Response:
        """来源登录：只保存登录后得到的 Cookie / Token（AES-GCM 加密），不保存统一认证密码。

        邮箱来源例外：IMAP/POP3 每次连接都需要口令，因此加密保存（建议使用应用专用密码）。
        公共来源与网页收藏不需要登录（也不能让某个订阅者借登录重置大家共用来源的采集状态）。
        """
        sid = path_id(req)
        src = await self._own_sub(user, sid)
        if not src:
            return Response.error(404, "来源不存在", "not_found")
        if src["owner_id"] is None or src["type"] == "clip":
            return Response.error(422, "这个来源不需要登录", "no_login")
        b = body_of(req)
        now = time.time()
        if src["type"] == "moodle" and "token" in b:
            # 统一认证学校：粘贴 Moodle 安全密钥（偏好设置 → 安全密钥），不经手统一认证密码
            key = normalize_ws_key(as_str(b.get("token"), "token", max_len=200, default=""))
            if key is None:
                return Response.error(422, "密钥格式不对：应为 32 位字母数字", "bad_token")
            try:
                sess = await moodle_token_session(self.fetcher, src["endpoint"], key)
            except FetchError as e:
                return _source_login_error(e)
            return await self._save_source_secret(user, sid, sess.to_secret(), "ws_token", now)
        username = as_str(b.get("username"), "username", max_len=254, default="").strip()
        password = as_str(b.get("password"), "password", max_len=PASSWORD_MAX, default="")
        if not username or not password:
            return Response.error(422, "请输入账号和密码", "missing")
        if src["type"] == "moodle":
            try:
                sess = await moodle_login(self.fetcher, src["endpoint"], username, password)
            except FetchError as e:
                return _source_login_error(e)
            secret = sess.to_secret()
            auth_type = "ws_token" if sess.ws_token else "cookie"
        elif src["type"] in ("imap", "pop3"):
            secret = {"username": username, "password": password, "smtp": _smtp_of(b.get("smtp"))}
            auth_type = "app_password"
            ok, err = await self._probe_mail(src, secret)
            if not ok:
                return Response.error(401, err or "邮箱登录失败", "mail_login_failed")
        else:
            secret = SourceSession().to_secret()
            auth_type = "cookie"
        return await self._save_source_secret(user, sid, secret, auth_type, now)

    async def _save_source_secret(
        self, user: dict[str, Any], sid: int, secret: dict[str, Any], auth_type: str, now: float
    ) -> Response:
        """加密保存来源凭据（AAD 绑定“用户 id:来源 id”），并立即触发一次采集。"""
        blob = security.encrypt(secret, aad=f"{user['id']}:{sid}".encode())
        await self.db.execute(
            """INSERT INTO credentials (user_id, source_id, auth_type, secret_encrypted, updated_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (user_id, source_id) DO UPDATE SET auth_type = excluded.auth_type, secret_encrypted = excluded.secret_encrypted, updated_at = excluded.updated_at""",
            user["id"],
            sid,
            auth_type,
            blob,
            now,
        )
        await self.db.execute(
            "UPDATE sources SET status = 'pending', next_fetch_at = 0, fail_count = 0, last_error = NULL, interval_s = 120 WHERE id = ?",
            sid,
        )
        await self.publish("collector.fetch", {"source_id": sid})
        await self.publish("mail.sources", {"source_id": sid})
        return Response.json_body({"ok": True, "auth_type": auth_type})

    async def _probe_mail(self, src: dict[str, Any], secret: dict[str, Any]) -> tuple[bool, str]:
        from ..mailsvc.receiver import probe

        return await probe(src, secret)

    async def refresh_source(self, req: Request, user: dict[str, Any]) -> Response:
        """立即检查。公共来源 60 秒内只受理一次（大家共用，不能被反复触发去刷对方网站）。"""
        sid = path_id(req)
        src = await self._own_sub(user, sid)
        if not src:
            return Response.error(404, "来源不存在", "not_found")
        if src["type"] == "clip":  # 网页收藏由插件推送，没有可采集的地址
            return Response.json_body({"ok": True, "via_agent": False})
        if src["owner_id"] is None:
            wait = self.refresh_shared.retry_after(str(sid))
            if wait:
                return _too_many(wait, "刚刚检查过，请稍后再试", "too_soon")
            self.refresh_shared.hit(str(sid))
        await self.db.execute("UPDATE sources SET next_fetch_at = 0 WHERE id = ?", sid)
        await self.publish("collector.fetch", {"source_id": sid})
        via_agent = False
        if self.agent_hub is not None:
            via_agent = await self.agent_hub.request_fetch(user["id"], sid)
        if not via_agent and self.collectors_online is not None and self.collectors_online() == 0:
            # 已排队（next_fetch_at = 0），采集节点恢复后会最先检查；如实告诉用户现在没在检查。
            # 用 202 而不是 503：网关把上游 503 计为被动健康检查失败，会误把 core 摘除
            return Response.json_body(
                {
                    "ok": True,
                    "via_agent": False,
                    "checking": False,
                    "message": "采集服务暂时不可用，恢复后会自动检查这个来源",
                },
                202,
            )
        return Response.json_body({"ok": True, "via_agent": via_agent, "checking": True})

    # ---- 邮件 ------------------------------------------------------------------

    async def mail_send(self, req: Request, user: dict[str, Any]) -> Response:
        """经已连接邮箱发信。Idempotency-Key 防重复提交：同一键重复提交直接返回上次结果。"""
        key = as_str(req.headers.get("Idempotency-Key"), "Idempotency-Key", max_len=100, default="")
        if not key:
            return Response.error(400, "缺少 Idempotency-Key 头", "missing_key")
        b = body_of(req)
        to = _addresses(b.get("to"), "to")
        cc = _addresses(b.get("cc"), "cc")
        if not to:
            return Response.error(422, "请填写有效的收件人", "bad_rcpt")
        if len(to) + len(cc) > MAIL_MAX_RCPT:
            return Response.error(422, f"收件人最多 {MAIL_MAX_RCPT} 个", "too_many_rcpt")
        atts = []
        total = 0
        for a in as_list(b.get("attachments"), "attachments", max_len=10, default=[]):
            a = as_dict(a, "attachment")
            try:
                content = base64.b64decode(
                    as_str(a.get("content_b64"), "content_b64", max_len=30_000_000), validate=True
                )
            except ValueError:
                return Response.error(422, "附件编码错误", "bad_attachment")
            mime = as_str(a.get("mime"), "mime", max_len=100, default="application/octet-stream")
            if not _MIME.fullmatch(mime):
                return Response.error(422, "附件类型不正确", "bad_attachment")
            total += len(content)
            atts.append(
                (
                    _one_line(as_str(a.get("filename"), "filename", max_len=200, default="file"))[
                        :100
                    ]
                    or "file",
                    content,
                    mime,
                )
            )
        if total > 20 * 1024 * 1024:
            return Response.error(413, "附件总大小不能超过 20 MB", "too_large")
        status, res = await send_user_mail(
            self.db,
            user,
            key,
            as_int(b.get("account_source_id"), "account_source_id", default=0, lo=0),
            to,
            cc,
            _one_line(as_str(b.get("subject"), "subject", max_len=1000, default=""))[:200],
            as_str(b.get("text"), "text", max_len=200_000, default=""),
            atts,
        )
        return Response.json_body(res, status)

    async def mail_sent(self, req: Request, user: dict[str, Any]) -> Response:
        rows = await self.db.fetch(
            "SELECT id, idempotency_key, message_id, recipients, subject, status, error, sent_at, created_at FROM sent_mails WHERE user_id = ? ORDER BY id DESC LIMIT 50",
            user["id"],
        )
        return Response.json_body(
            {"mails": [{**r, "recipients": loads(r["recipients"], [])} for r in rows]}
        )

    # ---- 看板与规则 --------------------------------------------------------------

    async def get_dashboard(self, req: Request, user: dict[str, Any]) -> Response:
        row = await self.db.fetchone(
            "SELECT layout, updated_at FROM dashboards WHERE user_id = ?", user["id"]
        )
        return Response.json_body(
            {
                "layout": loads(row["layout"], DEFAULT_DASHBOARD) if row else DEFAULT_DASHBOARD,
                "updated_at": row["updated_at"] if row else None,
            }
        )

    async def put_dashboard(self, req: Request, user: dict[str, Any]) -> Response:
        layout = body_of(req).get("layout")
        if (
            not isinstance(layout, dict)
            or not isinstance(layout.get("widgets"), list)
            or len(layout["widgets"]) > 30
        ):
            return Response.error(422, "布局格式错误", "bad_layout")
        for w in layout["widgets"]:
            if not isinstance(w, dict) or w.get("type") not in DASHBOARD_WIDGETS:
                return Response.error(422, "不支持的看板组件", "bad_widget")
        raw = json.dumps(layout, ensure_ascii=False)
        if len(raw) > 32_000:
            return Response.error(422, "布局过大", "bad_layout")
        await self.db.execute(
            "INSERT INTO dashboards (user_id, layout, updated_at) VALUES (?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET layout = excluded.layout, updated_at = excluded.updated_at",
            user["id"],
            raw,
            time.time(),
        )
        return Response.json_body({"ok": True})

    async def list_labels(self, req: Request, user: dict[str, Any]) -> Response:
        rows = await self.db.fetch(
            "SELECT id, name, color, created_at FROM labels WHERE user_id = ? ORDER BY id",
            user["id"],
        )
        return Response.json_body({"labels": [dict(r) for r in rows]})

    async def create_label(self, req: Request, user: dict[str, Any]) -> Response:
        b = body_of(req)
        name = as_str(b.get("name"), "name", max_len=40, default="").strip()
        if not name:
            return Response.error(422, "标签名不能为空", "invalid")
        color = as_str(b.get("color"), "color", max_len=20, default="").strip()
        count = await self.db.fetchval("SELECT COUNT(*) FROM labels WHERE user_id = ?", user["id"])
        if (count or 0) >= 50:
            return Response.error(422, "标签最多 50 个", "limit")
        exists = await self.db.fetchval(
            "SELECT id FROM labels WHERE user_id = ? AND name = ?", user["id"], name
        )
        if exists is not None:
            return Response.error(409, "已有同名标签", "conflict")
        now = time.time()
        lid = await self.db.insert(
            "labels",
            {"user_id": user["id"], "name": name, "color": color, "created_at": now},
        )
        return Response.json_body(
            {"id": lid, "name": name, "color": color, "created_at": now}, status=201
        )

    async def update_label(self, req: Request, user: dict[str, Any]) -> Response:
        lid = path_id(req)
        row = await self.db.fetchone(
            "SELECT id, name, color, created_at FROM labels WHERE id = ? AND user_id = ?",
            lid,
            user["id"],
        )
        if row is None:
            return Response.error(404, "标签不存在", "not_found")
        b = body_of(req)
        name = row["name"]
        color = row["color"]
        if "name" in b:
            name = as_str(b.get("name"), "name", max_len=40, default="").strip()
            if not name:
                return Response.error(422, "标签名不能为空", "invalid")
            clash = await self.db.fetchval(
                "SELECT id FROM labels WHERE user_id = ? AND name = ? AND id != ?",
                user["id"],
                name,
                lid,
            )
            if clash is not None:
                return Response.error(409, "已有同名标签", "conflict")
        if "color" in b:
            color = as_str(b.get("color"), "color", max_len=20, default="").strip()
        await self.db.execute(
            "UPDATE labels SET name = ?, color = ? WHERE id = ? AND user_id = ?",
            name,
            color,
            lid,
            user["id"],
        )
        return Response.json_body(
            {"id": lid, "name": name, "color": color, "created_at": row["created_at"]}
        )

    async def delete_label(self, req: Request, user: dict[str, Any]) -> Response:
        lid = path_id(req)
        row = await self.db.fetchone(
            "SELECT id FROM labels WHERE id = ? AND user_id = ?", lid, user["id"]
        )
        if row is None:
            return Response.error(404, "标签不存在", "not_found")
        async with self.db.transaction():
            await self.db.execute(
                "DELETE FROM item_labels WHERE user_id = ? AND label_id = ?", user["id"], lid
            )
            await self.db.execute(
                "DELETE FROM labels WHERE id = ? AND user_id = ?", lid, user["id"]
            )
        return Response.json_body({"ok": True})

    async def put_item_labels(self, req: Request, user: dict[str, Any]) -> Response:
        iid = path_id(req)
        owned = await self._items_for(user["id"], " AND i.id = ?", (iid,), limit=1)
        if not owned:
            return Response.error(404, "事项不存在", "not_found")
        b = body_of(req)
        raw_ids = as_list(b.get("label_ids"), "label_ids", max_len=50, default=[])
        label_ids: list[int] = []
        for i, v in enumerate(raw_ids):
            try:
                label_ids.append(int(v))
            except (TypeError, ValueError):
                return Response.error(422, f"第 {i + 1} 个 label_id 不正确", "invalid")
        label_ids = list(dict.fromkeys(label_ids))
        if label_ids:
            marks = ",".join("?" * len(label_ids))
            found = await self.db.fetch(
                f"SELECT id FROM labels WHERE user_id = ? AND id IN ({marks})",
                user["id"],
                *label_ids,
            )
            if len(found) != len(label_ids):
                return Response.error(422, "含有不属于你的标签", "invalid")
        now = time.time()
        async with self.db.transaction():
            await self.db.execute(
                "DELETE FROM item_labels WHERE user_id = ? AND item_id = ?", user["id"], iid
            )
            if label_ids:
                await self.db.executemany(
                    "INSERT INTO item_labels (user_id, item_id, label_id, created_at) VALUES (?, ?, ?, ?)",
                    [(user["id"], iid, lid, now) for lid in label_ids],
                )
        return Response.json_body({"item_id": iid, "label_ids": label_ids})

    async def get_rules(self, req: Request, user: dict[str, Any]) -> Response:
        rows = await self.db.fetch(
            "SELECT id, kind, pattern, boost FROM rules WHERE user_id = ? ORDER BY id", user["id"]
        )
        return Response.json_body({"rules": rows})

    async def put_rules(self, req: Request, user: dict[str, Any]) -> Response:
        rules = as_list(body_of(req).get("rules"), "rules", max_len=200, default=[])
        clean = []
        now = time.time()
        for i, r in enumerate(rules):
            if not isinstance(r, dict) or r.get("kind") not in ("keyword", "sender", "source"):
                return Response.error(422, f"第 {i + 1} 条规则的类型不正确", "bad_rule")
            pattern = as_str(r.get("pattern"), "pattern", max_len=500, default="").strip()[:100]
            if not pattern:
                return Response.error(422, f"第 {i + 1} 条规则缺少内容", "bad_rule")
            boost = as_float(r.get("boost"), "boost", default=0.5, lo=-1.0, hi=1.0, clamp=True)
            clean.append((user["id"], r["kind"], pattern, boost, now))
        async with self.db.transaction():  # 先删后插放在一个事务里，插入失败不会把规则清空
            await self.db.execute("DELETE FROM rules WHERE user_id = ?", user["id"])
            if clean:
                await self.db.executemany(
                    "INSERT INTO rules (user_id, kind, pattern, boost, created_at) VALUES (?, ?, ?, ?, ?)",
                    clean,
                )
        return await self.get_rules(req, user)

    # ---- 运营统计（真实用户指标） --------------------------------------------------

    async def stats(self, req: Request) -> Response:
        """运营统计：需要管理令牌（``GLEANER_ADMIN_TOKEN``，请求头 ``X-Admin-Token``）；结果缓存 60 秒。"""
        admin = os.environ.get("GLEANER_ADMIN_TOKEN", "")
        given = req.headers.get("X-Admin-Token", "")
        if not admin or not hmac.compare_digest(admin, given):
            return Response.error(403, "需要管理令牌", "forbidden")
        now = time.time()
        if self._stats_cache and now - self._stats_cache[0] < 60:
            return Response.json_body(self._stats_cache[1])
        users = await self.db.fetchval("SELECT COUNT(*) FROM users")
        dau = await self.db.fetchval(
            "SELECT COUNT(*) FROM users WHERE last_active_at > ?", now - 86400
        )
        subs = await self.db.fetchval("SELECT COUNT(*) FROM subscriptions")
        items = await self.db.fetchval("SELECT COUNT(*) FROM items")
        ni = await self.db.fetchval("SELECT COUNT(*) FROM events WHERE kind = 'not_important'")
        delivered = await self.db.fetchval(
            "SELECT COUNT(*) FROM deliveries WHERE priority != 'low'"
        )
        clicked = await self.db.fetchval(
            "SELECT COUNT(*) FROM user_item_state WHERE read_at IS NOT NULL"
        )
        out = {
            "users": users,
            "dau": dau,
            "subscriptions_per_user": round(subs / users, 2) if users else 0,
            "items": items,
            "not_important_ratio": round(ni / delivered, 3) if delivered else 0,
            "open_ratio": round(clicked / delivered, 3) if delivered else 0,
        }
        self._stats_cache = (now, out)
        return Response.json_body(out)

    async def _event(self, uid: int | None, kind: str, data: dict[str, Any] | None = None) -> None:
        await self.db.insert(
            "events", {"user_id": uid, "kind": kind, "data": data or {}, "created_at": time.time()}
        )
