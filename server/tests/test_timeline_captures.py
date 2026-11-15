"""Summary collections keep account identity without inventing calendar events."""

import copy
import time
import uuid

import pytest
from test_reading_sources import run_job

from gleaner.core.monitors import BrowserMonitorService, ContractError
from gleaner.core.pipeline import Pipeline, item_public
from gleaner.core.reading_sources import ReadingSourceService
from gleaner.core.timeline_captures import TimelineCaptureContract
from gleaner.core.web_captures import WebCaptureService
from gleaner.storage.db import Database


def timeline_batch():
    url = "https://moodle.must.edu.mo/my/"
    binding = {
        "adapter": "moodle",
        "origin": "https://moodle.must.edu.mo",
        "account_key": "account-a",
    }
    return {
        "schema_version": 1,
        "collection_type": "timeline_summary",
        "request_id": str(uuid.uuid4()),
        "device_id": "fixture-device",
        "source": {"url": url, "title": "Dashboard"},
        "query": "Timeline",
        "match_scope": "content",
        "observed_at": time.time() * 1000,
        "source_binding": binding,
        "fragments": [
            {
                "candidate_id": f"candidate-{i}",
                "title": f"模拟活动{i}",
                "text": f"模拟活动{i} 摘要",
                "url": "https://moodle.must.edu.mo/mod/assign/view.php?id=1001",
                "fields": {
                    "course": "合成课程",
                    "date_text": f"November {15 + i}",
                    "datetime_text": "23:59",
                },
                "evidence": {
                    "channel": "dom",
                    "locator": f"div:nth-child({i})",
                    "text": f"November {15 + i}\n模拟活动{i} 摘要",
                },
                "context": {"frame_url": url, "region": "Timeline", "completeness": "summary"},
            }
            for i in (1, 2)
        ],
        "reading": {
            "version": 1,
            "representation": "timeline_summary",
            "source": "moodle",
            "url": url,
            "query": "Timeline",
            "match_scope": "content",
            "choice": "",
            "view": {},
            "intent": {
                "version": 2,
                "query": "Timeline",
                "kind": "auto",
                "target": "timeline",
                "fields": [],
            },
            "binding": binding,
        },
    }


@pytest.fixture
async def setup(tmp_path):
    db = await Database(f"sqlite:///{tmp_path / 'timeline.db'}").connect()
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
    native, web = BrowserMonitorService(db, pipeline), WebCaptureService(db, pipeline)
    timeline = WebCaptureService(db, pipeline, TimelineCaptureContract())
    reading = ReadingSourceService(db, web, native, timeline)
    for service in (native, web, timeline):
        service.on_capture, service.validate_reading = reading.attach, reading.validate_capture
    yield timeline, reading, db, web
    await db.close()


async def test_summary_group_save_and_repeated_request_have_one_reference(setup):
    timeline, reading, db, web = setup
    body = timeline_batch()
    receipt = await timeline.capture(1, body)
    assert await timeline.capture(1, body) == receipt
    assert receipt["capture_type"] == "timeline_summary"
    assert receipt["results"][0]["fragment_count"] == 2
    item = await db.fetchone("SELECT * FROM items WHERE id = ?", receipt["results"][0]["item_id"])
    assert item["kind"] == "clip" and item["deadline_at"] is None
    assert item_public(item)["web_capture"]["account_state"] == "bound"
    assert len(item_public(item)["web_capture"]["fragments"]) == 2
    assert await db.fetchval("SELECT COUNT(*) FROM browser_monitors") == 0
    assert len((await reading.list_sources(1))["sources"]) == 1
    assert (await web.collections(1))["collections"] == []
    body["request_id"] = str(uuid.uuid4())
    again = await timeline.capture(1, body)
    assert again["results"][0]["status"] == "unchanged"
    assert again["results"][0]["item_id"] == item["id"]
    body["request_id"] = str(uuid.uuid4())
    body["fragments"].reverse()
    assert (await timeline.capture(1, body))["results"][0]["status"] == "unchanged"


async def test_background_summary_changes_time_link_and_group_without_losing_personal_state(setup):
    timeline, reading, db, _ = setup
    body = timeline_batch()
    receipt = await timeline.capture(1, body)
    row = await reading.own(1, receipt["reading_source_id"])
    snapshot = {k: v for k, v in body.items() if k != "reading"}
    await run_job(reading, row, snapshot=snapshot, account="account-a")
    iid = receipt["results"][0]["item_id"]
    await db.execute(
        "UPDATE user_item_state SET note = ?, todo_status = ? WHERE user_id = 1 AND item_id = ?",
        "保留备注",
        "done",
        iid,
    )
    snapshot["fragments"][0]["url"] = "https://moodle.must.edu.mo/mod/quiz/view.php?id=2222"
    row = await reading.own(1, row["id"])
    _, _, ack = await run_job(reading, row, purpose="check", snapshot=snapshot, account="account-a")
    assert ack["result"] == "changed"
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", iid) == 2
    snapshot["fragments"][0]["fields"]["datetime_text"] = "22:00"
    _, _, ack = await run_job(reading, row, purpose="check", snapshot=snapshot, account="account-a")
    assert ack["result"] == "changed"
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", iid) == 3
    assert (
        await db.fetchval("SELECT note FROM user_item_state WHERE user_id = 1 AND item_id = ?", iid)
        == "保留备注"
    )
    snapshot["fragments"].reverse()
    for i, f in enumerate(snapshot["fragments"]):
        f["candidate_id"] = f"reordered-{i}"
        f["evidence"]["locator"] = f"div:nth-child({i + 20})"
    _, _, ack = await run_job(reading, row, purpose="check", snapshot=snapshot, account="account-a")
    assert ack["result"] == "unchanged"
    assert await db.fetchval("SELECT version FROM items WHERE id = ?", iid) == 3
    success = (await reading.own(1, row["id"]))["last_success_at"]
    await run_job(reading, row, purpose="check", status="need_login")
    failed = await reading.own(1, row["id"])
    assert failed["paused"] and not failed["verified"] and failed["last_success_at"] == success
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1


@pytest.mark.parametrize(
    "change",
    [
        "public",
        "account",
        "origin",
        "action",
        "cookie",
        "evidence",
        "context",
        "recipe",
        "scope",
        "missing_reading",
    ],
)
async def test_invalid_summary_cannot_overwrite_success(setup, change):
    timeline, _, db, _ = setup
    body = timeline_batch()
    await timeline.capture(1, body)
    body["request_id"] = str(uuid.uuid4())
    if change == "public":
        body["source_binding"]["account_key"] = "public"
    elif change == "account":
        body["source_binding"] = {**body["source_binding"], "account_key": "other"}
    elif change == "origin":
        body["fragments"][0]["url"] = "https://other.test/"
    elif change == "action":
        body["fragments"][0]["url"] += "&action=editsubmission"
    elif change == "cookie":
        body["source_binding"]["cookie"] = "not-accepted"
    elif change == "evidence":
        body["fragments"][0]["evidence"]["text"] = "different"
    elif change == "context":
        body["fragments"][0]["context"]["completeness"] = "detail"
    elif change == "recipe":
        body["reading"]["representation"] = "native"
    elif change == "scope":
        body["match_scope"] = "title"
    else:
        del body["reading"]
    with pytest.raises(ContractError):
        await timeline.capture(1, body)
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 1
    assert await db.fetchval("SELECT MAX(version) FROM items") == 1


async def test_accounts_and_owners_have_distinct_summary_identity(setup):
    timeline, _, db, _ = setup
    a = timeline_batch()
    first = await timeline.capture(1, a)
    b = copy.deepcopy(a)
    b["request_id"] = str(uuid.uuid4())
    b["source_binding"]["account_key"] = "account-b"
    second = await timeline.capture(1, b)
    b["request_id"] = str(uuid.uuid4())
    third = await timeline.capture(2, b)
    assert len({r["results"][0]["item_id"] for r in (first, second, third)}) == 3
    with pytest.raises(ContractError, match="not_found"):
        await timeline.request_result(2, a["request_id"])
    assert await db.fetchval("SELECT COUNT(*) FROM items") == 3


from test_e2e import stack  # noqa: E402,F401

from gleaner.net.http import HTTPClient  # noqa: E402


async def test_http_summary_receipt_details_and_source_association(stack):  # noqa: F811
    gw = f"http://127.0.0.1:{stack['gw'].info['port']}"
    async with HTTPClient() as client:
        registered = await client.post(
            gw + "/api/auth/register",
            json_body={"email": "timeline-http@test.local", "password": "test-password"},
        )
        auth = {"Authorization": "Bearer " + registered.json()["token"]}
        body = timeline_batch()
        saved = await client.post(gw + "/api/v1/timeline-captures", json_body=body, headers=auth)
        assert saved.status == 200, saved.text()
        receipt = saved.json()
        recovered = await client.get(
            gw + "/api/v1/timeline-captures/" + body["request_id"], headers=auth
        )
        assert recovered.json() == receipt
        detail = (
            await client.get(gw + f"/api/items/{receipt['results'][0]['item_id']}", headers=auth)
        ).json()
        assert detail["web_capture"]["collection_type"] == "timeline_summary"
        assert detail["reading_source"]["id"] == receipt["reading_source_id"]
        assert len(detail["web_capture"]["fragments"]) == 2
        assert (
            await client.get(gw + "/api/v1/web-captures/" + body["request_id"], headers=auth)
        ).status == 404
        assert (
            await client.post(gw + "/api/v1/web-captures", json_body=body, headers=auth)
        ).status == 422
        assert (await client.post(gw + "/api/v1/timeline-captures", json_body=body)).status == 401
