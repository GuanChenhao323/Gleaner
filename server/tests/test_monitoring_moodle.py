from gleaner.monitoring.adapters.moodle import MoodleAdapter
from gleaner.monitoring.models import FetchPlan, MonitorSource, MonitorTarget, SafeResponse


def page(title="Task A", text="Read chapter 2", noise="Monday"):
    return f"""<html><body id="page-mod-assign-view" class="cmid-7"><div class="logininfo">
    <a href="/user/profile.php?id=42">Synthetic student</a><a href="/login/logout.php?sesskey=SECRET">Logout</a>
    </div><div class="page-header-headings"><h1>Synthetic course</h1></div>
    <section id="region-main"><div role="main"><h2>{title}</h2><div id="intro"><div class="no-overflow">{text}</div></div>
    <div class="submissionstatustable">PRIVATE SUBMISSION</div></div></section><footer>{noise}</footer></body></html>""".encode()


def select(body, locator="moodle:assign:7"):
    adapter = MoodleAdapter(b"test")
    source = MonitorSource(
        "s",
        1,
        "moodle",
        "https://moodle.must.edu.mo/mod/assign/view.php?id=7",
        "b",
        "a",
        targets=[MonitorTarget(1, locator)],
    )
    plan = FetchPlan("s", 1, 1, "c", source.canonical_url, (1,))
    response = SafeResponse(200, source.canonical_url, "text/html", body)
    return adapter.inspect(response), adapter.select(response, source, plan, 100)


def test_selected_content_and_independent_expected_values():
    verdict, batch = select(page())
    assert verdict.state == "authenticated" and verdict.principal_key
    entry = batch.entries[0]
    assert (entry.title, entry.text, entry.locator) == (
        "Task A",
        "Read chapter 2",
        "moodle:assign:7",
    )
    assert "PRIVATE" not in repr(batch) and "SECRET" not in repr(batch)
    assert select(page(noise="Tuesday"))[1].representation_hash == batch.representation_hash
    assert select(page(text="Read chapter 3"))[1].representation_hash != batch.representation_hash
    renamed = select(page(title="Task renamed"))[1]
    assert renamed.entries[0].locator == entry.locator
    assert renamed.representation_hash != batch.representation_hash


def test_login_forbidden_unknown_and_missing():
    adapter = MoodleAdapter()
    for status in (200, 403):
        r = SafeResponse(
            status, "https://moodle.must.edu.mo/my/", "text/html", b'<form id="login"></form>'
        )
        assert adapter.inspect(r).state == "auth_required"
    assert adapter.inspect(SafeResponse(403, "", "text/html", b"denied")).state == "forbidden"
    assert adapter.inspect(SafeResponse(200, "", "text/html", b"unknown")).state == "unknown"
    assert select(page(), "moodle:assign:8")[1].entries[0].outcome == "missing"
    changed = page().replace(b'id="intro"', b'id="new-structure"')
    assert select(changed)[1].entries[0].error == {"code": "parse_failed"}


def test_scripts_and_forms_are_not_observations():
    _, batch = select(page(text="Hello<script>EVIL()</script><form>credential</form><p>World</p>"))
    assert batch.entries[0].text == "Hello\nWorld"


def test_moodle_course_header_is_not_assignment_title():
    body = page(title="Synthetic assignment", text="<h2>Instructions</h2><p>Read chapter 2</p>")
    _, batch = select(body)
    assert batch.entries[0].title == "Synthetic assignment"
    assert select(body.replace(b"cmid-7", b"cmid-8"))[1].entries[0].error == {
        "code": "parse_failed"
    }
    assert select(body.replace(b"cmid-7", b"unknown"))[1].entries[0].error == {
        "code": "parse_failed"
    }
    missing_title = body.replace(b"<h2>Synthetic assignment</h2>", b"")
    assert select(missing_title)[1].entries[0].error == {"code": "parse_failed"}
    assert select(missing_title.replace(b"<h2>Instructions</h2>", b""))[1].entries[0].error == {
        "code": "parse_failed"
    }
