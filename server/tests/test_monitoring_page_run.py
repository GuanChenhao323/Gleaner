import pytest
from devtools.monitoring.page_run import summarize


def rounds(starts, finished=None):
    return [
        {
            "state": "delivered",
            "mono": at + (finished or 1),
            "utc": 1000 + at + (finished or 1),
            "request_start_observed": True,
            "content_started_mono": at,
            "content_started_utc": 1000 + at,
        }
        for at in starts
    ]


def test_validation_requires_actual_request_span_not_delayed_delivery():
    records = rounds([0, 601])
    records[-1].update(mono=7201, utc=8201)
    result = summarize(records, 7200, 600)
    assert result["span_s"] == 601 and not result["passed"]


def test_two_hours_of_observed_authenticated_deliveries_pass():
    result = summarize(rounds(range(0, 7201, 600)), 7200, 600)
    assert result["passed"] and result["observed_content_requests"] == 13
    assert result["min_gap_s"] == result["max_gap_s"] == 600


@pytest.mark.parametrize("gap", [599, 641])
def test_too_short_or_missing_round_rejects_continuity(gap):
    assert not summarize(rounds([0, gap]), gap, 600)["passed"]


def test_unknown_timing_failed_round_and_wall_clock_jump_cannot_pass():
    records = rounds([0, 600])
    records[0]["request_start_observed"] = False
    assert not summarize(records, 600, 600)["passed"]
    records = [*rounds([0, 600]), {"state": "failed"}]
    assert not summarize(records, 600, 600)["passed"]
    records = rounds([0, 600])
    records[-1]["content_started_utc"] += 60
    assert not summarize(records, 600, 600)["passed"]
