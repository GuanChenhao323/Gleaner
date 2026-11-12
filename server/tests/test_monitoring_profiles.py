import pytest
from monitoring_helpers import FakeClock, cookie

from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.models import MonitorError, SafeResponse, SitePolicy
from gleaner.monitoring.profiles import SessionInspector, page_policy

YT = "https://www.youtube.com/@3blue1brown/videos"
BILI = "https://www.bilibili.com/video/BV1Vd4y1e7pj/"


def imported(policy, records):
    auth = AuthManager(policy, FakeClock())
    c = auth.create(1, "bridge")
    auth.import_cookies(
        c.auth_id,
        records,
        backend_epoch=auth.backend_epoch,
        expected_revision=0,
        request_id="import",
    )
    return auth, c


def test_exact_targets_and_registered_profiles():
    policy = page_policy("youtube", YT)
    assert policy.canonical(YT, target=True) == YT
    assert policy.canonical(policy.origin + "/robots.txt").endswith("/robots.txt")
    for url in [
        YT + "?token=secret",
        "https://www.youtube.com/@other/videos",
        "https://evil.example/",
        "http://www.youtube.com/@3blue1brown/videos",
    ]:
        with pytest.raises(MonitorError):
            policy.canonical(url, target=True)
    for profile, url in [
        ("unknown", YT),
        ("youtube", BILI),
        ("youtube", "https://127.0.0.1/"),
        ("youtube", "https://user:secret@www.youtube.com/@x/videos"),
    ]:
        with pytest.raises(MonitorError):
            page_policy(profile, url)


async def test_domain_cookie_import_rotation_and_credential_isolation():
    policy = page_policy("youtube", YT)
    auth, c = imported(
        policy, [cookie("FIRST", name="SID", domain=".youtube.com", host_only=False)]
    )
    lease = await auth.acquire(c.auth_id)
    assert auth.header(lease, YT) == "SID=FIRST"
    generation = c.generation
    auth.update_cookies(lease, ["SID=SECOND; Domain=.youtube.com; Path=/; Secure; HttpOnly"], YT)
    assert auth.header(lease, YT) == "SID=SECOND"
    assert c.generation == generation
    for header in [
        "SID=EVIL; Domain=google.com; Path=/; Secure",
        "SID=EVIL; Domain=com; Path=/; Secure",
        "SID=; Domain=evil.example; Path=/; Secure; Max-Age=0",
    ]:
        auth.update_cookies(lease, [header], YT)
    assert auth.header(lease, YT) == "SID=SECOND"
    with pytest.raises(MonitorError, match="binding_denied"):
        auth.header(lease, "https://accounts.google.com/")
    auth.update_cookies(lease, ["SID=; Domain=youtube.com; Path=/; Secure; Max-Age=0"], YT)
    with pytest.raises(MonitorError, match="auth_required"):
        auth.header(lease, YT)


@pytest.mark.parametrize(
    "override",
    [
        {"domain": ".google.com"},
        {"domain": ".com"},
        {"host_only": True, "domain": ".youtube.com"},
        {"partitioned": True},
        {"value": "bad\nsecret"},
        {"name": "UNAPPROVED"},
        {"host_only": "false"},
        {"secure": "false"},
    ],
)
def test_cookie_scope_stays_closed(override):
    record = cookie(name="SID", domain=".youtube.com", host_only=False, **{})
    record.update(override)
    with pytest.raises(MonitorError):
        imported(page_policy("youtube", YT), [record])


def test_moodle_default_policy_is_unchanged():
    for override in [{"host_only": False}, {"domain": ".must.edu.mo"}, {"secure": False}]:
        with pytest.raises(MonitorError):
            imported(SitePolicy(), [cookie(**override)])


def test_login_evidence_is_separate_from_video_content():
    inspector = SessionInspector("youtube")

    def response(body):
        return SafeResponse(200, YT, "text/html", body)

    assert (
        inspector.inspect(response(b'<script>ytcfg.set({"LOGGED_IN":true});</script>')).state
        == "authenticated"
    )
    assert (
        inspector.inspect(response(b'<script>ytcfg.set({"LOGGED_IN":false});</script>')).state
        == "auth_required"
    )
    assert inspector.inspect(response(b'<p>"LOGGED_IN":true</p>')).state == "unknown"
    assert inspector.inspect(SafeResponse(403, YT, "text/html", b"")).state == "forbidden"
    assert inspector.inspect(SafeResponse(200, YT, "application/json", b"{}")).state == "unknown"


def test_bilibili_known_login_structure():
    inspector = SessionInspector("bilibili")
    body = b'<script>window.__INITIAL_STATE__={"loginInfo":{"isLogin":true,"mid":123}};</script>'
    result = inspector.inspect(SafeResponse(200, BILI, "text/html", body))
    assert result.state == "authenticated" and result.principal_key != "123"
    assert (
        inspector.inspect(SafeResponse(200, BILI, "text/html", b"<html></html>")).state == "unknown"
    )
