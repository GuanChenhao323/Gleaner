"""New browser contract: selected entities, private ownership, leases and durable confirmation."""

import copy
import time

import pytest

from gleaner.core.monitors import BrowserMonitorService, ContractError
from gleaner.core.pipeline import Pipeline
from gleaner.storage.db import Database


def batch(request_id="request-1", entities=("notice:a", "notice:b")):
    return {
        "schema_version": 1,
        "request_id": request_id,
        "device_id": "device-a",
        "binding": {
            "adapter": "student",
            "origin": "http://localhost:8098",
            "account_key": "account-a",
        },
        "targets": [
            {
                "candidate_id": key,
                "entity_id": key,
                "locator": {
                    "url": "http://localhost:8098/portal#news",
                    "frame_url": "http://localhost:8098/portal#news",
                    "view": {},
                },
                "raw": {"title": key, "text": "报名材料要求，日期待确认。", "fields": {}},
                "recipe": {
                    "adapter": "student",
                    "version": 1,
                    "entity_id": key,
                    "url": "http://localhost:8098/portal#news",
                    "view": {},
                    "selector": '[data-notice-id="a"]',
                },
                "supported": True,
                "enabled": True,
            }
            for key in entities
        ],
    }


@pytest.fixture
async def service(tmp_path):
    db = await Database(f"sqlite:///{tmp_path / 'browser.db'}").connect()
    for i in (1, 2):
        await db.insert(
            "users",
            {
                "id": i,
                "email": f"u{i}@test.local",
                "password_hash": "unused",
                "created_at": time.time(),
            },
        )
    events = []

    async def route(topic, payload):
        events.append((topic, payload))

    svc = BrowserMonitorService(db, Pipeline(db, route))
    yield svc, db, events
    await db.close()


async def test_two_selected_same_url_and_durable_idempotency(service):
    svc, db, _ = service
    req = batch()
    first = await svc.capture(1, req)
    assert [r["status"] for r in first["results"]] == ["new", "new"]
    assert len({r["item_id"] for r in first["results"]}) == 2
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 2
    restarted = BrowserMonitorService(db, svc.pipeline)
    assert await restarted.capture(1, req) == first
    assert await restarted.request_result(1, req["request_id"]) == first
    req["targets"][0]["raw"]["text"] = "different payload"
    with pytest.raises(ContractError, match="idempotency_conflict"):
        await svc.capture(1, req)
    assert [r["status"] for r in (await svc.capture(1, batch("again")))["results"]] == [
        "unchanged",
        "unchanged",
    ]


async def test_extraction_snapshot_recipe_cannot_be_scheduled(service):
    svc, db, _ = service
    req = batch("snapshot-v2")
    for target in req["targets"]:
        target["recipe"].update(version=2, strategy="snapshot")
        target["recipe"].pop("selector")
        target.update(supported=False, enabled=False)
        target["raw"]["fields"] = {"published_text": "2026-01-02", "valid_until_text": "2026-01-10"}
    result = await svc.capture(1, req)
    assert [r["status"] for r in result["results"]] == ["new", "new"]
    assert await svc.capture(1, req) == result
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 2
    assert (await svc.claim(1, {"device_id": "device-a"}))["job"] is None
    with pytest.raises(ContractError, match="monitor_unsupported"):
        await svc.control(1, result["results"][0]["monitor_id"], {"revision": 1, "enabled": True})
    req["request_id"] = "unsafe-v2"
    req["targets"][0]["supported"] = True
    assert (await svc.capture(1, req))["results"][0]["error"] == "snapshot_monitor_unsupported"


async def test_user_account_view_isolation_and_partial_validation(service):
    svc, _db, _ = service
    a = await svc.capture(1, batch())
    b = await svc.capture(2, batch())
    assert a["results"][0]["item_id"] != b["results"][0]["item_id"]
    req = batch("new-account")
    req["binding"]["account_key"] = "account-b"
    c = await svc.capture(1, req)
    assert c["results"][0]["item_id"] != a["results"][0]["item_id"]
    req = batch("week-2")
    req["targets"][0]["locator"]["view"] = {"week": "2"}
    req["targets"][0]["recipe"]["view"] = {"week": "2"}
    assert (await svc.capture(1, req))["results"][0]["item_id"] != a["results"][0]["item_id"]
    req = batch("partial")
    req["targets"][1]["raw"]["text"] = "x" * 20001
    assert [r["status"] for r in (await svc.capture(1, req))["results"]] == ["unchanged", "failed"]
    assert len((await svc.monitors(2))["monitors"]) == 2
    with pytest.raises(ContractError):
        await svc.control(2, a["results"][0]["monitor_id"], {"revision": 1, "enabled": False})


async def test_claim_change_replay_failure_preserves_baseline_and_user_edits(service):
    svc, db, events = service
    first = await svc.capture(1, batch(entities=("notice:a",)))
    mid = first["results"][0]["monitor_id"]
    iid = first["results"][0]["item_id"]
    assert (await svc.monitors(1))["monitors"][0]["last_result"] == "not_executed"
    job = (await svc.claim(1, {"device_id": "device-a"}))["job"]
    assert job and (await svc.claim(1, {"device_id": "device-a"}))["job"] is None
    await db.execute(
        "UPDATE user_item_state SET note = ?, deadline_override = ? WHERE user_id = 1 AND item_id = ?",
        "我的修正",
        2000000000,
        iid,
    )
    result = {
        "schema_version": 1,
        "device_id": "device-a",
        "lease": job["lease"],
        "revision": job["revision"],
        "status": "success",
        "account_key": "account-a",
        "raw": {"title": "notice:a", "text": "材料要求改为两份。", "fields": {}},
    }
    ack = await svc.result(1, job["id"], result)
    assert ack["status"] == "changed"
    assert await svc.result(1, job["id"], result) == ack
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", iid) == 2
    state = await db.fetchone(
        "SELECT note, deadline_override FROM user_item_state WHERE item_id = ?", iid
    )
    assert state == {"note": "我的修正", "deadline_override": 2000000000}
    before = (await svc.monitors(1))["monitors"][0]
    await db.execute("UPDATE browser_monitors SET next_at = 0 WHERE id = ?", mid)
    await db.execute("UPDATE browser_jobs SET claimed_at = 0")
    job2 = (await svc.claim(1, {"device_id": "device-a"}))["job"]
    failed = {**result, "lease": job2["lease"], "status": "need_login"}
    failed.pop("raw")
    await svc.result(1, job2["id"], failed)
    after = (await svc.monitors(1))["monitors"][0]
    assert after["last_success_at"] == before["last_success_at"]
    assert await db.fetchval("SELECT body FROM items WHERE id = ?", iid) == "材料要求改为两份。"
    assert any(m["type"] == "change" for _, m in events)
    assert len((await svc.checks(1, mid))["checks"]) == 2


async def test_revocation_expiry_account_switch_and_no_guessed_timetable_date(service):
    svc, db, _ = service
    req = batch(entities=("timetable:course-1",))
    req["targets"][0]["raw"]["fields"] = {
        "subtype": "timetable",
        "semester": "2026秋",
        "week": "2",
        "period": "3-4",
        "weekday": "周五",
    }
    first = await svc.capture(1, req)
    mid = first["results"][0]["monitor_id"]
    iid = first["results"][0]["item_id"]
    assert await db.fetchval("SELECT deadline_at FROM items WHERE id = ?", iid) is None
    job = (await svc.claim(1, {"device_id": "device-a"}))["job"]
    await svc.control(1, mid, {"revision": 1, "enabled": False})
    with pytest.raises(ContractError, match="stale_lease"):
        await svc.result(
            1,
            job["id"],
            {
                "schema_version": 1,
                "device_id": "device-a",
                "lease": job["lease"],
                "revision": 1,
                "status": "need_login",
            },
        )
    await svc.control(1, mid, {"revision": 2, "enabled": True})
    await db.execute("UPDATE browser_jobs SET claimed_at = 0")
    job = (await svc.claim(1, {"device_id": "device-a"}))["job"]
    raw = copy.deepcopy(req["targets"][0]["raw"])
    await svc.result(
        1,
        job["id"],
        {
            "schema_version": 1,
            "device_id": "device-a",
            "lease": job["lease"],
            "revision": 3,
            "status": "success",
            "account_key": "wrong-school-account",
            "raw": raw,
        },
    )
    monitor = (await svc.monitors(1))["monitors"][0]
    assert not monitor["enabled"] and monitor["last_result"] == "account_mismatch"
    with pytest.raises(ContractError, match="account_confirmation_required"):
        await svc.control(1, mid, {"revision": 3, "enabled": True})


async def test_reject_malformed_shell_identity_and_wrong_device(service):
    svc, _db, _ = service
    for change in [
        lambda x: x.update(schema_version=2),
        lambda x: x.update(targets=[]),
        lambda x: x.update(binding={}),
    ]:
        req = batch()
        change(req)
        with pytest.raises(ContractError):
            await svc.capture(1, req)
    req = batch()
    req["targets"][0]["raw"]["text"] = ""
    req["targets"][1]["recipe"]["url"] = "https://elsewhere.test/"
    assert all(r["status"] == "failed" for r in (await svc.capture(1, req))["results"])
    await svc.capture(1, batch("valid", ("notice:a",)))
    assert (await svc.claim(1, {"device_id": "another-device"}))["job"] is None


async def test_expired_lease_reclaimed_and_old_result_rejected(service):
    svc, db, _ = service
    await svc.capture(1, batch(entities=("notice:a",)))
    job = (await svc.claim(1, {"device_id": "device-a"}))["job"]
    await db.execute(
        "UPDATE browser_jobs SET expires_at = 0, claimed_at = 0 WHERE id = ?", job["id"]
    )
    new = (await svc.claim(1, {"device_id": "device-a"}))["job"]
    assert new["id"] == job["id"] and new["lease"] != job["lease"]
    with pytest.raises(ContractError, match="stale_lease"):
        await svc.result(
            1,
            job["id"],
            {
                "schema_version": 1,
                "device_id": "device-a",
                "lease": job["lease"],
                "revision": 1,
                "status": "need_login",
            },
        )
    await db.execute(
        "UPDATE browser_jobs SET expires_at = 0, claimed_at = 0, attempts = 3 WHERE id = ?",
        new["id"],
    )
    assert (await svc.claim(1, {"device_id": "device-a"}))["job"] is None
    monitor = (await svc.monitors(1))["monitors"][0]
    assert monitor["error"] == "lease_attempts_exhausted" and monitor["last_success_at"] is None


# Reuse the repository's real gateway/core/push/collector stack, entirely on ephemeral local ports.
from test_e2e import stack  # noqa: E402,F401

from gleaner.net.http import HTTPClient  # noqa: E402


async def test_http_capture_feed_lease_and_account_boundary(stack):  # noqa: F811
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as client:
        auths = []
        for i in (1, 2):
            r = await client.post(
                gw + "/api/auth/register",
                json_body={"email": f"browser{i}@test.local", "password": "password123"},
            )
            auths.append({"Authorization": "Bearer " + r.json()["token"]})
        req = batch()
        r = await client.post(gw + "/api/v1/captures", json_body=req, headers=auths[0])
        assert r.status == 200 and r.json()["schema_version"] == 1, r.text()
        saved = r.json()["results"]
        feed = (await client.get(gw + "/api/feed", headers=auths[0])).json()["items"]
        assert len(feed) == 2 and {i["id"] for i in feed} == {i["item_id"] for i in saved}
        assert (await client.get(gw + "/api/feed", headers=auths[1])).json()["items"] == []
        assert (await client.get(gw + "/api/v1/monitors", headers=auths[1])).json()[
            "monitors"
        ] == []
        denied = await client.post(
            gw + f"/api/v1/monitors/{saved[0]['monitor_id']}/check", json_body={}, headers=auths[1]
        )
        assert denied.status == 404 and denied.json()["ok"] is False
        job = (
            await client.post(
                gw + "/api/v1/monitor-jobs/claim",
                json_body={"device_id": "device-a"},
                headers=auths[0],
            )
        ).json()["job"]
        result = {
            "schema_version": 1,
            "device_id": "device-a",
            "lease": job["lease"],
            "revision": job["revision"],
            "status": "success",
            "account_key": "account-a",
            "raw": {
                "title": job["recipe"]["entity_id"],
                "text": "来源变更后的原文。",
                "fields": {},
            },
        }
        r = await client.post(
            gw + f"/api/v1/monitor-jobs/{job['id']}/result", json_body=result, headers=auths[0]
        )
        assert r.status == 200 and r.json()["status"] == "changed", r.text()
        iid = next(i["item_id"] for i in saved if i["monitor_id"] == job["monitor_id"])
        item = (await client.get(gw + f"/api/items/{iid}", headers=auths[0])).json()
        assert item["version"] == 2 and item["browser_monitor"]["last_result"] == "changed"
        assert (await client.get(gw + f"/api/items/{iid}/versions", headers=auths[0])).json()[
            "versions"
        ][0]["changed_fields"]["body"][1] == "来源变更后的原文。"


async def test_http_extraction_snapshot_save_history_and_no_schedule(stack):  # noqa: F811
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as client:
        login = await client.post(
            gw + "/api/auth/register",
            json_body={"email": "extraction@test.local", "password": "password123"},
        )
        auth = {"Authorization": "Bearer " + login.json()["token"]}
        req = batch("snapshot-http")
        for target in req["targets"]:
            target.update(supported=False, enabled=False)
            target["recipe"].update(version=2, strategy="snapshot")
            del target["recipe"]["selector"]
        first = await client.post(gw + "/api/v1/captures", json_body=req, headers=auth)
        assert first.status == 200
        saved = first.json()
        assert [r["status"] for r in saved["results"]] == ["new", "new"]
        assert (
            await client.post(gw + "/api/v1/captures", json_body=req, headers=auth)
        ).json() == saved
        feed = (await client.get(gw + "/api/feed", headers=auth)).json()["items"]
        assert len(feed) == 2
        iid = saved["results"][0]["item_id"]
        detail = (await client.get(gw + f"/api/items/{iid}", headers=auth)).json()
        assert detail["url"] == req["targets"][0]["locator"]["url"]
        assert detail["browser_monitor"]["supported"] is False
        req["request_id"] = "snapshot-http-next"
        req["targets"][0]["raw"]["text"] = "用户重新预览后显式保存的合成原文。"
        changed = (await client.post(gw + "/api/v1/captures", json_body=req, headers=auth)).json()
        assert changed["results"][0]["item_id"] == iid
        assert changed["results"][0]["status"] == "changed"
        versions = (await client.get(gw + f"/api/items/{iid}/versions", headers=auth)).json()
        assert (
            versions["versions"][0]["changed_fields"]["body"][1] == req["targets"][0]["raw"]["text"]
        )
        assert (
            await client.post(
                gw + "/api/v1/monitor-jobs/claim", json_body={"device_id": "device-a"}, headers=auth
            )
        ).json()["job"] is None


@pytest.mark.parametrize(
    "status",
    [
        "need_login",
        "selection_missing",
        "view_mismatch",
        "route_mismatch",
        "render_timeout",
        "permission_denied",
        "unsupported",
        "failed",
    ],
)
async def test_each_failure_keeps_initial_content_and_no_fake_success(service, status):
    svc, db, _ = service
    saved = (await svc.capture(1, batch(entities=("notice:a",))))["results"][0]
    job = (await svc.claim(1, {"device_id": "device-a"}))["job"]
    ack = await svc.result(
        1,
        job["id"],
        {
            "schema_version": 1,
            "device_id": "device-a",
            "lease": job["lease"],
            "revision": 1,
            "status": status,
        },
    )
    assert ack["status"] == "failed" and ack["result"] == status
    monitor = (await svc.monitors(1))["monitors"][0]
    assert monitor["last_result"] == status and monitor["last_success_at"] is None
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", saved["item_id"]) == 1
    assert (
        await db.fetchval("SELECT body FROM items WHERE id = ?", saved["item_id"])
        == "报名材料要求，日期待确认。"
    )


async def test_loading_shell_and_boolean_schema_rejected(service):
    svc, _db, _ = service
    req = batch()
    req["schema_version"] = True
    with pytest.raises(ContractError, match="schema_version"):
        await svc.capture(1, req)
    for n, raw in enumerate(
        [
            {"title": "正常标题", "text": "正在加载…", "fields": {}},
            {"title": "Log in", "text": "username password", "fields": {}},
        ]
    ):
        req = batch("shell-" + str(n), entities=("notice:a",))
        req["targets"][0]["raw"] = raw
        result = (await svc.capture(1, req))["results"][0]
        assert result["status"] == "failed" and result["error"] == "page_not_ready"


async def test_explicit_recapture_enables_saved_target_and_reconfirms_original_binding(service):
    svc, db, _ = service
    req = batch(entities=("notice:a",))
    req["targets"][0]["enabled"] = False
    saved = (await svc.capture(1, req))["results"][0]
    assert (await svc.claim(1, {"device_id": "device-a"}))["job"] is None
    enabled = await svc.capture(1, batch("enable", ("notice:a",)))
    assert enabled["results"][0]["item_id"] == saved["item_id"]
    await db.execute(
        "UPDATE browser_monitors SET enabled = 0, last_result = 'account_mismatch', error = 'account_mismatch' WHERE id = ?",
        saved["monitor_id"],
    )
    with pytest.raises(ContractError, match="account_confirmation_required"):
        await svc.control(1, saved["monitor_id"], {"revision": 2, "enabled": True})
    await svc.capture(1, batch("reconfirm", ("notice:a",)))
    monitor = (await svc.monitors(1))["monitors"][0]
    assert monitor["enabled"] and monitor["revision"] == 3 and monitor["error"] == ""
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1


async def test_person_field_projection_cannot_overwrite_full_profile(service):
    svc, db, _ = service
    req = batch("profile", entities=("person:1",))
    req["binding"].update(adapter="fie", account_key="public")
    target = req["targets"][0]
    url = "http://localhost:8098/person/view/id-1.html"
    target["locator"].update(url=url, frame_url=url, view={"projection": "profile"})
    target["recipe"] = {
        "adapter": "fie",
        "version": 2,
        "strategy": "snapshot",
        "entity_id": "person:1",
        "url": url,
        "view": {"projection": "profile"},
    }
    target.update(supported=False, enabled=False)
    target["raw"] = {"title": "合成人员", "text": "完整个人资料", "fields": {}}
    full = (await svc.capture(1, req))["results"][0]
    partial = copy.deepcopy(req)
    partial["request_id"] = "email-projection"
    chosen = partial["targets"][0]
    for container in (chosen["locator"], chosen["recipe"]):
        container["view"] = {"projection": "email"}
    chosen["raw"] = {
        "title": "合成人员",
        "text": "邮箱：sample@example.test",
        "fields": {"email": "sample@example.test"},
    }
    email = (await svc.capture(1, partial))["results"][0]
    assert email["status"] == "new" and email["item_id"] != full["item_id"]
    assert (
        await db.fetchval("SELECT body FROM items WHERE id = ?", full["item_id"]) == "完整个人资料"
    )
    assert (await svc.claim(1, {"device_id": "device-a"}))["job"] is None
