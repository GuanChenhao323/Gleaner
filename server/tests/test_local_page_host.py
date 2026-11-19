"""The normal browser lease and authenticated page check share one saved Moodle item."""

import hashlib
import json
import uuid

import pytest
from monitoring_helpers import cookie
from test_browser_capture import batch
from test_monitoring_moodle import page
from test_reading_sources import setup
from test_resident_monitoring import resident

from gleaner.monitoring.host import LocalPageHost
from gleaner.monitoring.models import SafeResponse
from gleaner.net.http import Headers, Request

URL = "https://moodle.must.edu.mo/mod/assign/view.php?id=7"


async def source_fixture(setup):
    reading, _, native, db = setup
    req = batch("scope", ("assignment:7",))
    req["binding"].update(adapter="moodle", origin="https://moodle.must.edu.mo")
    target = req["targets"][0]
    target["locator"].update(url=URL, frame_url=URL)
    target.update(supported=False, enabled=False)
    target["recipe"].pop("selector")
    target["recipe"].update(adapter="moodle", version=2, strategy="snapshot", url=URL)
    target["raw"] = {
        "title": "Lab 7",
        "text": "Original",
        "fields": {"course": "", "subtype": "moodle_assignment"},
    }
    req["reading"] = {
        "version": 1,
        "url": URL,
        "query": "lab 7",
        "source": "moodle",
        "match_scope": "content",
        "intent": {"version": 2, "query": "lab 7", "kind": "auto", "target": "lab 7", "fields": []},
        "view": {},
        "choice": "",
        "binding": req["binding"],
        "resident": resident(),
    }
    receipt = await native.capture(1, req)
    sid = receipt["reading_source_id"]
    job = (await reading.claim(1, {"device_id": req["device_id"]}))["job"]
    payload = {
        "schema_version": 1,
        "status": "success",
        "device_id": job["device_id"],
        "lease": job["lease"],
        "revision": job["revision"],
        "account_key": req["binding"]["account_key"],
        "resident": req["reading"]["resident"],
        "snapshot": {"binding": req["binding"], "targets": req["targets"]},
    }
    await reading.result(1, job["id"], payload)
    await db.execute("UPDATE reading_sources SET next_at=0 WHERE id=?", sid)
    return (
        await reading.own(1, sid),
        receipt["results"][0]["item_id"],
        req["reading"]["resident"]["page_id"],
    )


@pytest.mark.parametrize("case", ["changed", "wrong_account", "missing_intro"])
async def test_browser_protocol_handoff_real_contract(setup, tmp_path, case):
    reading, _, _, db = setup
    row, iid, pid = await source_fixture(setup)
    host = LocalPageHost(reading, tmp_path, 0, "a" * 32)
    await host.server.start()
    params = {"source_id": row["id"], "device_id": row["device_id"], "revision": row["revision"]}

    async def control(action, **fields):
        data = {**params, "action": action, **fields}
        req = Request(
            "POST",
            "/api/v1/page-control-ticket",
            headers=Headers({"Origin": host.origin}),
            body=json.dumps(data).encode(),
        )
        req.context["auth_via"] = "bearer"
        ticket = (await host.ticket(req, {"id": 1})).json()
        req = Request(
            "POST",
            "/api/monitor/v2/session",
            headers=Headers(
                {
                    "Origin": host.origin,
                    "Host": f"127.0.0.1:{host.server.port}",
                    "Content-Type": "application/json",
                    "X-Gleaner-Page-Ticket": ticket["ticket"],
                }
            ),
            body=json.dumps(data).encode(),
        )
        answer = await host.handle(req)
        assert answer.status == 200, answer.json()
        assert (await host.handle(req)).status == 401
        return answer.json()

    try:
        proof = hashlib.sha256(f"{host.epoch}|{row['id']}|moodle|42".encode()).hexdigest()
        await control("authorize", account_proof=proof, epoch=host.epoch)
        bound = reading.protocol.sessions[row["id"]]
        await reading.heartbeat(1, {"device_id": row["device_id"], "pages": {pid: "absent"}})
        await reading.protocol.tick()
        assert await db.fetchval("SELECT COUNT(*) FROM reading_jobs") == 1
        await control(
            "supply",
            cookies=[cookie()],
            epoch=host.epoch,
            auth_revision=0,
            request_id=str(uuid.uuid4()),
            reason="initial",
        )
        orig = bound.monitor.transport

        class Fixture:
            async def fetch(self, plan, lease):
                text = page(title="Lab 7", text="Updated").replace(
                    b"id=42", b"id=43" if case == "wrong_account" else b"id=42"
                )
                if case == "missing_intro":
                    text = text.replace(
                        b'<div id="intro"><div class="no-overflow">Updated</div></div>',
                        b'<div class="activity-dates"><p><strong>Due:</strong> 2027-06-12</p></div>',
                    )
                return SafeResponse(200, URL, "text/html", text)

        bound.monitor.transport = Fixture()
        try:
            assert (await reading.claim(1, {"device_id": row["device_id"]}))["job"] is None
            await reading.protocol.tick()
        finally:
            bound.monitor.transport = orig
        after = await reading.own(1, row["id"])
        if case == "missing_intro":
            assert after["last_result"] == "unsupported"
            assert await db.fetchval("SELECT body FROM items WHERE id=?", iid) == "Original"
        elif case == "wrong_account":
            assert after["last_result"] == "account_mismatch"
            assert await db.fetchval("SELECT body FROM items WHERE id=?", iid) == "Original"
        else:
            assert after["last_result"] == "changed"
            assert await db.fetchval("SELECT body FROM items WHERE id=?", iid) == "Updated"
            await reading.heartbeat(1, {"device_id": row["device_id"], "pages": {pid: "present"}})
            await db.execute("UPDATE reading_sources SET next_at=0 WHERE id=?", row["id"])
            assert (await reading.claim(1, {"device_id": row["device_id"]}))["job"]
    finally:
        await host.close()
