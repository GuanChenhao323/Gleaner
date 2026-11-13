import pytest
from monitoring.report import Report, RunAudit


def success(at):
    return {
        "mono": at,
        "utc": 1700000000 + at,
        "authentication": "authenticated",
        "entries": [{"outcome": "content"}],
        "stub_receipt": {"applied": True, "state": "succeeded"},
    }


def test_long_silent_gap_cannot_pass_soak():
    audit = RunAudit(600, 7800)
    audit.observe(success(0))
    audit.observe(success(7301))
    result = audit.result(7801, 1700007801)
    assert not result["passed"] and result["missed_rounds"] > 0


def test_complete_real_time_sequence_and_explicit_pause():
    audit = RunAudit(600, 7800)
    for at in range(0, 7801, 600):
        assert audit.observe(success(at))
    assert audit.result(7801, 1700007801)["passed"]
    audit.interrupt("bridge_paused")
    assert not audit.result(7801, 1700007801)["passed"]


def test_sleep_wall_gap_and_missing_stub_receipt_fail():
    audit = RunAudit(600, 7800)
    audit.observe(success(0))
    resumed = success(600)
    resumed["utc"] += 3600
    audit.observe(resumed)
    assert audit.missed_rounds > 0
    other = RunAudit(600, 7800)
    missing = success(0)
    missing.pop("stub_receipt")
    assert not other.observe(missing)


def test_report_rejects_sensitive_field_names(tmp_path):
    report = Report(tmp_path / "report.jsonl")
    with pytest.raises(ValueError, match="report_field_denied"):
        report.append("request", {"cookie": "SYNTHETIC_SECRET"})
    with pytest.raises(ValueError, match="report_field_denied"):
        report.append("observation", {"entries": [{"text": "SYNTHETIC_PRIVATE_PAGE"}]})
    assert not report.path.exists()


async def test_legacy_report_accepts_real_dns_event_shapes_without_credentials(tmp_path):
    import json

    import httpx
    from monitoring_helpers import Stream

    from gleaner.monitoring.transport import CloudflareDNS

    report = Report(tmp_path / "report.jsonl")
    attempts = 0

    async def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectTimeout("SYNTHETIC_SECRET")
        return httpx.Response(
            200,
            stream=Stream(b'{"Status":0,"Answer":[{"type":1,"TTL":30,"data":"1.1.1.1"}]}'),
        )

    resolver = CloudflareDNS(
        "moodle.must.edu.mo",
        engine=httpx.MockTransport(handler),
        event=lambda e: report.append("policy", e),
    )
    assert await resolver("moodle.must.edu.mo", 443) == ["1.1.1.1"]
    rows = [json.loads(line) for line in report.path.read_text().splitlines()]
    assert [row["kind"] for row in rows] == ["dns_fallback", "dns_resolved"]
    assert "SYNTHETIC_SECRET" not in report.path.read_text()
    with pytest.raises(ValueError, match="report_field_denied"):
        report.append("policy", {"kind": "dns_failure", "headers": "SYNTHETIC_SECRET"})
