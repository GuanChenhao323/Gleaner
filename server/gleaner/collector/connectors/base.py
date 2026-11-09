"""连接器公共结构。每个连接器把一个信息源变成一组“事项快照”。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..fetcher import Fetcher, FetchError
from ..session import SourceSession, looks_like_login


def normalize_url(url: str) -> str:
    """规范化链接用作身份键：小写主机、去掉片段与默认端口。"""
    p = urlsplit(url)
    netloc = p.hostname or ""
    if p.port and p.port not in (80, 443):
        netloc += f":{p.port}"
    return urlunsplit((p.scheme.lower(), netloc.lower(), p.path.rstrip("/") or "/", p.query, ""))


def url_alias(url: str) -> str:
    """跨渠道合并用的别名键：只看路径与查询，忽略主机名差异（邮件里的链接可能用外网域名）。"""
    p = urlsplit(url)
    return f"url:{p.path.rstrip('/')}?{p.query}"


@dataclass
class SourceInfo:
    id: int
    type: str
    endpoint: str
    config: dict[str, Any]
    course: str = ""
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    cache: dict[str, Any] = field(default_factory=dict)  # 每个 URL 的条件请求状态与解析结果


@dataclass
class Snapshot:
    key: str
    kind: str  # assignment / notice / rss / teacher / mail
    title: str
    url: str = ""
    body: str = ""
    course: str = ""
    deadline_at: float | None = None
    published_at: float | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    requirements: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)
    alias_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class FetchResult:
    status: str  # ok / not_modified / failed / need_login
    items: list[Snapshot] = field(default_factory=list)
    complete: bool = True  # items 是否为完整列表（用于识别删除）
    error: str = ""
    error_kind: str = ""
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    session_changed: bool = False
    requests: int = 0
    not_modified: int = 0
    bytes: int = 0
    retry_after: float | None = None  # 服务端要求的最短等待（Retry-After），下次检查不早于此


class Context:
    def __init__(self, fetcher: Fetcher, source: SourceInfo, session: SourceSession | None) -> None:
        self.fetcher = fetcher
        self.source = source
        self.session = session
        self.requests = 0
        self.not_modified = 0
        self.bytes = 0

    async def get(
        self, url: str, *, conditional: bool = True, auth: bool = True
    ) -> tuple[str | None, bool]:
        """带条件请求与解析缓存的 GET。返回 (正文或 None, 是否 304)。

        304 时返回 None，调用方应复用 cache 中上次的解析结果。
        """
        entry = self.source.cache.get(url, {}) if conditional else {}
        cookies = self.session.cookies if (auth and self.session) else None
        r = await self.fetcher.fetch(
            url, etag=entry.get("etag"), last_modified=entry.get("lm"), cookies=cookies
        )
        self.requests += 1
        self.bytes += len(r.body)
        if r.history and any(looks_like_login(u) for u in [r.url]):
            raise FetchError("need_login", "会话已失效，被重定向到登录页")
        if r.status == 304:
            self.not_modified += 1
            return None, True
        if r.status in (401, 403):
            raise FetchError("need_login", f"HTTP {r.status}")
        if r.status == 404:
            raise FetchError("http", "HTTP 404")
        if r.status != 200:
            raise FetchError("http", f"HTTP {r.status}")
        text = _decode(r.body, r.headers.get("Content-Type", ""))
        if auth and self.session and looks_like_login(r.url, text):
            raise FetchError("need_login", "页面要求登录")
        if conditional:
            self.source.cache[url] = {
                "etag": r.headers.get("ETag"),
                "lm": r.headers.get("Last-Modified"),
                "parsed": entry.get("parsed"),
            }
        return text, False

    def cached(self, url: str) -> Any:
        return self.source.cache.get(url, {}).get("parsed")

    def remember(self, url: str, parsed: Any) -> None:
        self.source.cache.setdefault(url, {})["parsed"] = parsed


def _decode(body: bytes, ctype: str) -> str:
    charset = "utf-8"
    if "charset=" in ctype:
        charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
    try:
        return body.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return body.decode("gb18030", errors="replace")


def content_hash(items: list[Snapshot]) -> str:
    h = hashlib.sha256()
    for it in sorted(items, key=lambda x: x.key):
        h.update(repr(sorted(it.to_dict().items())).encode())
    return h.hexdigest()
