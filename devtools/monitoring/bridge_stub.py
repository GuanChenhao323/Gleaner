"""Translate a local Cookie-Editor snapshot into the IC-003 import shape."""

from gleaner.monitoring.models import MonitorError


def normalize_cookies(records: object, host: str) -> list[dict]:
    if not isinstance(records, list):
        raise MonitorError("invalid")
    selected = []
    for record in records:
        if not isinstance(record, dict):
            raise MonitorError("invalid")
        # The debug input can receive the extension's site export. Only the approved cookie reaches AuthManager.
        if record.get("name") != "MoodleSession" or record.get("domain") != host:
            continue
        if (
            record.get("partitionKey")
            or record.get("partitioned")
            or record.get("incognito")
        ):
            raise MonitorError("partitioned_cookie_unsupported")
        session = record.get("session", "expirationDate" not in record)
        selected.append(
            {
                "name": record["name"],
                "value": record.get("value"),
                "domain": record["domain"],
                "path": record.get("path"),
                "host_only": record.get("hostOnly", record.get("host_only")),
                "secure": record.get("secure"),
                "http_only": record.get("httpOnly", record.get("http_only")),
                "same_site": record.get(
                    "sameSite", record.get("same_site", "unspecified")
                ),
                "session": session,
                "expires_at": None
                if session
                else record.get("expirationDate", record.get("expires_at")),
            }
        )
    if not selected:
        raise MonitorError("approved_cookie_missing")
    return selected
