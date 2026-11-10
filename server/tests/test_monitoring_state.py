from dataclasses import asdict, replace

import pytest
from monitoring_helpers import FakeClock, cookie

from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.models import MonitorError, SitePolicy
from gleaner.monitoring.registry import Registry
from gleaner.monitoring.store import Store


def make():
    clock = FakeClock()
    auth = AuthManager(SitePolicy(), clock)
    context = auth.create(1, "bridge")
    return auth, context, clock


def import_one(auth, context, records=None, **kwargs):
    return auth.import_cookies(
        context.auth_id,
        records or [cookie()],
        backend_epoch=auth.backend_epoch,
        expected_revision=context.revision,
        request_id="request",
        **kwargs,
    )


@pytest.mark.parametrize(
    "override,code",
    [
        ({"domain": "login.must.edu.mo"}, "cookie_scope_denied"),
        ({"domain": ".must.edu.mo"}, "cookie_scope_denied"),
        ({"secure": False}, "cookie_scope_denied"),
        ({"host_only": False}, "cookie_scope_denied"),
        ({"path": "/course"}, "cookie_scope_denied"),
        ({"name": "SESSION"}, "cookie_scope_denied"),
        ({"value": "invalid\tvalue"}, "cookie_scope_denied"),
        ({"expires_at": 1}, "invalid"),
        ({"session": False, "expires_at": 1}, "auth_required"),
        ({"partitionKey": {"topLevelSite": "example.org"}}, "partitioned_cookie_unsupported"),
    ],
)
def test_cookie_import_boundaries(override, code):
    auth, c, _ = make()
    with pytest.raises(MonitorError, match=code):
        import_one(auth, c, [cookie(**override)])
    assert c.state == "needs_credentials" and len(c.jar) == 0


async def test_revision_idempotency_epoch_and_scope():
    auth, c, _ = make()
    first = import_one(auth, c)
    assert c.state == "unverified"
    assert "SYNTHETIC_SECRET" not in repr(first)
    replay = auth.import_cookies(
        c.auth_id,
        [cookie()],
        backend_epoch=auth.backend_epoch,
        expected_revision=0,
        request_id="request",
    )
    assert replay == first
    with pytest.raises(MonitorError, match="idempotency_conflict"):
        auth.import_cookies(
            c.auth_id,
            [cookie("DIFFERENT")],
            backend_epoch=auth.backend_epoch,
            expected_revision=0,
            request_id="request",
        )
    with pytest.raises(MonitorError, match="stale_backend"):
        auth.import_cookies(
            c.auth_id, [cookie()], backend_epoch="old", expected_revision=1, request_id="new"
        )
    lease = await auth.acquire(c.auth_id)
    auth.verify(lease, "principal-one")
    with pytest.raises(MonitorError, match="active_session"):
        auth.import_cookies(
            c.auth_id,
            [cookie()],
            backend_epoch=auth.backend_epoch,
            expected_revision=c.revision,
            request_id="new",
        )
    generation = c.generation
    auth.update_cookies(
        lease, ["MoodleSession=ROTATED; Path=/; Secure; HttpOnly"], auth.policy.origin
    )
    assert c.generation == generation and c.revision == 2
    assert auth.header(lease, auth.policy.origin + "/my/") == "MoodleSession=ROTATED"
    auth.update_cookies(
        lease, ["MoodleSession=EVIL; Domain=must.edu.mo; Path=/; Secure"], auth.policy.origin
    )
    assert "EVIL" not in auth.header(lease, auth.policy.origin + "/my/")
    await auth.revoke(c.auth_id, c.revision)
    with pytest.raises(MonitorError, match="superseded"):
        auth.update_cookies(lease, ["MoodleSession=OLD; Path=/; Secure"], auth.policy.origin)
    assert len(c.jar) == 0


async def test_account_change_and_unknown_principal_rules():
    auth, c, _ = make()
    import_one(auth, c)
    auth.verify(await auth.acquire(c.auth_id), "one")
    auth.import_cookies(
        c.auth_id,
        [cookie("NEW")],
        backend_epoch=auth.backend_epoch,
        expected_revision=c.revision,
        request_id="reauth",
        reason="manual_reauthorize",
    )
    with pytest.raises(MonitorError, match="account_mismatch"):
        auth.verify(await auth.acquire(c.auth_id), "two")
    assert not len(c.jar)
    auth, c, _ = make()
    import_one(auth, c)
    lease = await auth.acquire(c.auth_id)
    auth.verify(lease, None)
    auth.verify(lease, None)  # Ordinary repeated checks do not ask to rebind an account.
    with pytest.raises(MonitorError, match="account_confirmation_required"):
        auth.import_cookies(
            c.auth_id,
            [cookie()],
            backend_epoch=auth.backend_epoch,
            expected_revision=c.revision,
            request_id="again",
            reason="manual_reauthorize",
        )


def test_presence_monotonic_expiry_and_restart_metadata(tmp_path):
    auth, c, clock = make()
    first = auth.presence("bridge", 1)
    clock.advance(100)
    assert auth.presence("bridge", 1) == first
    with pytest.raises(MonitorError, match="revision_conflict"):
        auth.presence("bridge", 0)
    clock.advance(81)
    assert not auth.online("bridge")
    auth.presence("bridge", 2)
    assert auth.online("bridge")
    auth.presence("bridge", 3, False)
    assert not auth.online("bridge")
    import_one(auth, c)
    path = tmp_path / "monitor.db"
    store = Store(str(path))
    store.put_meta("auth", auth.metadata(c.auth_id))
    fresh = AuthManager(auth.policy, clock)
    restored = fresh.restore(store.meta("auth"))
    assert restored.state == "needs_credentials" and restored.generation > c.generation
    assert fresh.backend_epoch != auth.backend_epoch and not fresh.online("bridge")
    store.close()
    assert b"SYNTHETIC_SECRET" not in path.read_bytes()


def test_source_identity_ownership_merge_and_revision():
    auth, c, clock = make()
    store = Store()
    url = auth.policy.origin + "/mod/assign/view.php?id=7"
    store.save_item(1, 1, url, "moodle:assign:7")
    store.save_item(2, 1, url, "moodle:assign:7")
    store.save_item(3, 2, url, "moodle:assign:7")
    registry = Registry(store, auth, auth.policy, clock)
    source = registry.register(1, [1], "bridge", c.auth_id)
    same = registry.register(1, [1], "bridge", c.auth_id)
    assert asdict(source) == asdict(same)
    merged = registry.register(1, [2], "bridge", c.auth_id)
    assert merged.source_id == source.source_id and merged.revision == 2
    with pytest.raises(MonitorError, match="not_found"):
        registry.register(1, [3], "bridge", c.auth_id)
    with pytest.raises(MonitorError, match="revision_conflict"):
        registry.configure(source.source_id, 1, 1, enabled=False)
    first = registry.request_check(source.source_id, 1, "one")
    assert registry.request_check(source.source_id, 1, "two")["check_id"] == first["check_id"]
    assert registry.request_check(source.source_id, 1, "one") == first
    store.close()


@pytest.mark.parametrize(
    "expiry", ["Max-Age=0", "Max-Age=-1", "Expires=Thu, 01 Jan 1970 00:00:00 GMT"]
)
async def test_valid_scoped_deletion_clears_credentials(expiry):
    auth, c, _ = make()
    import_one(auth, c)
    lease = await auth.acquire(c.auth_id)
    auth.verify(lease, "principal")
    auth.update_cookies(lease, [f"MoodleSession=; Path=/; Secure; {expiry}"], auth.policy.origin)
    assert not len(c.jar) and c.state == "auth_required"
    with pytest.raises(MonitorError, match="auth_required"):
        await auth.acquire(c.auth_id)


async def test_opaque_lease_does_not_expose_manager_or_cross_context():
    auth, c, _ = make()
    import_one(auth, c)
    lease = await auth.acquire(c.auth_id)
    assert not hasattr(lease.opaque_handle, "contexts")
    other = auth.create(1, "bridge")
    import_one(auth, other)
    with pytest.raises(MonitorError, match="superseded"):
        auth.current(replace(lease, auth_id=other.auth_id, generation=other.generation))
    await auth.revoke(c.auth_id, c.revision)
    with pytest.raises(MonitorError, match="superseded"):
        auth.current(replace(lease, generation=c.generation))
