"""Save-control metadata must never invalidate a later content re-read."""

import copy
import time

import pytest
import test_reading_sources as reading_tests
import test_timeline_captures as timeline_tests
from test_resident_monitoring import request, resident
from test_timeline_captures import timeline_batch

from gleaner.core.monitors import ContractError
from gleaner.storage.db import loads

setup = timeline_tests.setup


def result_body(req, job):
    body = {
        "schema_version": 1,
        "device_id": req["device_id"],
        "revision": job["revision"],
        "lease": job["lease"],
        "status": "success",
        "account_key": req["reading"]["binding"]["account_key"],
        "snapshot": {
            k: copy.deepcopy(v)
            for k, v in req.items()
            if k not in {"reading", "capture_generation"}
        },
    }
    if job["purpose"] == "activate":
        body["resident"] = req["reading"]["resident"]
    return body


@pytest.mark.parametrize("kind", ["generic", "timeline"])
@pytest.mark.parametrize("generation", [0, 12])
@pytest.mark.parametrize("legacy_baseline", [False, True])
async def test_new_epoch_capture_first_check_and_due_cycles_update_original(
    setup,
    monkeypatch,
    kind,
    generation,
    legacy_baseline,
):
    timeline, svc, db, web = setup
    now = time.time()
    monkeypatch.setattr("gleaner.core.reading_sources.time.time", lambda: now)
    await db.execute("UPDATE users SET capture_generation=? WHERE id=1", generation)
    req = request() if kind == "generic" else timeline_batch()
    req["reading"]["resident"] = resident()
    req["capture_generation"] = generation
    saved = await (web if kind == "generic" else timeline).capture(1, req)
    sid, iid = saved["reading_source_id"], saved["results"][0]["item_id"]
    row = await svc.own(1, sid)
    if legacy_baseline:
        baseline = loads(row["last_snapshot"])
        baseline["capture_generation"] = generation
        await db.execute("UPDATE reading_sources SET last_snapshot=? WHERE id=?", baseline, sid)
    else:
        assert "capture_generation" not in loads(row["last_snapshot"])
    job = (await svc.claim(1, {"device_id": req["device_id"]}))["job"]
    body = result_body(req, job)
    ack = await svc.result(1, job["id"], body)
    assert ack["result"] == "unchanged" and await svc.result(1, job["id"], body) == ack
    ready = await svc.own(1, sid)
    assert ready["verified"] and ready["last_success_at"] == now and ready["next_at"] > now
    await db.execute(
        "UPDATE user_item_state SET note='keep my note' WHERE user_id=1 AND item_id=?", iid
    )
    for expected in ("changed", "unchanged"):
        now += 1801
        req["fragments"][0]["text"] = req["fragments"][0]["evidence"]["text"] = "project update v2"
        job = (await svc.claim(1, {"device_id": req["device_id"]}))["job"]
        assert job["purpose"] == "check"
        assert (await svc.result(1, job["id"], result_body(req, job)))["result"] == expected
    assert await db.fetchval("SELECT version FROM items WHERE id=?", iid) == 2
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1
    assert (
        await db.fetchval("SELECT note FROM user_item_state WHERE user_id=1 AND item_id=?", iid)
        == "keep my note"
    )


async def test_rejected_valid_lease_is_terminal_and_preserves_successful_data(setup):
    _, svc, db, web = setup
    req = request()
    req["capture_generation"] = 0
    saved = await web.capture(1, req)
    sid = saved["reading_source_id"]
    job = (await svc.claim(1, {"device_id": req["device_id"]}))["job"]
    await svc.result(1, job["id"], result_body(req, job))
    before = await svc.own(1, sid)
    await svc.enqueue(1, sid, {"revision": before["revision"], "purpose": "check"})
    job = (await svc.claim(1, {"device_id": req["device_id"]}))["job"]
    body = result_body(req, job)
    body["snapshot"]["query"] = "a different unauthorized scope"
    for _ in range(2):
        with pytest.raises(ContractError, match="scope_mismatch"):
            await svc.result(1, job["id"], body)
    after = await svc.own(1, sid)
    assert after["last_result"] == "result_rejected" and after["paused"]
    assert after["last_snapshot"] == before["last_snapshot"]
    assert after["last_success_at"] == before["last_success_at"]
    assert await db.fetchval("SELECT COUNT(*) FROM reading_checks WHERE job_id=?", job["id"]) == 1
    assert await db.fetchval("SELECT finished_at FROM reading_jobs WHERE id=?", job["id"])
    assert (await svc.list_sources(1))["sources"][0]["active_job"] is None
    assert loads(
        (await db.fetchone("SELECT detail FROM reading_checks WHERE job_id=?", job["id"]))["detail"]
    ) == {"error": "scope_mismatch"}
    assert (
        await db.fetchval("SELECT version FROM items WHERE id=?", saved["results"][0]["item_id"])
        == 1
    )


async def test_unknown_baseline_field_is_not_silently_accepted_and_activation_rolls_back(setup):
    _, svc, db, web = setup
    req = request()
    saved = await web.capture(1, req)
    row = await svc.own(1, saved["reading_source_id"])
    baseline = loads(row["last_snapshot"])
    baseline["unexpected_business_field"] = "must reject"
    await db.execute("UPDATE reading_sources SET last_snapshot=? WHERE id=?", baseline, row["id"])
    job = (await svc.claim(1, {"device_id": req["device_id"]}))["job"]
    with pytest.raises(ContractError, match="invalid_request"):
        await svc.result(1, job["id"], result_body(req, job))
    row = await svc.own(1, row["id"])
    assert not row["verified"] and row["last_success_at"] is None
    assert row["last_result"] == "result_rejected" and row["paused"]


async def test_invalid_or_foreign_or_expired_lease_cannot_record_rejection(setup, monkeypatch):
    _, svc, db, web = setup
    req = request()
    saved = await web.capture(1, req)
    job = (await svc.claim(1, {"device_id": req["device_id"]}))["job"]
    body = result_body(req, job)
    body["unexpected"] = True
    wrong = {**body, "lease": "wrong"}
    for uid, payload in ((1, wrong), (2, body)):
        with pytest.raises(ContractError):
            await svc.result(uid, job["id"], payload)
    monkeypatch.setattr("gleaner.core.reading_sources.time.time", lambda: job["expires_at"] + 1)
    with pytest.raises(ContractError):
        await svc.result(1, job["id"], body)
    row = await svc.own(1, saved["reading_source_id"])
    assert row["last_result"] == "starting" and not row["paused"]
    assert await db.fetchval("SELECT COUNT(*) FROM reading_checks") == 0
    listing = (await svc.list_sources(1))["sources"][0]
    assert listing["active_job"] is None and listing["execution_state"] == "expired"


stack = reading_tests.stack


async def test_actual_plugin_modules_over_real_http_first_check_and_recovery(stack):
    import asyncio
    import json
    import shutil
    from pathlib import Path

    from gleaner.net.http import HTTPClient

    node = shutil.which("node") or "/usr/local/bin/node"
    if not Path(node).exists():
        pytest.skip("Node required for actual plugin interoperability")
    server = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as client:
        auth = (
            await client.post(
                server + "/api/auth/register",
                json_body={"email": "monitoring-recovery@test.local", "password": "test-password"},
            )
        ).json()
    proc = await asyncio.create_subprocess_exec(
        node,
        "devtools/monitoring_recovery_smoke.mjs",
        cwd=Path(__file__).resolve().parents[2],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, error = await asyncio.wait_for(
        proc.communicate(
            json.dumps(
                {"server": server, "uid": auth["user"]["id"], "token": auth["token"]}
            ).encode()
        ),
        timeout=30,
    )
    assert proc.returncode == 0, error.decode()
    assert json.loads(output) == {
        "first_check": True,
        "original_updated": True,
        "unchanged_version": True,
        "rejection_visible": True,
        "recovery_same_item": True,
        "reloads": 5,
    }
