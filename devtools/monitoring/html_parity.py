"""Manual HTML-input experiment; not a production Extractor or Capture API.

Run with ``python -m devtools.monitoring.html_parity --report PATH``.
Both browser DOM and HTTP bytes enter exactly the same Python extraction function.
Real HTML and credentials remain in memory; reports contain only comparisons.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from gleaner.monitoring.adapters.moodle import MoodleAdapter
from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.models import (
    FetchPlan,
    MonitorError,
    MonitorSource,
    MonitorTarget,
    SafeResponse,
    SitePolicy,
)
from gleaner.monitoring.transport import HTTPXTransport, resolve
from gleaner.net.http import Request, Response
from gleaner.net.http.message import Headers
from gleaner.net.http.server import HTTPServer, ServerConfig

from .bridge_stub import normalize_cookies
from .dns import CloudflareDNS

VERSION = "assignment-html-parity-prototype/1"
DATE_FORMATS = (
    "%A, %d %B %Y, %I:%M %p",
    "%d %B %Y, %I:%M %p",
    "%A, %d %B %Y, %H:%M",
    "%d %B %Y, %H:%M",
    "%Y年%m月%d日 %H:%M",
    "%Y-%m-%d %H:%M",
)
DUE = re.compile(
    r"^(?:due(?: date)?|截止(?:日期|时间|時間)?|到期日)\s*[:：]?\s*", re.IGNORECASE
)


def deadline(html: bytes, timezone: str) -> dict:
    """Read only explicit deadline labels; never infer from arbitrary nearby dates."""
    soup = BeautifulSoup(html, "lxml")
    candidates = []
    for node in soup.select(".activity-dates div, [data-region='activity-dates'] div"):
        value = node.get_text(" ", strip=True)
        if DUE.match(value):
            candidates.append(DUE.sub("", value, count=1))
    # Older Moodle themes put the due row inside the submission status table.
    for row in soup.select(".submissionstatustable tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) >= 2 and DUE.fullmatch(cells[0].get_text(" ", strip=True)):
            candidates.append(cells[1].get_text(" ", strip=True))
    if not candidates:
        return {"state": "absent", "value": None}
    values = set()
    for candidate in candidates:
        cleaned = " ".join(candidate.replace("\xa0", " ").split())
        for fmt in DATE_FORMATS:
            try:
                parsed = dt.datetime.strptime(cleaned, fmt).replace(
                    tzinfo=ZoneInfo(timezone)
                )
                values.add(int(parsed.timestamp()))
                break
            except ValueError:
                continue
        else:
            return {"state": "unparseable", "value": None}
    if len(values) != 1:
        return {"state": "conflict", "value": None}
    return {"state": "present", "value": values.pop()}


def extract(html: bytes, url: str, timezone: str = "Asia/Macau") -> dict:
    """Use the existing target selector, with an explicitly experimental date reader."""
    locator = "moodle:assign:" + parse_qs(urlsplit(url).query)["id"][0]
    source = MonitorSource(
        "experiment",
        1,
        "moodle",
        url,
        "browser",
        None,
        targets=[MonitorTarget(1, locator)],
    )
    response = SafeResponse(200, url, "text/html", html)
    adapter = MoodleAdapter(b"local-parity-experiment")
    if adapter.inspect(response).state != "authenticated":
        raise MonitorError("not_authenticated")
    entry = adapter.select(
        response, source, adapter.plan(source, source.targets, "c", None), 0
    ).entries[0]
    if entry.outcome != "content":
        raise MonitorError("parse_failed")
    return {
        "locator": entry.locator,
        "title": entry.title,
        "text": entry.text,
        "deadline_at": deadline(html, timezone),
    }


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def compare(
    browser_html: bytes, http_html: bytes, url: str, timezone: str = "Asia/Macau"
) -> dict:
    browser_result, http_result = (
        extract(browser_html, url, timezone),
        extract(http_html, url, timezone),
    )
    fields = {}
    for key in browser_result:
        a, b = browser_result[key], http_result[key]
        fields[key] = {"equal": a == b}
        if key == "deadline_at":
            fields[key].update(browser_state=a["state"], http_state=b["state"])
        else:
            fields[key].update(browser_length=len(a or ""), http_length=len(b or ""))
    return {
        "extractor": VERSION,
        "timezone": timezone,
        "browser_html_bytes": len(browser_html),
        "http_html_bytes": len(http_html),
        "raw_html_equal": browser_html == http_html,
        "fields": fields,
        "all_fields_equal": browser_result == http_result,
        "four_fields_verified": browser_result == http_result
        and browser_result["deadline_at"]["state"] == "present"
        and bool(browser_result["title"] and browser_result["text"]),
        "browser_result_sha256": digest(browser_result),
        "http_result_sha256": digest(http_result),
        "raw_content_saved": False,
    }


def fixture(dynamic: bool = False) -> bytes:
    dates = '<div class="activity-dates"><div><strong>Due:</strong> Friday, 13 November 2026, 11:59 PM</div></div>'
    script = (
        "document.getElementById('dates').innerHTML=" + json.dumps(dates) + ";"
        if dynamic
        else "document.body.classList.add('js-ready');"
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Synthetic parity page</title></head>
    <body id="page-mod-assign-view" class="cmid-7"><a href="/login/logout.php">Logout</a>
    <section id="region-main"><div role="main"><h2>Assignment A</h2>
    <div id="intro"><div class="no-overflow"><p>Read chapter 2.</p><p>Submit a PDF.</p></div></div>
    <div id="dates">{"" if dynamic else dates}</div>
    <table class="submissionstatustable"><tr><th>Grade</th><td>PRIVATE SYNTHETIC DATA</td></tr></table>
    </div></section><script>{script}</script></body></html>""".encode()


UI = """<!doctype html><meta charset="utf-8"><title>HTML extraction comparison</title>
<style>body{font:16px system-ui;max-width:950px;margin:30px auto}label{display:block;margin:12px 0}input,textarea{display:block;width:95%;padding:8px}textarea{height:70px}button{padding:10px}pre{white-space:pre-wrap}</style>
<h1>HTML 提取一致性实验</h1><p>一次性本地验证 · HTML 与凭证仅驻内存 · 正式插件尚未接入</p>
<label>模式<select id="mode"><option value="static">本地静态日期</option><option value="dynamic">本地 JavaScript 日期</option><option value="real">已授权 MUST 作业</option></select></label>
<label>作业 URL<input id="url"></label>
<label>浏览器 DOM HTML<textarea id="html" autocomplete="off"></textarea></label>
<label>Cookie-Editor JSON（仅真实模式）<input id="cookies" type="password" autocomplete="off"></label>
<button id="compare">执行一次对比</button><pre id="result">等待输入</pre>
<script>
document.getElementById('compare').onclick=async()=>{
const body={mode:document.getElementById('mode').value,url:document.getElementById('url').value,html:document.getElementById('html').value,cookies:[]};
try{body.cookies=JSON.parse(document.getElementById('cookies').value||'[]');}catch{document.getElementById('result').textContent='Cookie JSON 格式错误';return;}
document.getElementById('html').value='';document.getElementById('cookies').value='';
document.getElementById('compare').disabled=true;
try{const r=await fetch('/compare',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Token':'TOKEN'},body:JSON.stringify(body)});document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2);}
finally{document.getElementById('compare').disabled=false;body.html='';body.cookies=[];}
};</script>"""


class Harness:
    def __init__(self, report: Path) -> None:
        self.report = report
        self.token = secrets.token_urlsafe(32)
        self.origin = ""
        self.dynamic = False
        self.last_real = 0.0
        self.lock = asyncio.Lock()
        self.server = HTTPServer(
            self.handle,
            ServerConfig(host="127.0.0.1", port=0, max_body_bytes=10 * 1024 * 1024),
        )

    async def fetch(self, data: dict) -> tuple[bytes, str, list]:
        real = data["mode"] == "real"
        url = data["url"]
        policy = (
            SitePolicy(target_urls=(url,))
            if real
            else SitePolicy(
                origin=self.origin, local_test=True, target_urls=(url,), host_gap_s=0.1
            )
        )
        url = policy.canonical(url, target=True)
        if real and time.monotonic() - self.last_real < 600:
            raise MonitorError("wait_for_account_interval")
        auth, lease, context = AuthManager(policy), None, None
        if real:
            context = auth.create(1, "html-parity")
            auth.import_cookies(
                context.auth_id,
                normalize_cookies(data["cookies"], policy.host),
                backend_epoch=auth.backend_epoch,
                expected_revision=context.revision,
                request_id=str(uuid4()),
            )
            lease = await auth.acquire(context.auth_id)
            self.last_real = time.monotonic()
        events = []
        transport = HTTPXTransport(
            policy,
            auth,
            resolver=CloudflareDNS(policy.host) if real else resolve,
            inspect_access=MoodleAdapter().inspect,
            registered_target_fallback=real,
            event=events.append,
            policy_event=events.append,
        )
        try:
            response = await transport.fetch(
                FetchPlan(
                    "parity", 1, lease.generation if lease else None, "c", url, (1,)
                ),
                lease,
            )
            if response.status != 200 or response.final_url != url:
                raise MonitorError("unexpected_response")
            return response.body, url, events
        finally:
            await transport.close()
            if context:
                await auth.revoke(context.auth_id, context.revision)
            data["cookies"] = []

    async def handle(self, request: Request) -> Response:
        if request.headers.get("Host") != urlsplit(self.origin).netloc:
            return Response.error(403, "host_denied")
        if request.method == "GET" and request.path == "/":
            response = Response(
                200,
                body=UI.replace("TOKEN", self.token).encode(),
                headers=Headers({"Content-Type": "text/html; charset=utf-8"}),
            )
        elif request.method == "GET" and request.path == "/robots.txt":
            response = Response(
                200,
                body=b"User-agent: *\nAllow: /",
                headers=Headers({"Content-Type": "text/plain"}),
            )
        elif request.method == "GET" and request.path == "/mod/assign/view.php":
            # Synthetic content only; the mode is set through the protected form.
            response = Response(
                200,
                body=fixture(self.dynamic),
                headers=Headers({"Content-Type": "text/html; charset=utf-8"}),
            )
        elif request.method == "POST" and request.path == "/compare":
            if request.headers.get("Origin") != self.origin or not hmac.compare_digest(
                request.headers.get("X-Debug-Token", ""), self.token
            ):
                return Response.error(403, "origin_denied")
            if (
                request.headers.get("Content-Type", "").split(";")[0]
                != "application/json"
            ):
                return Response.error(415, "content_type_denied")
            async with self.lock:
                try:
                    data = request.json()
                    if data["mode"] not in ("static", "dynamic", "real"):
                        raise MonitorError("invalid_mode")
                    self.dynamic = data["mode"] == "dynamic"
                    if not data["html"]:
                        # Configure the synthetic page before opening it in Chrome.
                        if data["mode"] == "real":
                            raise MonitorError("html_required")
                        return Response.json_body({"fixture_configured": data["mode"]})
                    http_html, url, events = await self.fetch(data)
                    result = compare(data["html"].encode(), http_html, url)
                    result.update(
                        mode=data["mode"],
                        captured_at=dt.datetime.now(dt.UTC).isoformat(),
                        requests=events,
                    )
                    self.report.parent.mkdir(parents=True, exist_ok=True)
                    with self.report.open("a") as stream:
                        stream.write(json.dumps(result, ensure_ascii=False) + "\n")
                    data["html"] = ""
                    response = Response.json_body(result)
                except MonitorError as error:
                    response = Response.error(422, error.code)
                except (ValueError, TypeError, KeyError):
                    response = Response.error(422, "invalid_input")
        else:
            response = Response.error(404, "not_found")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'"
        )
        return response


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    harness = Harness(args.report)
    await harness.server.start()
    harness.origin = f"http://127.0.0.1:{harness.server.port}"
    print(harness.origin, flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await harness.server.close()


if __name__ == "__main__":
    asyncio.run(main())
