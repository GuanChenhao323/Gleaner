"""Synthetic three-source DOM fixtures only. No real school data or private APIs.
Run: .venv/bin/python devtools/campus_fixture/app.py --port 8098
"""

from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

STATE = {"revision": 1, "missing": False}


def page(adapter: str, body: str, account: str = "", script: str = "") -> str:
    marker = f'data-account-id="{html.escape(account)}"' if account else ""
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="campus-radar-fixture" content="{adapter}"><title>Campus Radar 模拟结构夹具</title>
<style>body{{font-family:system-ui;padding:24px}}article{{border:1px solid #ccc;padding:15px;margin:12px}}a,button{{margin:8px}}</style></head>
<body {marker}><header>仅用于开发，不是真实 MUST 页面结构的证明。</header><nav><a href="/">夹具首页</a><a href="/admin">管理台</a></nav>
{body}<footer>学院通用电话：0000-0000，不得归入个人资料。</footer><script>{script}</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def send(
        self, text: str, status: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        raw = text.encode()
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        path = u.path
        cookie = self.headers.get("Cookie", "")
        account = (
            "student-b"
            if "fixture_account=student-b" in cookie
            else "student-a"
            if "fixture_account=student-a" in cookie
            else ""
        )
        if path == "/":
            return self.send(
                page(
                    "fie",
                    '<main><h1>三来源模拟环境</h1><p>账号由本站模拟登录，不使用真实学校凭据。</p><a href="/person/id-828.html?locale=zh_MO">FIE 人员目录</a><a href="/my/">Moodle Dashboard</a><a href="/portal#news">学生资讯</a><a href="/portal#timetable">课表</a></main>',
                )
            )
        if path == "/admin":
            return self.send(
                page(
                    "fie",
                    f"""<main><h1>模拟管理台</h1><p>当前版本 {STATE["revision"]}</p>
<form action="/admin/change" method="post"><button>修改所选人员与作业正文</button></form>
<form action="/admin/missing" method="post"><button>切换选区丢失</button></form>
<form action="/logout" method="post"><button>使浏览器模拟登录失效</button></form></main>""",
                )
            )
        if path == "/login":
            return self.send(
                page(
                    "moodle",
                    '<main><h1>模拟学校登录</h1><form action="/login" method="post"><select name="account"><option>student-a</option><option>student-b</option></select><button>登录模拟学校</button></form></main>',
                )
            )
        if path.startswith("/person/view/"):
            pid = path.rsplit("id-", 1)[-1].split(".")[0]
            body = (
                ""
                if STATE["missing"]
                else f'''<article data-person-id="{pid}"><h1>模拟人员 {pid}</h1><dl><dt>部门</dt><dd>模拟教研室</dd><dt>办公室</dt><dd>测试楼 A{pid}</dd><dt>邮箱</dt><dd>person-{pid}@example.test</dd></dl><p>用户关心的资料，来源版本 {STATE["revision"]}。</p></article>'''
            )
            return self.send(page("fie", f"<main>{body}</main>"))
        if path.startswith("/person/"):
            cards = "".join(
                f'<article><a href="/person/view/id-{i}.html?locale=zh_MO">模拟人员 {i}</a></article>'
                for i in (9001, 9002, 9003)
            )
            return self.send(
                page(
                    "fie", "<main><h1>创新工程学院模拟人员目录</h1>" + cards + "</main>"
                )
            )
        if not account:
            return self.send("", 302, {"Location": "/login"})
        if path in ("/my/", "/course/view.php"):
            links = "".join(
                f'<li class="activity assign"><a href="/mod/assign/view.php?id={i}">模拟作业 {i}</a></li>'
                for i in (1001, 1002, 1003)
            )
            return self.send(
                page(
                    "moodle",
                    '<main id="region-main"><h1>Dashboard</h1><a href="/course/view.php?id=101">模拟课程</a><ul>'
                    + links
                    + "</ul></main>",
                    account,
                )
            )
        if path == "/mod/assign/view.php":
            aid = q.get("id", ["1001"])[0]
            detail = (
                ""
                if STATE["missing"]
                else f'<div class="activity-dates" data-region="activity-dates">Due: 2026-11-12 23:59</div><div id="intro" class="activity-description"><p>模拟作业 {aid} 原始要求，版本 {STATE["revision"]}。</p><p class="submission-requirements">提交两份 PDF。</p></div>'
            )
            return self.send(
                page(
                    "moodle",
                    '<main id="region-main"><h1>模拟作业 '
                    + aid
                    + '</h1><p data-shortname="CS-DEMO">模拟课程</p>'
                    + detail
                    + "</main>",
                    account,
                )
            )
        if path == "/portal":
            if q.get("fault") == ["shell"]:
                return self.send(
                    page("student", '<div id="app">正在加载…</div>', account)
                )
            notices = "".join(
                f'<article data-notice-id="{i}"><h2>模拟资讯 {i}</h2><p>资讯正文 {i}，来源版本 {STATE["revision"]}。</p></article>'
                for i in ("a", "b", "c")
            )
            courses = "".join(
                f'<article data-schedule-id="course-{i}"><h2>课程安排 {i}</h2><dl><dt>课程</dt><dd>模拟课 {i}</dd><dt>星期</dt><dd>周五</dd><dt>节次</dt><dd>3-4节</dd></dl><p>第2教学周，无校历映射，不推断日期。</p></article>'
                for i in (1, 2, 3)
            )
            js = "function draw(){document.querySelector('#news').hidden=location.hash==='#timetable';document.querySelector('#schedule').hidden=location.hash!=='#timetable'};addEventListener('hashchange',draw);draw();"
            return self.send(
                page(
                    "student",
                    f'<main data-semester="2026秋" data-week="2"><section id="news">{notices}</section><section id="schedule">{courses}</section></main>',
                    account,
                    js,
                )
            )
        return self.send("<title>Not found</title>", 404)

    def do_POST(self) -> None:
        form = parse_qs(
            self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
        )
        if self.path == "/login":
            account = form.get("account", ["student-a"])[0]
            if account not in ("student-a", "student-b"):
                return self.send("invalid account", 400)
            return self.send(
                "",
                303,
                {
                    "Location": "/my/",
                    "Set-Cookie": f"fixture_account={account}; HttpOnly; Path=/; SameSite=Lax",
                },
            )
        if self.path == "/logout":
            return self.send(
                "",
                303,
                {
                    "Location": "/login",
                    "Set-Cookie": "fixture_account=; Max-Age=0; Path=/",
                },
            )
        if self.path == "/admin/change":
            STATE["revision"] += 1
        elif self.path == "/admin/missing":
            STATE["missing"] = not STATE["missing"]
        else:
            return self.send("not found", 404)
        self.send("", 303, {"Location": "/admin"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8098)
    port = parser.parse_args().port
    print(
        json.dumps({"fixture": "synthetic-only", "url": f"http://127.0.0.1:{port}"}),
        flush=True,
    )
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
