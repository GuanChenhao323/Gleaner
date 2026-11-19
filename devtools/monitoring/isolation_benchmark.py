"""Paired local replay experiments. A non-unit time scale is for smoke tests only."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import multiprocessing as mp
import platform
import random
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from bs4 import BeautifulSoup
from gleaner.monitoring.adapters.moodle import MoodleAdapter
from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.handoff import Handoff
from gleaner.monitoring.models import (
    AccessVerdict,
    MonitorSource,
    MonitorTarget,
    ObservationBatch,
    TargetObservation,
)
from gleaner.monitoring.profiles import PagePolicy
from gleaner.monitoring.registry import Registry
from gleaner.monitoring.scheduler import Scheduler, SiteScheduler
from gleaner.monitoring.store import Store
from gleaner.monitoring.transport import HTTPXTransport, resolve

from .isolation_replay import samples, start_replay
from .sink_stub import DebugSink


class ReplayAdapter(MoodleAdapter):
    def inspect(self, response):
        return (
            AccessVerdict("public", "replay_html")
            if response.status == 200
            else AccessVerdict("unknown", "response_status")
        )

    def select(self, response, source, plan, observed_at):
        soup = BeautifulSoup(response.body, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else ""
        entry = TargetObservation(
            source.targets[0].item_id,
            source.targets[0].locator,
            "content",
            plan.canonical_url,
            title=title,
            text=title,
        )
        return ObservationBatch(
            str(uuid4()),
            plan.check_id,
            source.source_id,
            source.revision,
            None,
            observed_at,
            "public-title/1",
            hashlib.sha256(response.body).hexdigest(),
            [entry],
        )


class TimedStore(Store):
    def finish(self, batch, check, source, receipt=None):
        super().finish(batch, check, source, receipt)
        self.receipts[batch.source_id] = time.monotonic()

    def __init__(self, path, marks, expected):
        super().__init__(str(path))
        self.receipts = {}
        self.marks, self.expected = marks, expected

    def enqueue(self, batch, check):
        if (
            len(batch.entries) != 1
            or batch.entries[0].title != self.expected[batch.source_id]
        ):
            raise ValueError("replay content mismatch")
        super().enqueue(batch, check)
        self.marks[batch.source_id] = time.monotonic()


async def baseline(routes):
    # Same co-due snapshot and sequential fetch/drain loop as e0a9f24, with origin routing.
    due = [
        (source.source_id, route, source, key)
        for route in routes
        for source, key, _ in route.due_round()
    ]
    for _, route, source, key in sorted(due, key=lambda row: row[0]):
        route.store.put_meta(
            key, route.clock.utc() + route.registry.policy.min_interval_s
        )
        check = route.registry.request_check(
            source.source_id,
            source.owner_id,
            f"timer:{source.revision}:{source.next_due_at}",
        )
        await route._execute(source, check)
        await route.handoff.drain()


async def measure(directory, scenario, seed, strategy, fault, scale):
    manifest_bytes = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    urls = samples()[scenario].copy()
    random.Random(seed).shuffle(urls)
    ids = {url: f"s-{i:03}" for i, url in enumerate(urls)}
    expected = {ids[url]: manifest[url]["marker"] for url in urls}
    slow = "go.dev" if scenario == "A" else "moodle.must.edu.mo"
    parent, child = mp.Pipe()
    worker = mp.Process(
        target=start_replay, args=(directory, urls, slow if fault else "", scale, child)
    )
    worker.start()
    child.close()
    routes = []
    marks = {}
    traces = []
    arrivals = []
    temp = tempfile.TemporaryDirectory()
    beat = lag_task = None
    lag = []
    heartbeat_count = 0
    try:
        ports = await asyncio.wait_for(asyncio.to_thread(parent.recv), 30)
        # Sort routes by the first eligible source just as the initial baseline queue is sorted.
        for host in dict.fromkeys(urlsplit(u).netloc for u in urls):
            originals = [url for url in urls if urlsplit(url).netloc == host]
            origin = f"http://127.0.0.1:{ports[host]}"
            local = {
                url: origin + url.removeprefix("https://" + host) for url in originals
            }
            policy = PagePolicy(
                origin=origin,
                target_urls=tuple(local.values()),
                local_test=True,
                cookie_domains=("127.0.0.1",),
                host_gap_s=2 * scale,
            )
            store = TimedStore(Path(temp.name) / f"{host}.sqlite", marks, expected)
            auth = AuthManager(policy)
            registry = Registry(store, auth, policy)
            moodle = host == "moodle.must.edu.mo"
            context = auth.create(1, "test") if moodle else None
            if context:
                auth.import_cookies(
                    context.auth_id,
                    [
                        {
                            "name": "MoodleSession",
                            "value": "SYNTHETIC",
                            "domain": "127.0.0.1",
                            "path": "/",
                            "host_only": True,
                            "secure": False,
                            "http_only": True,
                            "session": True,
                            "same_site": "lax",
                            "expires_at": None,
                        }
                    ],
                    backend_epoch=auth.backend_epoch,
                    expected_revision=0,
                    request_id="fixture",
                )
            auth.presence("test", 1)
            transport = HTTPXTransport(
                policy,
                auth,
                resolver=resolve,
                event=arrivals.append,
                get_not_before=lambda s=store: s.meta("host_not_before", 0),
                set_not_before=lambda t, s=store: s.put_meta("host_not_before", t),
            )
            handoff = Handoff(store, auth, DebugSink(store))
            route = Scheduler(
                registry,
                transport,
                handoff,
                adapter=MoodleAdapter() if moodle else ReplayAdapter(),
            )
            routes.append(route)
            for url in originals:
                item = int(ids[url][2:]) + 1
                locator = (
                    "moodle:assign:" + urlsplit(url).query[3:] if moodle else ids[url]
                )
                source = MonitorSource(
                    ids[url],
                    1,
                    policy.adapter_id,
                    local[url],
                    "test",
                    context.auth_id if context else None,
                    targets=[MonitorTarget(item, locator)],
                )
                store.save_source(source)

        # Warm robots using the same transport and lease. Reset request observations before timing.
        async def warm(route):
            source = route.store.sources()[0]
            lease = await route.auth.acquire(source.auth_id) if source.auth_id else None
            plan = route.adapter.plan(
                source, source.targets, "warm", lease.generation if lease else None
            )
            await route.transport.fetch(plan, lease)

        await asyncio.gather(*(warm(route) for route in routes))
        await asyncio.sleep(2 * scale)
        arrivals.clear()

        async def heartbeat():
            nonlocal heartbeat_count
            sequence = 2
            while True:
                for route in routes:
                    route.auth.presence("test", sequence)
                    heartbeat_count += 1
                sequence += 1
                await asyncio.sleep(30)

        async def sample_lag():
            while True:
                before = time.monotonic()
                await asyncio.sleep(0.1)
                lag.append(max(0, time.monotonic() - before - 0.1))

        beat = asyncio.create_task(heartbeat())
        lag_task = asyncio.create_task(sample_lag())
        cpu = time.process_time()
        start = time.monotonic()
        due = time.time()
        for route in routes:
            for source in route.store.sources():
                source.next_due_at = due
                route.store.save_source(source)
        cutoff = False
        try:
            async with asyncio.timeout(590 * scale + (5 if scale != 1 else 0)):
                if strategy == "baseline":
                    await baseline(routes)
                else:
                    await SiteScheduler(
                        routes,
                        concurrency=1 if strategy == "oldest_1" else 8,
                        round_robin=strategy == "round_robin",
                    ).tick()
        except TimeoutError:
            cutoff = True
        elapsed = time.monotonic() - start
        cpu = time.process_time() - cpu
        parent.send("stop")
        traces, memory = await asyncio.to_thread(parent.recv)
        measured = [r for r in traces if start <= r[2] <= start + elapsed]
        rss = [
            value
            for timestamp, value in memory
            if start <= timestamp <= start + elapsed
        ]
        initial = next(
            (value for timestamp, value in reversed(memory) if timestamp <= start), None
        )
        points = sorted(
            (timestamp, delta, host)
            for host, _, begin, end, _ in measured
            for timestamp, delta in [(begin, 1), (end, -1)]
        )
        active = peak = single_peak = 0
        by_site = {}
        for _, delta, host in points:
            active += delta
            by_site[host] = by_site.get(host, 0) + delta
            peak = max(peak, active)
            single_peak = max(single_peak, by_site[host])
        healthy = {ids[u] for u in urls if urlsplit(u).netloc != slow}

        def percentile(population, fraction):
            times = sorted(marks[k] - start for k in population if k in marks)
            index = math.ceil(len(population) * fraction) - 1
            return times[index] if index < len(times) else None

        events = Counter(event["kind"] for event in arrivals)
        checks = {c["source_id"]: c for route in routes for c in route.store.checks()}
        response_bytes = sum(
            manifest[url]["bytes"] for url in urls if ids[url] in marks
        )
        return {
            "cutoff": cutoff,
            "failed": sum(
                c["state"] in ("failed", "cancelled") for c in checks.values()
            ),
            "unfinished": len(urls)
            - sum(
                c["state"] in ("failed", "cancelled", "succeeded", "superseded")
                for c in checks.values()
            ),
            "response_bytes": response_bytes,
            "request_kinds": dict(events),
            "probe_requests": events["probe"],
            "bridge_heartbeats": heartbeat_count,
            "loop_lag_p95": sorted(lag)[math.ceil(0.95 * len(lag)) - 1]
            if lag
            else None,
            "checks": checks,
            "sources": {ids[u]: u for u in urls},
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "loop": type(asyncio.get_running_loop()).__name__,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "scenario": scenario,
            "seed": seed,
            "strategy": strategy,
            "fault": fault,
            "time_scale": scale,
            "seconds": elapsed,
            "cpu_seconds": cpu,
            "success": len(marks),
            "healthy": len(healthy),
            "healthy_success": len(healthy.intersection(marks)),
            "healthy_p95": percentile(healthy, 0.95),
            "healthy_p99": percentile(healthy, 0.99),
            "all_p95": percentile(expected, 0.95),
            "all_p99": percentile(expected, 0.99),
            "inflight_peak": peak,
            "site_peak": single_peak,
            "rss_initial": initial,
            "rss_peak": max(rss, default=initial),
            "cpu_percent": 100 * cpu / elapsed,
            "mbps": 8 * response_bytes / elapsed / 1e6,
            "receipts": {
                k: t - start
                for route in routes
                for k, t in route.store.receipts.items()
            },
            "http_requests": len(arrivals),
            "pages_per_second": len(marks) / elapsed,
            "window_success": sum(
                marks[k] - start <= (30 if scenario == "A" else 50) * scale
                for k in healthy
                if k in marks
            ),
            "marks": {k: v - start for k, v in marks.items()},
            "requests": measured,
            "synthetic": sum(manifest[u]["kind"] == "synthetic" for u in urls),
        }
    finally:
        monitors = [t for t in (beat, lag_task) if t]
        for task in monitors:
            task.cancel()
        await asyncio.gather(*monitors, return_exceptions=True)
        for route in routes:
            await route.transport.close()
            route.store.close()
        parent.close()
        if worker.is_alive():
            worker.terminate()
        worker.join()
        temp.cleanup()


async def main(args):
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        [json.loads(line) for line in dest.read_text().splitlines()]
        if dest.exists()
        else []
    )
    completed = {
        (r["scenario"], r["seed"], r["strategy"], r["fault"], r["time_scale"])
        for r in existing
    }
    with dest.open("a") as stream:  # noqa: ASYNC230 - outside the timed experiment
        for seed in range(args.rounds):
            for scenario in ("A", "B"):
                for fault in (False, True):
                    strategies = ["baseline", "round_robin"]
                    if args.mechanisms:
                        strategies = ["oldest_1", "oldest_8", "round_robin"]
                    if seed % 2:
                        strategies.reverse()
                    for strategy in strategies:
                        if (scenario, seed, strategy, fault, args.scale) in completed:
                            continue
                        child = await asyncio.create_subprocess_exec(
                            sys.executable,
                            "-m",
                            __spec__.name,
                            "--corpus",
                            args.corpus,
                            "--output",
                            args.output,
                            "--scale",
                            str(args.scale),
                            "--one",
                            scenario,
                            str(seed),
                            strategy,
                            str(int(fault)),
                            stdout=asyncio.subprocess.PIPE,
                        )
                        try:
                            output, _ = await child.communicate()
                        finally:
                            if child.returncode is None:
                                child.terminate()
                                await child.wait()
                        if child.returncode:
                            raise RuntimeError(f"round exited {child.returncode}")
                        result = json.loads(output)
                        stream.write(json.dumps(result) + "\n")
                        stream.flush()
                        print(
                            scenario,
                            seed,
                            strategy,
                            fault,
                            result["success"],
                            round(result["seconds"], 2),
                            flush=True,
                        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mechanisms", action="store_true")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--scale", type=float, default=1)
    parser.add_argument(
        "--one", nargs=4, metavar=("SCENARIO", "SEED", "STRATEGY", "FAULT")
    )
    args = parser.parse_args()
    if args.one:
        scenario, seed, strategy, fault = args.one
        print(
            json.dumps(
                asyncio.run(
                    measure(
                        Path(args.corpus),
                        scenario,
                        int(seed),
                        strategy,
                        bool(int(fault)),
                        args.scale,
                    )
                )
            )
        )
    else:
        asyncio.run(main(args))
