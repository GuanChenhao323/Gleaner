from dataclasses import replace

from monitoring.sink_stub import DebugSink
from test_monitoring_scheduler import system, wake

from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.handoff import Handoff
from gleaner.monitoring.models import ApplyReceipt
from gleaner.monitoring.store import Store


async def test_delivery_retries_same_observation_without_refetch():
    s = system()
    s.sink.fail = True
    await s.scheduler.tick()
    batch = s.store.pending()[0]
    assert s.store.checks()[-1]["state"] == "processing"
    wake(s, 3600)
    await s.scheduler.tick()
    assert len(s.transport.calls) == 1
    assert s.store.pending()[0].observation_id == batch.observation_id
    s.sink.fail = False
    await s.handoff.drain()
    first = s.store.receipt(batch.observation_id)
    assert first and first.applied
    assert await s.sink.apply(batch) == first
    assert s.store.pending() == []
    assert s.store.source(s.source.source_id).last_success_at == batch.observed_at
    s.store.close()


async def test_outbox_and_idempotency_survive_process_recreation(tmp_path):
    path = tmp_path / "outbox.db"
    s = system(path, auth_required=False)
    s.sink.fail = True
    await s.scheduler.tick()
    batch = s.store.pending()[0]
    receipt = await DebugSink(s.store).apply(
        batch
    )  # Sink commit succeeds; caller crashes before acknowledgement.
    s.store.close()
    store = Store(str(path))
    auth = AuthManager(s.policy, s.clock)
    handoff = Handoff(store, auth, DebugSink(store))
    await handoff.drain()
    assert store.pending() == [] and store.receipt(batch.observation_id) == receipt
    store.close()


async def test_auth_restart_supersedes_old_observation(tmp_path):
    path = tmp_path / "outbox.db"
    s = system(path)
    s.sink.fail = True
    await s.scheduler.tick()
    metadata = s.auth.metadata(s.context.auth_id)
    s.store.close()
    store = Store(str(path))
    fresh = AuthManager(s.policy, s.clock)
    fresh.restore(metadata)
    await Handoff(store, fresh, DebugSink(store)).drain()
    assert store.pending() == [] and store.checks()[-1]["state"] == "superseded"
    store.close()


async def test_partial_failure_preserves_per_target_success_time():
    s = system(count=2)
    await s.scheduler.tick()
    old = s.store.target(s.source.source_id, 2)["last_success_at"]
    source = s.store.source(s.source.source_id)
    source.targets[1] = replace(source.targets[1], locator="moodle:assign:999")
    source.revision += 1
    s.store.save_source(source)
    wake(s)
    await s.scheduler.tick()
    assert s.store.checks()[-1]["outcome"] == "partial"
    assert s.store.target(s.source.source_id, 2)["last_success_at"] == old
    assert s.store.target(s.source.source_id, 1)["last_success_at"] > old
    assert s.store.source(s.source.source_id).last_success_at == old
    s.store.close()


async def test_mismatched_receipt_and_backpressure_do_not_complete():
    s = system()

    class InvalidSink:
        async def apply(self, batch):
            return ApplyReceipt("wrong", batch.source_id, batch.source_revision, True, [])

    s.handoff.sink = InvalidSink()
    s.scheduler.max_pending = 1
    await s.scheduler.tick()
    wake(s, 3600)
    await s.scheduler.tick()
    assert len(s.store.pending()) == 1 and len(s.transport.calls) == 1
    assert s.store.source(s.source.source_id).last_success_at is None
    s.store.close()


async def test_committed_receipt_survives_auth_epoch_change(tmp_path):
    path = tmp_path / "committed.db"
    s = system(path)
    s.sink.fail = True
    await s.scheduler.tick()
    batch = s.store.pending()[0]
    receipt = await DebugSink(s.store).apply(batch)
    meta = s.auth.metadata(s.context.auth_id)
    s.store.close()
    store = Store(str(path))
    fresh = AuthManager(s.policy, s.clock)
    fresh.restore(meta)
    await Handoff(store, fresh, DebugSink(store)).drain()
    assert store.receipt(batch.observation_id) == receipt
    assert store.checks()[-1]["state"] == "superseded"
    assert store.source(s.source.source_id).last_success_at is None
    store.close()
