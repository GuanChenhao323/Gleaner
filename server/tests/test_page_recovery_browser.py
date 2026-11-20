"""Opt-in real Chromium extension test against an isolated loopback core and synthetic DOM."""

import asyncio
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

import pytest
import test_reading_sources as reading_tests
from test_local_page_host import URL, source_fixture

from gleaner.core.api import API
from gleaner.monitoring.host import LocalPageHost
from gleaner.net.http import HTTPServer, Router, ServerConfig
from gleaner.security import sign_token

setup = reading_tests.setup


@pytest.mark.skipif(
    os.getenv("GLEANER_TEST_CHROME") != "1", reason="explicit isolated Chromium run"
)
async def test_real_worker_local_presence_account_confirmation_and_revocation(setup, tmp_path):
    from playwright.async_api import async_playwright

    _, web, _, db = setup
    extension = tmp_path / "extension"
    shutil.copytree(
        Path(__file__).resolve().parents[2] / "extension",
        extension,
        ignore=shutil.ignore_patterns("node_modules", "tests"),
    )
    manifest = json.loads((extension / "manifest.json").read_text())
    manifest["host_permissions"] = ["http://127.0.0.1/*", "https://moodle.must.edu.mo/*"]
    (extension / "manifest.json").write_text(json.dumps(manifest))
    router = Router()

    async def publish(topic, payload):
        pass

    api = API(db, web.pipeline, publish)
    api.register(router)
    reading = api.reading
    srv = HTTPServer(router, ServerConfig(host="127.0.0.1", port=0))
    await srv.start()
    try:
        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                str(tmp_path / "test-profile"),
                channel="chromium",
                headless=True,
                args=[
                    "--disable-extensions-except=" + str(extension),
                    "--load-extension=" + str(extension),
                    "--host-resolver-rules=MAP moodle.must.edu.mo ~NOTFOUND",
                ],
            )
            try:
                worker = (
                    ctx.service_workers[0]
                    if ctx.service_workers
                    else await ctx.wait_for_event("serviceworker", timeout=15000)
                )
                ext_id = await worker.evaluate("chrome.runtime.id")
                host = LocalPageHost(reading, tmp_path, 0, ext_id)
                await host.start()
                try:

                    async def local_ticket(req, user):
                        return await host.ticket(req, user)

                    router.add("POST", "/api/v1/page-control-ticket", api.authed(local_ticket))
                    cfg = {
                        "server": f"http://127.0.0.1:{srv.port}",
                        "uid": 1,
                        "token": sign_token(
                            {
                                "uid": 1,
                                "tv": await db.fetchval(
                                    "SELECT token_version FROM users WHERE id=1"
                                ),
                            }
                        ),
                    }
                    device, salt = str(uuid.uuid4()), str(uuid.uuid4())
                    await worker.evaluate(
                        "(v)=>chrome.storage.local.set(v)",
                        {"config": cfg, "device": device, "salt": salt},
                    )
                    key = hashlib.sha256((salt + "|moodle|42").encode()).hexdigest()
                    row, _, _ = await source_fixture(
                        (reading, reading.web, reading.native, db), account=key, device=device
                    )
                    await ctx.route(
                        URL,
                        lambda route: route.fulfill(
                            status=200,
                            content_type="text/html",
                            body='<html><body id="page-mod-assign-view" data-userid="42" class="cmid-7"><section id="region-main"><h2>Lab 7</h2><p id="intro">Synthetic assignment</p></section></body></html>',
                        ),
                    )
                    target = await ctx.new_page()
                    await target.goto(URL)
                    tabs = await worker.evaluate("()=>chrome.tabs.query({})")
                    tab_id = next(t["id"] for t in tabs if t.get("url") == URL)
                    popup = await ctx.new_page()
                    await popup.goto(f"chrome-extension://{ext_id}/popup.html")

                    async def control(action):
                        reply = await popup.evaluate(
                            "(m)=>chrome.runtime.sendMessage(m)",
                            {
                                "type": "page-control.run",
                                "source_id": row["id"],
                                "action": action,
                                "tabId": tab_id,
                            },
                        )
                        assert reply["ok"], reply.get("error")
                        return reply["value"]

                    assert (await control("authorize"))["state"] == "needs_credentials"
                    assert (await control("status"))["state"] == "needs_credentials"
                    await target.close()
                    bound = reading.protocol.sessions[row["id"]]
                    await worker.evaluate(
                        "()=>chrome.alarms.create('local-page-session',{when:Date.now()+200,periodInMinutes:1})"
                    )
                    async with asyncio.timeout(65):
                        while not bound.monitor.auth.online(device):
                            await asyncio.sleep(0.1)
                    # Supply a deterministic fixture, never read browser cookies.
                    from monitoring_helpers import cookie

                    await bound.monitor.transport.close()

                    class NoNetwork:
                        async def fetch(self, *args):
                            raise AssertionError("no external upstream expected")

                        async def close(self):
                            pass

                    bound.monitor.transport = NoNetwork()

                    state = await host.session(
                        row,
                        {
                            "action": "supply",
                            "cookies": [cookie("SYNTHETIC")],
                            "auth_revision": 0,
                            "request_id": str(uuid.uuid4()),
                            "reason": "initial",
                            "epoch": host.epoch,
                        },
                    )
                    assert state["state"] == "unverified"
                    await host.close()
                    host = LocalPageHost(reading, tmp_path, 0, ext_id)
                    await host.start()
                    state = await control("status")
                    assert (
                        state["state"] == "needs_credentials"
                        and state["task_id"] == bound.task.task_id
                    )
                    assert (await control("revoke"))["state"] == "revoked"
                    target = await ctx.new_page()
                    await target.goto(URL)
                    tab_id = next(
                        t["id"]
                        for t in await worker.evaluate("()=>chrome.tabs.query({})")
                        if t.get("url") == URL
                    )
                    authorized = await control("authorize")
                    assert authorized["state"] == "needs_credentials"
                    await host.session(
                        row,
                        {
                            "action": "supply",
                            "cookies": [cookie("SYNTHETIC")],
                            "auth_revision": authorized["auth_revision"],
                            "request_id": str(uuid.uuid4()),
                            "reason": "manual_reauthorize",
                            "epoch": host.epoch,
                        },
                    )
                    logout = await popup.evaluate("()=>chrome.runtime.sendMessage({type:'logout'})")
                    assert logout["ok"]
                    last = reading.protocol.sessions[row["id"]]
                    assert last.monitor.auth.context(last.task.auth_context_id).state == "revoked"
                    assert (await worker.evaluate("()=>chrome.alarms.get('local-page-session')"))[
                        "periodInMinutes"
                    ] == 1
                finally:
                    await host.close()
            finally:
                await ctx.close()
    finally:
        await srv.close()
