"""端到端：proposal“一条通知的端到端流程”与三个演示时刻（在同一进程内组合全部服务）。"""

import asyncio
import json
import threading
import time

import paho.mqtt.client as paho
import pytest
from fake_moodle import app as fm

from gleaner.collector import engine
from gleaner.config import Config
from gleaner.net.http import HTTPClient
from gleaner.net.websocket import ConnectionClosed, connect
from gleaner.services import start_broker, start_collector, start_core, start_gateway, start_push


@pytest.fixture
async def stack(tmp_path, monkeypatch, db_url):
    monkeypatch.setattr(engine, "MIN_INTERVAL", 0.5)
    monkeypatch.setattr(engine, "MAX_INTERVAL", 2.0)
    fm.STATE.__dict__.update(fm.State().__dict__)
    srv = fm.serve(0, "127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    moodle = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setenv("GLEANER_MOODLE_URL", moodle)
    monkeypatch.setenv("GLEANER_COLLEGE_URL", moodle)
    cfg = Config(
        db_url=db_url("e2e.db"),
        data_dir=str(tmp_path),
        core_port=0,
        bus_port=0,
        push_port=0,
        gateway_port=0,
        mqtt_port=0,
        mqtt_ws_port=0,
    )
    core = await start_core(cfg, host="127.0.0.1")
    cfg.bus_port = core.info["bus_port"]
    p1 = await start_push(cfg, "push-1", 0, host="127.0.0.1")
    p2 = await start_push(cfg, "push-2", 0, host="127.0.0.1")
    cfg.core_upstreams = f"core-1=127.0.0.1:{core.info['port']}"
    cfg.push_upstreams = f"push-1=127.0.0.1:{p1.info['port']},push-2=127.0.0.1:{p2.info['port']}"
    cfg.metrics_port = 0
    cfg.mqtt_ws_port = 0
    broker = await start_broker(cfg, host="127.0.0.1", port=0)
    cfg.mqtt_ws_upstream = ""
    gw = await start_gateway(cfg, host="127.0.0.1", port=0, check_interval=0.2)
    col = await start_collector(cfg, "collector-1")
    pushes = {"push-1": p1, "push-2": p2}
    yield {
        "cfg": cfg,
        "core": core,
        "gw": gw,
        "pushes": pushes,
        "broker": broker,
        "moodle": moodle,
        "fm": srv,
    }
    for r in (col, broker, gw, p2, p1, core):
        await r.close()
    srv.shutdown()


def admin(moodle, path, body):
    import requests

    return requests.post(f"{moodle}/admin/api/{path}", json=body, timeout=5).json()


async def until(fn, timeout=15.0, interval=0.1):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        r = await fn()
        if r:
            return r
        await asyncio.sleep(interval)
    raise AssertionError("condition not met in time")


async def recv_until(ws, pred, timeout=15.0):
    async with asyncio.timeout(timeout):
        while True:
            m = json.loads((await ws.recv()).text)
            if pred(m):
                return m


async def test_full_demo_path(stack):
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as c:
        r = await c.post(
            gw + "/api/auth/register",
            json_body={
                "email": "lin@test.edu",
                "password": "password1",
                "agree_privacy": True,
                "name": "小林",
                "grade": "2024级",
                "major": "计算机",
            },
        )
        assert r.status == 201, r.text()
        token = r.json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        me = (await c.get(gw + "/api/me", headers=auth)).json()
        assert me["mqtt"]["username"] == str(me["id"])

        # 1) 校园模板一键添加 Moodle，登录一次（只保存会话，不保存密码）
        r = await c.post(gw + "/api/sources", json_body={"template": "moodle"}, headers=auth)
        assert r.status == 201
        sid = r.json()["source"]["id"]
        r = await c.post(
            gw + f"/api/sources/{sid}/login",
            json_body={"username": "student", "password": "wrong"},
            headers=auth,
        )
        assert r.status == 401
        r = await c.post(
            gw + f"/api/sources/{sid}/login",
            json_body={"username": "student", "password": "moodle123"},
            headers=auth,
        )
        assert r.json()["ok"], r.text()

        async def feed_ready():
            f = (await c.get(gw + "/api/feed?kind=assignment", headers=auth)).json()
            return f if len(f["items"]) >= 7 else None

        feed = await until(feed_ready, 20)
        lab1 = next(i for i in feed["items"] if i["title"].startswith("实验一"))
        assert lab1["deadline_at"] and lab1["source"]["last_success_at"] and lab1["attachments"]
        assert lab1["priority"] in ("normal", "urgent")

        # 2) WebSocket 经网关连到推送节点，hello 带 last_seq
        ws = await connect(f"ws://127.0.0.1:{stack['gw'].info['port']}/ws?token={token}")
        await ws.send(json.dumps({"type": "hello", "token": token, "last_seq": 0}))
        welcome = await recv_until(ws, lambda m: m["type"] == "welcome")
        assert welcome["replayed"] >= 1
        cursor = welcome["cursor"]

        # MQTT：用 /api/me 给出的口令订阅自己的主题
        mq_msgs = []
        mq = paho.Client(
            paho.CallbackAPIVersion.VERSION2, client_id=f"phone-{me['id']}", clean_session=False
        )
        mq.username_pw_set(me["mqtt"]["username"], me["mqtt"]["password"])
        mq.on_message = lambda cl, u, msg: mq_msgs.append((msg.topic, json.loads(msg.payload)))
        mq.on_connect = lambda cl, u, f, rc, p=None: cl.subscribe(f"gleaner/u/{me['id']}/#", 1)
        mq.connect("127.0.0.1", stack["broker"].info["port"])
        mq.loop_start()

        # 3) 老师把截止时间提前 2 天 → 同一事项更新，标出“截止提前”，WebSocket 与 MQTT 同时送达
        admin(stack["moodle"], "assignments/1001", {"shift_days": -2})
        await c.post(gw + f"/api/sources/{sid}/refresh", headers=auth)
        ch = await recv_until(
            ws, lambda m: m["type"] == "change" and m["item_id"] == lab1["id"], 20
        )
        assert ch["important"] and "截止提前" in ch["note"] and ch["priority"] == "urgent"
        assert ch["seq"] > cursor
        old, new = ch["changed"]["deadline_at"]
        assert round((old - new) / 86400) == 2
        await until(lambda: asyncio.sleep(0, any(t.endswith("/urgent") for t, _ in mq_msgs)), 10)
        versions = (await c.get(gw + f"/api/items/{lab1['id']}/versions", headers=auth)).json()[
            "versions"
        ]
        assert versions[0]["important"] and len(versions) == 2
        feed2 = (await c.get(gw + "/api/feed?kind=assignment", headers=auth)).json()
        assert len(feed2["items"]) == 7  # 更新原有记录，而不是多出一条

        # 4) 离线操作按幂等键回放：同一 op_id 只生效一次
        for _ in range(2):
            r = await c.request(
                "PUT",
                gw + f"/api/items/{lab1['id']}/state",
                json_body={"todo": "todo"},
                headers={**auth, "Idempotency-Key": "op-123"},
            )
        assert r.json().get("duplicate")
        st = await recv_until(ws, lambda m: m["type"] == "state")
        assert st["state"]["todo"] == "todo"

        # 5) 当场结束该用户所在的推送节点 → 重连到另一节点，并补发宕机期间的消息
        node = welcome["node"]
        last_seq = ch["seq"]
        await stack["pushes"][node].close()
        with pytest.raises(ConnectionClosed):
            async with asyncio.timeout(5):
                while True:
                    await ws.recv()
        admin(stack["moodle"], "assignments/1101", {"requirements": "改为纸质版提交"})
        await c.post(gw + f"/api/sources/{sid}/refresh", headers=auth)
        await asyncio.sleep(1.0)

        async def reconnect():
            try:
                w = await connect(f"ws://127.0.0.1:{stack['gw'].info['port']}/ws?token={token}")
            except Exception:
                return None
            await w.send(json.dumps({"type": "hello", "token": token, "last_seq": last_seq}))
            try:
                m = await recv_until(w, lambda m: m["type"] in ("welcome", "change"), 5)
            except (ConnectionClosed, TimeoutError):
                return None
            return w, m

        ws2, first = await until(reconnect, 15, 0.3)
        got = [first]
        if first["type"] != "welcome":
            got.append(await recv_until(ws2, lambda m: m["type"] == "welcome"))
        welcome2 = got[-1]
        assert welcome2["node"] != node
        assert (
            any(m.get("type") == "change" and "提交要求变化" in m.get("note", "") for m in got)
            or welcome2["replayed"] >= 1
        )

        # 6) Moodle 会话失效 → 来源标为“需要重新登录”，并通知用户
        admin(stack["moodle"], "expire-sessions", {})
        await c.post(gw + f"/api/sources/{sid}/refresh", headers=auth)

        async def need_login():
            s = (await c.get(gw + "/api/sources", headers=auth)).json()["sources"]
            return any(x["id"] == sid and x["status"] == "need_login" for x in s)

        await until(need_login, 15)
        await ws2.close()
        mq.loop_stop()
        mq.disconnect()

        # 7) 网关指标与状态
        metrics = (await c.get(gw + "/metrics")).text()
        assert "gleaner_gateway_requests_total" in metrics and "gleaner_ws_connections" in metrics
        status = (await c.get(gw + "/gateway/status")).json()
        assert {p["name"] for p in status["push"]} == {"push-1", "push-2"}


async def test_notices_rss_teachers_and_preview(stack):
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as c:
        r = await c.post(
            gw + "/api/auth/register",
            json_body={
                "email": "mia@test.edu",
                "password": "password1",
                "agree_privacy": True,
                "grade": "2024级",
                "major": "计算机",
            },
        )
        auth = {"Authorization": f"Bearer {r.json()['token']}"}
        pv = (
            await c.post(
                gw + "/api/sources/preview", json_body={"template": "college_news"}, headers=auth
            )
        ).json()
        assert pv["ok"] and pv["count"] == 4
        for t in ("college_news", "faculty"):
            assert (
                await c.post(gw + "/api/sources", json_body={"template": t}, headers=auth)
            ).status == 201

        async def notices():
            f = (await c.get(gw + "/api/feed?kind=notice", headers=auth)).json()
            return f if len(f["items"]) >= 4 else None

        f = await until(notices, 20)
        contest = next(i for i in f["items"] if "创新创业" in i["raw_title"])
        assert contest["deadline_at"]  # “报名截止时间为11月15日23:59”
        assert "通知" not in contest["title"]  # 精简标题
        assert contest["facts"]["majors"]

        # 现场发布通知 → 一个检查周期内出现
        admin(
            stack["moodle"],
            "notices",
            {"title": "关于明天停课的通知", "body": "因故明天停课，补课时间另行通知。"},
        )
        srcs = (await c.get(gw + "/api/sources", headers=auth)).json()["sources"]
        news = next(s for s in srcs if s["template"] == "college_news")
        await c.post(gw + f"/api/sources/{news['id']}/refresh", headers=auth)

        async def new_notice():
            f = (await c.get(gw + "/api/feed?kind=notice", headers=auth)).json()
            return any("停课" in i["title"] for i in f["items"])

        await until(new_notice, 20)
        # 第二次检查应命中条件请求（304）
        srcs = (await c.get(gw + "/api/sources", headers=auth)).json()["sources"]
        assert any((s.get("saved_ratio") or 0) > 0 for s in srcs)

        # 第二个用户订阅同一公共来源，立即看到已有通知
        r = await c.post(
            gw + "/api/auth/register",
            json_body={"email": "jie@test.edu", "password": "password1", "agree_privacy": True},
        )
        auth2 = {"Authorization": f"Bearer {r.json()['token']}"}
        f2 = (await c.get(gw + "/api/feed", headers=auth2)).json()
        assert len(f2["items"]) >= 4

        # 账号删除：必须再次输入密码
        r = await c.request("DELETE", gw + "/api/account", headers=auth2)
        assert r.status == 403
        r = await c.request(
            "DELETE", gw + "/api/account", headers=auth2, json_body={"password": "password1"}
        )
        assert r.json()["deleted"]
        assert (await c.get(gw + "/api/me", headers=auth2)).status == 401


async def test_rate_limit(stack):
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as c:
        statuses = [(await c.get(gw + "/api/templates")).status for _ in range(80)]
    assert 429 in statuses and statuses[0] == 200


async def test_mail_merge_and_send(stack, monkeypatch):
    from fake_mail.server import FakeMailServer

    from gleaner.net.mail import OutgoingMail, build_message
    from gleaner.services import start_mailsvc

    ms = FakeMailServer({"student@test.local": "secret"})
    smtp, imap, _pop = await ms.start()
    monkeypatch.setenv("GLEANER_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("GLEANER_SMTP_PORT", str(smtp))
    monkeypatch.setenv("GLEANER_SMTP_INSECURE", "1")
    mail = await start_mailsvc(stack["cfg"], "mail-1")
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    try:
        async with HTTPClient() as c:
            r = await c.post(
                gw + "/api/auth/register",
                json_body={
                    "email": "jie2@test.edu",
                    "password": "password1",
                    "agree_privacy": True,
                },
            )
            auth = {"Authorization": f"Bearer {r.json()['token']}"}
            sid = (
                await c.post(gw + "/api/sources", json_body={"template": "moodle"}, headers=auth)
            ).json()["source"]["id"]
            await c.post(
                gw + f"/api/sources/{sid}/login",
                json_body={"username": "student", "password": "moodle123"},
                headers=auth,
            )

            async def assignments():
                f = (await c.get(gw + "/api/feed?kind=assignment", headers=auth)).json()
                return f["items"] if len(f["items"]) >= 7 else None

            items = await until(assignments, 20)
            lab2 = next(i for i in items if i["title"].startswith("实验二"))

            r = await c.post(
                gw + "/api/sources",
                json_body={
                    "type": "imap",
                    "endpoint": f"imap://127.0.0.1:{imap}",
                    "name": "学校邮箱",
                    "config": {"tls": False},
                },
                headers=auth,
            )
            mid = r.json()["source"]["id"]
            r = await c.post(
                gw + f"/api/sources/{mid}/login",
                json_body={"username": "student@test.local", "password": "bad"},
                headers=auth,
            )
            assert r.status == 401
            r = await c.post(
                gw + f"/api/sources/{mid}/login",
                json_body={"username": "student@test.local", "password": "secret"},
                headers=auth,
            )
            assert r.json()["ok"]
            await asyncio.sleep(1.0)  # 等 IDLE 建立

            # Moodle 提醒邮件（带作业链接）+ 一封普通邮件经 IDLE 秒级到达
            _, raw = build_message(
                OutgoingMail(
                    sender="noreply@moodle.test",
                    to=["student@test.local"],
                    subject="CS3105: 作业即将截止 - 实验二",
                    text=f"实验二即将截止。查看：{stack['moodle']}/mod/assign/view.php?id=1002",
                )
            )
            ms.deliver("student@test.local", raw)
            _, raw2 = build_message(
                OutgoingMail(
                    sender="office@school.edu",
                    to=["student@test.local"],
                    subject="关于下周三调课的通知",
                    text="下周三的课调整到周四，请于下周三下午3点前回复是否有冲突。",
                )
            )
            ms.deliver("student@test.local", raw2)

            async def merged():
                it = (await c.get(gw + f"/api/items/{lab2['id']}", headers=auth)).json()
                return it if "imap" in it["channels"] else None

            it = await until(merged, 15)
            assert set(it["channels"]) == {"imap", "moodle"}

            async def mail_item():
                f = (await c.get(gw + "/api/feed?kind=mail", headers=auth)).json()
                return f["items"] or None

            mails = await until(mail_item, 10)
            assert len(mails) == 1 and "调课" in mails[0]["title"]  # 提醒邮件被合并，没有多出一条
            assert mails[0]["deadline_at"]  # “下周三 … 下午3点” 被换算成具体时间

            # 经已连接邮箱发信，同一幂等键重复提交不会发出第二封
            body = {
                "to": ["teacher@school.edu"],
                "subject": "关于实验二的问题",
                "text": "老师您好",
                "attachments": [
                    {"filename": "截图.png", "content_b64": "iVBORw0KGgo=", "mime": "image/png"}
                ],
            }
            r1 = await c.post(
                gw + "/api/mail/send", json_body=body, headers={**auth, "Idempotency-Key": "mail-1"}
            )
            r2 = await c.post(
                gw + "/api/mail/send", json_body=body, headers={**auth, "Idempotency-Key": "mail-1"}
            )
            assert r1.json()["status"] == "sent", r1.text()
            assert r2.json()["duplicate"] and len(ms.sent) == 1
            assert b"filename" in ms.sent[0][2]
    finally:
        await mail.close()
        await ms.close()


async def test_local_agent_long_connection(stack, tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    monkeypatch.setenv("GLEANER_AGENT_STATE", str(tmp_path / "agent.json"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
    import gleaner_agent

    monkeypatch.setattr(gleaner_agent, "STATE_FILE", tmp_path / "agent.json")
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as c:
        r = await c.post(
            gw + "/api/auth/register",
            json_body={"email": "agent@test.edu", "password": "password1", "agree_privacy": True},
        )
        token = r.json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        # 校园网内才能访问的来源：标记 via_agent，由本地代理采集
        r = await c.post(
            gw + "/api/sources",
            json_body={
                "type": "web",
                "endpoint": stack["moodle"] + "/news/",
                "name": "内网通知",
                "private": True,
                "via_agent": True,
                "config": {"item_selector": "ul.news-list li", "detail_selector": ".arti-content"},
            },
            headers=auth,
        )
        sid = r.json()["source"]["id"]
        agent = gleaner_agent.Agent(gw, token, "laptop-test")
        task = asyncio.create_task(agent.run_forever())

        async def got_items():
            f = (await c.get(gw + "/api/feed", headers=auth)).json()
            return f["items"] if sum(i["source_id"] == sid for i in f["items"]) >= 4 else None

        items = await until(got_items, 20)
        assert len([i for i in items if i["source_id"] == sid]) == 4
        r = await c.post(gw + f"/api/sources/{sid}/refresh", headers=auth)
        assert r.json()["via_agent"]
        task.cancel()


async def test_register_requires_email_code(stack, monkeypatch):
    import re

    from fake_mail.server import FakeMailServer

    from gleaner.net.mail import parse_mail

    ms = FakeMailServer({"noreply@gleaner.test": "pw"})
    smtp, _, _ = await ms.start()
    monkeypatch.setenv("GLEANER_REQUIRE_EMAIL_CODE", "1")
    monkeypatch.setenv("GLEANER_PLATFORM_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("GLEANER_PLATFORM_SMTP_PORT", str(smtp))
    monkeypatch.setenv("GLEANER_PLATFORM_SMTP_USER", "noreply@gleaner.test")
    monkeypatch.setenv("GLEANER_PLATFORM_SMTP_PASS", "pw")
    monkeypatch.setenv("GLEANER_SMTP_INSECURE", "1")
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    email = "newbie@any-mail.com"
    try:
        async with HTTPClient() as c:
            body = {"email": email, "password": "password1", "agree_privacy": True}
            r = await c.post(gw + "/api/auth/register", json_body=body)
            assert r.status == 422 and r.json()["error"] == "bad_code"
            r = await c.post(gw + "/api/auth/code", json_body={"email": email})
            assert r.json()["ok"], r.text()
            # 60 秒内重复获取被拒绝
            r2 = await c.post(gw + "/api/auth/code", json_body={"email": email})
            assert r2.status == 429 and r2.headers.get("Retry-After")
            _sender, rcpts, raw = ms.sent[-1]
            assert rcpts == [email]
            code = re.search(r"(\d{6})", parse_mail(raw).subject).group(1)
            wrong = "000000" if code != "000000" else "111111"
            r = await c.post(gw + "/api/auth/register", json_body={**body, "code": wrong})
            assert r.json()["message"] == "验证码不正确"
            r = await c.post(gw + "/api/auth/register", json_body={**body, "code": code})
            assert r.status == 201, r.text()
            # 验证码一次性
            r = await c.post(gw + "/api/auth/register", json_body={**body, "code": code})
            assert r.status == 409
    finally:
        await ms.close()


async def test_moodle_login_with_pasted_security_key(stack):
    """统一认证（CAS）学校用的登录方式：用户从 Moodle“偏好设置 → 安全密钥”复制密钥粘贴进来，拾课不经手密码。"""
    import requests

    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    s = requests.Session()
    s.trust_env = False
    # 用户在浏览器里登录 Moodle 后打开“安全密钥”页
    s.post(
        f"{stack['moodle']}/login/index.php",
        data={"username": "student", "password": "moodle123", "logintoken": "x"},
        timeout=5,
    )
    page = s.get(f"{stack['moodle']}/user/managetoken.php", timeout=5).text
    key = page.split("<code>")[1].split("</code>")[0]

    async with HTTPClient() as c:
        r = await c.post(
            gw + "/api/auth/register",
            json_body={
                "email": "key@test.edu",
                "password": "password1",
                "agree_privacy": True,
                "name": "小钥",
            },
        )
        auth = {"Authorization": f"Bearer {r.json()['token']}"}
        sid = (
            await c.post(gw + "/api/sources", json_body={"template": "moodle"}, headers=auth)
        ).json()["source"]["id"]
        login = gw + f"/api/sources/{sid}/login"

        r = await c.post(login, json_body={"token": "not-a-key"}, headers=auth)
        assert r.status == 422  # 格式不对，不发请求
        r = await c.post(login, json_body={"token": "0" * 32}, headers=auth)
        assert r.status == 401 and r.json()["error"] == "source_login_failed"  # 格式对但无效

        r = await c.post(login, json_body={"token": f"  {key}\n"}, headers=auth)
        assert r.json() == {"ok": True, "auth_type": "ws_token"}

        async def feed_ready():
            f = (await c.get(gw + "/api/feed?kind=assignment", headers=auth)).json()
            return f if len(f["items"]) >= 7 else None

        feed = await until(feed_ready, 20)
        assert all(i["source"]["id"] == sid for i in feed["items"])


async def test_browser_extension_clip_and_page_subscription(stack):
    """浏览器插件：保存当前页面到收件箱（同一网址再存记新版本）；订阅页面更新（整页监测）。"""
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    page_url = f"{stack['moodle']}/news/1.html"
    async with HTTPClient() as c:
        r = await c.post(
            gw + "/api/auth/register",
            json_body={
                "email": "clip@test.edu",
                "password": "password1",
                "agree_privacy": True,
                "name": "小藏",
            },
        )
        auth = {"Authorization": f"Bearer {r.json()['token']}"}
        # 先订阅学院通知：同一网页已经作为通知在收件箱里（compose 实测时插件保存被并进通知、正文丢失）
        await c.post(gw + "/api/sources", json_body={"template": "college_news"}, headers=auth)

        async def notice_ready():
            items = (await c.get(gw + "/api/feed", headers=auth)).json()["items"]
            return [i for i in items if i["url"].endswith("/news/1.html")]

        await until(notice_ready, 20)

        clip = {"url": page_url, "title": "讲座通知", "text": "本周五下午三点在 A101 举行讲座。"}
        r = await c.post(gw + "/api/clips", json_body=clip, headers=auth)
        assert r.status == 201, r.text()
        first = r.json()
        assert first["ok"] and first["status"] == "new"

        r = await c.post(
            gw + "/api/clips",
            json_body={**clip, "text": "讲座改到 B202，时间不变。"},
            headers=auth,
        )
        assert r.json()["status"] == "changed" and r.json()["item_id"] == first["item_id"]
        versions = (
            await c.get(gw + f"/api/items/{first['item_id']}/versions", headers=auth)
        ).json()["versions"]
        assert len(versions) == 2

        r = await c.post(
            gw + "/api/clips", json_body={**clip, "url": "file:///etc/passwd"}, headers=auth
        )
        assert r.status == 422

        feed = (await c.get(gw + "/api/feed", headers=auth)).json()["items"]
        saved = [i for i in feed if i["id"] == first["item_id"]]
        assert (
            saved
            and saved[0]["kind"] == "clip"
            and "B202" in saved[0]["summary"] + saved[0]["title"] + str(saved[0].get("body", ""))
        )
        sources = (await c.get(gw + "/api/sources", headers=auth)).json()["sources"]
        assert [s["type"] for s in sources if s["id"] == saved[0]["source"]["id"]] == ["clip"]

        # 订阅更新：整页监测
        r = await c.post(
            gw + "/api/sources",
            json_body={
                "type": "web",
                "endpoint": page_url,
                "name": "讲座页",
                "config": {"mode": "page"},
            },
            headers=auth,
        )
        assert r.status == 201, r.text()
        sid = r.json()["source"]["id"]
        await c.post(gw + f"/api/sources/{sid}/refresh", headers=auth)

        async def page_item():
            items = (await c.get(gw + "/api/feed", headers=auth)).json()["items"]
            return [i for i in items if i["source"]["id"] == sid]

        got = await until(page_item, 20)
        assert len(got) == 1 and got[0]["kind"] == "page" and got[0]["url"]

        # 页面内容变化 → 同一事项出现新版本（不能被当成重复，也不能并进学院通知那条）
        with fm.STATE.lock:
            fm.STATE.notices[0].body += "（地点改到 B202）"
        await c.post(gw + f"/api/sources/{sid}/refresh", headers=auth)

        async def page_changed():
            v = (await c.get(gw + f"/api/items/{got[0]['id']}/versions", headers=auth)).json()[
                "versions"
            ]
            return v if len(v) >= 2 else None

        await until(page_changed, 20)
