"""REST API 的健壮性与安全（docs/review-2026-11.md 第 1、2 批）。"""

# ruff: noqa: F811  （stack 是从 test_e2e 导入的 pytest fixture，作为参数名使用）

import json
import re
import time
from pathlib import Path

from test_e2e import stack, until  # noqa: F401

from gleaner.net.http import HTTPClient


def gw_of(stack) -> str:
    return f"http://127.0.0.1:{stack['gw'].info['port']}"


async def register(c: HTTPClient, gw: str, email: str, pw: str = "password1") -> dict:
    r = await c.post(
        gw + "/api/auth/register",
        json_body={"email": email, "password": pw, "agree_privacy": True},
    )
    assert r.status == 201, r.text()
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_malformed_input_is_4xx_and_never_ejects_core(stack):
    """坏 JSON、非对象请求体、非数字 id、越界参数都应是 4xx；网关不能因此把 core 摘除。"""
    gw = gw_of(stack)
    async with HTTPClient() as c:
        auth = await register(c, gw, "robust@test.edu")
        for _ in range(8):  # 比被动摘除阈值（连续 5 次）多
            r = await c.post(
                gw + "/api/auth/login",
                body=b"{",
                headers={"Content-Type": "application/json"},
            )
            assert r.status == 400 and r.json()["error"] == "bad_json"
        r = await c.post(gw + "/api/auth/login", json_body=[1, 2])
        assert r.status == 400 and r.json()["error"] == "bad_body"
        assert (await c.get(gw + "/api/items/abc", headers=auth)).status == 404
        assert (await c.get(gw + "/api/feed?limit=0", headers=auth)).status == 422
        assert (await c.get(gw + "/api/feed?limit=x", headers=auth)).status == 422
        assert (await c.get(gw + "/api/feed?cursor=bad", headers=auth)).json()[
            "error"
        ] == "bad_cursor"
        assert (await c.get(gw + "/api/feed?kind=evil", headers=auth)).status == 422
        assert (await c.get(gw + "/api/deadlines?from=nan", headers=auth)).status == 422
        r = await c.request(
            "PUT", gw + "/api/sources/1", headers=auth, json_body={"weight": "heavy"}
        )
        assert r.status in (404, 422)
        r = await c.post(
            gw + "/api/sources", headers=auth, json_body={"type": "web", "endpoint": "ftp://x"}
        )
        assert r.status == 422 and r.json()["error"] == "bad_endpoint"
        r = await c.post(
            gw + "/api/sources",
            headers=auth,
            json_body={"type": "web", "endpoint": "http://x/", "config": "a"},
        )
        assert r.status == 422
        # 网关仍然把请求转给 core（没有因为上面的 4xx 摘除节点）
        assert (await c.get(gw + "/api/me", headers=auth)).status == 200
        # 搜索里的 % 不当通配符
        assert (await c.get(gw + "/api/feed?q=%25", headers=auth)).json()["items"] == []


async def test_state_batch_isolates_bad_ops_and_idempotency(stack):
    gw = gw_of(stack)
    async with HTTPClient() as c:
        auth = await register(c, gw, "batch@test.edu")
        r = await c.post(gw + "/api/sources", headers=auth, json_body={"template": "college_news"})
        assert r.status == 201

        async def first_item():
            items = (await c.get(gw + "/api/feed", headers=auth)).json()["items"]
            return items[0]["id"] if items else None

        iid = await until(first_item, 20)
        ops = [
            "not-an-op",
            {"op_id": "a1", "item_id": "x", "read": True},
            {"op_id": "a2", "item_id": iid, "todo": "maybe"},
            {
                "op_id": "a3",
                "item_id": iid,
                "starred": True,
                "ts": 1e12,
            },  # 未来时间会被夹到“现在 + 5 分钟”
            {
                "op_id": "a4",
                "item_id": iid,
                "read": True,
                "ts": 1e12,
            },  # 同样夹到“现在 + 5 分钟”，不算旧操作
        ]
        r = await c.post(gw + "/api/state/batch", headers=auth, json_body={"ops": ops})
        res = r.json()["results"]
        assert [x["status"] for x in res] == [422, 422, 422, 200, 200]
        assert res[4]["state"]["read"] is True and res[3]["state"]["starred"] is True
        assert r.json()["truncated"] is False
        # 同一个幂等键：相同内容返回 duplicate，不同内容 422
        r = await c.request(
            "PUT",
            gw + f"/api/items/{iid}/state",
            headers={**auth, "Idempotency-Key": "a4"},
            json_body={"read": True},
        )
        assert r.json()["duplicate"]
        r = await c.request(
            "PUT",
            gw + f"/api/items/{iid}/state",
            headers={**auth, "Idempotency-Key": "a4"},
            json_body={"starred": False},
        )
        assert r.status == 422 and r.json()["error"] == "idempotency_mismatch"
        # 别人私有来源里的事项：feedback 与状态都按不存在处理
        import requests

        key = requests.post(
            f"{stack['moodle']}/login/token.php",
            data={"username": "student", "password": "moodle123", "service": "moodle_mobile_app"},
            timeout=5,
        ).json()["token"]
        r = await c.post(gw + "/api/sources", headers=auth, json_body={"template": "moodle"})
        psid = r.json()["source"]["id"]
        r = await c.post(gw + f"/api/sources/{psid}/login", headers=auth, json_body={"token": key})
        assert r.json()["ok"], r.text()

        async def private_item():
            items = (await c.get(gw + "/api/feed", headers=auth)).json()["items"]
            return next((i["id"] for i in items if i["source"]["id"] == psid), None)

        pid = await until(private_item, 20)
        other = await register(c, gw, "other@test.edu")
        assert (await c.post(gw + f"/api/items/{pid}/feedback", headers=other)).status == 404
        r = await c.request(
            "PUT", gw + f"/api/items/{pid}/state", headers=other, json_body={"read": True}
        )
        assert r.status == 404


async def test_ssrf_blocked_when_private_addresses_not_allowed(stack, monkeypatch):
    gw = gw_of(stack)
    async with HTTPClient() as c:
        auth = await register(c, gw, "ssrf@test.edu")
        monkeypatch.setenv("GLEANER_EGRESS_ALLOW_PRIVATE", "0")
        core_port = stack["core"].info["port"]
        for url in (
            f"http://127.0.0.1:{core_port}/api/stats",
            "http://169.254.169.254/latest/meta-data/",
            f"http://localhost:{core_port}/",
        ):
            r = await c.post(
                gw + "/api/sources/preview",
                headers=auth,
                json_body={"type": "web", "endpoint": url},
            )
            assert r.status == 422 and r.json()["error"] == "fetch_blocked", (url, r.text())
        # 按主机名放行（compose 里的 fake_moodle 就是这样放行的）
        monkeypatch.setenv("GLEANER_EGRESS_ALLOW_HOSTS", "127.0.0.1")
        r = await c.post(
            gw + "/api/sources/preview",
            headers=auth,
            json_body={"type": "rss", "endpoint": f"{stack['moodle']}/news/rss.xml"},
        )
        assert r.json()["ok"], r.text()


async def test_login_throttle_sessions_and_password_change(stack):
    gw = gw_of(stack)
    async with HTTPClient() as c:
        await register(c, gw, "sess@test.edu")
        login = {"email": "sess@test.edu", "password": "password1"}
        t1 = (await c.post(gw + "/api/auth/login", json_body=login)).json()["token"]
        t2 = (await c.post(gw + "/api/auth/login", json_body=login)).json()["token"]
        a1, a2 = ({"Authorization": f"Bearer {t}"} for t in (t1, t2))
        sessions = (await c.get(gw + "/api/me/sessions", headers=a1)).json()["sessions"]
        assert len(sessions) == 3 and sum(s["current"] for s in sessions) == 1
        # 退出当前设备只吊销这一个会话
        await c.post(gw + "/api/auth/logout", headers=a1, json_body={})
        assert (await c.get(gw + "/api/me", headers=a1)).status == 401
        assert (await c.get(gw + "/api/me", headers=a2)).status == 200
        # 吊销指定会话
        other = next(
            s
            for s in (await c.get(gw + "/api/me/sessions", headers=a2)).json()["sessions"]
            if not s["current"]
        )
        assert (
            await c.request("DELETE", gw + f"/api/me/sessions/{other['id']}", headers=a2)
        ).status == 200
        # 改密码：旧密码错 403；成功后其他设备全部失效，返回的新令牌可用
        r = await c.request(
            "PUT",
            gw + "/api/me/password",
            headers=a2,
            json_body={"old_password": "x" * 8, "new_password": "newpass99"},
        )
        assert r.status == 403
        r = await c.request(
            "PUT",
            gw + "/api/me/password",
            headers=a2,
            json_body={"old_password": "password1", "new_password": "newpass99"},
        )
        assert r.status == 200
        a3 = {"Authorization": f"Bearer {r.json()['token']}"}
        assert (await c.get(gw + "/api/me", headers=a2)).status == 401
        assert (await c.get(gw + "/api/me", headers=a3)).status == 200
        # 防爆破：同一邮箱连续失败后 429，封禁期内正确密码也不行
        bad = {"email": "sess@test.edu", "password": "wrong-pass"}
        codes = [(await c.post(gw + "/api/auth/login", json_body=bad)).status for _ in range(6)]
        assert codes[:5] == [401] * 5 and codes[5] == 429
        r = await c.post(
            gw + "/api/auth/login", json_body={"email": "sess@test.edu", "password": "newpass99"}
        )
        assert r.status == 429 and int(r.headers["Retry-After"]) > 0
        # 不存在的邮箱同样只返回 401（不泄露是否注册）
        r = await c.post(
            gw + "/api/auth/login", json_body={"email": "nobody@test.edu", "password": "whatever1"}
        )
        assert r.status == 401


async def test_password_reset_by_email_code(stack, monkeypatch):
    from fake_mail.server import FakeMailServer

    from gleaner.net.mail import parse_mail

    ms = FakeMailServer({"noreply@gleaner.test": "pw"})
    smtp, _, _ = await ms.start()
    monkeypatch.setenv("GLEANER_PLATFORM_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("GLEANER_PLATFORM_SMTP_PORT", str(smtp))
    monkeypatch.setenv("GLEANER_PLATFORM_SMTP_USER", "noreply@gleaner.test")
    monkeypatch.setenv("GLEANER_PLATFORM_SMTP_PASS", "pw")
    monkeypatch.setenv("GLEANER_SMTP_INSECURE", "1")
    gw = gw_of(stack)
    try:
        async with HTTPClient() as c:
            old = await register(c, gw, "forgot@test.edu")
            # 未注册的邮箱也返回成功（不泄露注册情况），但不发信
            r = await c.post(gw + "/api/auth/reset/code", json_body={"email": "ghost@test.edu"})
            assert r.json()["ok"] and not ms.sent
            r = await c.post(gw + "/api/auth/reset/code", json_body={"email": "forgot@test.edu"})
            assert r.json()["ok"], r.text()
            code = re.search(r"(\d{6})", parse_mail(ms.sent[-1][2]).subject).group(1)
            body = {"email": "forgot@test.edu", "new_password": "resetpass1"}
            r = await c.post(
                gw + "/api/auth/reset",
                json_body={**body, "code": "000000" if code != "000000" else "111111"},
            )
            assert r.status == 422
            r = await c.post(gw + "/api/auth/reset", json_body={**body, "code": code})
            assert r.status == 200, r.text()
            assert (await c.get(gw + "/api/me", headers=old)).status == 401  # 旧会话失效
            r = await c.post(
                gw + "/api/auth/login",
                json_body={"email": "forgot@test.edu", "password": "resetpass1"},
            )
            assert r.status == 200
    finally:
        await ms.close()


async def test_shared_source_controls_csrf_and_stats(stack, monkeypatch):
    gw = gw_of(stack)
    async with HTTPClient() as c:
        auth = await register(c, gw, "shared@test.edu")
        sid = (
            await c.post(gw + "/api/sources", headers=auth, json_body={"template": "college_news"})
        ).json()["source"]["id"]
        # 公共来源不能“登录”（否则可以借此重置大家共用来源的采集状态）
        r = await c.post(
            gw + f"/api/sources/{sid}/login",
            headers=auth,
            json_body={"username": "a", "password": "b"},
        )
        assert r.status == 422 and r.json()["error"] == "no_login"
        # 立即检查 60 秒冷却
        assert (await c.post(gw + f"/api/sources/{sid}/refresh", headers=auth)).status == 200
        r = await c.post(gw + f"/api/sources/{sid}/refresh", headers=auth)
        assert r.status == 429 and r.headers.get("Retry-After")
        # 只凭 Cookie 的修改请求：非 JSON 请求体 415；无请求体且跨站 403；同源允许
        token = auth["Authorization"][7:]
        cookie = {"Cookie": f"gl_session={token}"}
        r = await c.request(
            "PUT",
            gw + "/api/me",
            headers={**cookie, "Content-Type": "text/plain"},
            body=b'{"name":"x"}',
        )
        assert r.status == 415
        r = await c.post(
            gw + "/api/auth/logout", headers={**cookie, "Origin": "https://evil.example"}
        )
        assert r.status == 403
        host = gw.split("://", 1)[1]
        r = await c.request(
            "PUT",
            gw + "/api/me",
            headers={**cookie, "Origin": f"http://{host}"},
            json_body={"name": "同源"},
        )
        assert r.status == 200 and r.json()["name"] == "同源"
        # 运营统计需要管理令牌
        assert (await c.get(gw + "/api/stats")).status == 403
        monkeypatch.setenv("GLEANER_ADMIN_TOKEN", "admin-secret")
        r = await c.get(gw + "/api/stats", headers={"X-Admin-Token": "admin-secret"})
        assert r.status == 200 and r.json()["users"] >= 1


async def test_mail_header_injection_rejected(stack):
    gw = gw_of(stack)
    async with HTTPClient() as c:
        auth = await register(c, gw, "mailer@test.edu")
        base = {"to": ["teacher@school.edu"], "subject": "hi", "text": "x"}
        for bad in (
            {"cc": ["a@b.c\r\nRCPT TO:<x@y.z>"]},
            {"to": ["teacher@school.edu\nBcc: z@z.z"]},
            {
                "attachments": [
                    {"filename": "a.txt", "content_b64": "aGk=", "mime": "text/plain\r\nX: y"}
                ]
            },
            {"attachments": [{"filename": "a.txt", "content_b64": "%%%"}]},
        ):
            r = await c.post(
                gw + "/api/mail/send",
                headers={**auth, "Idempotency-Key": f"k{time.time()}"},
                json_body={**base, **bad},
            )
            assert r.status == 422, (bad, r.text())


async def test_delete_account_requires_password_and_removes_files(stack):
    gw = gw_of(stack)
    data_dir = Path(stack["cfg"].data_dir)
    async with HTTPClient() as c:
        auth = await register(c, gw, "bye@test.edu")
        t = (await c.post(gw + "/api/transfer", headers=auth)).json()
        r = await c.post(
            gw + f"/api/transfer/{t['code']}/files",
            headers=auth,
            json_body={"name": "a.bin", "size": 3, "sha256": "0" * 64},
        )
        assert r.status == 201
        tdir = data_dir / "transfers" / str(t["id"])
        assert tdir.exists()
        # 配对码只能用一次
        assert (await c.post(gw + f"/api/transfer/{t['code']}/join", json_body={})).status == 200
        assert (await c.post(gw + f"/api/transfer/{t['code']}/join", json_body={})).status == 409
        assert (
            await c.request(
                "DELETE", gw + "/api/account", headers=auth, json_body={"password": "nope-nope"}
            )
        ).status == 403
        r = await c.request(
            "DELETE", gw + "/api/account", headers=auth, json_body={"password": "password1"}
        )
        assert r.json()["deleted"]
        assert not tdir.exists()
        assert (await c.get(gw + "/api/me", headers=auth)).status == 401
        r = await c.post(
            gw + "/api/auth/login", json_body={"email": "bye@test.edu", "password": "password1"}
        )
        assert r.status == 401


def test_throttle_backoff_doubles():
    from gleaner.core.throttle import Throttle

    t = Throttle(limit=2, window=60, base_block=10, max_block=25)
    assert t.hit("k", now=0) == 0 and t.hit("k", now=1) == 0
    assert t.hit("k", now=2) == 10 and t.retry_after("k", now=5) == 7
    assert t.hit("k", now=20) == 0 and t.hit("k", now=21) == 0 and t.hit("k", now=22) == 20
    assert t.hit("k", now=100) == 0 and t.hit("k", now=101) == 0 and t.hit("k", now=102) == 25


def test_egress_classification():
    from gleaner.net.egress import is_public

    for ip in (
        "127.0.0.1",
        "10.0.0.5",
        "172.18.0.7",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "0.0.0.0",
    ):
        assert not is_public(ip), ip
    for ip in ("8.8.8.8", "202.175.1.1", "2001:4860:4860::8888"):
        assert is_public(ip), ip


def test_validators():
    import pytest

    from gleaner.core.validate import BadRequest, as_float, as_int

    assert as_int("5", "x", lo=1, hi=10) == 5
    for bad in ("x", True, 1.5, None):
        with pytest.raises(BadRequest):
            as_int(bad, "x")
    assert as_float(5, "x", lo=0, hi=1, clamp=True) == 1
    for bad in ("nan", "inf", float("nan")):
        with pytest.raises(BadRequest):
            as_float(bad, "x")
    assert json.loads(BadRequest(422, "m", "c").response().body) == {"error": "c", "message": "m"}


async def test_put_rules_is_atomic_and_validated(stack):
    gw = gw_of(stack)
    async with HTTPClient() as c:
        auth = await register(c, gw, "rules@test.edu")
        good = [
            {"kind": "keyword", "pattern": "考试", "boost": 0.8},
            {"kind": "sender", "pattern": "dean@x.edu"},
        ]
        r = await c.request("PUT", gw + "/api/rules", headers=auth, json_body={"rules": good})
        assert r.status == 200 and len(r.json()["rules"]) == 2
        # 非法规则整批拒绝，原有规则保持不变
        r = await c.request(
            "PUT",
            gw + "/api/rules",
            headers=auth,
            json_body={"rules": [{"kind": "evil", "pattern": "x"}]},
        )
        assert r.status == 422
        assert len((await c.get(gw + "/api/rules", headers=auth)).json()["rules"]) == 2


async def test_refresh_without_collector_says_so(stack):
    """BUS-7：没有在线采集节点时“立即检查”如实告诉用户只是排队（202，checking=false），而不是假装在查。

    不用 503：网关会把上游 503 计入被动健康检查，把 core 摘除。"""
    gw = gw_of(stack)
    api = stack["core"].info["api"]
    async with HTTPClient() as c:
        auth = await register(c, gw, "nocollector@test.edu")
        sid = (
            await c.post(gw + "/api/sources", headers=auth, json_body={"template": "college_rss"})
        ).json()["source"]["id"]
        assert stack["core"].info["hub"].live_nodes("collector")
        assert api.collectors_online() >= 1
        online = api.collectors_online
        api.collectors_online = lambda: 0
        try:
            r = await c.post(gw + f"/api/sources/{sid}/refresh", headers=auth)
            assert r.status == 202 and r.json()["checking"] is False and r.json()["message"]
            r = await c.get(gw + "/api/sources", headers=auth)  # 网关没有因此摘除 core
            assert r.status == 200
        finally:
            api.collectors_online = online
