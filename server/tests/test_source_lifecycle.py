"""Personal trash, source tombstones and account proof compatibility, local DB only."""

import copy
import json
import time
import uuid
from types import SimpleNamespace

import pytest
from test_reading_sources import public_batch, run_job, save
from test_reading_sources import setup as setup

from gleaner.core.api import API
from gleaner.core.monitors import ContractError
from gleaner.storage.db import loads


async def wire(setup):
    svc, web, native, db = setup

    async def publish(topic, payload):
        pass

    api = API(db, web.pipeline, publish)
    api.reading = svc
    svc.change_state = api.apply_state
    web.guard_reading = native.guard_reading = svc.guard_capture
    return svc, web, api, db


async def test_delete_retains_documents_versions_and_access_but_revokes_late_results(setup):
    svc, web, api, db = await wire(setup)
    req, receipt, row = await save(setup)
    iid, sid = receipt["results"][0]["item_id"], row["id"]
    await svc.enqueue(1, sid, {"revision": row["revision"], "purpose": "verify"})
    job = (await svc.claim(1, {"device_id": row["device_id"]}))["job"]
    result = await svc.remove(1, sid, {"revision": row["revision"], "trash_items": False})
    assert result["deleted"] and result["trashed_item_ids"] == []
    assert await svc.remove(1, sid, {"revision": row["revision"], "trash_items": False}) == result
    assert (await svc.list_sources(1))["sources"] == []
    assert (await svc.claim(1, {"device_id": row["device_id"]}))["job"] is None
    assert await db.fetchval("SELECT COUNT(*) FROM items WHERE id = ?", iid) == 1
    assert await db.fetchval("SELECT COUNT(*) FROM item_versions WHERE item_id = ?", iid) == 1
    assert len(await api._items_for(1, " AND i.id = ?", (iid,))) == 1
    assert await api._items_for(2, " AND i.id = ?", (iid,)) == []
    with pytest.raises(ContractError, match="source_deleted"):
        await svc.result(
            1,
            job["id"],
            {
                "schema_version": 1,
                "device_id": row["device_id"],
                "revision": job["revision"],
                "lease": job["lease"],
                "status": "success",
                "account_key": "public",
                "snapshot": req,
            },
        )
    fresh = copy.deepcopy(req)
    fresh["request_id"] = str(uuid.uuid4())
    with pytest.raises(ContractError, match="source_deleted"):
        await web.capture(1, fresh)
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", iid) == 1
    with pytest.raises(ContractError, match="not_found"):
        await svc.remove(2, sid, {"revision": row["revision"], "trash_items": False})
    with pytest.raises(ContractError, match="idempotency_conflict"):
        await svc.remove(1, sid, {"revision": row["revision"], "trash_items": True})


async def test_trash_and_restore_are_personal_persistent_and_do_not_restart_source(setup):
    svc, _, api, db = await wire(setup)
    req, receipt, row = await save(setup)
    iid = receipt["results"][0]["item_id"]
    _, _, verified = await run_job(
        svc, row, snapshot={k: v for k, v in req.items() if k != "reading"}
    )
    assert verified["result"] == "verified"
    await db.execute(
        "UPDATE items SET course = ?, deadline_at = ? WHERE id = ?", "课程", time.time() + 3600, iid
    )
    underlying = receipt["results"][0]["source_id"]
    await db.execute(
        "INSERT INTO subscriptions (user_id, source_id, created_at) VALUES (?, ?, ?)",
        2,
        underlying,
        time.time(),
    )
    await api.apply_state(1, iid, {"note": "保留备注", "starred": True}, None)
    status, result = await api.apply_state(1, iid, {"hidden": True}, "trash-once")
    assert status == 200 and result["state"]["hidden"]
    assert (await api.apply_state(1, iid, {"hidden": True}, "trash-once"))[1]["duplicate"]
    paused = await svc.own(1, row["id"])
    assert paused["paused"] and paused["verified"] and paused["last_result"] == "documents_trashed"
    normal = json.loads((await api.feed(SimpleNamespace(query={}), {"id": 1, "next_seq": 0})).body)
    trash = json.loads(
        (await api.feed(SimpleNamespace(query={"filter": "trash"}), {"id": 1, "next_seq": 0})).body
    )
    assert normal["items"] == [] and [v["id"] for v in trash["items"]] == [iid]
    assert (
        json.loads((await api.deadlines(SimpleNamespace(query={}), {"id": 1, "next_seq": 0})).body)[
            "items"
        ]
        == []
    )
    assert (
        json.loads((await api.courses(SimpleNamespace(query={}), {"id": 1, "next_seq": 0})).body)[
            "courses"
        ]
        == []
    )
    assert (
        len(
            json.loads((await api.feed(SimpleNamespace(query={}), {"id": 2, "next_seq": 0})).body)[
                "items"
            ]
        )
        == 1
    )
    await api.apply_state(1, iid, {"hidden": False}, "restore-once")
    assert (await svc.own(1, row["id"]))["paused"]
    assert (await svc.own(1, row["id"]))["last_result"] == "documents_restored"
    state = await db.fetchone(
        "SELECT * FROM user_item_state WHERE user_id = 1 AND item_id = ?", iid
    )
    assert state["note"] == "保留备注" and state["starred"] and not state["hidden"]
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", iid) == 1


async def test_optional_source_delete_trashes_only_current_users_documents(setup):
    svc, _, api, db = await wire(setup)
    _, receipt, row = await save(setup)
    iid = receipt["results"][0]["item_id"]
    result = await svc.remove(1, row["id"], {"revision": row["revision"], "trash_items": True})
    assert result["trashed_item_ids"] == [iid]
    assert (
        await db.fetchval(
            "SELECT hidden FROM user_item_state WHERE user_id = 1 AND item_id = ?", iid
        )
        == 1
    )
    assert await db.fetchval("SELECT COUNT(*) FROM items WHERE id = ?", iid) == 1
    await api.apply_state(1, iid, {"hidden": False}, None)
    assert (await svc.list_sources(1))["sources"] == []


async def test_verified_private_proof_contract_is_consistent_and_compatible(setup):
    svc, web, _, db = await wire(setup)
    req = public_batch()
    key = "a" * 64
    identity = {
        "version": 1,
        "probe": "account-control-email-v1",
        "account_key": key,
        "display": "s***@example.test",
    }
    req["source_binding"] = {"kind": "labeled", "label": "学校邮箱", "identity": identity}
    req["reading"]["binding"]["account_key"] = key
    req["reading"]["source_label"] = "学校邮箱"
    req["reading"]["account_probe"] = {
        "version": 1,
        "kind": identity["probe"],
        "display": identity["display"],
    }
    receipt = await web.capture(1, req)
    source = (await svc.list_sources(1))["sources"][0]
    assert (
        source["capability"] == "unverified" and source["recipe"]["binding"]["account_key"] == key
    )
    metadata = loads(
        await db.fetchval("SELECT attrs FROM items WHERE id = ?", receipt["results"][0]["item_id"])
    )
    assert metadata["web_capture"]["account_state"] == "bound"
    bad = copy.deepcopy(req)
    bad["request_id"] = str(uuid.uuid4())
    bad["source_binding"]["identity"]["account_key"] = "b" * 64
    with pytest.raises(ContractError, match="invalid_binding"):
        await web.capture(1, bad)
    bad = copy.deepcopy(req)
    bad["request_id"] = str(uuid.uuid4())
    del bad["reading"]["account_probe"]
    with pytest.raises(ContractError, match="invalid_account_proof"):
        await web.capture(1, bad)
    old = public_batch()
    old["source_binding"] = {"kind": "labeled", "label": "旧私人标签"}
    old["reading"]["binding"]["account_key"] = "unverified"
    old["reading"]["source_label"] = "旧私人标签"
    old_receipt = await web.capture(1, old)
    with pytest.raises(ContractError, match="account_unknown"):
        await svc.enqueue(1, old_receipt["reading_source_id"], {"revision": 1, "purpose": "verify"})


async def test_source_restore_is_explicit_paused_and_preserves_trash_and_old_lease_rejection(setup):
    svc, web, api, db = await wire(setup)
    req, receipt, row = await save(setup)
    iid, sid = receipt["results"][0]["item_id"], row["id"]
    await svc.enqueue(1, sid, {"revision": row["revision"], "purpose": "verify"})
    job = (await svc.claim(1, {"device_id": row["device_id"]}))["job"]
    await svc.remove(1, sid, {"revision": row["revision"], "trash_items": True})
    deleted = (await svc.deleted_sources(1))["sources"][0]
    assert (await svc.deleted_sources(2))["sources"] == []
    with pytest.raises(ContractError, match="not_found"):
        await svc.restore(2, sid, {"revision": deleted["revision"]})
    ack = await svc.restore(1, sid, {"revision": deleted["revision"]})
    assert ack["paused"] and ack["restored"]
    assert await svc.restore(1, sid, {"revision": deleted["revision"]}) == ack
    restored = await svc.own(1, sid)
    assert restored["paused"] and not restored["verified"] and restored["mode"] == "manual"
    assert (await svc.deleted_sources(1))["sources"] == []
    assert (
        await db.fetchval(
            "SELECT hidden FROM user_item_state WHERE user_id = 1 AND item_id = ?", iid
        )
        == 1
    )
    with pytest.raises(ContractError, match="stale_lease"):
        await svc.result(
            1,
            job["id"],
            {
                "schema_version": 1,
                "device_id": job["device_id"],
                "lease": job["lease"],
                "revision": job["revision"],
                "status": "worker_interrupted",
            },
        )
    await api.apply_state(1, iid, {"hidden": False}, None)
    req["request_id"] = str(uuid.uuid4())
    assert (await web.capture(1, req))["reading_source_id"] == sid
    assert (await svc.own(1, sid))["paused"]


async def test_collection_updates_do_not_resurrect_personal_trash(setup):
    svc, web, api, db = await wire(setup)
    req, receipt, row = await save(setup)
    iid = receipt["results"][0]["item_id"]
    await api.apply_state(1, iid, {"hidden": True, "note": "保留个人备注"}, None)
    req["request_id"] = str(uuid.uuid4())
    req["fragments"][0]["text"] = req["fragments"][0]["evidence"]["text"] = "资料内容变化"
    await web.capture(1, req)
    state = await db.fetchone(
        "SELECT * FROM user_item_state WHERE user_id = 1 AND item_id = ?", iid
    )
    assert state["hidden"] and state["note"] == "保留个人备注"
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", iid) == 2
    assert (await svc.own(1, row["id"]))["paused"]
    assert (await api.apply_state(1, iid, {"hidden": "false"}, None))[0] == 422


async def test_deletion_revision_conflict_does_not_mutate_source(setup):
    svc, _, _, db = await wire(setup)
    _, _, row = await save(setup)
    with pytest.raises(ContractError, match="revision_conflict"):
        await svc.remove(1, row["id"], {"revision": 99, "trash_items": False})
    with pytest.raises(ContractError, match="revision_conflict"):
        await svc.restore(1, row["id"], {"revision": 0})
    assert (await svc.own(1, row["id"]))["revision"] == 1
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1


async def test_known_webmail_cannot_be_declared_public(setup):
    _, web, _, _ = await wire(setup)
    req = public_batch()
    for key in ("source",):
        req[key]["url"] = "https://wx.mail.qq.com/home/index"
    req["reading"]["url"] = req["source"]["url"]
    req["reading"]["binding"]["origin"] = "https://wx.mail.qq.com"
    for f in req["fragments"]:
        f["context"]["frame_url"] = req["source"]["url"]
    with pytest.raises(ContractError, match="private_source_required"):
        await web.capture(1, req)
