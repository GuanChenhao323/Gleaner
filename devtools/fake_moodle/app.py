"""模拟 Moodle 4.x、学院通知网站、教师信息页（开发与演示专用，不连接真实学校系统）。

    python -m fake_moodle.app --port 8090        （在 devtools/ 目录下）
    浏览器打开 http://localhost:8090/admin 可以现场修改截止时间、替换附件、发布通知。

账号：student / moodle123。HTML 结构仿照 Moodle 4.x 的 class 命名（generaltable、activity-dates 等）。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import secrets
import smtplib
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate, parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

try:
    from .data import DAY, Assignment, Attachment, Notice, seed
except ImportError:  # 直接以脚本运行
    from data import DAY, Assignment, Attachment, Notice, seed  # type: ignore[no-redef]

USERS = {"student": "moodle123", "alice": "moodle123"}


class State:
    def __init__(self) -> None:
        d = seed()
        self.courses = d["courses"]
        self.assignments: list[Assignment] = d["assignments"]  # type: ignore[assignment]
        self.notices: list[Notice] = d["notices"]  # type: ignore[assignment]
        self.teachers = d["teachers"]
        self.sessions: dict[str, tuple[str, float]] = {}
        self.tokens: dict[str, str] = {}
        self.session_ttl = float(os.environ.get("FAKE_MOODLE_SESSION_TTL", "3600"))
        self.lock = threading.RLock()
        self.hits: dict[str, int] = {}
        self.log: list[str] = []
        self.ws_enabled = os.environ.get("FAKE_MOODLE_WS", "1") == "1"

    def course(self, cid: int) -> Any:
        return next((c for c in self.courses if c.id == cid), None)

    def assignment(self, aid: int) -> Assignment | None:
        return next((a for a in self.assignments if a.id == aid), None)

    def note(self, msg: str) -> None:
        self.log.insert(0, time.strftime("%H:%M:%S ") + msg)
        del self.log[50:]


STATE = State()


def moodle_date(ts: float) -> str:
    """Moodle 默认英文日期格式：Friday, 6 November 2026, 11:59 PM。"""
    lt = time.localtime(ts)
    return (
        time.strftime("%A, ", lt)
        + str(lt.tm_mday)
        + time.strftime(" %B %Y, ", lt)
        + time.strftime("%I:%M %p", lt).lstrip("0")
    )


def page(title: str, body: str, *, user: str | None = None) -> str:
    nav = (
        f'<span class="usertext">{html.escape(user)}</span> · <a href="/login/logout.php">Log out</a>'
        if user
        else '<a href="/login/index.php">Log in</a>'
    )
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;background:#f5f6f8}}header{{background:#0f6cbf;color:#fff;padding:12px 24px;display:flex;justify-content:space-between}}
header a{{color:#fff}}main{{max-width:960px;margin:24px auto;background:#fff;padding:24px;border-radius:8px}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left}}</style>
</head><body id="page-site"><header><a href="/my/" class="navbar-brand">Fake Moodle（测试环境）</a><div class="usermenu">{nav}</div></header>
<main id="region-main" role="main"><h2>{html.escape(title)}</h2>{body}</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FakeMoodle/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("FAKE_MOODLE_VERBOSE"):
            super().log_message(fmt, *args)

    # ---- 工具 ----
    def _user(self) -> str | None:
        cookies = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k] = v
        sid = cookies.get("MoodleSession")
        if not sid:
            return None
        with STATE.lock:
            entry = STATE.sessions.get(sid)
            if not entry or entry[1] < time.time():
                STATE.sessions.pop(sid, None)
                return None
            return entry[0]

    def _send(
        self,
        status: int,
        body: bytes | str,
        ctype: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
        last_modified: float | None = None,
    ) -> None:
        data = body.encode() if isinstance(body, str) else body
        etag = '"' + hashlib.sha1(data).hexdigest()[:16] + '"'
        h = dict(headers or {})
        if status == 200 and self.command == "GET":
            h["ETag"] = etag
            if last_modified:
                h["Last-Modified"] = formatdate(last_modified, usegmt=True)
            inm = self.headers.get("If-None-Match")
            ims = self.headers.get("If-Modified-Since")
            fresh = False
            if inm is not None:
                fresh = etag in [t.strip() for t in inm.split(",")]
            elif ims and last_modified:
                try:
                    fresh = int(last_modified) <= parsedate_to_datetime(ims).timestamp()
                except (TypeError, ValueError):
                    fresh = False
            if fresh:
                self.send_response(304)
                for k, v in h.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", "0")
                self.end_headers()
                STATE.hits["304"] = STATE.hits.get("304", 0) + 1
                return
        rng = self.headers.get("Range")
        if status == 200 and rng and rng.startswith("bytes=") and ctype.startswith("application/"):
            a, _, b = rng[6:].partition("-")
            start = int(a or 0)
            end = int(b) if b else len(data) - 1
            h["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
            data = data[start : end + 1]
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for k, v in h.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        STATE.hits[str(status)] = STATE.hits.get(str(status), 0) + 1

    def _redirect(self, to: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", to)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _form(self) -> dict[str, str]:
        raw = self._body()
        ctype = self.headers.get("Content-Type", "")
        if "json" in ctype:
            return json.loads(raw or b"{}")
        return {k: v[0] for k, v in parse_qs(raw.decode()).items()}

    def _need_login(self) -> str | None:
        user = self._user()
        if user is None:
            # 会话过期：跳转登录页（与真实 Moodle 行为一致）
            self._redirect("/login/index.php")
        return user

    # ---- 路由 ----
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        with STATE.lock:
            STATE.hits["requests"] = STATE.hits.get("requests", 0) + 1
            if p == "/":
                return self._redirect("/my/")
            if p == "/robots.txt":
                return self._send(
                    200, "User-agent: *\nDisallow: /admin\nCrawl-delay: 1\n", "text/plain"
                )
            if p == "/login/index.php":
                token = secrets.token_hex(8)
                form = f"""<form action="/login/index.php" method="post" id="login"><input type="hidden" name="logintoken" value="{token}">
<p><label>Username <input name="username" id="username"></label></p><p><label>Password <input type="password" name="password" id="password"></label></p>
<button type="submit" id="loginbtn">Log in</button></form><p class="text-muted">测试账号 student / moodle123</p>"""
                return self._send(200, page("Log in to the site", form))
            if p == "/login/logout.php":
                return self._redirect(
                    "/login/index.php", {"Set-Cookie": "MoodleSession=; Max-Age=0; Path=/"}
                )
            if p.startswith("/news"):
                return self._news(p)
            if p.startswith("/faculty"):
                return self._faculty(p)
            if p == "/admin":
                return self._send(200, ADMIN_HTML)
            if p == "/admin/api/state":
                return self._json(self._state_json())
            if p.startswith("/webservice/rest/server.php"):
                return self._ws(q)
            if p.startswith("/pluginfile.php/"):
                return self._file(p)
            user = self._need_login()
            if user is None:
                return
            if p == "/user/managetoken.php":
                # 偏好设置 → 安全密钥：显示（必要时创建）当前用户的 Moodle mobile web service 密钥
                with STATE.lock:
                    tok = next((t for t, u in STATE.tokens.items() if u == user), None)
                    if tok is None:
                        tok = secrets.token_hex(16)
                        STATE.tokens[tok] = user
                body = (
                    '<table class="generaltable" id="webservicetokens"><thead><tr><th>Key</th><th>Service</th></tr></thead>'
                    f'<tbody><tr><td class="c0"><code>{tok}</code></td><td class="c1">Moodle mobile web service</td></tr></tbody></table>'
                )
                return self._send(200, page("Security keys", body, user=user))
            if p == "/my/":
                items = "".join(
                    f'<li class="course-listitem"><a href="/course/view.php?id={c.id}" class="coursename">{html.escape(c.shortname)} {html.escape(c.fullname)}</a> <span class="text-muted">{html.escape(c.teacher)}</span></li>'
                    for c in STATE.courses
                )
                return self._send(
                    200,
                    page("Dashboard", f'<ul class="list-group courses">{items}</ul>', user=user),
                )
            if p == "/course/view.php":
                c = STATE.course(int(q.get("id", 0)))
                if not c:
                    return self._send(404, page("Not found", "Course not found"))
                acts = "".join(
                    f'<li class="activity assign modtype_assign" id="module-{a.id}"><a href="/mod/assign/view.php?id={a.id}"><span class="instancename">{html.escape(a.name)}</span></a></li>'
                    for a in STATE.assignments
                    if a.course_id == c.id and a.visible
                )
                body = f'<p class="page-header-headings" data-shortname="{c.shortname}">{html.escape(c.fullname)}</p><ul class="section img-text">{acts}</ul><p><a href="/mod/assign/index.php?id={c.id}">All assignments</a></p>'
                return self._send(
                    200,
                    page(f"{c.shortname} {c.fullname}", body, user=user),
                    last_modified=self._course_mtime(c.id),
                )
            if p == "/mod/assign/index.php":
                c = STATE.course(int(q.get("id", 0)))
                if not c:
                    return self._send(404, page("Not found", "Course not found"))
                rows = "".join(
                    f'<tr><td class="cell c0">Topic {i}</td><td class="cell c1"><a href="/mod/assign/view.php?id={a.id}">{html.escape(a.name)}</a></td>'
                    f'<td class="cell c2">{moodle_date(a.due)}</td><td class="cell c3">No submission</td></tr>'
                    for i, a in enumerate(
                        (a for a in STATE.assignments if a.course_id == c.id and a.visible), 1
                    )
                )
                body = f'<p class="course-shortname" data-shortname="{c.shortname}">{html.escape(c.fullname)}</p><table class="generaltable mod_index"><thead><tr><th>Topic</th><th>Assignments</th><th>Due date</th><th>Submission</th></tr></thead><tbody>{rows}</tbody></table>'
                return self._send(
                    200,
                    page("Assignments", body, user=user),
                    last_modified=self._course_mtime(c.id),
                )
            if p == "/mod/assign/view.php":
                a = STATE.assignment(int(q.get("id", 0)))
                if not a or not a.visible:
                    return self._send(404, page("Not found", "Activity not found"))
                c = STATE.course(a.course_id)
                files = "".join(
                    f'<li><a href="/pluginfile.php/{a.id}/mod_assign/introattachment/0/{quote(f.name)}">{html.escape(f.name)}</a> <span class="size">{f.size} bytes</span></li>'
                    for f in a.attachments
                )
                body = f"""<nav class="breadcrumb"><a href="/course/view.php?id={c.id}" data-shortname="{c.shortname}">{c.shortname}</a></nav>
<div class="activity-header"><div class="activity-dates" data-region="activity-dates"><div><strong>Opened:</strong> {moodle_date(a.due - 14 * DAY)}</div><div><strong>Due:</strong> {moodle_date(a.due)}</div></div>
<div class="activity-description" id="intro"><div class="no-overflow"><p>{html.escape(a.intro)}</p></div>
<div class="submission-requirements"><strong>Submission:</strong> {html.escape(a.requirements)}</div>
<div id="assign_files_tree"><ul class="fileattachments">{files}</ul></div></div></div>"""
                return self._send(200, page(a.name, body, user=user), last_modified=a.modified)
            return self._send(404, page("Not found", "No such page"))

    def do_POST(self) -> None:
        u = urlsplit(self.path)
        p = u.path
        with STATE.lock:
            if p == "/login/index.php":
                f = self._form()
                if USERS.get(f.get("username", "")) == f.get("password") and f.get("logintoken"):
                    sid = secrets.token_hex(16)
                    STATE.sessions[sid] = (f["username"], time.time() + STATE.session_ttl)
                    STATE.note(f"用户 {f['username']} 登录")
                    return self._redirect(
                        "/my/", {"Set-Cookie": f"MoodleSession={sid}; Path=/; HttpOnly"}
                    )
                return self._send(
                    200,
                    page(
                        "Log in to the site",
                        '<div class="alert alert-danger" id="loginerrormessage">Invalid login, please try again</div><a href="/login/index.php">Back</a>',
                    ),
                )
            if p == "/login/token.php":
                f = self._form() or {k: v[0] for k, v in parse_qs(u.query).items()}
                if not STATE.ws_enabled:
                    return self._json(
                        {"error": "Web services are disabled", "errorcode": "enablewsdescription"}
                    )
                if USERS.get(f.get("username", "")) == f.get("password"):
                    tok = secrets.token_hex(16)
                    STATE.tokens[tok] = f["username"]
                    return self._json({"token": tok})
                return self._json(
                    {"error": "Invalid login, please try again", "errorcode": "invalidlogin"}
                )
            if p.startswith("/webservice/rest/server.php"):
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                q.update(self._form())
                return self._ws(q)
            if p.startswith("/admin/api/"):
                return self._admin(p[len("/admin/api/") :], self._form())
            return self._send(404, "not found", "text/plain")

    do_PATCH = do_POST

    def _json(self, obj: Any, status: int = 200) -> None:
        self._send(
            status,
            json.dumps(obj, ensure_ascii=False, default=str),
            "application/json; charset=utf-8",
        )

    def _course_mtime(self, cid: int) -> float:
        return max(
            (a.modified for a in STATE.assignments if a.course_id == cid), default=time.time()
        )

    # ---- Moodle Web Service（moodle_mobile_app 服务的子集） ----
    def _ws(self, q: dict[str, str]) -> None:
        if not STATE.ws_enabled:
            return self._json(
                {"exception": "webservice_access_exception", "errorcode": "accessexception"}
            )
        user = STATE.tokens.get(q.get("wstoken", ""))
        if user is None:
            return self._json(
                {
                    "exception": "moodle_exception",
                    "errorcode": "invalidtoken",
                    "message": "Invalid token - token not found",
                }
            )
        fn = q.get("wsfunction")
        if fn == "core_webservice_get_site_info":
            return self._json(
                {
                    "sitename": "Fake Moodle",
                    "username": user,
                    "userid": 3,
                    "release": "4.3 (Build: 20231009)",
                    # 与真实 Moodle 一致：列出该 token 所属服务允许调用的函数
                    "functions": [
                        {"name": n, "version": "2023100900"}
                        for n in (
                            "core_webservice_get_site_info",
                            "core_enrol_get_users_courses",
                            "mod_assign_get_assignments",
                        )
                    ],
                }
            )
        if fn == "core_enrol_get_users_courses":
            return self._json(
                [
                    {"id": c.id, "shortname": c.shortname, "fullname": c.fullname}
                    for c in STATE.courses
                ]
            )
        if fn == "mod_assign_get_assignments":
            out = []
            for c in STATE.courses:
                out.append(
                    {
                        "id": c.id,
                        "shortname": c.shortname,
                        "fullname": c.fullname,
                        "assignments": [
                            {
                                "id": a.id,
                                "cmid": a.id,
                                "name": a.name,
                                "duedate": int(a.due),
                                "intro": f"<p>{html.escape(a.intro)}</p><p>提交要求：{html.escape(a.requirements)}</p>",
                                "timemodified": int(a.modified),
                                "introattachments": [
                                    {
                                        "filename": f.name,
                                        "filesize": f.size,
                                        "fileurl": f"/pluginfile.php/{a.id}/mod_assign/introattachment/0/{quote(f.name)}",
                                    }
                                    for f in a.attachments
                                ],
                            }
                            for a in STATE.assignments
                            if a.course_id == c.id and a.visible
                        ],
                    }
                )
            return self._json({"courses": out, "warnings": []})
        return self._json(
            {
                "exception": "invalid_parameter_exception",
                "errorcode": "invalidparameter",
                "message": f"unknown function {fn}",
            }
        )

    def _file(self, p: str) -> None:
        m = re.match(r"/pluginfile.php/(\d+)/.+/(.+)$", p)
        if not m:
            return self._send(404, "not found", "text/plain")
        a = STATE.assignment(int(m.group(1)))
        name = unquote(m.group(2))
        f = next((f for f in (a.attachments if a else []) if f.name == name), None)
        if f is None:
            return self._send(404, "not found", "text/plain")
        return self._send(200, f.content, "application/pdf", {"Accept-Ranges": "bytes"})

    # ---- 学院通知 ----
    def _news(self, p: str) -> None:
        notices = sorted(STATE.notices, key=lambda n: -n.published)
        if p in ("/news", "/news/"):
            lis = "".join(
                f'<li class="news-item"><span class="cat">[{html.escape(n.category)}]</span> <a href="/news/{n.id}.html" title="{html.escape(n.title)}">{html.escape(n.title)}</a> <span class="date">{time.strftime("%Y-%m-%d", time.localtime(n.published))}</span></li>'
                for n in notices
            )
            return self._send(
                200,
                page(
                    "学院通知公告",
                    f'<ul class="news-list">{lis}</ul><p><a href="/news/rss.xml">RSS</a></p>',
                ),
                last_modified=max(n.published for n in notices),
            )
        if p == "/news/rss.xml":
            items = "".join(
                f"<item><title>{html.escape(n.title)}</title><link>http://{self.headers.get('Host')}/news/{n.id}.html</link><guid>notice-{n.id}</guid><pubDate>{formatdate(n.published)}</pubDate><description>{html.escape(n.body[:200])}</description><category>{html.escape(n.category)}</category></item>"
                for n in notices
            )
            xml = f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>学院通知公告</title><link>http://{self.headers.get("Host")}/news/</link><description>测试用学院通知</description>{items}</channel></rss>'
            return self._send(
                200,
                xml,
                "application/rss+xml; charset=utf-8",
                last_modified=max(n.published for n in notices),
            )
        m = re.match(r"/news/(\d+)\.html$", p)
        n = next((n for n in STATE.notices if m and n.id == int(m.group(1))), None)
        if not n:
            return self._send(404, page("未找到", "通知不存在"))
        body = f'<div class="article"><h1 class="arti-title">{html.escape(n.title)}</h1><p class="arti-meta">发布时间：<span class="arti-date">{time.strftime("%Y-%m-%d %H:%M", time.localtime(n.published))}</span> 分类：{html.escape(n.category)}</p><div class="arti-content"><p>{html.escape(n.body)}</p></div></div>'
        return self._send(200, page(n.title, body), last_modified=n.published)

    # ---- 教师信息 ----
    def _faculty(self, p: str) -> None:
        if p in ("/faculty", "/faculty/"):
            lis = "".join(
                f'<li class="teacher"><a href="/faculty/{t.id}.html">{html.escape(t.name)}</a> <span class="title">{html.escape(t.title)}</span></li>'
                for t in STATE.teachers
            )
            return self._send(200, page("师资队伍", f'<ul class="faculty-list">{lis}</ul>'))
        m = re.match(r"/faculty/(\d+)\.html$", p)
        t = next((t for t in STATE.teachers if m and t.id == int(m.group(1))), None)
        if not t:
            return self._send(404, page("未找到", "教师不存在"))
        body = f"""<div class="teacher-profile"><h1 class="name">{html.escape(t.name)}</h1><p class="title">{html.escape(t.title)}</p>
<table class="info"><tr><th>办公室</th><td class="office">{html.escape(t.office)}</td></tr><tr><th>电话</th><td class="phone">{html.escape(t.phone)}</td></tr>
<tr><th>邮箱</th><td class="email">{html.escape(t.email)}</td></tr><tr><th>主讲课程</th><td class="courses">{"、".join(t.courses)}</td></tr></table></div>"""
        return self._send(200, page(t.name, body))

    # ---- 管理接口：用于测试与现场演示变更检测 ----
    def _state_json(self) -> dict[str, Any]:
        return {
            "courses": [
                {"id": c.id, "shortname": c.shortname, "fullname": c.fullname}
                for c in STATE.courses
            ],
            "assignments": [
                {
                    "id": a.id,
                    "course_id": a.course_id,
                    "name": a.name,
                    "due": a.due,
                    "due_text": moodle_date(a.due),
                    "requirements": a.requirements,
                    "attachments": [f.name for f in a.attachments],
                    "visible": a.visible,
                }
                for a in STATE.assignments
            ],
            "notices": [
                {"id": n.id, "title": n.title, "published": n.published} for n in STATE.notices
            ],
            "sessions": len(STATE.sessions),
            "hits": STATE.hits,
            "log": STATE.log,
            "ws_enabled": STATE.ws_enabled,
        }

    def _admin(self, path: str, f: dict[str, Any]) -> None:
        now = time.time()
        if path == "assignments":
            aid = max(a.id for a in STATE.assignments) + 1
            due = float(f["due"]) if f.get("due") else now + float(f.get("due_days", 7)) * DAY
            a = Assignment(
                aid,
                int(f.get("course_id", 101)),
                f.get("name") or f"新作业 {aid}",
                f.get("intro") or "老师新发布的作业，请按时完成。",
                due,
                f.get("requirements") or "在线提交 PDF",
            )
            STATE.assignments.append(a)
            STATE.note(f"新增作业 {a.name}")
            return self._json({"ok": True, "id": aid})
        m = re.match(r"assignments/(\d+)(/attachment|/delete)?$", path)
        if m:
            a = STATE.assignment(int(m.group(1)))
            if not a:
                return self._json({"error": "not found"}, 404)
            if m.group(2) == "/attachment":
                name = f.get("name") or f"补充材料-v{int(now) % 1000}.pdf"
                if f.get("mode") == "add":
                    a.attachments.append(Attachment(name, f"%PDF-1.4 {now}".encode()))
                else:
                    a.attachments = [Attachment(name, f"%PDF-1.4 {now}".encode())]
                STATE.note(f"{a.name}：附件改为 {name}")
            elif m.group(2) == "/delete":
                a.visible = False
                STATE.note(f"隐藏作业 {a.name}")
            else:
                if "due" in f:
                    a.due = float(f["due"])
                if "shift_days" in f:
                    a.due += float(f["shift_days"]) * DAY
                for k in ("name", "intro", "requirements"):
                    if k in f:
                        setattr(a, k, f[k])
                STATE.note(f"修改作业 {a.name}：截止 {moodle_date(a.due)}")
            a.modified = now
            return self._json({"ok": True})
        if path == "notices":
            nid = max(n.id for n in STATE.notices) + 1
            n = Notice(
                nid,
                f.get("title") or f"测试通知 {nid}",
                f.get("body") or "这是一条新的测试通知。",
                now,
                f.get("category") or "教务",
            )
            STATE.notices.append(n)
            STATE.note(f"发布通知 {n.title}")
            return self._json({"ok": True, "id": nid})
        if path == "expire-sessions":
            STATE.sessions.clear()
            STATE.tokens.clear()
            STATE.note("所有会话已失效")
            return self._json({"ok": True})
        if path == "toggle-ws":
            STATE.ws_enabled = not STATE.ws_enabled
            return self._json({"ok": True, "ws_enabled": STATE.ws_enabled})
        if path == "mail-reminder":
            return self._json(
                send_reminder_mail(
                    int(f.get("assignment_id", 1001)),
                    f.get("to", "student@test.local"),
                    self.headers.get("Host", "localhost"),
                )
            )
        if path == "reset":
            fresh = State()
            STATE.__dict__.update(fresh.__dict__)
            return self._json({"ok": True})
        return self._json({"error": "unknown admin api"}, 404)


def send_reminder_mail(aid: int, to: str, host: str) -> dict[str, Any]:
    """模拟 Moodle 发出的作业提醒邮件，用于演示“跨渠道合并”。"""
    a = STATE.assignment(aid)
    if not a:
        return {"error": "not found"}
    c = STATE.course(a.course_id)
    msg = EmailMessage()
    msg["From"] = "Fake Moodle <noreply@moodle.test>"
    msg["To"] = to
    msg["Subject"] = f"{c.shortname}: 作业即将截止 - {a.name}"
    msg.set_content(
        f"{a.name} 将于 {moodle_date(a.due)} 截止。\n\n查看作业：http://{host}/mod/assign/view.php?id={a.id}\n"
    )
    smtp_host = os.environ.get("FAKE_MOODLE_SMTP_HOST", "localhost")
    smtp_port = int(os.environ.get("FAKE_MOODLE_SMTP_PORT", "2525"))
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=5) as s:
            s.ehlo()
            if s.has_extn("starttls"):
                import ssl

                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                s.starttls(context=ctx)
                s.ehlo()
            user = os.environ.get("FAKE_MOODLE_SMTP_USER")
            if user:
                s.login(user, os.environ.get("FAKE_MOODLE_SMTP_PASS", ""))
            s.send_message(msg)
        STATE.note(f"发送提醒邮件：{a.name} → {to}")
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "error": str(e)}


ADMIN_HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>Fake Moodle 演示控制台</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f172a;--card:#111c33;--fg:#e2e8f0;--muted:#94a3b8;--acc:#38bdf8;--warn:#f59e0b;--ok:#22c55e}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--fg)}
header{padding:20px 28px;border-bottom:1px solid #1e293b;display:flex;gap:12px;align-items:center}h1{font-size:20px;margin:0}
.wrap{display:grid;grid-template-columns:2fr 1fr;gap:20px;padding:24px 28px}@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid #1e293b;border-radius:14px;padding:18px}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:8px 6px;border-bottom:1px solid #1e293b;text-align:left;vertical-align:top}
button{background:#1e293b;color:var(--fg);border:1px solid #334155;border-radius:8px;padding:6px 10px;cursor:pointer;margin:2px;font-size:13px}
button:hover{border-color:var(--acc)}button.warn{border-color:var(--warn)}.muted{color:var(--muted);font-size:12px}
input,select{background:#0b1222;color:var(--fg);border:1px solid #334155;border-radius:8px;padding:6px;margin:2px}
#log div{font-size:13px;padding:4px 0;border-bottom:1px dashed #1e293b}.pill{font-size:12px;padding:2px 8px;border-radius:99px;background:#1e293b}
</style></head><body>
<header><h1>Fake Moodle 演示控制台</h1><span class="pill" id="stat"></span></header>
<div class="wrap"><div class="card"><h3>作业</h3><table id="tbl"></table>
<h3>新增作业</h3><select id="c"></select><input id="n" placeholder="作业名称"><input id="d" type="number" value="5" style="width:70px"> 天后截止 <button onclick="add()">发布</button>
<h3>发布通知</h3><input id="nt" placeholder="通知标题" style="width:60%"><button onclick="notice()">发布</button></div>
<div class="card"><h3>会话与渠道</h3><button class="warn" onclick="api('expire-sessions')">让所有登录会话失效</button><button onclick="api('toggle-ws')">切换 Web Service</button>
<p class="muted">会话失效后，拾课应把来源标为“需要重新登录”。</p><h3>操作记录</h3><div id="log"></div></div></div>
<script>
async function api(p,b){await fetch('/admin/api/'+p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});load()}
function add(){api('assignments',{course_id:+c.value,name:n.value,due_days:+d.value})}
function notice(){api('notices',{title:nt.value})}
async function load(){const s=await (await fetch('/admin/api/state')).json();
stat.textContent=`会话 ${s.sessions} · 请求 ${s.hits.requests||0} · 304 ${s.hits['304']||0} · WS ${s.ws_enabled?'开':'关'}`;
c.innerHTML=s.courses.map(x=>`<option value="${x.id}">${x.shortname} ${x.fullname}</option>`).join('');
tbl.innerHTML='<tr><th>课程</th><th>作业</th><th>截止</th><th>操作</th></tr>'+s.assignments.filter(a=>a.visible).map(a=>`<tr><td>${s.courses.find(x=>x.id==a.course_id).shortname}</td><td>${a.name}<div class="muted">${a.attachments.join('、')||'无附件'}</div></td><td>${a.due_text}</td>
<td><button class="warn" onclick="api('assignments/${a.id}',{shift_days:-2})">提前 2 天</button><button onclick="api('assignments/${a.id}',{shift_days:1})">推迟 1 天</button>
<button onclick="api('assignments/${a.id}/attachment',{})">替换附件</button><button onclick="api('assignments/${a.id}',{requirements:'改为纸质版提交，课上交'})">改要求</button>
<button onclick="api('mail-reminder',{assignment_id:${a.id}})">发提醒邮件</button><button onclick="api('assignments/${a.id}/delete',{})">删除</button></td></tr>`).join('');
log.innerHTML=s.log.map(l=>`<div>${l}</div>`).join('')}
load();setInterval(load,3000)
</script></body></html>"""


def serve(port: int = 8090, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8090")))
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    srv = serve(a.port, a.host)
    print(f"fake_moodle on http://localhost:{a.port}  (admin: /admin, user student/moodle123)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
