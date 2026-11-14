"""Generic collection identity, literal fragments, durable receipts and no monitors."""

import copy
import time
import uuid

import pytest

from gleaner.core.monitors import ContractError
from gleaner.core.pipeline import Pipeline, item_public
from gleaner.core.web_captures import WebCaptureService
from gleaner.storage.db import Database, loads


def batch():
    url = "https://unregistered.example.test/mail#inbox"
    return {
        "schema_version": 1,
        "request_id": str(uuid.uuid4()),
        "device_id": "fixture-device",
        "source": {"url": url, "title": "合成邮件列表"},
        "query": "项目会议",
        "match_scope": "content",
        "observed_at": time.time() * 1000,
        "source_binding": {"kind": "labeled", "label": "测试学校邮箱"},
        "fragments": [
            {
                "candidate_id": f"candidate-{i}",
                "title": f"项目会议 {i}",
                "text": f"项目会议 {i} 摘要，不代表完整邮件。",
                "evidence": {
                    "channel": "dom",
                    "locator": f"div:nth-child({i})",
                    "text": f"项目会议 {i} 摘要，不代表完整邮件。",
                },
                "context": {
                    "frame_url": url,
                    "boundary": "table_row",
                    "completeness": "fragment",
                    "matched_by": "literal",
                },
            }
            for i in (1, 2)
        ],
    }


@pytest.fixture
async def service(tmp_path):
    db = await Database(f"sqlite:///{tmp_path / 'web.db'}").connect()
    for uid in (1, 2):
        await db.insert(
            "users",
            {
                "id": uid,
                "email": f"test{uid}@example.test",
                "password_hash": "unused",
                "created_at": time.time(),
            },
        )
    events = []

    async def route(topic, payload):
        events.append((topic, payload))

    svc = WebCaptureService(db, Pipeline(db, route))
    yield svc, db, events
    await db.close()


async def test_collection_preserves_fragments_idempotency_and_no_monitor(service):
    svc, db, events = service
    req = batch()
    first = await svc.capture(1, req)
    assert first["candidate_ids"] == ["candidate-1", "candidate-2"]
    assert len(first["results"]) == 1
    row = first["results"][0]
    assert row["fragment_count"] == 2 and row["status"] == "new"
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1
    assert await db.fetchval("SELECT COUNT(*) FROM browser_monitors") == 0
    assert await db.fetchval("SELECT COUNT(*) FROM browser_jobs") == 0
    assert len(events) > 0
    assert await WebCaptureService(db, svc.pipeline).capture(1, req) == first
    assert await svc.request_result(1, req["request_id"]) == first
    item = await db.fetchone("SELECT * FROM items WHERE id = ?", row["item_id"])
    public = item_public(item)
    assert public["web_capture"]["account_state"] == "unverified"
    assert public["web_capture"]["monitoring"] is False
    assert public["web_capture"]["fragments"][1]["text"] == req["fragments"][1]["text"]
    assert item["deadline_at"] is None
    changed = copy.deepcopy(req)
    changed["source_binding"]["label"] = "另一个邮箱"
    with pytest.raises(ContractError, match="idempotency_conflict"):
        await svc.capture(1, changed)
    with pytest.raises(ContractError, match="not_found"):
        await svc.request_result(2, req["request_id"])


async def test_explicit_resave_updates_one_collection_version_without_positional_identity(service):
    svc, db, _ = service
    req = batch()
    first = (await svc.capture(1, req))["results"][0]
    await db.execute(
        "UPDATE user_item_state SET note = ?, todo_status = ? WHERE user_id = 1 AND item_id = ?",
        "用户自己的备注",
        "todo",
        first["item_id"],
    )
    req["request_id"] = str(uuid.uuid4())
    unchanged = (await svc.capture(1, req))["results"][0]
    assert unchanged["status"] == "unchanged" and unchanged["version"] == 1
    req["request_id"] = str(uuid.uuid4())
    req["fragments"] = req["fragments"][1:]
    req["fragments"][0]["text"] = req["fragments"][0]["evidence"]["text"] = (
        "项目会议摘要更新，具体时间待查阅。"
    )
    changed = (await svc.capture(1, req))["results"][0]
    assert changed["item_id"] == first["item_id"] and changed["capture_id"] == first["capture_id"]
    assert changed["status"] == "changed" and changed["version"] == 2
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1
    state = await db.fetchone(
        "SELECT * FROM user_item_state WHERE user_id = 1 AND item_id = ?", first["item_id"]
    )
    assert state["note"] == "用户自己的备注" and state["todo_status"] == "todo"
    version = await db.fetchone(
        "SELECT changed_fields FROM item_versions WHERE item_id = ? AND version = 2",
        first["item_id"],
    )
    assert "body" in loads(version["changed_fields"])
    assert len((await svc.collections(1))["collections"]) == 1
    assert not (await svc.collections(2))["collections"]


@pytest.mark.parametrize("variation", ["owner", "label", "public", "query", "scope", "hash"])
async def test_collection_isolation(service, variation):
    svc, db, _ = service
    req = batch()
    a = (await svc.capture(1, req))["results"][0]
    req["request_id"] = str(uuid.uuid4())
    uid = 2 if variation == "owner" else 1
    if variation == "label":
        req["source_binding"]["label"] = "个人邮箱"
    elif variation == "public":
        req["source_binding"] = {"kind": "public", "label": "公开网页"}
    elif variation == "query":
        req["query"] = "会议"
    elif variation == "scope":
        req["match_scope"] = "title"
    elif variation == "hash":
        req["source"]["url"] += "-other"
        for f in req["fragments"]:
            f["context"]["frame_url"] = req["source"]["url"]
    b = (await svc.capture(uid, req))["results"][0]
    assert a["item_id"] != b["item_id"]
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 2


@pytest.mark.parametrize(
    "variation",
    [
        "empty",
        "missing_label",
        "fake_public",
        "duplicate",
        "wrong_frame",
        "wrong_evidence",
        "shell",
        "too_big",
        "campus",
        "extra",
        "future",
    ],
)
async def test_invalid_capture_cannot_overwrite_previous_success(service, variation):
    svc, db, _ = service
    req = batch()
    await svc.capture(1, req)
    req["request_id"] = str(uuid.uuid4())
    if variation == "empty":
        req["fragments"] = []
    elif variation == "missing_label":
        req["source_binding"]["label"] = ""
    elif variation == "fake_public":
        req["source_binding"]["kind"] = "public"
    elif variation == "duplicate":
        req["fragments"][1]["candidate_id"] = "candidate-1"
    elif variation == "wrong_frame":
        req["fragments"][0]["context"]["frame_url"] = "https://other.test/"
    elif variation == "wrong_evidence":
        req["fragments"][0]["evidence"]["text"] = "different"
    elif variation == "shell":
        req["fragments"][0]["title"] = "Loading…"
    elif variation == "too_big":
        for f in req["fragments"]:
            f["text"] = f["evidence"]["text"] = "x" * 11000
    elif variation == "campus":
        req["source"]["url"] = "https://moodle.must.edu.mo/my/"
    elif variation == "extra":
        req["enabled"] = True
    elif variation == "future":
        req["observed_at"] += 600000
    with pytest.raises(ContractError):
        await svc.capture(1, req)
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1
    assert await db.fetchval("SELECT MAX(version) FROM items") == 1
