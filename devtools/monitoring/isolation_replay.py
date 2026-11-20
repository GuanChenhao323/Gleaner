"""Freeze the plan's corpus and serve identical responses on per-origin loopback ports."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import html
import json
import operator
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from gleaner.net.http import HTTPServer, Request, Response, ServerConfig
from gleaner.net.http.message import Headers

PLAN = (
    Path(__file__).resolve().parents[2]
    / "docs/exec-plans/active/2026-11-18-monitoring-slow-site-isolation.md"
)


def samples():
    public = []
    assignments = []
    for line in PLAN.read_text().splitlines():
        if re.match(r"^\| \d\d \|", line):
            public.extend(re.findall(r"\]\((https?://[^)]+)\)", line))
        if line.startswith("| ["):
            assignments.extend(
                re.findall(
                    r"\]\((https://moodle\.must\.edu\.mo/mod/assign/view\.php\?id=\d+)\)",
                    line,
                )
            )
    first = {}
    for url in public:
        first.setdefault(urlsplit(url).netloc, url)
    if len(set(public)) != 100 or len(first) != 50 or len(set(assignments)) != 60:
        raise ValueError("unexpected plan corpus")
    return {"A": public, "B": assignments + list(first.values())[:40]}


def synthetic(url):
    parsed = urlsplit(url)
    if parsed.hostname == "moodle.must.edu.mo":
        number = parsed.query.removeprefix("id=")
        marker = f"Assignment {number}"
        body = f'<html><body id="page-mod-assign-view" class="cmid-{number}"><div class="logininfo"><a href="/user/profile.php?id=42">Test</a><a href="/login/logout.php">Logout</a></div><section id="region-main" role="main"><h2>{marker}</h2><div id="intro">Synthetic assignment {number}</div></section></body></html>'
    else:
        marker = "Replay " + url
        body = f"<html><head><title>{html.escape(marker)}</title></head><body><main><h1>{html.escape(marker)}</h1></main></body></html>"
    return marker, body.encode()


def freeze(directory: Path, snapshots: Path | None = None):
    """Use pre-frozen public HTML if available; mark each synthetic replacement explicitly."""
    directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for url in dict.fromkeys(functools.reduce(operator.iadd, samples().values(), [])):
        key = hashlib.sha256(url.encode()).hexdigest()
        marker, body = synthetic(url)
        kind = "synthetic"
        cached = snapshots / (key + ".html") if snapshots else None
        if (
            cached
            and cached.exists()
            and urlsplit(url).hostname != "moodle.must.edu.mo"
        ):
            candidate = cached.read_bytes()
            title = BeautifulSoup(candidate, "lxml").title
            if title and title.get_text(strip=True):
                body, marker, kind = candidate, title.get_text(strip=True), "frozen"
        (directory / (key + ".html")).write_bytes(body)
        result[url] = {
            "file": key + ".html",
            "marker": marker,
            "kind": kind,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
    (directory / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    return result


async def serve(directory, urls, slow_host, delay_scale, pipe):
    manifest = json.loads((directory / "manifest.json").read_text())
    servers = {}
    traces = []
    memory = []
    parent_pid = os.getppid()

    async def sample_memory():
        while True:
            process = await asyncio.create_subprocess_exec(
                "ps", "-o", "rss=", "-p", str(parent_pid), stdout=subprocess.PIPE
            )
            value, _ = await process.communicate()
            if value.strip().isdigit():
                memory.append((time.monotonic(), int(value) * 1024))
            await asyncio.sleep(0.1)

    def handler(host, pages):
        async def respond(req: Request):
            if req.path == "/robots.txt":
                return Response(
                    200,
                    body=b"User-agent: *\nAllow: /",
                    headers=Headers({"Content-Type": "text/plain"}),
                )
            if req.target not in pages:
                return Response.error(404, "unknown page")
            if (
                host == "moodle.must.edu.mo"
                and req.headers.get("cookie") != "MoodleSession=SYNTHETIC"
            ):
                return Response(403)
            start = asyncio.get_running_loop().time()
            await asyncio.sleep((8 if host == slow_host else 0.1) * delay_scale)
            body = pages[req.target]
            traces.append(
                [host, req.target, start, asyncio.get_running_loop().time(), len(body)]
            )
            return Response(
                200,
                body=body,
                headers=Headers({"Content-Type": "text/html; charset=utf-8"}),
            )

        return respond

    groups = {}
    for url in urls:
        parts = urlsplit(url)
        entry = manifest[url]
        body = (directory / entry["file"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError("snapshot checksum mismatch")
        groups.setdefault(parts.netloc, {})[
            parts.path + ("?" + parts.query if parts.query else "")
        ] = body
    try:
        for host, pages in groups.items():
            srv = HTTPServer(
                handler(host, pages), ServerConfig(host="127.0.0.1", port=0)
            )
            await srv.start()
            servers[host] = srv
        sampler = asyncio.create_task(sample_memory())
        pipe.send({host: srv.port for host, srv in servers.items()})
        await asyncio.to_thread(pipe.recv)
        sampler.cancel()
        await asyncio.gather(sampler, return_exceptions=True)
        pipe.send((traces, memory))
    finally:
        for srv in servers.values():
            await srv.close()


def start_replay(*args):
    asyncio.run(serve(*args))


async def sample_public(directory: Path):
    from gleaner.monitoring.auth import AuthManager
    from gleaner.monitoring.models import FetchPlan, MonitorError
    from gleaner.monitoring.profiles import PagePolicy
    from gleaner.monitoring.transport import HTTPXTransport

    directory.mkdir(parents=True, exist_ok=True)
    by_origin = {}
    for url in samples()["A"]:
        by_origin.setdefault("https://" + urlsplit(url).netloc, []).append(url)
    limit = asyncio.Semaphore(4)
    states = {}

    async def collect(origin, urls):
        policy = PagePolicy(origin=origin, target_urls=tuple(urls))
        transport = HTTPXTransport(policy, AuthManager(policy), total_timeout=12)
        try:
            for url in urls:
                try:
                    async with limit:
                        response = await transport.fetch(
                            FetchPlan("sample", 1, None, "sample", url, ()), None
                        )
                    soup = BeautifulSoup(response.body, "lxml")
                    title = soup.title.get_text(strip=True) if soup.title else ""
                    if (
                        response.status != 200
                        or "html" not in response.content_type
                        or not title
                        or re.search(
                            r"just a moment|access denied|captcha|sign in|log in",
                            title,
                            re.IGNORECASE,
                        )
                    ):
                        raise MonitorError("unusable_page")
                    (
                        directory / (hashlib.sha256(url.encode()).hexdigest() + ".html")
                    ).write_bytes(response.body)
                    states[url] = "frozen"
                except MonitorError as err:
                    states[url] = err.code
        finally:
            await transport.close()

    await asyncio.gather(*(collect(origin, urls) for origin, urls in by_origin.items()))
    (directory / "sampling.json").write_text(json.dumps(states, indent=2))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    asyncio.run(sample_public(args.directory / "public"))
    frozen = freeze(args.directory / "corpus", args.directory / "public")
    print(
        f"{sum(row['kind'] == 'frozen' for row in frozen.values())} public snapshots, {len(frozen)} unique pages"
    )
