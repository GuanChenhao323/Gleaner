"""Manual parameter-driven HTML validation; never invoked by CI against real sites.

python -m devtools.monitoring.page_run --site youtube --target URL --report PATH
The loopback UI simulates the upstream caller and accepts Cookie-Editor JSON in memory.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import math
import re
import secrets
import signal
import time
from itertools import pairwise
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from bs4 import BeautifulSoup
from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.models import MonitorError
from gleaner.monitoring.pages import HTMLReceipt, HTMLSnapshot, PageMonitor
from gleaner.monitoring.profiles import SessionInspector, page_policy
from gleaner.monitoring.transport import HTTPXTransport
from gleaner.net.http import Request, Response
from gleaner.net.http.message import Headers
from gleaner.net.http.server import HTTPServer, ServerConfig

UI = """<!doctype html><meta charset="utf-8"><title>HTML monitoring validation</title>
<style>body{font:16px system-ui;max-width:900px;margin:32px auto}input,button,textarea{font:inherit;margin:6px;padding:8px}pre{white-space:pre-wrap;background:#eee;padding:16px}</style>
<h1>参数化 HTML 监测验证</h1><p>模拟上游 · 内存 HTML 接收替身 · 无业务内容提取</p>
<label>上游参数<textarea id="params" rows="6" cols="75">__PARAMS__</textarea></label><br>
<label>Cookie-Editor JSON<input id="cookies" type="password" autocomplete="off"></label>
<button id="start">导入并开始</button><button id="stop">停止并清理会话</button>
<p id="message"></p><pre id="status">等待导入</pre>
<script>const token='__TOKEN__';
async function send(action){let payload={action};if(action==='start'){const field=document.getElementById('cookies');let raw=field.value;field.value='';payload.params=JSON.parse(document.getElementById('params').value);payload.cookies=JSON.parse(raw);raw='';}const r=await fetch('/control',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Token':token},body:JSON.stringify(payload)});payload=null;document.getElementById('message').textContent=JSON.stringify(await r.json());await refresh();}
document.getElementById('start').onclick=()=>send('start').catch(()=>{document.getElementById('message').textContent='输入格式无效';});
document.getElementById('stop').onclick=()=>send('stop');
async function refresh(){const r=await fetch('/state');document.getElementById('status').textContent=JSON.stringify(await r.json(),null,2);}setInterval(refresh,3000);refresh();</script>"""


def normalize(records: object, names: tuple[str, ...]) -> list[dict]:
    if not isinstance(records, list):
        raise MonitorError("invalid_cookie_input")
    selected = []
    for c in records:
        if not isinstance(c, dict) or c.get("name") not in names:
            continue
        if (
            c.get("partitionKey") is not None
            or c.get("partitioned")
            or c.get("incognito")
        ):
            raise MonitorError("partitioned_cookie_unsupported")
        session = c.get("session", "expirationDate" not in c)
        same_site = c.get("sameSite", c.get("same_site"))
        if same_site is None:
            same_site = "unspecified"
        elif isinstance(same_site, str):
            same_site = same_site.lower()
        selected.append(
            {
                "name": c["name"],
                "value": c.get("value"),
                "domain": c.get("domain"),
                "path": c.get("path", "/"),
                "host_only": c.get("hostOnly", c.get("host_only")),
                "secure": c.get("secure"),
                "http_only": c.get("httpOnly", c.get("http_only", False)),
                "same_site": same_site,
                "session": session,
                "expires_at": None
                if session
                else c.get("expirationDate", c.get("expires_at")),
            }
        )
    return selected


class MemorySink:
    def __init__(self) -> None:
        self.receipts: dict[str, HTMLReceipt] = {}
        self.count = 0

    async def accept(self, snapshot: HTMLSnapshot) -> HTMLReceipt:
        if snapshot.snapshot_id not in self.receipts:
            self.receipts[snapshot.snapshot_id] = HTMLReceipt(
                snapshot.snapshot_id, True
            )
            self.count += 1
        # Full HTML reaches this boundary unchanged. No page or business data is retained.
        return self.receipts[snapshot.snapshot_id]


class DiagnosticAuthManager(AuthManager):
    """Compare rotations in memory; emit only registered names and change counts."""

    def __init__(self, policy, emit) -> None:
        super().__init__(policy)
        self.emit = emit

    def update_cookies(self, lease, headers, url) -> None:
        def snapshot():
            return {
                (c["name"], c["domain"], c["path"]): c
                for c in self.context(lease.auth_id).jar.to_list()
            }

        before = snapshot()
        super().update_cookies(lease, headers, url)
        after = snapshot()
        # Neither raw headers nor cookie values/hashes leave this method.
        self.emit(
            {
                "received_count": len(headers),
                "received_registered_names": sorted(
                    {
                        name
                        for header in headers
                        if (name := header.partition("=")[0].strip())
                        in self.policy.cookie_names
                    }
                ),
                "added_names": sorted({k[0] for k in after.keys() - before.keys()}),
                "removed_names": sorted({k[0] for k in before.keys() - after.keys()}),
                "changed_names": sorted(
                    {
                        k[0]
                        for k in before.keys() & after.keys()
                        if before[k] != after[k]
                    }
                ),
                "utc": time.time(),
            }
        )


class DiagnosticSessionInspector(SessionInspector):
    """Record only known structural signals, never page text or credential values."""

    def __init__(self, profile: str, emit) -> None:
        super().__init__(profile)
        self.emit = emit

    def inspect(self, response):
        verdict = super().inspect(response)
        if (
            self.profile in ("bilibili", "youtube")
            and response.status == 200
            and response.content_type.split(";")[0].strip().lower()
            in ("text/html", "application/xhtml+xml")
        ):
            soup = BeautifulSoup(response.body, "lxml")
            scripts = [script.string or "" for script in soup.find_all("script")]
            states = []
            pattern = (
                r"ytcfg\.set\s*\(\s*"
                if self.profile == "youtube"
                else r"(?:window\.)?__INITIAL_STATE__\s*=\s*"
            )
            for script in scripts:
                for match in re.finditer(pattern, script):
                    try:
                        data = json.JSONDecoder().raw_decode(script[match.end() :])[0]
                    except ValueError:
                        continue
                    if isinstance(data, dict):
                        states.append(data)
            if self.profile == "youtube":
                flags = [state.get("LOGGED_IN") for state in states]
                signals = {
                    "config_objects": len(states),
                    "logged_in_true": sum(flag is True for flag in flags),
                    "logged_in_false": sum(flag is False for flag in flags),
                }
            else:
                signals = {
                    "initial_state_objects": len(states),
                    "initial_state_login_info": any(
                        "loginInfo" in state for state in states
                    ),
                    "script_has_login_info_key": any(
                        re.search(r'["\']loginInfo["\']\s*:', script)
                        for script in scripts
                    ),
                    "script_has_is_login_key": any(
                        re.search(r'["\'](?:isLogin|is_login)["\']\s*:', script)
                        for script in scripts
                    ),
                    "has_logout_link": bool(soup.select_one('a[href*="logout"]')),
                }
            signals.update(verdict=verdict.state, evidence_code=verdict.evidence_code)
            self.emit(signals)
        return verdict


class Harness:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.policy = page_policy(args.site, args.target)
        self.auth = DiagnosticAuthManager(
            self.policy, lambda event: self.append("cookie_update", event)
        )
        self.context = self.auth.create(1, "debug-browser")
        self.inspector = DiagnosticSessionInspector(
            args.site, lambda signals: self.append("auth_diagnostic", signals)
        )
        self.sink = MemorySink()
        self.report = Path(args.report)
        self.report.parent.mkdir(parents=True, exist_ok=True)
        if self.report.exists():
            raise ValueError("report already exists; choose a new run path")
        self.run_id = str(uuid4())
        self.transport = HTTPXTransport(
            self.policy,
            self.auth,
            inspect_access=self.inspector.inspect,
            registered_target_fallback=args.robots_fallback == "registered-target",
            event=self.request_event,
            policy_event=lambda e: self.append("policy", e),
        )
        self.monitor = PageMonitor(
            self.policy, self.auth, self.transport, self.inspector, self.sink
        )
        self.token = secrets.token_urlsafe(32)
        self.server = HTTPServer(
            self.handle,
            ServerConfig(host="127.0.0.1", port=args.port, max_body_bytes=262144),
        )
        self.origin = ""
        self.running = False
        self.finished = False
        self.stop = asyncio.Event()
        self.rounds: list[dict] = []
        self.sequence = 0
        self.last_presence = 0.0
        self.last_cookie_count = 0
        self.last_cookie_revision = 0
        self.started_mono: float | None = None
        self.summary: dict | None = None
        self.params = {
            "target_url": args.target,
            "interval_s": args.interval,
            "auth_context_id": self.context.auth_id,
            "site_profile": args.site,
        }

    def append(self, kind: str, values: dict) -> None:
        with self.report.open("a") as stream:
            stream.write(
                json.dumps(
                    {"record": kind, "run_id": self.run_id, **values},
                    ensure_ascii=False,
                )
                + "\n"
            )

    def request_event(self, event: dict) -> None:
        count, revision = len(self.context.jar), self.context.revision
        self.append(
            "request",
            {
                k: v
                for k, v in event.items()
                if k
                in (
                    "kind",
                    "status",
                    "wire_bytes",
                    "decoded_bytes",
                    "started_mono",
                    "finished_mono",
                    "utc",
                    "redirect_same_origin",
                )
            }
            | {
                "previous_cookie_count": self.last_cookie_count,
                "cookie_count": count,
                "previous_cookie_revision": self.last_cookie_revision,
                "cookie_revision": revision,
            },
        )
        self.last_cookie_count, self.last_cookie_revision = count, revision

    async def setup(self) -> None:
        await self.server.start()
        self.origin = f"http://127.0.0.1:{self.server.port}"
        self.append(
            "run",
            {
                "site": self.args.site,
                "interval_s": self.args.interval,
                "duration_s": self.args.duration,
                "started_utc": time.time(),
                "execution_mode": "debug",
                "sink_kind": "memory_stub",
                "bridge_kind": "simulated",
                "target_sha256": hashlib.sha256(self.args.target.encode()).hexdigest(),
                "robots_fallback": self.args.robots_fallback,
            },
        )
        print(self.origin, flush=True)

    def state(self) -> dict:
        successes = [r for r in self.rounds if r["state"] == "delivered"]
        span = successes[-1]["mono"] - successes[0]["mono"] if successes else 0
        return {
            "site": self.args.site,
            "running": self.running,
            "finished": self.finished,
            "auth_state": self.context.state,
            "cookie_count": len(self.context.jar),
            "cookie_revision": self.context.revision,
            "auth_generation": self.context.generation,
            "successful_rounds": len(successes),
            "span_s": span,
            "next_due_at": self.monitor.next_due_at,
            "last_result": self.rounds[-1] if self.rounds else None,
            "summary": self.summary,
            "sink_kind": "memory_stub",
            "bridge_kind": "simulated",
        }

    async def handle(self, request: Request) -> Response:
        if request.headers.get("Host") != urlsplit(self.origin).netloc:
            return Response.error(403, "host_denied")
        if request.method == "GET" and request.path == "/":
            import html

            content = UI.replace("__TOKEN__", self.token).replace(
                "__PARAMS__", html.escape(json.dumps(self.params, indent=2))
            )
            response = Response(
                200,
                body=content.encode(),
                headers=Headers({"Content-Type": "text/html; charset=utf-8"}),
            )
        elif request.method == "GET" and request.path == "/state":
            response = Response.json_body(self.state())
        elif request.method == "POST" and request.path == "/control":
            if request.headers.get("Origin") != self.origin or not hmac.compare_digest(
                request.headers.get("X-Debug-Token", ""), self.token
            ):
                return Response.error(403, "origin_denied")
            if (
                request.headers.get("Content-Type", "").split(";")[0]
                != "application/json"
            ):
                return Response.error(415, "content_type_denied")
            try:
                data = request.json()
                if data["action"] == "start":
                    if self.running or self.finished or self.rounds:
                        raise MonitorError("new_run_required")
                    self.monitor.register(
                        data["params"], owner_id=1, bridge_id="debug-browser"
                    )
                    records = normalize(data["cookies"], self.policy.cookie_names)
                    self.auth.import_cookies(
                        self.context.auth_id,
                        records,
                        backend_epoch=self.auth.backend_epoch,
                        expected_revision=self.context.revision,
                        request_id=str(uuid4()),
                    )
                    data["cookies"] = []
                    self.last_cookie_count = len(self.context.jar)
                    self.last_cookie_revision = self.context.revision
                    self.append(
                        "session",
                        {
                            "event": "imported",
                            "cookie_count": self.last_cookie_count,
                            "cookie_revision": self.last_cookie_revision,
                            "registered_cookie_names": sorted(
                                {c["name"] for c in self.context.jar.to_list()}
                            ),
                            "utc": time.time(),
                        },
                    )
                    self.sequence += 1
                    self.auth.presence("debug-browser", self.sequence)
                    self.started_mono = time.monotonic()
                    self.last_presence = time.monotonic()
                    self.running = True
                elif data["action"] == "stop":
                    self.stop.set()
                else:
                    raise MonitorError("invalid_action")
                response = Response.json_body({"accepted": True})
            except MonitorError as error:
                response = Response.error(422, error.code)
            except (ValueError, KeyError, TypeError):
                response = Response.error(422, "invalid")
        else:
            response = Response.error(404, "not_found")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'"
        )
        return response

    async def loop(self) -> None:
        while not self.stop.is_set():
            if self.running:
                now = time.monotonic()
                if now - self.last_presence >= 60:
                    self.sequence += 1
                    self.auth.presence("debug-browser", self.sequence)
                    self.last_presence = now
                result = await self.monitor.tick()
                if result:
                    self.rounds.append(result)
                    self.append("round", result)
                    print(json.dumps({"site": self.args.site, **result}), flush=True)
                    if (
                        result["state"] != "delivered"
                        or len(self.rounds) > 1
                        and result["mono"] - self.rounds[0]["mono"]
                        >= self.args.duration
                        or self.args.duration == 0
                    ):
                        self.stop.set()
                if self.rounds and not self.stop.is_set():
                    last = self.rounds[-1]
                    if (
                        max(time.monotonic() - last["mono"], time.time() - last["utc"])
                        > self.args.interval + 40
                    ):
                        self.append(
                            "interruption",
                            {"reason": "missing_round", "utc": time.time()},
                        )
                        self.stop.set()
            await asyncio.sleep(0.5)
        successes = [r for r in self.rounds if r["state"] == "delivered"]
        span = successes[-1]["mono"] - successes[0]["mono"] if successes else 0
        wall_span = successes[-1]["utc"] - successes[0]["utc"] if successes else 0
        gaps = [
            max(b["mono"] - a["mono"], b["utc"] - a["utc"])
            for a, b in pairwise(successes)
        ]
        self.summary = {
            "successful_rounds": len(successes),
            "failed_rounds": len(self.rounds) - len(successes),
            "span_s": span,
            "wall_span_s": wall_span,
            "max_gap_s": max(gaps, default=0),
            "passed": bool(
                successes
                and span >= self.args.duration
                and wall_span >= self.args.duration
                and len(successes) == len(self.rounds)
                and all(g <= self.args.interval + 40 for g in gaps)
            ),
            "finished_utc": time.time(),
            "sink_kind": "memory_stub",
        }
        self.auth.close()
        self.monitor.pause()
        self.running = False
        self.finished = True
        self.append("summary", self.summary)
        print(json.dumps({"site": self.args.site, "summary": self.summary}), flush=True)

    async def close(self) -> None:
        self.auth.close()
        self.monitor.pause()
        await self.transport.close()
        await self.server.close()


async def main(args: argparse.Namespace) -> None:
    harness = Harness(args)
    shutdown = asyncio.Event()

    def stop() -> None:
        harness.stop.set()
        shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop)
    await harness.setup()
    try:
        await harness.loop()
        if not args.exit_on_finish:
            await shutdown.wait()
    finally:
        await harness.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site", choices=("moodle", "youtube", "bilibili"), required=True
    )
    parser.add_argument("--target", required=True)
    parser.add_argument("--interval", type=float, default=600)
    parser.add_argument("--duration", type=float, default=7200)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--robots-fallback", choices=("strict", "registered-target"), default="strict"
    )
    parser.add_argument("--exit-on-finish", action="store_true")
    options = parser.parse_args()
    if (
        not math.isfinite(options.interval)
        or options.interval < 600
        or not math.isfinite(options.duration)
        or options.duration < 0
    ):
        parser.error("interval >= 600 and duration >= 0 required")
    if options.site != "moodle" and options.robots_fallback != "strict":
        parser.error("registered-target is only the documented MUST robots fallback")
    asyncio.run(main(options))
