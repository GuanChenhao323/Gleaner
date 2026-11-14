"""REST API（proposal“REST API”一节）。所有路由在 ``/api`` 下，由网关转发到这里。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections.abc import Awaitable, Callable
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
from ..storage.db import Database, loads
from .monitors import BrowserMonitorService
from .pipeline import Pipeline, item_public, owner_prefix
from .templates import get_template, list_templates
from .web_captures import WebCaptureService

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


class API:
    def __init__(
        self, db: Database, pipeline: Pipeline, publish: Publish, *, fetcher: Fetcher | None = None
    ) -> None:
        self.db = db
        self.pipeline = pipeline
        self.publish = publish
        self.fetcher = fetcher or Fetcher(min_interval=0.2)
        self.agent_hub: Any = None

    # ---- 鉴权 ------------------------------------------------------------------

    async def user_of(self, req: Request) -> dict[str, Any] | None:
        if "user" in req.context:
            return req.context["user"]
        token = None
        auth = req.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        token = token or req.cookies().get(COOKIE)
        claims = security.verify_token(token) if token else None
        user = None
        if claims:
            user = await self.db.fetchone("SELECT * FROM users WHERE id = ?", int(claims["uid"]))
            if user and user["token_version"] != claims.get("tv"):
                user = None
        req.context["user"] = user
        return user

    def authed(
        self, fn: Callable[[Request, dict[str, Any]], Awaitable[Response]]
    ) -> Callable[[Request], Awaitable[Response]]:
        async def h(req: Request) -> Response:
            user = await self.user_of(req)
            if user is None:
                return Response.error(401, "请先登录", "unauthorized")
            return await fn(req, user)

        return h

    def register(self, r: Router) -> None:
        a = self.authed
        BrowserMonitorService(self.db, self.pipeline).register(r, a)
        WebCaptureService(self.db, self.pipeline).register(r, a)
        r.add("GET", "/health", self.health)
        r.add("GET", "/api/health", self.health)
        r.add("POST", "/api/auth/code", self.send_code)
        r.add("POST", "/api/auth/register", self.register_user)
        r.add("POST", "/api/auth/login", self.login)
        r.add("POST", "/api/auth/logout", a(self.logout))
        r.add("GET", "/api/me", a(self.me))
        r.add("PUT", "/api/me", a(self.update_me))
        r.add("DELETE", "/api/account", a(self.delete_account))
        r.add("GET", "/api/feed", a(self.feed))
        r.add("GET", "/api/sync", a(self.sync))
        r.add("GET", "/api/items/{id}", a(self.get_item))
        r.add("GET", "/api/items/{id}/versions", a(self.versions))
        r.add("PUT", "/api/items/{id}/state", a(self.put_state))
        r.add("POST", "/api/items/{id}/feedback", a(self.feedback))
        r.add("POST", "/api/state/batch", a(self.state_batch))
        r.add("GET", "/api/deadlines", a(self.deadlines))
        r.add("GET", "/api/courses", a(self.courses))
        r.add("GET", "/api/templates", self.templates)
        r.add("GET", "/api/sources", a(self.list_sources))
        r.add("POST", "/api/sources", a(self.add_source))
        r.add("POST", "/api/clips", a(self.save_clip))
        r.add("POST", "/api/sources/preview", a(self.preview_source))
        r.add("PUT", "/api/sources/{id}", a(self.update_source))
        r.add("DELETE", "/api/sources/{id}", a(self.remove_source))
        r.add("POST", "/api/sources/{id}/login", a(self.source_login))
        r.add("POST", "/api/sources/{id}/refresh", a(self.refresh_source))
        r.add("POST", "/api/mail/send", a(self.mail_send))
        r.add("GET", "/api/mail/sent", a(self.mail_sent))
        r.add("GET", "/api/dashboard", a(self.get_dashboard))
        r.add("PUT", "/api/dashboard", a(self.put_dashboard))
        r.add("GET", "/api/rules", a(self.get_rules))
        r.add("PUT", "/api/rules", a(self.put_rules))
        r.add("GET", "/api/stats", self.stats)

    # ---- 账号 ------------------------------------------------------------------

    async def health(self, req: Request) -> Response:
        await self.db.fetchval("SELECT 1")
        return Response.json_body({"status": "ok", "service": "core", "time": time.time()})

    def _session_response(self, user: dict[str, Any], status: int = 200) -> Response:
        token = security.sign_token({"uid": user["id"], "tv": user["token_version"]})
        resp = Response.json_body({"token": token, "user": _user_public(user)}, status)
        resp.headers.add(
            "Set-Cookie", f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={30 * 86400}"
        )
        return resp

    async def send_code(self, req: Request) -> Response:
        """注册验证码：6 位数字，经平台账号用自研 SMTP 发出；10 分钟有效，同一邮箱 60 秒内只发一次。"""
        email = str((req.json() or {}).get("email", "")).strip().lower()
        if not _EMAIL.match(email):
            return Response.error(422, "邮箱格式不正确", "bad_email")
        if await self.db.fetchone("SELECT id FROM users WHERE email = ?", email):
            return Response.error(409, "该邮箱已注册", "exists")
        now = time.time()
        prev = await self.db.fetchone("SELECT sent_at FROM email_codes WHERE email = ?", email)
        if prev and now - prev["sent_at"] < CODE_RESEND:
            resp = Response.error(429, "验证码已发送，请稍后再试", "too_soon")
            resp.headers["Retry-After"] = str(int(CODE_RESEND - (now - prev["sent_at"])) + 1)
            return resp
        code = f"{secrets.randbelow(1_000_000):06d}"
        await self.db.execute(
            """INSERT INTO email_codes (email, code_hash, expires_at, attempts, sent_at) VALUES (?, ?, ?, 0, ?)
               ON CONFLICT (email) DO UPDATE SET code_hash = excluded.code_hash, expires_at = excluded.expires_at,
               attempts = 0, sent_at = excluded.sent_at""",
            email,
            _code_hash(email, code),
            now + CODE_TTL,
            now,
        )
        ok = await send_platform_mail(
            email,
            f"拾课注册验证码：{code}",
            f"你的拾课注册验证码是 {code}，10 分钟内有效。\n\n如果不是你本人操作，请忽略这封邮件。",
        )
        if not ok:
            await self.db.execute("DELETE FROM email_codes WHERE email = ?", email)
            return Response.error(502, "验证码邮件发送失败，请稍后重试", "mail_failed")
        return Response.json_body({"ok": True, "expires_in": CODE_TTL, "resend_after": CODE_RESEND})

    async def _check_code(self, email: str, code: str) -> str | None:
        """校验验证码，返回错误信息；连续错 5 次作废。"""
        row = await self.db.fetchone("SELECT * FROM email_codes WHERE email = ?", email)
        if not row or row["expires_at"] < time.time():
            return "验证码已过期，请重新获取"
        if row["attempts"] >= CODE_MAX_ATTEMPTS:
            return "验证码错误次数过多，请重新获取"
        if not hmac.compare_digest(row["code_hash"], _code_hash(email, code)):
            await self.db.execute(
                "UPDATE email_codes SET attempts = attempts + 1 WHERE email = ?", email
            )
            return "验证码不正确"
        await self.db.execute("DELETE FROM email_codes WHERE email = ?", email)
        return None

    async def register_user(self, req: Request) -> Response:
        b = req.json() or {}
        email = str(b.get("email", "")).strip().lower()
        pw = str(b.get("password", ""))
        if not _EMAIL.match(email):
            return Response.error(422, "邮箱格式不正确", "bad_email")
        if len(pw) < 8:
            return Response.error(422, "密码至少 8 位", "weak_password")
        if not b.get("agree_privacy", True):
            return Response.error(422, "请先阅读并同意隐私说明", "privacy")
        if await self.db.fetchone("SELECT id FROM users WHERE email = ?", email):
            return Response.error(409, "该邮箱已注册", "exists")
        if require_email_code():
            err = await self._check_code(email, str(b.get("code", "")).strip())
            if err:
                return Response.error(422, err, "bad_code")
        uid = await self.db.insert(
            "users",
            {
                "email": email,
                "password_hash": security.hash_password(pw),
                "name": str(b.get("name") or email.split("@")[0])[:40],
                "grade": str(b.get("grade", ""))[:20],
                "major": str(b.get("major", ""))[:40],
                "courses": b.get("courses") or [],
                "created_at": time.time(),
            },
        )
        await self._event(uid, "register")
        user = await self.db.fetchone("SELECT * FROM users WHERE id = ?", uid)
        assert user
        # New users choose their own sources. dev_all --seed explicitly adds demo sources.
        return self._session_response(user, 201)

    async def login(self, req: Request) -> Response:
        b = req.json() or {}
        user = await self.db.fetchone(
            "SELECT * FROM users WHERE email = ?", str(b.get("email", "")).strip().lower()
        )
        if not user or not security.verify_password(
            user["password_hash"], str(b.get("password", ""))
        ):
            return Response.error(401, "邮箱或密码错误", "bad_credentials")
        await self.db.execute(
            "UPDATE users SET last_active_at = ? WHERE id = ?", time.time(), user["id"]
        )
        await self._event(user["id"], "login")
        return self._session_response(user)

    async def logout(self, req: Request, user: dict[str, Any]) -> Response:
        resp = Response.json_body({"ok": True})
        resp.headers.add("Set-Cookie", f"{COOKIE}=; Path=/; HttpOnly; Max-Age=0")
        if (req.json() or {}).get("all_devices"):
            await self.db.execute(
                "UPDATE users SET token_version = token_version + 1 WHERE id = ?", user["id"]
            )
        return resp

    async def me(self, req: Request, user: dict[str, Any]) -> Response:
        out = _user_public(user)
        out["cursor"] = user["next_seq"]
        return Response.json_body(out)

    async def update_me(self, req: Request, user: dict[str, Any]) -> Response:
        b = req.json() or {}
        fields = {}
        for k in ("name", "grade", "major", "digest_time", "quiet_start", "quiet_end"):
            if k in b:
                v = str(b[k])[:40]
                if k in ("digest_time", "quiet_start", "quiet_end") and not re.fullmatch(
                    r"\d{2}:\d{2}", v
                ):
                    return Response.error(422, f"{k} 应为 HH:MM", "bad_time")
                fields[k] = v
        if "digest_email" in b:
            fields["digest_email"] = int(bool(b["digest_email"]))
        if "courses" in b and isinstance(b["courses"], list):
            fields["courses"] = json.dumps(
                [str(c)[:60] for c in b["courses"]][:50], ensure_ascii=False
            )
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            await self.db.execute(
                f"UPDATE users SET {sets} WHERE id = ?", *fields.values(), user["id"]
            )
        u = await self.db.fetchone("SELECT * FROM users WHERE id = ?", user["id"])
        assert u
        return Response.json_body(_user_public(u))

    async def delete_account(self, req: Request, user: dict[str, Any]) -> Response:
        """一键删除账号与全部数据（安全、隐私与合规）。私有来源及其事项级联删除。"""
        uid = user["id"]
        for t in (
            "deliveries",
            "user_item_state",
            "op_log",
            "rules",
            "sent_mails",
            "dashboards",
            "credentials",
            "subscriptions",
            "reminders_sent",
            "transfers",
        ):
            await self.db.execute(f"DELETE FROM {t} WHERE user_id = ?", uid)
        await self.db.execute("DELETE FROM sources WHERE owner_id = ?", uid)
        await self.db.execute("DELETE FROM events WHERE user_id = ?", uid)
        await self.db.execute("DELETE FROM users WHERE id = ?", uid)
        resp = Response.json_body({"ok": True, "deleted": True})
        resp.headers.add("Set-Cookie", f"{COOKIE}=; Path=/; HttpOnly; Max-Age=0")
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
        sql = f"""SELECT i.*, st.read_at, st.starred, st.todo_status, st.hidden, st.not_important, st.deadline_override, st.note, st.score, st.priority, st.reasons,
                    src.name AS src_name, src.type AS src_type, src.last_success_at AS src_last_success, src.status AS src_status
                  FROM items i
                  JOIN subscriptions s ON s.source_id = i.source_id AND s.user_id = ?
                  JOIN sources src ON src.id = i.source_id
                  LEFT JOIN user_item_state st ON st.item_id = i.id AND st.user_id = ?
                  WHERE i.kind != 'teacher' {where} {order} LIMIT {int(limit)}"""
        rows = await self.db.fetch(sql, uid, uid, *params)
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
            out.append(item_public(r, state, src))
        return out

    async def feed(self, req: Request, user: dict[str, Any]) -> Response:
        """分页收件箱。cursor = ``排序时间:id``（键集分页，翻页期间有新数据也不会重复或遗漏）。"""
        q = req.query
        where = " AND i.deleted = 0 AND COALESCE(st.hidden, 0) = 0"
        params: list[Any] = []
        if q.get("kind"):
            where += " AND i.kind = ?"
            params.append(q["kind"])
        if q.get("course"):
            where += " AND i.course LIKE ?"
            params.append(f"%{q['course']}%")
        f = q.get("filter")
        if f == "unread":
            where += " AND st.read_at IS NULL"
        elif f == "starred":
            where += " AND st.starred = 1"
        elif f == "todo":
            where += " AND COALESCE(st.todo_status, '') IN ('todo', 'doing')"
        elif f == "important":
            where += " AND COALESCE(st.priority, 'low') != 'low'"
        if q.get("q"):
            where += " AND (i.title LIKE ? OR i.summary LIKE ? OR i.course LIKE ?)"
            params += [f"%{q['q']}%"] * 3
        sort = "COALESCE(i.published_at, i.first_seen_at)"
        if q.get("cursor"):
            try:
                ts_s, id_s = q["cursor"].split(":")
                where += f" AND ({sort} < ? OR ({sort} = ? AND i.id < ?))"
                params += [float(ts_s), float(ts_s), int(id_s)]
            except ValueError:
                return Response.error(400, "bad cursor")
        limit = min(int(q.get("limit", 30)), 100)
        items = await self._items_for(
            user["id"], where, tuple(params), f"ORDER BY {sort} DESC, i.id DESC", limit + 1
        )
        nxt = None
        if len(items) > limit:
            items = items[:limit]
            last = items[-1]
            nxt = f"{last['published_at'] or last['first_seen_at']}:{last['id']}"
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
        try:
            cursor = int(req.query.get("cursor", "0"))
        except ValueError:
            return Response.error(400, "bad cursor")
        rows = await self.db.fetch(
            "SELECT seq, payload FROM deliveries WHERE user_id = ? AND seq > ? ORDER BY seq LIMIT 501",
            user["id"],
            cursor,
        )
        more = len(rows) > 500
        rows = rows[:500]
        out = [loads(r["payload"], {}) for r in rows]
        new_cursor = rows[-1]["seq"] if rows else cursor
        # 游标落后太多（例如投递已被清理）时让客户端全量刷新
        reset = cursor > user["next_seq"]
        return Response.json_body(
            {"deliveries": out, "cursor": new_cursor, "has_more": more, "reset": reset}
        )

    async def get_item(self, req: Request, user: dict[str, Any]) -> Response:
        items = await self._items_for(user["id"], " AND i.id = ?", (int(req.params["id"]),))
        if not items:
            return Response.error(404, "事项不存在")
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
        return Response.json_body(it)

    async def versions(self, req: Request, user: dict[str, Any]) -> Response:
        iid = int(req.params["id"])
        if not await self._items_for(user["id"], " AND i.id = ?", (iid,)):
            return Response.error(404, "事项不存在")
        rows = await self.db.fetch(
            "SELECT version, changed_fields, important, change_note, detected_at FROM item_versions WHERE item_id = ? ORDER BY version DESC",
            iid,
        )
        return Response.json_body(
            {
                "versions": [
                    {
                        **r,
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
        """修改个人状态；op_id 作为幂等键，重复提交直接返回第一次的结果（离线回放）。"""
        if op_id:
            prev = await self.db.fetchone(
                "SELECT result FROM op_log WHERE user_id = ? AND op_id = ?", uid, op_id
            )
            if prev:
                return 200, {**loads(prev["result"], {}), "duplicate": True}
        if not await self.db.fetchone(
            "SELECT 1 FROM items i JOIN subscriptions s ON s.source_id = i.source_id AND s.user_id = ? WHERE i.id = ?",
            uid,
            item_id,
        ):
            return 404, {"error": "not_found"}
        now = time.time()
        client_ts = float(b.get("ts") or now)
        cur = await self.db.fetchone(
            "SELECT * FROM user_item_state WHERE user_id = ? AND item_id = ?", uid, item_id
        )
        if cur and cur["updated_at"] > client_ts and op_id:
            # 冲突处理：个人状态以最后修改时间为准
            result = {"ok": True, "stale": True, "item_id": item_id}
        else:
            vals: dict[str, Any] = {}
            if "read" in b:
                vals["read_at"] = client_ts if b["read"] else None
            if "starred" in b:
                vals["starred"] = int(bool(b["starred"]))
            if "todo" in b:
                vals["todo_status"] = (
                    str(b["todo"] or "") if b["todo"] in (None, "", "todo", "doing", "done") else ""
                )
            if "hidden" in b:
                vals["hidden"] = int(bool(b["hidden"]))
            if "deadline_override" in b:
                vals["deadline_override"] = (
                    float(b["deadline_override"]) if b["deadline_override"] else None
                )
            if "note" in b:
                vals["note"] = str(b["note"])[:2000]
            if not cur:
                await self.db.execute(
                    "INSERT INTO user_item_state (user_id, item_id, updated_at) VALUES (?, ?, ?)",
                    uid,
                    item_id,
                    client_ts,
                )
            if vals:
                sets = ", ".join(f"{k} = ?" for k in vals)
                await self.db.execute(
                    f"UPDATE user_item_state SET {sets}, updated_at = ? WHERE user_id = ? AND item_id = ?",
                    *vals.values(),
                    max(client_ts, cur["updated_at"] if cur else 0),
                    uid,
                    item_id,
                )
            st = await self.db.fetchone(
                "SELECT * FROM user_item_state WHERE user_id = ? AND item_id = ?", uid, item_id
            )
            assert st
            result = {
                "ok": True,
                "item_id": item_id,
                "state": {
                    "read": st["read_at"] is not None,
                    "starred": bool(st["starred"]),
                    "todo": st["todo_status"],
                    "hidden": bool(st["hidden"]),
                    "deadline_override": st["deadline_override"],
                    "note": st["note"],
                },
            }
            # 多设备同步：把状态变化推给该用户的其他在线设备
            await self.publish(
                f"u.{uid}",
                {"type": "state", "item_id": item_id, "state": result["state"], "op_id": op_id},
            )
        if op_id:
            await self.db.execute(
                "INSERT INTO op_log (user_id, op_id, result, created_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                uid,
                op_id,
                json.dumps(result, ensure_ascii=False),
                now,
            )
        return 200, result

    async def put_state(self, req: Request, user: dict[str, Any]) -> Response:
        b = req.json() or {}
        op = req.headers.get("Idempotency-Key") or b.get("op_id")
        status, res = await self.apply_state(user["id"], int(req.params["id"]), b, op)
        return Response.json_body(res, status)

    async def state_batch(self, req: Request, user: dict[str, Any]) -> Response:
        """离线操作队列按顺序回放。"""
        ops = (req.json() or {}).get("ops", [])
        results = []
        for op in ops[:500]:
            status, res = await self.apply_state(
                user["id"], int(op.get("item_id", 0)), op, op.get("op_id")
            )
            results.append({"op_id": op.get("op_id"), "status": status, **res})
        return Response.json_body({"results": results})

    async def feedback(self, req: Request, user: dict[str, Any]) -> Response:
        """“不重要”：降低该来源的权重，系统逐步贴合个人习惯。"""
        iid = int(req.params["id"])
        item = await self.db.fetchone("SELECT source_id FROM items WHERE id = ?", iid)
        if not item:
            return Response.error(404, "事项不存在")
        await self.db.execute(
            "UPDATE subscriptions SET weight = MAX(0.1, weight - 0.1) WHERE user_id = ? AND source_id = ?"
            if self.db.kind == "sqlite"
            else "UPDATE subscriptions SET weight = GREATEST(0.1, weight - 0.1) WHERE user_id = ? AND source_id = ?",
            user["id"],
            item["source_id"],
        )
        await self.db.execute(
            "INSERT INTO user_item_state (user_id, item_id, not_important, updated_at) VALUES (?, ?, 1, ?) ON CONFLICT (user_id, item_id) DO UPDATE SET not_important = 1",
            user["id"],
            iid,
            time.time(),
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
        frm = float(req.query.get("from", now - 7 * 86400))
        to = float(req.query.get("to", now + 60 * 86400))
        items = await self._items_for(
            user["id"],
            " AND i.deleted = 0 AND COALESCE(st.deadline_override, i.deadline_at) BETWEEN ? AND ?",
            (frm, to),
            "ORDER BY COALESCE(st.deadline_override, i.deadline_at)",
            500,
        )
        return Response.json_body({"items": items})

    async def courses(self, req: Request, user: dict[str, Any]) -> Response:
        """课程主页：未完成作业、近期通知、来自官网的教师信息（场景 6）。"""
        items = await self._items_for(
            user["id"], " AND i.deleted = 0 AND i.course != ''", (), "ORDER BY i.deadline_at", 500
        )
        teachers = await self.db.fetch(
            "SELECT title, url, attrs FROM items WHERE kind = 'teacher' AND deleted = 0"
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

    async def add_source(self, req: Request, user: dict[str, Any]) -> Response:
        b = req.json() or {}
        tpl = get_template(b["template"]) if b.get("template") else None
        if b.get("template") and not tpl:
            return Response.error(404, "模板不存在")
        stype = (tpl or {}).get("type") or b.get("type")
        endpoint = str(b.get("endpoint") or (tpl or {}).get("endpoint") or "").strip()
        if stype not in ("moodle", "web", "rss", "teacher", "imap", "pop3"):
            return Response.error(422, "不支持的来源类型", "bad_type")
        if not re.match(r"^(https?|imaps?|pop3s?)://", endpoint):
            return Response.error(422, "请输入完整网址", "bad_endpoint")
        config = {**((tpl or {}).get("config") or {}), **(b.get("config") or {})}
        shared = (
            bool((tpl or {}).get("shared"))
            if tpl
            else (stype in ("web", "rss") and not b.get("private"))
        )
        now = time.time()
        src = None
        if shared:
            # 同一网址可能既有“列表”订阅又有“整页监测”订阅（浏览器插件），按 mode 区分
            for cand in await self.db.fetch(
                "SELECT * FROM sources WHERE owner_id IS NULL AND endpoint = ? AND type = ?",
                endpoint,
                stype,
            ):
                if loads(cand.get("config"), {}).get("mode") == config.get("mode"):
                    src = cand
                    break
        if src is None:
            sid = await self.db.insert(
                "sources",
                {
                    "owner_id": None if shared else user["id"],
                    "type": stype,
                    "name": str(b.get("name") or (tpl or {}).get("name") or endpoint)[:60],
                    "endpoint": endpoint,
                    "template": (tpl or {}).get("id", ""),
                    "config": config,
                    "course": str(b.get("course", ""))[:60],
                    "via_agent": int(bool(b.get("via_agent"))),
                    "status": "pending"
                    if not (tpl or {}).get("needs_login") and stype not in ("imap", "pop3")
                    else "need_login",
                    "created_at": now,
                    "next_fetch_at": 0,
                },
            )
        else:
            sid = src["id"]
        weight = float(b.get("weight") or (tpl or {}).get("weight") or 0.6)
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
            },
            201,
        )

    async def preview_source(self, req: Request, user: dict[str, Any]) -> Response:
        """首次采集预览：不保存，直接运行一次连接器，让用户确认提取的字段对不对。"""
        b = req.json() or {}
        tpl = get_template(b["template"]) if b.get("template") else {}
        stype = (tpl or {}).get("type") or b.get("type")
        if stype not in ("web", "rss", "teacher"):
            return Response.error(422, "该类型需要先登录，无法预览", "need_login")
        info = SourceInfo(
            0,
            stype,
            b.get("endpoint") or (tpl or {}).get("endpoint", ""),
            {**((tpl or {}).get("config") or {}), **(b.get("config") or {})},
        )
        try:
            res = await CONNECTORS[stype](Context(self.fetcher, info, None))
        except FetchError as e:
            return Response.json_body({"ok": False, "error": str(e), "kind": e.kind})
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
        sid = int(req.params["id"])
        if not await self._own_sub(user, sid):
            return Response.error(404, "来源不存在")
        b = req.json() or {}
        if "weight" in b:
            await self.db.execute(
                "UPDATE subscriptions SET weight = ? WHERE user_id = ? AND source_id = ?",
                max(0.0, min(1.0, float(b["weight"]))),
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
        if "name" in b:
            await self.db.execute(
                "UPDATE sources SET name = ? WHERE id = ? AND owner_id = ?",
                str(b["name"])[:60],
                sid,
                user["id"],
            )
        if "course" in b:
            await self.db.execute(
                "UPDATE sources SET course = ? WHERE id = ? AND owner_id = ?",
                str(b["course"])[:60],
                sid,
                user["id"],
            )
        return Response.json_body({"ok": True})

    async def remove_source(self, req: Request, user: dict[str, Any]) -> Response:
        sid = int(req.params["id"])
        src = await self._own_sub(user, sid)
        if not src:
            return Response.error(404, "来源不存在")
        await self.db.execute(
            "DELETE FROM subscriptions WHERE user_id = ? AND source_id = ?", user["id"], sid
        )
        await self.db.execute(
            "DELETE FROM credentials WHERE user_id = ? AND source_id = ?", user["id"], sid
        )
        if src["owner_id"] == user["id"]:
            await self.db.execute("DELETE FROM sources WHERE id = ?", sid)
        return Response.json_body({"ok": True})

    # ---- 浏览器插件：保存当前页面 -----------------------------------------------

    async def save_clip(self, req: Request, user: dict[str, Any]) -> Response:
        """插件“保存到收件箱”：页面正文由插件在用户浏览器里读取后上传（登录后才能看的页面也能存）。

        每个用户一个个人来源“网页收藏”（类型 clip，不参与定时采集）；事项走正常流水线，
        同一网址再次保存会比较正文并记录新版本。不按链接与其他事项合并：
        否则保存一篇已在收件箱里的通知会被并进通知，用户保存的正文和之后的版本都会丢失。
        """
        b = req.json() or {}
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
        sid = await self.db.insert(
            "sources",
            {
                "owner_id": user["id"],
                "type": "clip",
                "name": "网页收藏",
                "endpoint": "extension://clip",
                "template": "",
                "config": {},
                "status": "ok",
                "created_at": now,
                "next_fetch_at": 0,
            },
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

    async def source_login(self, req: Request, user: dict[str, Any]) -> Response:
        """来源登录：只保存登录后得到的 Cookie / Token（AES-GCM 加密），不保存统一认证密码。

        邮箱来源例外：IMAP/POP3 每次连接都需要口令，因此加密保存（建议使用应用专用密码）。
        """
        sid = int(req.params["id"])
        src = await self._own_sub(user, sid)
        if not src:
            return Response.error(404, "来源不存在")
        b = req.json() or {}
        now = time.time()
        if src["type"] == "moodle" and "token" in b:
            # 统一认证学校：粘贴 Moodle 安全密钥（偏好设置 → 安全密钥），不经手统一认证密码
            key = normalize_ws_key(str(b.get("token") or ""))
            if key is None:
                return Response.error(422, "密钥格式不对：应为 32 位字母数字", "bad_token")
            try:
                sess = await moodle_token_session(self.fetcher, src["endpoint"], key)
            except FetchError as e:
                return Response.json_body(
                    {"ok": False, "error": str(e), "kind": e.kind},
                    401 if e.kind == "need_login" else 502,
                )
            return await self._save_source_secret(user, sid, sess.to_secret(), "ws_token", now)
        username, password = str(b.get("username", "")), str(b.get("password", ""))
        if not username or not password:
            return Response.error(422, "请输入账号和密码", "missing")
        if src["type"] == "moodle":
            try:
                sess = await moodle_login(self.fetcher, src["endpoint"], username, password)
            except FetchError as e:
                return Response.json_body(
                    {"ok": False, "error": str(e), "kind": e.kind},
                    401 if e.kind == "need_login" else 502,
                )
            secret = sess.to_secret()
            auth_type = "ws_token" if sess.ws_token else "cookie"
        elif src["type"] in ("imap", "pop3"):
            secret = {"username": username, "password": password, "smtp": b.get("smtp") or {}}
            auth_type = "app_password"
            ok, err = await self._probe_mail(src, secret)
            if not ok:
                return Response.json_body({"ok": False, "error": err}, 401)
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
        sid = int(req.params["id"])
        src = await self._own_sub(user, sid)
        if not src:
            return Response.error(404, "来源不存在")
        if src["type"] == "clip":  # 网页收藏由插件推送，没有可采集的地址
            return Response.json_body({"ok": True, "via_agent": False})
        await self.db.execute("UPDATE sources SET next_fetch_at = 0 WHERE id = ?", sid)
        await self.publish("collector.fetch", {"source_id": sid})
        via_agent = False
        if self.agent_hub is not None:
            via_agent = await self.agent_hub.request_fetch(user["id"], sid)
        return Response.json_body({"ok": True, "via_agent": via_agent})

    # ---- 邮件 ------------------------------------------------------------------

    async def mail_send(self, req: Request, user: dict[str, Any]) -> Response:
        """经已连接邮箱发信。Idempotency-Key 防重复提交：同一键重复提交直接返回上次结果。"""
        key = req.headers.get("Idempotency-Key", "")
        if not key:
            return Response.error(400, "缺少 Idempotency-Key 头", "missing_key")
        b = req.json() or {}
        to = [str(x).strip() for x in b.get("to", []) if _EMAIL.match(str(x).strip())]
        if not to:
            return Response.error(422, "请填写有效的收件人", "bad_rcpt")
        atts = []
        total = 0
        for a in b.get("attachments", [])[:10]:
            try:
                content = base64.b64decode(a["content_b64"])
            except (KeyError, ValueError):
                return Response.error(422, "附件编码错误", "bad_attachment")
            total += len(content)
            atts.append(
                (
                    str(a.get("filename", "file"))[:100],
                    content,
                    str(a.get("mime", "application/octet-stream")),
                )
            )
        if total > 20 * 1024 * 1024:
            return Response.error(413, "附件总大小不能超过 20 MB", "too_large")
        status, res = await send_user_mail(
            self.db,
            user,
            key,
            int(b.get("account_source_id") or 0),
            to,
            [str(x) for x in b.get("cc", [])],
            str(b.get("subject", ""))[:200],
            str(b.get("text", "")),
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
        layout = (req.json() or {}).get("layout")
        if (
            not isinstance(layout, dict)
            or not isinstance(layout.get("widgets"), list)
            or len(layout["widgets"]) > 30
        ):
            return Response.error(422, "布局格式错误", "bad_layout")
        allowed = {
            "inbox",
            "deadlines",
            "calendar",
            "todo",
            "sources",
            "starred",
            "board",
            "course",
            "digest",
        }
        for w in layout["widgets"]:
            if not isinstance(w, dict) or w.get("type") not in allowed:
                return Response.error(422, f"不支持的组件 {w}", "bad_widget")
        await self.db.execute(
            "INSERT INTO dashboards (user_id, layout, updated_at) VALUES (?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET layout = excluded.layout, updated_at = excluded.updated_at",
            user["id"],
            json.dumps(layout, ensure_ascii=False),
            time.time(),
        )
        return Response.json_body({"ok": True})

    async def get_rules(self, req: Request, user: dict[str, Any]) -> Response:
        rows = await self.db.fetch(
            "SELECT id, kind, pattern, boost FROM rules WHERE user_id = ? ORDER BY id", user["id"]
        )
        return Response.json_body({"rules": rows})

    async def put_rules(self, req: Request, user: dict[str, Any]) -> Response:
        rules = (req.json() or {}).get("rules", [])
        if not isinstance(rules, list) or len(rules) > 200:
            return Response.error(422, "规则格式错误")
        clean = []
        for r in rules:
            if (
                r.get("kind") not in ("keyword", "sender", "source")
                or not str(r.get("pattern", "")).strip()
            ):
                return Response.error(422, f"非法规则 {r}")
            clean.append(
                (
                    user["id"],
                    r["kind"],
                    str(r["pattern"]).strip()[:100],
                    max(-1.0, min(1.0, float(r.get("boost", 0.5)))),
                    time.time(),
                )
            )
        await self.db.execute("DELETE FROM rules WHERE user_id = ?", user["id"])
        if clean:
            await self.db.executemany(
                "INSERT INTO rules (user_id, kind, pattern, boost, created_at) VALUES (?, ?, ?, ?, ?)",
                clean,
            )
        return await self.get_rules(req, user)

    # ---- 运营统计（真实用户指标） --------------------------------------------------

    async def stats(self, req: Request) -> Response:
        now = time.time()
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
        return Response.json_body(
            {
                "users": users,
                "dau": dau,
                "subscriptions_per_user": round(subs / users, 2) if users else 0,
                "items": items,
                "not_important_ratio": round(ni / delivered, 3) if delivered else 0,
                "open_ratio": round(clicked / delivered, 3) if delivered else 0,
            }
        )

    async def _event(self, uid: int | None, kind: str, data: dict[str, Any] | None = None) -> None:
        await self.db.insert(
            "events", {"user_id": uid, "kind": kind, "data": data or {}, "created_at": time.time()}
        )
