"""Schedule policy; only synthetic loopback sources may use the explicit QA clock."""

from typing import Any
from urllib.parse import urlsplit

from ..storage.db import loads


class ReadingSchedule:
    def __init__(self, fixture_interval: int = 0) -> None:
        if fixture_interval not in (0, 60):
            raise ValueError("fixture reading interval must be 0 or 60")
        self.fixture_interval = fixture_interval

    def interval(self, row: dict[str, Any]) -> int:
        recipe = loads(row["recipe"])
        host = urlsplit(recipe["url"]).hostname
        if self.fixture_interval and host in {"localhost", "127.0.0.1", "::1"}:
            return self.fixture_interval
        return row["interval_s"]
