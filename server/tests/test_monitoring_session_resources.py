import asyncio

import pytest
from monitoring_helpers import FakeClock, cookie

from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.models import MonitorError, SitePolicy


def setup():
    auth = AuthManager(SitePolicy(), FakeClock())
    context = auth.create(1, "bridge")
    return auth, context


def install(auth, context, value, request_id):
    auth.import_cookies(
        context.auth_id,
        [cookie(value)],
        backend_epoch=auth.backend_epoch,
        expected_revision=context.revision,
        request_id=request_id,
        reason="manual_reauthorize",
    )


async def test_revocation_fences_immediately_and_waits_for_runtime_cleanup():
    auth, context = setup()
    install(auth, context, "INITIAL", "one")
    lease = await auth.acquire(context.auth_id)
    fenced, started, release, cleaned = [], asyncio.Event(), asyncio.Event(), []

    async def cleanup():
        started.set()
        await release.wait()
        cleaned.append(True)

    def invalidate():
        fenced.append(True)
        return asyncio.create_task(cleanup())

    auth.attach_resource(context.auth_id, object(), invalidate)
    revoke = asyncio.create_task(auth.revoke(context.auth_id, context.revision))
    await started.wait()
    assert fenced and context.state == "revoked" and not len(context.jar)
    with pytest.raises(MonitorError, match="superseded"):
        auth.current(lease)
    assert not revoke.done()
    duplicate = asyncio.create_task(auth.revoke(context.auth_id, context.revision))
    await asyncio.sleep(0)
    assert not duplicate.done()
    release.set()
    await asyncio.gather(revoke, duplicate)
    assert cleaned


async def test_reauthorization_invalidates_old_runtime_without_erasing_new_jar():
    auth, context = setup()
    install(auth, context, "INITIAL", "one")
    lease = await auth.acquire(context.auth_id)
    invalidated = []
    auth.attach_resource(context.auth_id, object(), lambda: invalidated.append(True))
    install(auth, context, "REPLACEMENT", "two")
    assert invalidated == [True]
    with pytest.raises(MonitorError, match="superseded"):
        auth.current(lease)
    assert (
        auth.header(await auth.acquire(context.auth_id), auth.policy.origin)
        == "MoodleSession=REPLACEMENT"
    )


def test_only_the_bound_owner_can_replace_or_detach_a_resource():
    auth, context = setup()
    owner, other = object(), object()
    invalidated = []
    auth.attach_resource(context.auth_id, owner, lambda: invalidated.append(True))
    with pytest.raises(MonitorError, match="binding_denied"):
        auth.attach_resource(context.auth_id, other, lambda: None)
    auth.detach_resource(context.auth_id, other)
    auth.require_auth(context.auth_id)
    assert invalidated == [True]
    auth.detach_resource(context.auth_id, owner)
    auth.close()
    assert invalidated == [True]


def test_callback_failure_does_not_restore_credentials_or_expose_its_message():
    auth, context = setup()
    install(auth, context, "INITIAL", "one")

    def failing():
        raise ValueError("PRIVATE_RUNTIME_DETAIL")

    auth.attach_resource(context.auth_id, object(), failing)
    with pytest.raises(MonitorError, match="session_cleanup_failed") as error:
        install(auth, context, "REPLACEMENT", "two")
    assert "PRIVATE" not in str(error.value)
    assert context.state == "auth_required" and not len(context.jar)
    other = auth.create(1, "other")
    install(auth, other, "OTHER", "three")
    with pytest.raises(MonitorError, match="session_cleanup_failed"):
        auth.close()
    assert not len(other.jar) and other.state == "needs_credentials"
