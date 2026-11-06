"""插件批量采集、三类事项与状态、用户修改与冲突、事项级监测（IC-001、IC-002，决策 D19–D23）。"""

# ruff: noqa: F811  （stack 是从 test_e2e 导入的 pytest fixture，作为参数名使用）

import time

from test_api import gw_of, register
from test_e2e import stack  # noqa: F401

from gleaner.net.http import HTTPClient
from gleaner.storage.db import Database

PAGE = "https://moodle.test.edu/course/view.php?id=7"


def cap(locator: str, title: str, **extra) -> dict:
    return {"locator": locator, "title": title, "text": extra.pop("text", ""), **extra}


async def save(c: HTTPClient, gw: str, auth: dict, items: list, url: str = PAGE):
    return await c.post(
        gw + "/api/captures",
        headers=auth,
        json_body={"page": {"url": url, "title": "课程 7", "platform": "moodle"}, "items": items},
    )


async def item(c: HTTPClient, gw: str, auth: dict, iid: int) -> dict:
    r = await c.get(gw + f"/api/items/{iid}", headers=auth)
    assert r.status == 200, r.text()
    return r.json()


async def test_capture_batch_identity_and_partial_failure(stack):
    """同页多条事项各自独立；同一定位符再保存不新建；一条坏数据不影响其他条，也不虚报成功。"""
    gw = gw_of(stack)
    async with HTTPClient() as c:
        auth = await register(c, gw, "cap1@test.edu")
        # 两条链接和标题都相同、只有定位符不同：仍是两条事项
        r = await save(c, gw, auth, [cap("cmid:1", "讨论区公告"), cap("cmid:2", "讨论区公告")])
        assert r.status == 200, r.text()
        body = r.json()
        assert body["ok"] and body["saved"] == 2 and body["failed"] == 0
        a, b = (x["item_id"] for x in body["results"])
        assert a and b and a != b
        assert [x["status"] for x in body["results"]] == ["new", "new"]

        # 再保存：一条没变、一条正文变了、一条标题为空（只有这一条失败）
        r = await save(
            c,
            gw,
            auth,
            [
                cap("cmid:1", "讨论区公告"),
                cap("cmid:2", "讨论区公告", text="新增：下周一停课"),
                cap("cmid:3", "   "),
            ],
        )
        body = r.json()
        assert r.status == 200 and body["ok"] is False
        assert body["saved"] == 2 and body["failed"] == 1
        st = {x["locator"]: x for x in body["results"]}
        assert st["cmid:1"]["status"] == "unchanged" and st["cmid:1"]["item_id"] == a
        assert st["cmid:2"]["status"] == "changed" and st["cmid:2"]["item_id"] == b
        assert st["cmid:3"]["status"] == "error" and st["cmid:3"]["item_id"] is None
        assert st["cmid:3"]["error"]["code"] == "invalid"
        assert (await item(c, gw, auth, b))["version"] == 2

        # 事项记录来源页面与定位符，可以返回原页面
        it = await item(c, gw, auth, a)
        assert it["origin"] == "capture" and it["page_url"] == PAGE and it["locator"] == "cmid:1"

        # 只有勾选的条目被保存
        feed = (await c.get(gw + "/api/feed?origin=capture", headers=auth)).json()["items"]
        assert sorted(x["id"] for x in feed) == sorted([a, b])

        # 另一位同学保存同一页面：各存一份，互不可见
        auth2 = await register(c, gw, "cap2@test.edu")
        r = await save(c, gw, auth2, [cap("cmid:1", "讨论区公告")])
        other = r.json()["results"][0]["item_id"]
        assert other not in (a, b)
        assert (await c.get(gw + f"/api/items/{a}", headers=auth2)).status == 404


async def test_capture_rejects_bad_batch_without_saving(stack):
    gw = gw_of(stack)
    async with HTTPClient() as c:
        auth = await register(c, gw, "cap3@test.edu")
        assert (await save(c, gw, {}, [cap("a", "x")])).status == 401
        bad = [
            (await save(c, gw, auth, [cap("a", "x")], url="file:///etc/passwd")),
            (await save(c, gw, auth, [])),
            (await save(c, gw, auth, [cap("a", "x"), cap("a", "y")])),
            (await save(c, gw, auth, [{"title": "没有定位符"}])),
            (await save(c, gw, auth, [cap(f"l{i}", "x") for i in range(51)])),
            (await save(c, gw, auth, ["not an object"])),
        ]
        assert [r.status for r in bad] == [422] * 6
        r = await c.post(gw + "/api/captures", headers=auth, json_body={"items": []})
        assert r.status == 422
        # 字段类型不对只影响这一条
        r = await save(
            c,
            gw,
            auth,
            [
                cap("ok", "正常"),
                cap("t", "坏类型", type="homework"),
                cap("d", "坏时间", fields={"deadline_at": "tomorrow"}),
                cap("u", "坏链接", url="javascript:alert(1)"),
            ],
        )
        res = r.json()["results"]
        assert [x["status"] for x in res] == ["new", "error", "error", "error"]
        feed = (await c.get(gw + "/api/feed", headers=auth)).json()["items"]
        assert [x["title"] for x in feed] == ["正常"]


async def test_three_types_states_and_filters(stack):
    gw = gw_of(stack)
    now = time.time()
    async with HTTPClient() as c:
        auth = await register(c, gw, "types@test.edu")
        r = await save(
            c,
            gw,
            auth,
            [
                cap("hw", "作业一", fields={"deadline_at": now + 86400 * 3}),
                cap("talk", "讲座", fields={"start_at": now + 86400, "location": "N101"}),
                cap("news", "教学调整"),
                cap("hint", "插件判定为日程", type="event"),
            ],
        )
        ids = {x["locator"]: x["item_id"] for x in r.json()["results"]}
        assert [x["type"] for x in r.json()["results"]] == ["todo", "event", "notice", "event"]
        talk = await item(c, gw, auth, ids["talk"])
        assert talk["location"] == "N101" and talk["status"] == "active"

        async def ids_of(q: str) -> set:
            r = await c.get(gw + "/api/feed?" + q, headers=auth)
            assert r.status == 200, r.text()
            return {x["id"] for x in r.json()["items"]}

        assert await ids_of("type=todo") == {ids["hw"]}
        assert await ids_of("type=event") == {ids["talk"], ids["hint"]}
        assert await ids_of("status=unread") == {ids["news"]}
        assert await ids_of("status=open") == {ids["hw"]}

        async def put(iid: int, body: dict):
            r = await c.request("PUT", gw + f"/api/items/{iid}/state", headers=auth, json_body=body)
            assert r.status == 200, r.text()
            return r.json()

        await put(ids["hw"], {"done": True})
        await put(ids["news"], {"read": True})
        res = await put(ids["talk"], {"archived": True})
        assert res["state"]["archived"] is True
        assert await ids_of("status=done") == {ids["hw"]}
        assert await ids_of("status=read") == {ids["news"]}
        assert await ids_of("type=event&status=archived") == {ids["talk"]}
        assert await ids_of("status=active") == {ids["hint"]}
        assert (await item(c, gw, auth, ids["hw"]))["status"] == "done"
        await put(ids["hw"], {"done": False})
        assert (await item(c, gw, auth, ids["hw"]))["status"] == "open"
        # 用户改类型后，筛选按修改后的类型
        r = await c.request(
            "PATCH",
            gw + f"/api/items/{ids['news']}/fields",
            headers=auth,
            json_body={"set": {"type": "todo"}},
        )
        assert r.status == 200 and r.json()["type"] == "todo" and r.json()["status"] == "open"
        assert await ids_of("type=todo") == {ids["hw"], ids["news"]}
        for q in ("type=x", "status=x", "origin=x"):
            assert (await c.get(gw + "/api/feed?" + q, headers=auth)).status == 422
        r = await c.request(
            "PUT", gw + f"/api/items/{ids['hw']}/state", headers=auth, json_body={"archived": "y"}
        )
        assert r.status == 422


async def test_user_edits_are_kept_apart_from_source_versions(stack):
    """来源更新不覆盖用户修改；改过之后来源又变了就标冲突，两边都返回，由用户选择。"""
    gw = gw_of(stack)
    async with HTTPClient() as c:
        auth = await register(c, gw, "edits@test.edu")
        r = await save(c, gw, auth, [cap("n1", "原标题", text="正文", fields={"location": "A1"})])
        iid = r.json()["results"][0]["item_id"]
        url = gw + f"/api/items/{iid}/fields"

        async def patch(body: dict):
            return await c.request("PATCH", url, headers=auth, json_body=body)

        r = await patch({"set": {"title": "我的标题", "deadline_at": None}})
        assert r.status == 200, r.text()
        it = r.json()
        assert it["title"] == "我的标题" and it["conflicts"] == []
        assert it["fields"]["title"] == {
            "value": "我的标题",
            "source": "原标题",
            "edited": True,
            "conflict": False,
        }
        assert it["fields"]["deadline_at"]["edited"] and it["deadline_at"] is None

        # 来源更新了标题和地点：用户的标题保留并标冲突；没改过的地点直接用来源的新值
        await save(c, gw, auth, [cap("n1", "来源新标题", text="正文", fields={"location": "B2"})])
        it = await item(c, gw, auth, iid)
        assert it["version"] == 2
        assert it["title"] == "我的标题" and it["fields"]["title"]["source"] == "来源新标题"
        assert it["conflicts"] == ["title"] and it["location"] == "B2"

        # 保留我的：冲突消失，值不变；来源再变又会冲突
        r = await c.post(
            url + "/resolve", headers=auth, json_body={"field": "title", "keep": "mine"}
        )
        assert r.status == 200 and r.json()["conflicts"] == [] and r.json()["title"] == "我的标题"
        r = await c.post(
            url + "/resolve", headers=auth, json_body={"field": "title", "keep": "mine"}
        )
        assert r.status == 409 and r.json()["error"] == "no_conflict"
        await save(c, gw, auth, [cap("n1", "第三版标题", text="正文", fields={"location": "B2"})])
        assert (await item(c, gw, auth, iid))["conflicts"] == ["title"]
        # 采用来源：修改被删除
        r = await c.post(
            url + "/resolve", headers=auth, json_body={"field": "title", "keep": "source"}
        )
        it = r.json()
        assert it["title"] == "第三版标题" and not it["fields"]["title"]["edited"]

        # 恢复来源值；版本历史里是来源内容，不含用户修改
        r = await patch({"reset": ["deadline_at"]})
        assert not r.json()["fields"]["deadline_at"]["edited"]
        vs = (await c.get(gw + f"/api/items/{iid}/versions", headers=auth)).json()["versions"]
        assert [v["snapshot"]["title"] for v in vs] == ["第三版标题", "来源新标题", "原标题"]
        assert vs[1]["snapshot"]["location"] == "B2" and vs[2]["snapshot"]["location"] == "A1"

        # 旧接口的截止时间覆盖仍然生效，并同步为用户修改
        r = await c.request(
            "PUT",
            gw + f"/api/items/{iid}/state",
            headers=auth,
            json_body={"deadline_override": 2e9},
        )
        assert r.status == 200
        it = await item(c, gw, auth, iid)
        assert it["deadline_at"] == 2e9 and it["fields"]["deadline_at"]["edited"]

        # 坏输入
        for body in (
            {},
            {"set": {"kind": "x"}},
            {"set": {"title": ""}},
            {"set": {"type": "homework"}},
            {"set": {"start_at": "soon"}},
            {"set": {"title": "x"}, "reset": ["title"]},
            {"reset": ["evil"]},
        ):
            assert (await patch(body)).status == 422, body
        r = await c.post(url + "/resolve", headers=auth, json_body={"field": "title", "keep": "x"})
        assert r.status == 422
        auth2 = await register(c, gw, "edits2@test.edu")
        r = await c.request("PATCH", url, headers=auth2, json_body={"set": {"title": "x"}})
        assert r.status == 404


async def test_item_monitoring_lease_results_and_failures(stack):
    """插件领取到期任务、回报结果：成功更新最后成功时间；失败只记原因，不显示成无变化。"""
    gw = gw_of(stack)
    db: Database = stack["core"].info["db"]
    async with HTTPClient() as c:
        auth = await register(c, gw, "mon@test.edu")
        r = await save(
            c,
            gw,
            auth,
            [
                cap("m1", "可监测通知", text="原文", monitor={"supported": True}),
                cap("m2", "不支持监测"),
            ],
        )
        res = r.json()["results"]
        assert [x["monitor"] for x in res] == ["enabled", "unsupported"]
        m1, m2 = res[0]["item_id"], res[1]["item_id"]
        it = await item(c, gw, auth, m1)
        assert it["monitor"]["status"] == "pending" and it["monitor"]["last_success_at"] is None
        assert (await item(c, gw, auth, m2))["monitor"]["status"] == "unsupported"
        r = await c.request(
            "PUT", gw + f"/api/items/{m2}/monitor", headers=auth, json_body={"enabled": True}
        )
        assert r.status == 409 and r.json()["error"] == "unsupported"

        # 还没到期：没有任务，告诉插件下次什么时候来
        due = (await c.get(gw + "/api/monitor/due", headers=auth)).json()
        assert due["tasks"] == [] and due["next_due_at"] > time.time()
        await db.execute("UPDATE item_monitors SET next_check_at = 0")
        due = (await c.get(gw + "/api/monitor/due", headers=auth)).json()
        assert [(t["item_id"], t["page_url"], t["locator"]) for t in due["tasks"]] == [
            (m1, PAGE, "m1")
        ]
        # 租期内不再发出
        assert (await c.get(gw + "/api/monitor/due", headers=auth)).json()["tasks"] == []

        async def report(entry: dict) -> dict:
            r = await c.post(
                gw + "/api/monitor/results", headers=auth, json_body={"results": [entry]}
            )
            assert r.status == 200, r.text()
            return r.json()["results"][0]

        out = await report({"item_id": m1, "ok": True, "title": "可监测通知", "text": "原文"})
        assert out["status"] == "unchanged" and out["last_success_at"]
        first_ok = out["last_success_at"]
        it = await item(c, gw, auth, m1)
        assert it["monitor"]["status"] == "unchanged" and it["version"] == 1

        out = await report(
            {"item_id": m1, "ok": True, "title": "可监测通知", "text": "截止改到周五"}
        )
        assert out["status"] == "changed"
        it = await item(c, gw, auth, m1)
        assert it["monitor"]["status"] == "changed" and it["version"] == 2

        # 登录过期：标为失败，最后成功时间不变
        await db.execute("UPDATE item_monitors SET last_success_at = ?", first_ok)
        out = await report(
            {"item_id": m1, "ok": False, "error": {"code": "auth_expired", "message": "请重新登录"}}
        )
        assert out["status"] == "failed" and out["last_success_at"] == first_ok
        mon = (await item(c, gw, auth, m1))["monitor"]
        assert mon["status"] == "failed" and mon["last_success_at"] == first_ok
        assert mon["error"] == {"code": "auth_expired", "message": "请重新登录"}
        # 失败后退避：下次检查往后推
        assert mon["next_check_at"] > time.time() + 3000

        # 无效回报逐条报错，不影响别的条目
        r = await c.post(
            gw + "/api/monitor/results",
            headers=auth,
            json_body={
                "results": [
                    {"item_id": m2, "ok": True, "title": "x"},
                    {"item_id": m1, "ok": False, "error": {"code": "weird"}},
                    {"item_id": m1, "ok": "yes"},
                    {"item_id": m1, "ok": True},
                    "bad",
                ]
            },
        )
        codes = [x.get("error", {}).get("code") for x in r.json()["results"]]
        assert codes == ["not_monitored", "invalid", "invalid", "invalid", "invalid"]
        assert (await c.post(gw + "/api/monitor/results", headers=auth, json_body={})).status == 422

        # 关闭监测后不再发任务；页面不再支持时自动停用
        r = await c.request(
            "PUT", gw + f"/api/items/{m1}/monitor", headers=auth, json_body={"enabled": False}
        )
        assert r.json()["monitor"]["status"] == "disabled"
        await db.execute("UPDATE item_monitors SET next_check_at = 0")
        assert (await c.get(gw + "/api/monitor/due", headers=auth)).json()["tasks"] == []
        await c.request(
            "PUT", gw + f"/api/items/{m1}/monitor", headers=auth, json_body={"enabled": True}
        )
        await report({"item_id": m1, "ok": False, "error": {"code": "unsupported"}})
        assert (await item(c, gw, auth, m1))["monitor"]["status"] == "unsupported"

        # 别人的事项不能领取或回报
        auth2 = await register(c, gw, "mon2@test.edu")
        r = await c.post(
            gw + "/api/monitor/results",
            headers=auth2,
            json_body={"results": [{"item_id": m1, "ok": True, "title": "x"}]},
        )
        assert r.json()["results"][0]["error"]["code"] == "not_monitored"


async def test_migration_backfills_types_and_deadline_overrides(db_url):
    url = db_url("m7.db")
    db = await Database(url).connect()
    uid = await db.insert("users", {"email": "m7@x.com", "password_hash": "x", "created_at": 0})
    sid = await db.insert(
        "sources", {"type": "web", "name": "w", "endpoint": "http://w/", "created_at": 0}
    )
    ids = {}
    for key, kind, deadline in (
        ("a", "assignment", None),
        ("n", "notice", None),
        ("d", "notice", 1.9e9),
    ):
        ids[key] = await db.insert(
            "items",
            {
                "source_id": sid,
                "identity_key": key,
                "kind": kind,
                "title": key,
                "deadline_at": deadline,
                "first_seen_at": 0,
                "updated_at": 0,
            },
        )
    await db.execute(
        "INSERT INTO user_item_state (user_id, item_id, deadline_override, updated_at) VALUES (?, ?, ?, 0)",
        uid,
        ids["d"],
        2.0e9,
    )
    # 模拟迁移 7 之前的旧库：清空回填结果和执行记录后重新连接
    await db.execute("UPDATE items SET item_type = ''")
    await db.execute("DELETE FROM user_item_edits")
    await db.execute("DELETE FROM schema_migrations WHERE version = 7")
    await db.close()
    db = await Database(url).connect()
    types = {r["identity_key"]: r["item_type"] for r in await db.fetch("SELECT * FROM items")}
    assert types == {"a": "todo", "n": "notice", "d": "todo"}
    e = await db.fetchone("SELECT * FROM user_item_edits WHERE item_id = ?", ids["d"])
    assert e and e["field"] == "deadline_at" and float(e["value"]) == 2.0e9
    assert float(e["base"]) == 1.9e9
    await db.close()
