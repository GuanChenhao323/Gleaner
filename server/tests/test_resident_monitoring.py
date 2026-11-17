"""Resident monitoring lifecycle, deterministic due cycles, isolation and group controls."""

import copy
import uuid

import pytest
import test_reading_sources as reading_tests
from test_reading_sources import public_batch

from gleaner.core.monitors import ContractError
from gleaner.core.reading_schedule import ReadingSchedule
from gleaner.storage.db import loads

setup = reading_tests.setup


def resident():
    return {
        "version": 1,
        "session_id": str(uuid.uuid4()),
        "page_id": str(uuid.uuid4()),
        "refresh": "reload",
        "interval_s": 1800,
    }


def request(*, descriptor=None, query="项目会议", private=True):
    req = public_batch()
    req["reading"]["resident"] = descriptor or resident()
    req["query"] = req["reading"]["query"] = req["reading"]["intent"]["query"] = query
    if private:
        req["source_binding"] = {"kind": "labeled", "label": "当前网页会话"}
        req["reading"]["binding"]["account_key"] = "unverified"
        req["reading"]["source_label"] = "当前网页会话"
    return req


async def claim(svc, req):
    return (await svc.claim(1, {"device_id": req["device_id"]}))["job"]


async def complete(svc, req, job, *, status="success"):
    body = {
        "schema_version": 1,
        "device_id": req["device_id"],
        "lease": job["lease"],
        "revision": job["revision"],
        "status": status,
    }
    if status == "success":
        body.update(
            account_key=req["reading"]["binding"]["account_key"],
            snapshot={k: v for k, v in req.items() if k != "reading"},
        )
        if job["purpose"] == "activate":
            body["resident"] = req["reading"]["resident"]
    ack = await svc.result(1, job["id"], body)
    assert await svc.result(1, job["id"], body) == ack
    return ack


async def test_save_starts_first_actual_check_and_three_due_cycles_update_original(
    setup,
    monkeypatch,
):
    svc, web, _, db = setup
    now = 2_000_000_000.0
    monkeypatch.setattr("gleaner.core.reading_sources.time.time", lambda: now)
    req = request()
    receipt = await web.capture(1, req)
    sid, iid = receipt["reading_source_id"], receipt["results"][0]["item_id"]
    before = await svc.own(1, sid)
    assert receipt["monitoring"]["state"] == "starting"
    assert before["mode"] == "periodic" and before["pending"] == "activate"
    assert before["last_success_at"] is None and not before["verified"]
    assert (await svc.list_sources(1))["sources"][0]["capability"] == "unverified"
    job = await claim(svc, req)
    assert job["purpose"] == "activate"
    assert (await complete(svc, req, job))["result"] == "unchanged"
    assert (await svc.own(1, sid))["last_success_at"] == now
    assert await claim(svc, req) is None
    # No enqueue/manual check. Time reaching the persisted schedule alone makes work due.
    for cycle in range(1, 4):
        now += 1801
        if cycle == 2:
            req["fragments"][0]["text"] = req["fragments"][0]["evidence"]["text"] = (
                "项目会议：来源变更，保留同一资料。"
            )
        job = await claim(svc, req)
        assert job["purpose"] == "check"
        assert (await complete(svc, req, job))["result"] == (
            "changed" if cycle == 2 else "unchanged"
        )
        current = await svc.own(1, sid)
        assert current["verified"] and not current["paused"]
        assert current["next_at"] == now + 1800
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", iid) == 2
    assert len((await svc.checks(1, sid))["checks"]) == 4


async def test_page_batch_has_independent_results_shared_schedule_and_group_pause(setup):
    svc, web, _, _ = setup
    a, b = request(), request(query="第二条件")
    b["reading"]["resident"] = copy.deepcopy(a["reading"]["resident"])
    b["reading"]["view"] = {"projection": "email"}
    ra, rb = await web.capture(1, a), await web.capture(1, b)
    first = await claim(svc, a)
    assert len(first["companions"]) == 1
    jobs = {j["source_id"]: j for j in [first, *first["companions"]]}
    assert await claim(svc, a) is None
    for req, receipt in [(a, ra), (b, rb)]:
        assert (await complete(svc, req, jobs[receipt["reading_source_id"]]))[
            "result"
        ] == "unchanged"
    rows = [await svc.own(1, r["reading_source_id"]) for r in (ra, rb)]
    assert rows[0]["next_at"] == rows[1]["next_at"]
    await svc.configure(
        1,
        rows[0]["id"],
        {"revision": rows[0]["revision"], "mode": "periodic", "paused": True, "interval_s": 3600},
    )
    for row in rows:
        current = await svc.own(1, row["id"])
        assert current["paused"] and current["interval_s"] == 3600
        assert loads(current["recipe"])["resident"]["interval_s"] == 3600
    assert await claim(svc, a) is None
    row = await svc.own(1, rows[0]["id"])
    await svc.activate(1, row["id"], {"revision": row["revision"], "interval_s": 3600})
    restarted = await claim(svc, a)
    assert len(restarted["companions"]) == 1
    assert all(j["purpose"] == "activate" for j in [restarted, *restarted["companions"]])


async def test_busy_defers_and_missing_tab_pauses_without_erasing_success(setup, monkeypatch):
    svc, web, _, _ = setup
    now = 2_000_000_000.0
    monkeypatch.setattr("gleaner.core.reading_sources.time.time", lambda: now)
    req = request()
    receipt = await web.capture(1, req)
    await complete(svc, req, await claim(svc, req))
    success = await svc.own(1, receipt["reading_source_id"])
    now += 1801
    await complete(svc, req, await claim(svc, req), status="user_busy")
    busy = await svc.own(1, success["id"])
    assert busy["next_at"] == now + 60 and not busy["paused"]
    now += 61
    await complete(svc, req, await claim(svc, req), status="tab_missing")
    after = await svc.own(1, success["id"])
    assert after["paused"] and not after["verified"]
    assert after["last_success_at"] == success["last_success_at"]
    assert after["last_snapshot"] == success["last_snapshot"]
    now += 7200
    assert await claim(svc, req) is None


async def test_explicit_upgrade_of_old_private_source_preserves_identity(setup):
    svc, web, _, db = setup
    req = request()
    descriptor = req["reading"].pop("resident")
    receipt = await web.capture(1, req)
    sid = receipt["reading_source_id"]
    await svc.activate(1, sid, {"revision": 1, "interval_s": 1800})
    job = await claim(svc, req)
    assert job["purpose"] == "activate" and "resident" not in job["recipe"]
    req["reading"]["resident"] = descriptor
    await complete(svc, req, job)
    row = await svc.own(1, sid)
    assert loads(row["recipe"])["resident"] == descriptor and row["verified"]
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1
    assert await db.fetchval("SELECT COUNT(*) FROM reading_sources") == 1


async def test_session_conflict_and_tampered_activation_are_atomic(setup):
    svc, web, _, db = setup
    a = request()
    await web.capture(1, a)
    b = request(query="第二规则")
    with pytest.raises(ContractError, match="single_account_conflict"):
        await web.capture(1, b)
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1
    job = await claim(svc, a)
    tampered = copy.deepcopy(a)
    tampered["reading"]["resident"]["page_id"] = str(uuid.uuid4())
    with pytest.raises(ContractError, match="invalid_resident"):
        await complete(svc, tampered, job)
    assert not (await svc.own(1, job["source_id"]))["verified"]


def test_fixture_clock_cannot_accelerate_real_sources():
    policy = ReadingSchedule(60)
    for url, expected in [
        ("http://127.0.0.1:8098/generic", 60),
        ("https://mail.example.test/inbox", 1800),
        ("https://localhost.example.test/", 1800),
    ]:
        assert policy.interval({"recipe": {"url": url}, "interval_s": 1800}) == expected
    with pytest.raises(ValueError):
        ReadingSchedule(1)


async def test_resident_transient_failures_have_bounded_retry_and_keep_snapshot(setup, monkeypatch):
    svc, web, _, _ = setup
    now = 2_000_000_000.0
    monkeypatch.setattr("gleaner.core.reading_sources.time.time", lambda: now)
    req = request()
    receipt = await web.capture(1, req)
    await complete(svc, req, await claim(svc, req))
    initial = await svc.own(1, receipt["reading_source_id"])
    for attempt in range(3):
        now += 1801
        await complete(svc, req, await claim(svc, req), status="render_timeout")
        current = await svc.own(1, initial["id"])
        assert current["failure_count"] == attempt + 1
        assert bool(current["paused"]) == (attempt == 2)
        assert current["last_success_at"] == initial["last_success_at"]
        assert current["last_snapshot"] == initial["last_snapshot"]
    now += 1801
    assert await claim(svc, req) is None


stack = reading_tests.stack


async def test_resident_http_activation_strict_ack_and_cross_user_isolation(stack):
    from gleaner.net.http import HTTPClient

    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as client:
        reg = await client.post(
            gw + "/api/auth/register",
            json_body={
                "email": "resident-http@test.local",
                "password": "test-password",
                "agree_privacy": True,
            },
        )
        headers = {"Authorization": "Bearer " + reg.json()["token"]}
        req = request()
        saved = await client.post(gw + "/api/v1/web-captures", json_body=req, headers=headers)
        assert saved.status == 200, saved.text()
        assert saved.json()["monitoring"]["state"] == "starting"
        sid = saved.json()["reading_source_id"]
        job = (
            await client.post(
                gw + "/api/v1/reading-jobs/claim",
                json_body={"device_id": req["device_id"]},
                headers=headers,
            )
        ).json()["job"]
        body = {
            "schema_version": 1,
            "device_id": req["device_id"],
            "lease": job["lease"],
            "revision": job["revision"],
            "status": "success",
            "account_key": "unverified",
            "snapshot": {k: v for k, v in req.items() if k != "reading"},
            "resident": req["reading"]["resident"],
        }
        response = await client.post(
            gw + f"/api/v1/reading-jobs/{job['id']}/result", json_body=body, headers=headers
        )
        assert response.status == 200 and response.json()["result"] == "unchanged"
        current = (await client.get(gw + "/api/v1/reading-sources", headers=headers)).json()[
            "sources"
        ][0]
        assert (
            current["last_success_at"]
            and current["verified"]
            and current["next_at"] > current["last_success_at"]
        )
        path = gw + f"/api/v1/reading-sources/{sid}/activate"
        assert (
            await client.post(
                path,
                json_body={"revision": current["revision"], "interval_s": 1800},
                headers=headers,
            )
        ).json()["status"] == "queued"
        assert (
            await client.post(
                path, json_body={"revision": 999, "interval_s": 1800}, headers=headers
            )
        ).status == 409
        assert (
            await client.post(path, json_body={"revision": 1, "interval_s": 1}, headers=headers)
        ).status == 422
        assert (
            await client.post(path, json_body={"revision": 1, "interval_s": 1800})
        ).status == 401


async def test_checking_healthy_rule_does_not_reactivate_failed_peer(setup):
    svc, web, _, _ = setup
    a, b = request(), request(query="第二条件")
    b["reading"]["resident"] = copy.deepcopy(a["reading"]["resident"])
    ra, rb = await web.capture(1, a), await web.capture(1, b)
    first = await claim(svc, a)
    jobs = {j["source_id"]: j for j in [first, *first["companions"]]}
    await complete(svc, a, jobs[ra["reading_source_id"]])
    await complete(svc, b, jobs[rb["reading_source_id"]], status="need_login")
    healthy = await svc.own(1, ra["reading_source_id"])
    await svc.enqueue(1, healthy["id"], {"revision": healthy["revision"], "purpose": "check"})
    job = await claim(svc, a)
    assert "companions" not in job
    failed = await svc.own(1, rb["reading_source_id"])
    assert not failed["pending"] and failed["paused"] and not failed["verified"]
