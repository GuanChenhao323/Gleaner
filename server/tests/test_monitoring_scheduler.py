import asyncio
from types import SimpleNamespace

import pytest
from monitoring.sink_stub import DebugSink
from monitoring_helpers import FakeClock, cookie
from test_monitoring_moodle import page

from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.handoff import Handoff
from gleaner.monitoring.models import MonitorError, SafeResponse, SitePolicy
from gleaner.monitoring.registry import Registry
from gleaner.monitoring.scheduler import Scheduler
from gleaner.monitoring.store import Store


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.body = page()
        self.error = None
        self.during = None

    async def fetch(self, plan, auth):
        self.calls.append(plan)
        if self.during:
            await self.during()
        if self.error:
            raise self.error
        return SafeResponse(200, plan.canonical_url, "text/html", self.body)


def system(path=":memory:", count=1, auth_required=True, port=8888):
    clock = FakeClock()
    policy = SitePolicy(origin=f"http://127.0.0.1:{port}", local_test=True)
    auth = AuthManager(policy, clock)
    c = auth.create(1, "b")
    auth.import_cookies(
        c.auth_id,
        [cookie(domain="127.0.0.1")],
        backend_epoch=auth.backend_epoch,
        expected_revision=0,
        request_id="initial",
    )
    auth.presence("b", 1)
    store = Store(str(path))
    registry = Registry(store, auth, policy, clock)
    for item_id in range(1, count + 1):
        store.save_item(item_id, 1, policy.origin + "/mod/assign/view.php?id=7", "moodle:assign:7")
    source = registry.register(
        1, list(range(1, count + 1)), "b", c.auth_id if auth_required else None
    )
    transport = FakeTransport()
    sink = DebugSink(store)
    handoff = Handoff(store, auth, sink)
    sink.fence = handoff.current
    scheduler = Scheduler(registry, transport, handoff, clock=clock)
    return SimpleNamespace(
        clock=clock,
        policy=policy,
        auth=auth,
        context=c,
        store=store,
        registry=registry,
        source=source,
        transport=transport,
        sink=sink,
        handoff=handoff,
        scheduler=scheduler,
    )


def wake(s, seconds=600):
    s.clock.advance(seconds)
    s.auth.presence("b", int(s.clock.mono()))


async def test_same_page_coalescing_intervals_and_changes():
    s = system(count=10)
    for i in range(20):
        s.registry.request_check(s.source.source_id, 1, str(i))
    assert await s.scheduler.tick() == 1
    assert len(s.transport.calls) == 1
    assert s.store.checks()[-1]["outcome"] == "changed"
    assert (
        len(
            s.store.receipt(
                s.store.db.execute("SELECT observation_id FROM monitor_receipts").fetchone()[0]
            ).results
        )
        == 10
    )
    assert await s.scheduler.tick() == 0
    wake(s)
    await s.scheduler.tick()
    assert s.store.checks()[-1]["outcome"] == "unchanged"
    s.transport.body = page(text="Read chapter 3")
    wake(s)
    await s.scheduler.tick()
    assert s.store.checks()[-1]["outcome"] == "changed"
    assert len(s.transport.calls) == 3
    s.store.close()


async def test_browser_pause_and_resume_skip_missed_rounds():
    s = system()
    await s.scheduler.tick()
    last = s.store.source(s.source.source_id).last_success_at
    s.clock.advance(3600)
    await s.scheduler.tick()
    assert s.store.source(s.source.source_id).runtime_status == "waiting_browser"
    assert s.store.source(s.source.source_id).last_success_at == last
    wake(s, 0)
    await s.scheduler.tick()
    assert len(s.transport.calls) == 2
    assert await s.scheduler.tick() == 0
    s.store.close()


async def test_failures_cooldown_and_authentication_pause():
    s = system()
    s.transport.error = MonitorError("timeout", retryable=True)
    for i in range(3):
        if i:
            wake(s)
        await s.scheduler.tick()
    assert len(s.transport.calls) == 3
    assert s.store.source(s.source.source_id).next_due_at >= s.clock.utc() + 1800
    wake(s, 1799)
    assert await s.scheduler.tick() == 0
    assert s.store.source(s.source.source_id).runtime_status == "backoff"
    wake(s, 1)
    s.transport.error = None
    s.transport.body = b'<form id="login"></form>'
    await s.scheduler.tick()
    assert s.context.state == "auth_required"
    last_count = len(s.transport.calls)
    wake(s, 10000)
    await s.scheduler.tick()
    assert len(s.transport.calls) == last_count
    assert s.store.source(s.source.source_id).last_success_at is None
    s.store.close()


@pytest.mark.parametrize("change", ["revoke", "revision"])
async def test_late_network_results_are_fenced(change):
    s = system()

    async def modify():
        if change == "revoke":
            await s.auth.revoke(s.context.auth_id, s.context.revision)
        else:
            s.registry.configure(s.source.source_id, 1, 1, enabled=False)

    s.transport.during = modify
    await s.scheduler.tick()
    assert s.store.checks()[-1]["state"] == "superseded"
    assert s.store.pending() == []
    assert s.store.source(s.source.source_id).last_success_at is None
    s.store.close()


async def test_retry_after_and_manual_checks_do_not_bypass_time():
    s = system()
    s.transport.error = MonitorError("rate_limited", retryable=True, retry_after_s=2400)
    await s.scheduler.tick()
    for i in range(5):
        s.registry.request_check(s.source.source_id, 1, f"manual{i}")
    wake(s, 600)
    assert await s.scheduler.tick() == 0
    assert len(s.transport.calls) == 1
    s.store.close()


async def test_empty_jar_does_not_escape_scheduler_error_handling():
    s = system()
    s.context.jar.clear()
    await s.scheduler.tick()
    assert s.context.state == "auth_required"
    assert s.store.checks()[-1]["state"] == "failed"
    assert s.store.checks()[-1]["error"] == "auth_required"
    assert not s.transport.calls
    s.store.close()


async def test_restart_restores_bindings_and_waits_for_credentials(tmp_path):
    path = tmp_path / "restart.db"
    s = system(path)
    await s.scheduler.tick()
    before = s.context.generation
    s.store.close()
    store = Store(str(path))
    fresh = AuthManager(s.policy, s.clock)
    registry = Registry(store, fresh, s.policy, s.clock)
    restored = fresh.context(s.context.auth_id)
    assert restored.state == "needs_credentials" and restored.generation > before
    fresh.presence("b", 1)
    sink = DebugSink(store)
    handoff = Handoff(store, fresh, sink)
    scheduler = Scheduler(registry, s.transport, handoff, clock=s.clock)
    assert await scheduler.tick() == 0
    assert store.source(s.source.source_id).runtime_status == "waiting_auth"
    store.close()


async def test_concurrent_ticks_do_not_overlap_requests():
    s = system()
    started, release = asyncio.Event(), asyncio.Event()

    async def delay():
        started.set()
        await release.wait()

    s.transport.during = delay
    first = asyncio.create_task(s.scheduler.tick())
    await started.wait()
    assert await asyncio.gather(*(s.scheduler.tick() for _ in range(10))) == [0] * 10
    release.set()
    await first
    assert len(s.transport.calls) == 1
    s.store.close()


async def test_slow_origin_does_not_delay_healthy_origin_receipt():
    from gleaner.monitoring.scheduler import SiteScheduler

    slow, healthy = system(), system(port=8889)
    entered, release = asyncio.Event(), asyncio.Event()
    received = asyncio.Event()

    async def slow_response():
        entered.set()
        await release.wait()

    original_apply = healthy.sink.apply

    async def healthy_receipt(batch):
        result = await original_apply(batch)
        received.set()
        return result

    slow.transport.during = slow_response
    healthy.sink.apply = healthy_receipt
    scheduler = SiteScheduler([slow.scheduler, healthy.scheduler])
    task = asyncio.create_task(scheduler.tick())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.wait_for(received.wait(), 1)
        assert await scheduler.tick() == 0
    finally:
        release.set()
        await task
        slow.store.close()
        healthy.store.close()
    assert task.result() == 2


async def test_occupied_session_does_not_use_global_network_slot():
    from gleaner.monitoring.scheduler import SiteScheduler

    busy, healthy = system(), system(port=8889)
    scheduler = SiteScheduler([busy.scheduler, healthy.scheduler], concurrency=1)
    received = asyncio.Event()

    async def mark():
        received.set()

    healthy.transport.during = mark
    async with busy.context.network_lock:
        task = asyncio.create_task(scheduler.tick())
        await asyncio.wait_for(received.wait(), 1)
        assert not busy.transport.calls
    assert await asyncio.wait_for(task, 1) == 2
    busy.store.close()
    healthy.store.close()


async def test_shared_quota_resumes_without_a_second_tick():
    from gleaner.monitoring.scheduler import SiteScheduler

    a, b = system(), system(port=8889)
    for item in (a, b):
        item.clock.utc = __import__("time").time
        source = item.store.source(item.source.source_id)
        source.next_due_at = item.clock.utc()
        item.store.save_source(source)
    a.store.put_meta("host_not_before", a.clock.utc() + 0.06)
    dispatcher = SiteScheduler(
        [a.scheduler, b.scheduler],
        quota_groups={a.policy.origin: "shared", b.policy.origin: "shared"},
    )
    assert await asyncio.wait_for(dispatcher.tick(), 1) == 2
    a.store.close()
    b.store.close()
