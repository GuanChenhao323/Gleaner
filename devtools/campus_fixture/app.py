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
                    '<main><h1>三来源模拟环境</h1><p>账号由本站模拟登录，不使用真实学校凭据。</p><a href="/person/id-828.html?locale=zh_MO">FIE 人员目录</a><a href="/my/">Moodle Dashboard</a><a href="/capture/courses">按条件抓取：三门课程</a><a href="/capture/moodle-dashboard">Moodle 内容 aside、课程卡片与 Timeline</a><a href="/portal#news">学生资讯</a><a href="/portal#timetable">课表</a><a href="/extraction/home">新版：首页公告与资讯读取</a><a href="/my-class-timetable-student">新版：当前课表读取</a></main>',
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
        if path == "/capture/moodle-dashboard":
            cards = []
            for cid, name, ids in [
                (101, "網絡編程", [1101, 1102]),
                (202, "ARTIFICIAL INTELLIGENCE（人工智能）", []),
                (303, "数据科学", [3301]),
            ]:
                activities = "".join(
                    f'<li class="activity"><a href="/mod/assign/view.php?id={aid}">{name} 实验 {aid}</a><div class="activity-description">{name} 合成要求 {aid}，版本 {STATE["revision"]}。</div></li>'
                    for aid in ids
                )
                cards.append(
                    f'<div class="list-group-item"><a class="aalink coursename" href="/course/view.php?id={cid}">{name}</a><p>40% complete</p><ul>{activities}</ul></div>'
                )
            return self.send(
                page(
                    "moodle",
                    '<div id="region-main-box"><section id="region-main"><div role="main"><aside id="block-region-content" class="block-region" data-blockregion="content"><section class="block block_myoverview" id="inst-overview"><h5>Course overview</h5>'
                    + "".join(cards)
                    + """</section><section class="block block_recentlyaccesseditems"><h5>Recently accessed items</h5>
<a class="card dashboard-card coursename" href="/mod/assign/view.php?id=2201"><div class="card-body course-info-container"><div class="d-flex text-truncate"><span class="sr-only">Assignment</span><div><h6>assignment</h6><small>FOUNDATIONS(人工智能数学基础) - DEMO-B</small></div></div></div></a></section>
</aside></div></section><section data-region="blocks-column"><aside id="block-region-side-pre" data-blockregion="side-pre">
<section class="block block_html" data-block="html"><h5>Moodle Support</h5><div class="content"><h6>IT Office X100<br>0000-1234<br><a href="mailto:support@example.test">✉</a>support@example.test<br><a href="/message/index.php?id=77">Talk with us</a></h6></div></section>
<section class="block block_timeline" data-block="timeline"><h5>Timeline</h5><div data-region="event-list-content"><div><h5>Sunday, 15 November 2026</h5><div class="list-group">
<div data-region="event-list-item"><div class="event-name-container"><a href="/mod/assign/view.php?id=1101">合成实验提醒一</a><small>網絡編程</small><h6><a href="/mod/assign/view.php?id=1101&amp;action=editsubmission">Add submission</a></h6></div><small class="text-right">23:59</small></div>
<div data-region="event-list-item"><div class="event-name-container"><a href="/mod/assign/view.php?id=3301">合成实验提醒二</a><small>数据科学</small></div><small class="text-right">00:00</small></div>
</div></div></div></section><section class="block"><h5>Private files</h5><p>不得读入其他区块的测试文本</p></section></aside></section></div>""",
                    account,
                )
            )
        if path == "/capture/unsupported":
            return self.send(
                page("moodle", "<main><p>未知的合成页面布局</p></main>", account)
            )
        if path == "/capture/courses":
            courses = [
                (101, "網絡編程", [1101, 1102]),
                (202, "数据科学", [2201]),
                (303, "操作系统", [3301]),
            ]
            if q.get("ambiguous") == ["1"]:
                courses.append((404, "網絡編程（重修班）", [4401]))
            sections = []
            for cid, name, assignments in courses:
                items = "".join(
                    f'<li class="activity" data-assignment-id="{aid}"><a href="/mod/assign/view.php?id={aid}">{name} 实验 {aid}</a><div class="activity-description">{name} 原始要求 {aid}，合成版本 {STATE["revision"]}。提交两份 PDF。</div></li>'
                    for aid in assignments
                )
                sections.append(
                    f'<section data-course-id="{cid}" data-semester="2026秋"><h2><a href="/course/view.php?id={cid}">{name}</a></h2><ul>{items}</ul></section>'
                )
            return self.send(
                page(
                    "moodle",
                    '<main id="region-main"><h1>三门课程的当前已加载面板</h1>'
                    + "".join(sections)
                    + "</main>",
                    account,
                )
            )
        if path == "/extraction/home":
            notices = "".join(
                f'<li><a href="/detail?id={i}&amp;category=info.dict.category.notice">读取样本公告 {i}</a><p>样本发布单位 | 2026/01/02 | 浏览 10</p></li>'
                for i in (7001, 7002, 7003)
            )
            return self.send(
                page(
                    "student",
                    f'<main><section><h2>最新公告</h2><ul>{notices}</ul><a href="/list?category=info.dict.category.notice">更多</a></section><section><h2>大学新闻</h2><a href="/detail?id=8001&amp;category=info.dict.category.news">新闻样本</a></section></main><iframe title="不读取的助手嵌入页"></iframe>',
                    account,
                )
            )
        if path == "/detail":
            nid = html.escape(q.get("id", ["7001"])[0])
            return self.send(
                page(
                    "student",
                    f"<main><article><h1>读取样本公告 {nid}</h1><dl><dt>發佈時間</dt><dd>2026-01-02 10:00</dd><dt>有效期</dt><dd>2026-01-10</dd></dl><p>样本正文，要求核对当前安排。来源版本 {STATE['revision']}。这些均为合成数据。</p><p>瀏覽量：10</p></article></main>",
                    account,
                )
            )
        if path == "/my-class-timetable-student":
            return self.send(
                page(
                    "student",
                    '<main data-semester="2609"><h1>我的課表（合成）</h1><div role="grid"><div role="columnheader">11月9日 星期一</div><div class="fc-event"><div>样本课程甲</div><div>样本教师 @课室 X100</div><div>09:00 - 11:50</div></div><div class="fc-event"><div>样本课程乙</div><div>样本教师 @课室 X200</div><div>12:30 - 15:20</div></div></div></main>',
                    account,
                )
            )
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
