"""信息源连接器注册表。"""

from collections.abc import Awaitable, Callable

from .base import Context, FetchResult, Snapshot, SourceInfo, content_hash, normalize_url, url_alias
from .moodle import fetch_moodle
from .web import fetch_rss, fetch_teachers, fetch_web

CONNECTORS: dict[str, Callable[[Context], Awaitable[FetchResult]]] = {
    "moodle": fetch_moodle,
    "web": fetch_web,
    "rss": fetch_rss,
    "teacher": fetch_teachers,
}

__all__ = [
    "CONNECTORS",
    "Context",
    "FetchResult",
    "Snapshot",
    "SourceInfo",
    "content_hash",
    "normalize_url",
    "url_alias",
]
