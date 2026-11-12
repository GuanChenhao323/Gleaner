"""Manual monitoring harness: python -m devtools.monitoring.run [--real --target URL]."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import secrets
import signal
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from gleaner.monitoring.adapters.moodle import MoodleAdapter
from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.handoff import Handoff
from gleaner.monitoring.models import Clock, MonitorError, SitePolicy
from gleaner.monitoring.registry import Registry
from gleaner.monitoring.scheduler import Scheduler
from gleaner.monitoring.store import Store
from gleaner.monitoring.transport import HTTPXTransport, resolve
from gleaner.net.http import Request, Response
from gleaner.net.http.message import Headers
from gleaner.net.http.server import HTTPServer, ServerConfig

from devtools.fake_moodle.monitoring_fixture import MonitoringFixture

from .bridge_stub import normalize_cookies
from .dns import CloudflareDNS
from .report import Report, RunAudit
from .sink_stub import DebugSink

HTML = """<!doctype html><meta charset="utf-8"><title>Monitoring validation</title>
<style>body{font:16px system-ui;max-width:900px;margin:32px auto}input,button{font:inherit;margin:6px;padding:8px}pre{white-space:pre-wrap;background:#eee;padding:16px}</style>
<h1>Moodle 监测验证</h1><p>本地调试环境 · 桥接和业务回执均为替身</p>
<label>Cookie-Editor JSON（隐藏输入，仅驻内存）<input id="cookies" type="password" autocomplete="off"></label>
<button id="import">导入会话</button><button data-action="start">开始验证</button>
<button data-action="pause_bridge">暂停模拟心跳</button><button data-action="resume_bridge">恢复模拟心跳</button>
<button data-action="changed">模拟正文变化</button><button data-action="expired">模拟登录失效</button>
<button data-action="recover">恢复本地测试</button><button data-action="stop">停止并清理凭证</button>
<p id="message"></p><pre id="state">正在读取状态</pre>
<script>
const token='__TOKEN__';
async function send(body){const r=await fetch('/control',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Token':token},body:JSON.stringify(body)});const d=await r.json();document.getElementById('message').textContent=d.message||d.error||'已执行';await refresh();}
document.getElementById('import').onclick=async()=>{const input=document.getElementById('cookies');let value=input.value;input.value='';try{const records=JSON.parse(value);const approved=records.filter(c=>c.name==='MoodleSession'&&c.domain==='__COOKIE_HOST__');await send({action:'import',cookies:approved});}catch(e){document.getElementById('message').textContent='导入格式无效';}value='';};
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>send({action:b.dataset.action}));
async function refresh(){const r=await fetch('/state');document.getElementById('state').textContent=JSON.stringify(await r.json(),null,2);}
refresh();setInterval(refresh,2000);
</script>"""


class Harness:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args, self.clock = args, Clock()
        self.store, self.run_id = Store(args.database), str(uuid4())
        self.report = Report(Path(args.report))
        self.token = secrets.token_urlsafe(32)
        self.control = HTTPServer(
            self.handle,
            ServerConfig(host="127.0.0.1", port=args.port, max_body_bytes=262144),
        )
        self.fixture = None if args.real else MonitoringFixture()
        self.running, self.bridge_enabled, self.finished = False, True, False
        self.sequence, self.last_heartbeat, self.reported = 0, 0.0, 0
        self.first_success: float | None = None
        self.successes: list[float] = []
        self.failed_rounds = 0
        self.completed = asyncio.Event()
        self.summary = None

    async def setup(self) -> None:
        if self.fixture:
            self.fixture.server.config.port = self.store.meta("fixture_port", 0)
            await self.fixture.server.start()
            self.store.put_meta("fixture_port", self.fixture.server.port)
            origin = f"http://127.0.0.1:{self.fixture.server.port}"
            self.policy = SitePolicy(
                origin=origin, local_test=True, min_interval_s=2, host_gap_s=0.1
            )
            self.target = origin + "/mod/assign/view.php?id=7"
        else:
            self.policy = SitePolicy(target_urls=(self.args.target,))
            self.target = self.policy.canonical(self.args.target, target=True)
        self.auth = AuthManager(self.policy, self.clock)
        self.registry = Registry(self.store, self.auth, self.policy, self.clock)
        existing = self.store.sources()
        if existing:
            self.source = existing[0]
            if self.source.canonical_url != self.target:
                raise MonitorError("debug_database_target_mismatch")
            self.context = self.auth.context(self.source.auth_id)
        else:
            self.context = self.auth.create(1, "debug-browser")
            locator = "moodle:assign:" + parse_qs(urlsplit(self.target).query)["id"][0]
            self.store.save_item(1, 1, self.target, locator)
            self.source = self.registry.register(
                1,
                [1],
                "debug-browser",
                self.context.auth_id,
                self.policy.min_interval_s,
            )
        self.audit = RunAudit(self.policy.min_interval_s, self.args.duration)
        self.sink = DebugSink(self.store)
        self.handoff = Handoff(self.store, self.auth, self.sink)
        self.sink.fence = self.handoff.current
        adapter = MoodleAdapter()
        self.transport = HTTPXTransport(
            self.policy,
            self.auth,
            resolver=CloudflareDNS(self.policy.host)
            if getattr(self.args, "dns", "auto") == "cloudflare"
            else (resolve if getattr(self.args, "dns", "auto") == "system" else None),
            get_not_before=lambda: self.store.meta("host_not_before", 0),
            set_not_before=lambda t: self.store.put_meta("host_not_before", t),
            event=lambda e: self.report.append("request", e),
            inspect_access=adapter.inspect,
            registered_target_fallback=getattr(self.args, "robots_fallback", "strict")
            == "registered-target",
            policy_event=lambda e: self.report.append("policy", e),
        )
        self.scheduler = Scheduler(
            self.registry,
            self.transport,
            self.handoff,
            adapter=adapter,
            clock=self.clock,
        )
        if self.fixture:
            self.fake_credentials()
        await self.control.start()
        self.origin = f"http://127.0.0.1:{self.control.port}"
        commit = (
            await asyncio.to_thread(
                subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
            )
        ).strip()
        self.report.append(
            "run",
            {
                "run_id": self.run_id,
                "mode": "real" if self.args.real else "local",
                "execution_mode": "debug",
                "sink_kind": "stub",
                "python": sys.version.split()[0],
                "httpx": version("httpx"),
                "chrome": self.args.chrome_version,
                "adapter": MoodleAdapter.version,
                "commit": commit,
                "duration_s": self.args.duration,
                "dns_mode": getattr(self.args, "dns", "auto"),
                "robots_fallback": getattr(self.args, "robots_fallback", "strict"),
                "started_at": self.clock.utc(),
            },
        )
        print(self.origin, flush=True)

    def fake_credentials(self) -> None:
        self.auth.import_cookies(
            self.context.auth_id,
            [
                {
                    "name": "MoodleSession",
                    "value": "SYNTHETIC",
                    "domain": self.policy.host,
                    "path": "/",
                    "host_only": True,
                    "secure": True,
                    "http_only": True,
                    "same_site": "lax",
                    "session": True,
                    "expires_at": None,
                }
            ],
            backend_epoch=self.auth.backend_epoch,
            expected_revision=self.context.revision,
            request_id=str(uuid4()),
            reason="manual_reauthorize",
            confirmed_same_account=True,
        )

    def state(self) -> dict:
        source = self.store.source(self.source.source_id)
        return {
            "mode": "real" if self.args.real else "local",
            "sink_kind": "stub",
            "running": self.running,
            "auth_state": self.context.state,
            "runtime_status": source.runtime_status if self.running else "paused",
            "successful_fetch_parse_rounds": len(self.successes),
            "failed_rounds": self.failed_rounds,
            "elapsed_since_first_success_s": self.summary["elapsed_s"]
            if self.summary
            else round(self.clock.mono() - self.first_success, 1)
            if self.first_success
            else None,
            "next_due_at": source.next_due_at,
            "checks": self.store.checks()[-3:],
            "latest_observation": self.scheduler.observations[-1]
            if self.scheduler.observations
            else None,
            "finished": self.finished,
            "validation_summary": self.summary,
        }

    async def handle(self, request: Request) -> Response:
        if request.headers.get("Host") != urlsplit(self.origin).netloc:
            return Response.error(403, "host_denied")
        if request.headers.get("Sec-Fetch-Site") == "cross-site" and not (
            request.method == "GET"
            and request.path == "/"
            and request.headers.get("Sec-Fetch-Mode") == "navigate"
            and request.headers.get("Sec-Fetch-Dest") == "document"
        ):
            return Response.error(403, "origin_denied")
        if request.method == "GET" and request.path == "/":
            response = Response(
                200,
                body=HTML.replace("__TOKEN__", self.token)
                .replace("__COOKIE_HOST__", self.policy.host)
                .encode(),
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
                await self.action(data)
                response = Response.json_body({"message": "已执行；业务回执为模拟结果"})
            except MonitorError as error:
                response = Response.error(422, error.code, error.code)
            except (ValueError, TypeError, KeyError):
                response = Response.error(422, "invalid")
        else:
            response = Response.error(404, "not_found")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'"
        )
        return response

    async def action(self, data: dict) -> None:
        action = data["action"]
        if action == "import":
            if self.running:
                raise MonitorError("stop_before_reauthorize")
            records = normalize_cookies(data["cookies"], self.policy.host)
            self.auth.import_cookies(
                self.context.auth_id,
                records,
                backend_epoch=self.auth.backend_epoch,
                expected_revision=self.context.revision,
                request_id=str(uuid4()),
                reason="initial",
            )
        elif action == "start":
            if self.context.state not in ("unverified", "valid"):
                raise MonitorError("auth_required")
            self.running = True
        elif action in ("pause_bridge", "resume_bridge"):
            self.bridge_enabled = action == "resume_bridge"
            self.sequence += 1
            self.auth.presence("debug-browser", self.sequence, self.bridge_enabled)
            if not self.bridge_enabled and self.first_success is not None:
                self.audit.interrupt("bridge_paused")
                self.report.append(
                    "interruption",
                    {
                        "utc": self.clock.utc(),
                        "mono": self.clock.mono(),
                        "reason": "bridge_paused",
                    },
                )
                if self.args.real:
                    self.completed.set()
        elif action in ("changed", "expired", "recover") and self.fixture:
            self.fixture.scenario = "normal" if action == "recover" else action
            if action == "recover":
                self.fake_credentials()
                current = self.store.source(self.source.source_id)
                self.registry.configure(
                    current.source_id, 1, current.revision, enabled=True
                )
        elif action == "stop":
            self.running = False
            await self.auth.revoke(self.context.auth_id, self.context.revision)
            self.completed.set()
        else:
            raise MonitorError("invalid")

    async def loop(self) -> None:
        while not self.completed.is_set():
            if self.running:
                if self.clock.mono() - self.last_heartbeat >= 60:
                    self.sequence += 1
                    self.auth.presence(
                        "debug-browser", self.sequence, self.bridge_enabled
                    )
                    self.last_heartbeat = self.clock.mono()
                await self.scheduler.tick()
                for obs in self.scheduler.observations[self.reported :]:
                    obs = dict(obs)
                    receipt = (
                        self.store.receipt(obs["observation_id"])
                        if obs.get("observation_id")
                        else None
                    )
                    check = self.store.check(obs["check_id"])
                    obs["stub_receipt"] = {
                        "applied": bool(receipt and receipt.applied),
                        "state": check["state"],
                        "outcome": check["outcome"],
                        "results": receipt.results if receipt else [],
                    }
                    self.report.append("observation", obs)
                    if self.audit.observe(obs):
                        self.first_success = self.first_success or obs["mono"]
                        self.successes.append(obs["mono"])
                    else:
                        self.failed_rounds = self.audit.failed_rounds
                    if self.args.real and (
                        self.failed_rounds or self.context.state == "auth_required"
                    ):
                        self.running = False
                        self.completed.set()
                self.reported = len(self.scheduler.observations)
                self.audit.watchdog(self.clock.mono(), self.clock.utc())
                if self.args.real and self.audit.interruptions:
                    self.report.append(
                        "interruption",
                        {
                            "utc": self.clock.utc(),
                            "mono": self.clock.mono(),
                            "reason": self.audit.interruptions[-1],
                        },
                    )
                    self.completed.set()
                if (
                    self.first_success
                    and self.clock.mono() - self.first_success >= self.args.duration
                ):
                    self.completed.set()
            await asyncio.sleep(0.5)
        self.summary = self.audit.result(self.clock.mono(), self.clock.utc())
        self.report.append(
            "summary",
            {
                "run_id": self.run_id,
                "finished_at": self.clock.utc(),
                **self.summary,
            },
        )
        self.auth.close()
        self.running, self.finished = False, True

    async def close(self) -> None:
        self.auth.close()
        await self.transport.close()
        await self.control.close()
        if self.fixture:
            await self.fixture.server.close()
        self.store.close()


async def main(args: argparse.Namespace) -> None:
    harness = Harness(args)
    await harness.setup()
    shutdown = asyncio.Event()

    def stop() -> None:
        harness.completed.set()
        shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop)
    try:
        await harness.loop()
        print("validation finished; status UI remains available", flush=True)
        if args.exit_on_finish:
            return
        await shutdown.wait()
    finally:
        await harness.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--target", default="")
    parser.add_argument("--duration", type=float, default=7800)
    parser.add_argument("--report", default="data/monitoring/report.jsonl")
    parser.add_argument(
        "--database",
        default=":memory:",
        help="Optional independent SQLite file for synthetic restart tests",
    )
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--chrome-version", default="not_recorded")
    parser.add_argument(
        "--dns",
        choices=("auto", "system", "cloudflare"),
        default="auto",
        help="auto uses public DoH on Fake-IP; system disables fallback",
    )
    parser.add_argument("--exit-on-finish", action="store_true")
    parser.add_argument(
        "--robots-fallback",
        choices=("strict", "registered-target"),
        default="strict",
        help="Explicit single-target grant for the verified MUST robots-to-dashboard redirect only",
    )
    options = parser.parse_args()
    if options.real and (not options.target or options.duration < 7800):
        parser.error(
            "real validation needs an explicit target and duration >= 7800 seconds"
        )
    if options.real and options.database != ":memory:":
        parser.error(
            "real page content is memory-only; persistent databases are for synthetic tests"
        )
    if not options.real and options.dns == "cloudflare":
        parser.error("debug DoH is only available for an explicit real Moodle target")
    if not options.real and options.robots_fallback != "strict":
        parser.error(
            "registered-target fallback is only available for one explicit real Moodle target"
        )
    asyncio.run(main(options))
