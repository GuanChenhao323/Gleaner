"""Synthetic, offline checks for the manual shared-extractor experiment."""

import datetime as dt
import json

import pytest
from devtools.monitoring.html_parity import compare, deadline, extract, fixture

from gleaner.monitoring.models import MonitorError

URL = "https://moodle.must.edu.mo/mod/assign/view.php?id=7"
EXPECTED_DUE = int(dt.datetime(2026, 11, 13, 15, 59, tzinfo=dt.UTC).timestamp())


def test_independent_expected_values():
    assert extract(fixture(), URL) == {
        "locator": "moodle:assign:7",
        "title": "Assignment A",
        "text": "Read chapter 2.\nSubmit a PDF.",
        "deadline_at": {"state": "present", "value": EXPECTED_DUE},
    }


def test_dom_noise_does_not_change_fields_or_leak_content():
    browser = (
        fixture().replace(b"cmid-7", b"cmid-7 js-ready").replace(b"<h2>", b'<h2 tabindex="0">')
    )
    result = compare(browser, fixture(), URL)
    assert result["four_fields_verified"]
    assert not result["raw_html_equal"]
    for private in ("Assignment A", "PRIVATE SYNTHETIC DATA", "Read chapter 2"):
        assert private not in json.dumps(result)


def test_date_only_change_is_detected_with_stable_identity():
    changed = fixture().replace(b"13 November 2026", b"14 November 2026")
    result = compare(changed, fixture(), URL)
    assert result["fields"]["locator"]["equal"]
    assert result["fields"]["text"]["equal"]
    assert not result["fields"]["deadline_at"]["equal"]
    assert not result["four_fields_verified"]


def test_missing_dates_are_not_a_pass_and_js_content_is_not_executed():
    assert deadline(fixture(True), "Asia/Macau") == {"state": "absent", "value": None}
    assert not compare(fixture(True), fixture(True), URL)["four_fields_verified"]
    result = compare(fixture(), fixture(True), URL)
    assert not result["fields"]["deadline_at"]["equal"]
    assert result["fields"]["deadline_at"]["http_state"] == "absent"


def test_older_status_table_only_selects_due_row():
    html = b"""<table class="submissionstatustable"><tr><th>Grade</th><td>PRIVATE</td></tr>
    <tr><th>Due date</th><td>Friday, 13 November 2026, 11:59 PM</td></tr></table>"""
    assert deadline(html, "Asia/Macau") == {"state": "present", "value": EXPECTED_DUE}
    assert (
        deadline(html.replace(b"13 November 2026", b"some day"), "Asia/Macau")["state"]
        == "unparseable"
    )


def test_opened_and_last_modified_dates_do_not_override_due_date():
    html = (
        fixture()
        .replace(
            b'<div class="activity-dates">',
            b'<div class="activity-dates"><div>Opened: 2026-11-09 00:00</div>',
        )
        .replace(
            b"<th>Grade</th>",
            b"<th>Last modified</th>",
        )
    )
    assert extract(html, URL)["deadline_at"] == {"state": "present", "value": EXPECTED_DUE}


def test_conflicting_deadlines_are_not_a_pass():
    html = fixture() + b'<div class="activity-dates"><div>Due: 2026-11-14 23:59</div></div>'
    assert deadline(html, "Asia/Macau")["state"] == "conflict"
    assert not compare(html, html, URL)["four_fields_verified"]


@pytest.mark.parametrize(
    "html", [b'<form id="login"></form>', fixture().replace(b"cmid-7", b"cmid-8")]
)
def test_wrong_page_fails_closed(html):
    with pytest.raises(MonitorError):
        compare(html, html, URL)
