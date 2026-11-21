"""Permanent deletion uses isolated databases; no user's local records are purged."""

import copy
import uuid

import pytest
import test_reading_sources as reading_tests
from test_resident_monitoring import claim, complete
from test_resident_monitoring import request as resident_request
from test_source_lifecycle import wire

from gleaner.core.monitors import ContractError
from gleaner.storage.db import loads

setup = reading_tests.setup


async def purge_body(svc, uid, sid):
    preview = await svc.purge_preview(uid, sid)
    return {"plan": preview["plan"], "token": preview["token"], "confirm": True}


async def test_atomic_erasure_releases_identity_and_fences_all_old_previews(setup):
    svc, web, _, db = await wire(setup)
    req = resident_request()
    response = await web.capture(1, req)
    sid, iid = response["reading_source_id"], response["results"][0]["item_id"]
    await complete(svc, req, await claim(svc, req))
    row = await svc.own(1, sid)
    await svc.remove(1, sid, {"revision": row["revision"], "trash_items": False})
    body = await purge_body(svc, 1, sid)
    assert body["plan"]["version_count"] == 1
    ack = await svc.purge(1, sid, body)
    assert ack["purged"] and ack["generation"] == 1 and ack["item_ids"] == [iid]
    assert (await svc.purge(1, sid, body))["already_absent"]
    assert await svc.fence.generation(1) == 1
    for table in (
        "reading_sources",
        "items",
        "item_versions",
        "reading_jobs",
        "reading_checks",
        "reading_source_items",
        "web_collections",
        "web_capture_requests",
        "reading_pages",
        "reading_sessions",
    ):
        assert await db.fetchval(f"SELECT COUNT(*) FROM {table}") == 0, table
    old = copy.deepcopy(req)
    old["request_id"] = str(uuid.uuid4())
    with pytest.raises(ContractError, match="capture_context_changed"):
        await web.capture(1, old)
    old["capture_generation"] = 1
    new = await web.capture(1, old)
    assert new["reading_source_id"] != sid and new["results"][0]["item_id"] != iid
    assert new["results"][0]["version"] == 1


async def test_purge_requires_deleted_owned_unchanged_signed_confirmation(setup):
    svc, _, _, _ = await wire(setup)
    _, _, row = await reading_tests.save(setup)
    sid = row["id"]
    with pytest.raises(ContractError, match="delete_first"):
        await svc.purge_preview(1, sid)
    await svc.remove(1, sid, {"revision": row["revision"], "trash_items": False})
    with pytest.raises(ContractError, match="not_found"):
        await svc.purge_preview(2, sid)
    body = await purge_body(svc, 1, sid)
    with pytest.raises(ContractError, match="not_found"):
        await svc.purge(2, sid, body)
    altered = copy.deepcopy(body)
    altered["plan"]["items"] = []
    with pytest.raises(ContractError, match="invalid_purge_plan"):
        await svc.purge(1, sid, altered)
    with pytest.raises(ContractError, match="invalid_request"):
        await svc.purge(1, sid, {**body, "confirm": False})
    await svc.restore(1, sid, {"revision": body["plan"]["revision"]})
    with pytest.raises(ContractError, match="delete_first"):
        await svc.purge(1, sid, body)


async def test_purge_prunes_delivery_note_receipt_history_and_protects_other_owner(setup):
    svc, web, api, db = await wire(setup)
    req, response, row = await reading_tests.save(setup)
    iid, sid = response["results"][0]["item_id"], row["id"]
    await api.apply_state(1, iid, {"note": "delete private note"}, "note-op")
    await api._event(1, "test", {"item_id": iid})
    await svc.remove(1, sid, {"revision": row["revision"], "trash_items": True})
    await db.execute(
        "INSERT INTO subscriptions (user_id,source_id,created_at) VALUES (2,?,0)",
        response["results"][0]["source_id"],
    )
    with pytest.raises(ContractError, match="shared_document"):
        await svc.purge_preview(1, sid)
    await db.execute("DELETE FROM subscriptions WHERE user_id=2")
    # A different owner's independent data survives even though their generation is also zero.
    other = copy.deepcopy(req)
    other["request_id"] = str(uuid.uuid4())
    saved_other = await web.capture(2, other)
    body = await purge_body(svc, 1, sid)
    await svc.purge(1, sid, body)
    assert await db.fetchval("SELECT COUNT(*) FROM op_log WHERE user_id=1") == 0
    assert await db.fetchval("SELECT COUNT(*) FROM events WHERE user_id=1") == 0
    assert await db.fetchval("SELECT COUNT(*) FROM deliveries WHERE item_id=?", iid) == 0
    assert (
        await db.fetchval(
            "SELECT COUNT(*) FROM items WHERE id=?", saved_other["results"][0]["item_id"]
        )
        == 1
    )
    assert await svc.fence.generation(2) == 0


async def test_empty_related_rule_removed_and_mixed_rule_requires_recapture(setup):
    svc, web, _, db = await wire(setup)
    req, response, row = await reading_tests.save(setup)
    sid, iid = row["id"], response["results"][0]["item_id"]
    other = copy.deepcopy(req)
    other["request_id"] = str(uuid.uuid4())
    other["query"] = other["reading"]["query"] = other["reading"]["intent"]["query"] = (
        "another condition"
    )
    saved = await web.capture(1, other)
    peer = saved["reading_source_id"]
    await db.execute(
        "INSERT INTO reading_source_items (reading_id,item_id) VALUES (?,?)", peer, iid
    )
    await svc.remove(1, sid, {"revision": row["revision"], "trash_items": False})
    body = await purge_body(svc, 1, sid)
    assert body["plan"]["affected"][0]["remaining"] == 1
    result = await svc.purge(1, sid, body)
    assert result["paused_source_ids"] == [peer]
    after = await svc.own(1, peer)
    assert (
        after["paused"]
        and after["last_result"] == "documents_purged"
        and loads(after["last_snapshot"]) == {}
    )
    assert (
        await db.fetchval("SELECT COUNT(*) FROM items WHERE id=?", saved["results"][0]["item_id"])
        == 1
    )
    with pytest.raises(ContractError, match="recapture_required"):
        await svc.activate(1, peer, {"revision": after["revision"], "interval_s": 1800})


async def test_unrelated_monitoring_continues_after_capture_epoch_changes(setup):
    svc, web, _, _ = await wire(setup)
    a, b = resident_request(), resident_request(query="another condition")
    b["reading"]["resident"] = copy.deepcopy(a["reading"]["resident"])
    ra, rb = await web.capture(1, a), await web.capture(1, b)
    job = await claim(svc, a)
    jobs = {j["source_id"]: j for j in [job, *job["companions"]]}
    await complete(svc, a, jobs[ra["reading_source_id"]])
    await complete(svc, b, jobs[rb["reading_source_id"]])
    deleted = await svc.own(1, ra["reading_source_id"])
    await svc.remove(1, deleted["id"], {"revision": deleted["revision"], "trash_items": False})
    await svc.purge(1, deleted["id"], await purge_body(svc, 1, deleted["id"]))
    healthy = await svc.own(1, rb["reading_source_id"])
    assert healthy["verified"] and not healthy["paused"] and healthy["mode"] == "periodic"
    await svc.enqueue(1, healthy["id"], {"revision": healthy["revision"], "purpose": "check"})
    b["fragments"][0]["text"] = b["fragments"][0]["evidence"]["text"] = "another condition updated"
    assert (await complete(svc, b, await claim(svc, b)))["result"] == "changed"


async def test_expired_or_changed_impact_cannot_be_confirmed(setup):
    import time

    svc, _, _, db = await wire(setup)
    _, response, row = await reading_tests.save(setup)
    await svc.remove(1, row["id"], {"revision": row["revision"], "trash_items": False})
    body = await purge_body(svc, 1, row["id"])
    expired = copy.deepcopy(body)
    expired["plan"]["expires_at"] = int(time.time()) - 1
    expired["token"] = svc.purging.sign(expired["plan"])
    with pytest.raises(ContractError, match="purge_plan_expired"):
        await svc.purge(1, row["id"], expired)
    await db.execute(
        "UPDATE items SET version=version+1 WHERE id=?", response["results"][0]["item_id"]
    )
    with pytest.raises(ContractError, match="purge_plan_changed"):
        await svc.purge(1, row["id"], body)
    assert await db.fetchval("SELECT COUNT(*) FROM reading_sources") == 1


async def test_failed_erasure_rolls_back_and_empty_related_rule_is_removed(setup, monkeypatch):
    svc, _, _, db = await wire(setup)
    _, response, row = await reading_tests.save(setup)
    iid = response["results"][0]["item_id"]
    peer = await db.insert(
        "reading_sources",
        {
            "owner_id": 1,
            "device_id": row["device_id"],
            "identity_key": "related-only",
            "recipe": row["recipe"],
            "last_snapshot": row["last_snapshot"],
            "created_at": row["created_at"],
        },
    )
    await db.execute(
        "INSERT INTO reading_source_items (reading_id,item_id) VALUES (?,?)", peer, iid
    )
    await svc.remove(1, row["id"], {"revision": row["revision"], "trash_items": False})
    body = await purge_body(svc, 1, row["id"])
    assert body["plan"]["affected"] == [{"id": peer, "revision": 1, "remaining": 0}]
    execute = db.execute

    async def failing(sql, *args):
        if "capture_generation = capture_generation + 1" in sql:
            raise RuntimeError("simulated storage failure")
        return await execute(sql, *args)

    monkeypatch.setattr(db, "execute", failing)
    with pytest.raises(RuntimeError, match="simulated storage failure"):
        await svc.purge(1, row["id"], body)
    assert await db.fetchval("SELECT COUNT(*) FROM items WHERE id=?", iid) == 1
    assert await db.fetchval("SELECT COUNT(*) FROM item_versions WHERE item_id=?", iid) == 1
    assert await db.fetchval("SELECT COUNT(*) FROM reading_sources") == 2
    assert await svc.fence.generation(1) == 0
    monkeypatch.setattr(db, "execute", execute)
    assert (await svc.purge(1, row["id"], body))["purged_source_ids"] == [row["id"], peer]
    assert await db.fetchval("SELECT COUNT(*) FROM reading_sources") == 0


async def test_native_capture_uses_same_account_fence(setup):
    from test_browser_capture import batch

    _svc, _, native, db = setup
    await db.execute("UPDATE users SET capture_generation=1 WHERE id=1")
    with pytest.raises(ContractError, match="capture_context_changed"):
        await native.capture(1, batch())
    req = batch()
    req["capture_generation"] = 1
    assert all(r["status"] == "new" for r in (await native.capture(1, req))["results"])


stack = reading_tests.stack


async def test_http_purge_confirmation_old_payload_rejected_new_capture_allowed(stack):
    from gleaner.net.http import HTTPClient

    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as client:
        registered = await client.post(
            gw + "/api/auth/register",
            json_body={
                "email": "purge-http@test.local",
                "password": "test-password",
                "agree_privacy": True,
            },
        )
        auth = {"Authorization": "Bearer " + registered.json()["token"]}
        req = reading_tests.public_batch()
        saved = (await client.post(gw + "/api/v1/web-captures", headers=auth, json_body=req)).json()
        sid = saved["reading_source_id"]
        path = gw + f"/api/v1/reading-sources/{sid}"
        assert (await client.get(path + "/purge-preview", headers=auth)).status == 409
        assert (
            await client.request(
                "DELETE", path, headers=auth, json_body={"revision": 1, "trash_items": False}
            )
        ).status == 200
        preview = (await client.get(path + "/purge-preview", headers=auth)).json()
        body = {"plan": preview["plan"], "token": preview["token"], "confirm": True}
        erased = await client.post(path + "/purge", headers=auth, json_body=body)
        assert erased.status == 200, erased.text()
        assert erased.json()["purged"]
        again = await client.post(path + "/purge", headers=auth, json_body=body)
        assert again.status == 200 and again.json()["already_absent"]
        context = (await client.get(gw + "/api/v1/capture-context", headers=auth)).json()
        assert context["generation"] == 1 and context["item_ids"] == []
        assert (
            await client.get(gw + f"/api/items/{saved['results'][0]['item_id']}", headers=auth)
        ).status == 404
        assert (
            await client.post(gw + "/api/v1/web-captures", headers=auth, json_body=req)
        ).status == 409
        req["request_id"], req["capture_generation"] = str(uuid.uuid4()), context["generation"]
        fresh = await client.post(gw + "/api/v1/web-captures", headers=auth, json_body=req)
        assert fresh.status == 200 and fresh.json()["results"][0]["status"] == "new"


async def test_actual_extension_lifecycle_modules_over_loopback_http(stack):
    import asyncio
    import json
    import shutil
    from pathlib import Path

    from gleaner.net.http import HTTPClient

    node = shutil.which("node") or "/usr/local/bin/node"
    if not Path(node).exists():
        pytest.skip("Node is required for extension HTTP interoperability")
    server = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as client:
        registered = (
            await client.post(
                server + "/api/auth/register",
                json_body={
                    "email": "purge-extension@test.local",
                    "password": "test-password",
                    "agree_privacy": True,
                },
            )
        ).json()
    proc = await asyncio.create_subprocess_exec(
        node,
        "devtools/source_purge_smoke.mjs",
        cwd=Path(__file__).resolve().parents[2],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, error = await asyncio.wait_for(
        proc.communicate(
            json.dumps(
                {
                    "server": server,
                    "token": registered["token"],
                    "uid": registered["user"]["id"],
                    "payload": reading_tests.public_batch(),
                }
            ).encode()
        ),
        timeout=30,
    )
    assert proc.returncode == 0, error.decode()
    result = json.loads(output)
    assert result == {
        "generation": 1,
        "old_submission_rejected": True,
        "local_previews": 0,
        "local_outbox": 0,
        "fresh_saved": True,
    }
