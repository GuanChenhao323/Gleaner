"""Condition monitoring: saved identity, verification, leased updates and recovery."""

import copy
import time
import uuid

import pytest
from test_web_captures import batch

from gleaner.core.monitors import BrowserMonitorService, ContractError
from gleaner.core.pipeline import Pipeline
from gleaner.core.reading_sources import ReadingSourceService
from gleaner.core.web_captures import WebCaptureService
from gleaner.storage.db import Database


def public_batch():
    req = batch()
    req["source_binding"] = {"kind": "public", "label": "公开网页"}
    req["reading"] = {
        "source_label": "公开网页",
        "version": 1,
        "url": req["source"]["url"],
        "query": req["query"],
        "match_scope": "content",
        "source": "generic",
        "choice": "",
        "view": {},
        "intent": {"version": 2, "query": req["query"], "mode": "literal", "fields": []},
        "binding": {
            "adapter": "generic",
            "origin": "https://unregistered.example.test",
            "account_key": "public",
        },
    }
    return req


@pytest.fixture
async def setup(tmp_path):
    db = await Database(f"sqlite:///{tmp_path / 'reading.db'}").connect()
    for uid in (1, 2):
        await db.insert(
            "users",
            {
                "id": uid,
                "email": f"u{uid}@test.local",
                "password_hash": "unused",
                "created_at": time.time(),
            },
        )

    async def route(topic, payload):
        pass

    pipeline = Pipeline(db, route)
    web, native = WebCaptureService(db, pipeline), BrowserMonitorService(db, pipeline)
    service = ReadingSourceService(db, web, native)
    web.on_capture = native.on_capture = service.attach
    web.validate_reading = native.validate_reading = service.validate_capture
    yield service, web, native, db
    await db.close()


async def save(setup):
    svc, web, _, _ = setup
    req = public_batch()
    receipt = await web.capture(1, req)
    return req, receipt, await svc.own(1, receipt["reading_source_id"])


async def run_job(svc, row, *, purpose="verify", snapshot=None, status="success", account="public"):
    await svc.enqueue(1, row["id"], {"revision": row["revision"], "purpose": purpose})
    job = (await svc.claim(1, {"device_id": row["device_id"]}))["job"]
    assert job
    payload = {
        "schema_version": 1,
        "device_id": row["device_id"],
        "lease": job["lease"],
        "revision": job["revision"],
        "status": status,
    }
    if status == "success":
        payload.update(account_key=account, snapshot=snapshot)
    return job, payload, await svc.result(1, job["id"], payload)


async def test_save_is_atomic_idempotent_and_not_a_successful_check(setup):
    svc, web, _, db = setup
    req, receipt, row = await save(setup)
    assert await web.capture(1, req) == receipt
    assert row["mode"] == "manual" and not row["verified"]
    assert row["last_success_at"] is None and row["last_result"] == "not_executed"
    assert await db.fetchval("SELECT COUNT(*) FROM reading_sources") == 1
    assert len((await svc.list_sources(1))["sources"][0]["items"]) == 1
    assert (await svc.list_sources(2))["sources"] == []
    with pytest.raises(ContractError, match="not_found"):
        await svc.own(2, row["id"])
    invalid = public_batch()
    invalid["reading"]["query"] = "wrong"
    with pytest.raises(ContractError):
        await web.capture(1, invalid)
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1


async def test_verify_then_update_original_collection_preserving_user_state(setup):
    svc, _, _, db = setup
    req, receipt, row = await save(setup)
    snapshot = {k: v for k, v in req.items() if k != "reading"}
    job, payload, ack = await run_job(svc, row, snapshot=snapshot)
    assert ack["result"] == "verified"
    assert await svc.result(1, job["id"], payload) == ack
    row = await svc.own(1, row["id"])
    assert row["verified"] and row["last_success_at"] is None
    iid = receipt["results"][0]["item_id"]
    await db.execute(
        "UPDATE user_item_state SET note = ?, todo_status = ? WHERE user_id = 1 AND item_id = ?",
        "保留备注",
        "done",
        iid,
    )
    snapshot["fragments"][0]["text"] = snapshot["fragments"][0]["evidence"]["text"] = (
        "项目会议内容更新"
    )
    _, _, ack = await run_job(svc, row, purpose="check", snapshot=snapshot)
    assert ack["result"] == "changed"
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", iid) == 2
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1
    assert (
        await db.fetchval("SELECT note FROM user_item_state WHERE user_id = 1 AND item_id = ?", iid)
        == "保留备注"
    )
    row = await svc.own(1, row["id"])
    reordered = copy.deepcopy(snapshot)
    reordered["fragments"].reverse()
    for i, f in enumerate(reordered["fragments"]):
        f["candidate_id"] = f"candidate-{i + 1}"
        f["evidence"]["locator"] = f"div:nth-child({i + 10})"
    _, _, ack = await run_job(svc, row, purpose="check", snapshot=reordered)
    assert ack["result"] == "unchanged"
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", iid) == 2


async def test_no_match_failure_and_login_do_not_replace_success(setup):
    svc, _, _, _ = setup
    req, _, row = await save(setup)
    snap = {k: v for k, v in req.items() if k != "reading"}
    await run_job(svc, row, snapshot=snap)
    row = await svc.own(1, row["id"])
    await run_job(svc, row, purpose="check", snapshot=snap)
    before = await svc.own(1, row["id"])
    for status in ("no_match", "render_timeout", "need_login"):
        row = await svc.own(1, row["id"])
        _, _, ack = await run_job(svc, row, purpose="check", status=status)
        assert ack["result"] == status
        after = await svc.own(1, row["id"])
        assert after["last_success_at"] == before["last_success_at"]
        assert after["last_snapshot"] == before["last_snapshot"]
        if status == "need_login":
            assert not after["verified"]


async def test_paused_manual_check_and_stale_lease_after_revision(setup):
    svc, _, _, _ = setup
    req, _, row = await save(setup)
    with pytest.raises(ContractError, match="verification_required"):
        await svc.configure(
            1, row["id"], {"revision": 1, "mode": "periodic", "paused": False, "interval_s": 1800}
        )
    await run_job(svc, row, snapshot={k: v for k, v in req.items() if k != "reading"})
    row = await svc.own(1, row["id"])
    await svc.configure(
        1,
        row["id"],
        {"revision": row["revision"], "mode": "periodic", "paused": True, "interval_s": 1800},
    )
    row = await svc.own(1, row["id"])
    await svc.enqueue(1, row["id"], {"revision": row["revision"], "purpose": "check"})
    job = (await svc.claim(1, {"device_id": row["device_id"]}))["job"]
    await svc.configure(
        1,
        row["id"],
        {"revision": row["revision"], "mode": "manual", "paused": False, "interval_s": 1800},
    )
    with pytest.raises(ContractError, match="stale_lease"):
        await svc.result(
            1,
            job["id"],
            {
                "schema_version": 1,
                "device_id": row["device_id"],
                "lease": job["lease"],
                "revision": job["revision"],
                "status": "failed",
            },
        )


async def test_unknown_private_identity_cannot_enable_or_claim(setup):
    svc, web, _, _ = setup
    req = public_batch()
    req["source_binding"] = {"kind": "labeled", "label": "私人邮箱"}
    req["reading"]["binding"]["account_key"] = "unverified"
    req["reading"]["source_label"] = "私人邮箱"
    response = await web.capture(1, req)
    row = await svc.own(1, response["reading_source_id"])
    with pytest.raises(ContractError, match="account_unknown"):
        await svc.enqueue(1, row["id"], {"revision": row["revision"], "purpose": "verify"})


async def test_periodic_due_lease_retry_bound_and_heartbeat(setup):
    svc, _, _, db = setup
    req, _, row = await save(setup)
    await run_job(svc, row, snapshot={k: v for k, v in req.items() if k != "reading"})
    row = await svc.own(1, row["id"])
    await svc.configure(
        1,
        row["id"],
        {"revision": row["revision"], "mode": "periodic", "paused": False, "interval_s": 1800},
    )
    await db.execute("UPDATE reading_sources SET next_at = 0 WHERE id = ?", row["id"])
    jobs = []
    for _ in range(3):
        job = (await svc.claim(1, {"device_id": row["device_id"]}))["job"]
        assert job
        jobs.append(job)
        assert (await svc.claim(1, {"device_id": row["device_id"]}))["job"] is None
        await db.execute("UPDATE reading_jobs SET expires_at = 0 WHERE id = ?", job["id"])
    assert len({j["id"] for j in jobs}) == 1
    assert (await svc.claim(1, {"device_id": row["device_id"]}))["job"] is None
    assert (await svc.own(1, row["id"]))["last_result"] == "worker_interrupted"
    assert not (await svc.list_sources(1))["sources"][0]["device_online"]
    await svc.heartbeat(1, {"device_id": row["device_id"]})
    assert (await svc.list_sources(1))["sources"][0]["device_online"]


async def test_native_query_updates_original_items_and_blocks_account_switch(setup):
    from test_browser_capture import batch as native_batch

    svc, _, native, db = setup
    req = native_batch("native-scope")
    for t in req["targets"]:
        t["supported"] = t["enabled"] = False
        t["recipe"] = {k: v for k, v in t["recipe"].items() if k != "selector"}
        t["recipe"].update(version=2, strategy="snapshot")
    req["reading"] = {
        "version": 1,
        "url": req["targets"][0]["locator"]["url"],
        "query": "报名",
        "match_scope": "content",
        "source": "student",
        "intent": {"version": 2, "query": "报名", "fields": []},
        "choice": "",
        "view": {},
        "binding": req["binding"],
    }
    receipt = await native.capture(1, req)
    row = await svc.own(1, receipt["reading_source_id"])
    snap = {"binding": req["binding"], "targets": copy.deepcopy(req["targets"])}
    await run_job(svc, row, snapshot=snap, account="account-a")
    row = await svc.own(1, row["id"])
    snap["targets"][0]["raw"]["text"] = "报名材料原文已更新"
    _, _, ack = await run_job(svc, row, purpose="check", snapshot=snap, account="account-a")
    assert ack["result"] == "changed"
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 2
    assert (
        await db.fetchval(
            "SELECT version FROM items WHERE id = ?", receipt["results"][0]["item_id"]
        )
        == 2
    )
    before = await svc.own(1, row["id"])
    _, _, ack = await run_job(svc, before, purpose="check", snapshot=snap, account="other-account")
    after = await svc.own(1, row["id"])
    assert ack["result"] == "account_mismatch" and not after["verified"] and after["paused"]
    assert before["last_success_at"] == after["last_success_at"]


async def test_source_labels_and_keywords_isolate_conditions(setup):
    svc, web, _, db = setup
    req = public_batch()
    for label in ("私人 A", "私人 B"):
        value = copy.deepcopy(req)
        value["request_id"] = str(uuid.uuid4())
        value["source_binding"] = {"kind": "labeled", "label": label}
        value["reading"]["binding"]["account_key"] = "unverified"
        value["reading"]["source_label"] = label
        await web.capture(1, value)
    assert len((await svc.list_sources(1))["sources"]) == 2
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 2


async def test_verification_never_rebases_changed_content_and_deleted_source_cannot_return(setup):
    svc, _, _, db = setup
    req, receipt, row = await save(setup)
    snapshot = {k: copy.deepcopy(v) for k, v in req.items() if k != "reading"}
    snapshot["fragments"][0]["text"] = snapshot["fragments"][0]["evidence"]["text"] = (
        "项目会议：测试时来源已改变"
    )
    await run_job(svc, row, snapshot=snapshot)
    verified = await svc.own(1, row["id"])
    assert verified["last_snapshot"] == row["last_snapshot"]
    assert (
        await db.fetchval(
            "SELECT version FROM items WHERE id = ?", receipt["results"][0]["item_id"]
        )
        == 1
    )
    await svc.enqueue(1, row["id"], {"revision": verified["revision"], "purpose": "check"})
    job = (await svc.claim(1, {"device_id": verified["device_id"]}))["job"]
    await db.execute("DELETE FROM sources WHERE id = ?", receipt["results"][0]["source_id"])
    with pytest.raises(ContractError, match="stale_lease"):
        await svc.result(
            1,
            job["id"],
            {
                "schema_version": 1,
                "device_id": verified["device_id"],
                "lease": job["lease"],
                "revision": verified["revision"],
                "status": "success",
                "account_key": "public",
                "snapshot": snapshot,
            },
        )
    assert (await svc.claim(1, {"device_id": verified["device_id"]}))["job"] is None
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 0
    assert (await svc.list_sources(1))["sources"] == []


async def test_explicit_save_on_another_device_requires_new_verification(setup):
    svc, web, _, _ = setup
    req, receipt, row = await save(setup)
    await run_job(svc, row, snapshot={k: v for k, v in req.items() if k != "reading"})
    row = await svc.own(1, row["id"])
    await svc.configure(
        1,
        row["id"],
        {"revision": row["revision"], "mode": "periodic", "paused": False, "interval_s": 1800},
    )
    req["request_id"] = str(uuid.uuid4())
    req["device_id"] = "different-local-device"
    again = await web.capture(1, req)
    assert again["reading_source_id"] == receipt["reading_source_id"]
    row = await svc.own(1, row["id"])
    assert row["mode"] == "manual" and not row["verified"] and row["paused"]


from test_e2e import stack  # noqa: E402,F401

from gleaner.net.http import HTTPClient  # noqa: E402


async def test_http_saved_source_verify_result_feed_and_strict_errors(stack):  # noqa: F811
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as client:
        registered = await client.post(
            gw + "/api/auth/register",
            json_body={"email": "reading-http@test.local", "password": "test-password"},
        )
        auth = {"Authorization": "Bearer " + registered.json()["token"]}
        req = public_batch()
        saved = await client.post(gw + "/api/v1/web-captures", json_body=req, headers=auth)
        assert saved.status == 200, saved.text()
        sid = saved.json()["reading_source_id"]
        sources = (await client.get(gw + "/api/v1/reading-sources", headers=auth)).json()["sources"]
        assert sources[0]["id"] == sid and sources[0]["last_success_at"] is None
        for purpose in ("verify", "check"):
            queued = await client.post(
                gw + f"/api/v1/reading-sources/{sid}/check",
                json_body={"revision": 1, "purpose": purpose},
                headers=auth,
            )
            assert queued.json()["status"] == "queued"
            job = (
                await client.post(
                    gw + "/api/v1/reading-jobs/claim",
                    json_body={"device_id": req["device_id"]},
                    headers=auth,
                )
            ).json()["job"]
            payload = {
                "schema_version": 1,
                "device_id": req["device_id"],
                "lease": job["lease"],
                "revision": 1,
                "status": "success",
                "account_key": "public",
                "snapshot": {k: v for k, v in req.items() if k != "reading"},
            }
            result = await client.post(
                gw + f"/api/v1/reading-jobs/{job['id']}/result", json_body=payload, headers=auth
            )
            assert result.status == 200, result.text()
            assert result.json()["result"] == ("verified" if purpose == "verify" else "unchanged")
        detail = (
            await client.get(
                gw + f"/api/items/{saved.json()['results'][0]['item_id']}", headers=auth
            )
        ).json()
        assert detail["reading_source"]["id"] == sid
        assert (
            await client.post(
                gw + f"/api/v1/reading-sources/{sid}/check",
                json_body={"revision": 99, "purpose": "check"},
                headers=auth,
            )
        ).status == 409
        assert (await client.get(gw + "/api/v1/reading-sources")).status == 401
        for path in ("reading-devices/heartbeat", "reading-jobs/claim"):
            for malformed in ([], {"device_id": "d", "cookie": "must-not-be-accepted"}):
                rejected = await client.post(
                    gw + "/api/v1/" + path, json_body=malformed, headers=auth
                )
                assert rejected.status == 422
                assert rejected.json()["ok"] is False
        assert (
            await client.post(
                gw + f"/api/v1/reading-sources/{sid}/check",
                json_body={"revision": True, "purpose": "check"},
                headers=auth,
            )
        ).status == 422
