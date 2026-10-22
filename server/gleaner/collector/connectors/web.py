"""通用网页列表、RSS、教师信息页连接器。"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup

from ...core.extract import TZ, extract_deadline
from .base import Context, FetchResult, Snapshot, normalize_url, url_alias

_DATE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")


def _date(text: str) -> float | None:
    m = _DATE.search(text)
    if not m:
        return None
    try:
        return time.mktime((int(m.group(1)), int(m.group(2)), int(m.group(3)), 12, 0, 0, 0, 0, -1))
    except (OverflowError, ValueError):
        return None


async def fetch_web(ctx: Context) -> FetchResult:
    """列表页 + 详情页。选择器来自来源配置（校园模板预置），也支持自定义“关注区域”。"""
    cfg = ctx.source.config
    url = ctx.source.endpoint
    text, nm = await ctx.get(url, auth=bool(ctx.session))
    if nm and ctx.cached(url) is not None:
        entries = ctx.cached(url)
    else:
        assert text is not None
        soup = BeautifulSoup(text, "lxml")
        scope = soup.select_one(cfg["region"]) if cfg.get("region") else soup
        if scope is None:
            from ..fetcher import FetchError

            raise FetchError("parse", f"找不到关注区域 {cfg.get('region')}")
        entries = []
        for li in scope.select(cfg.get("item_selector", "li")):
            a = li.select_one(cfg.get("link_selector", "a[href]"))
            if not a or not a.get("href"):
                continue
            d = li.select_one(cfg["date_selector"]) if cfg.get("date_selector") else None
            entries.append(
                {
                    "title": (a.get("title") or a.get_text(" ", strip=True)).strip(),
                    "url": normalize_url(urljoin(url, a["href"])),
                    "date": _date(d.get_text() if d else li.get_text()),
                    "category": (
                        li.select_one(cfg["category_selector"]).get_text(strip=True).strip("[]【】")
                        if cfg.get("category_selector") and li.select_one(cfg["category_selector"])
                        else ""
                    ),
                }
            )
        ctx.remember(url, entries)
    limit = int(cfg.get("limit", 30))
    items: list[Snapshot] = []
    for e in entries[:limit]:
        body = ""
        if cfg.get("detail_selector"):
            body = await _detail(ctx, e["url"], cfg["detail_selector"])
        published = e.get("date")
        import datetime as dt

        ref = dt.datetime.fromtimestamp(published, TZ) if published else None
        dl = extract_deadline(f"{e['title']} {body}", ref)
        items.append(
            Snapshot(
                key=f"web:{e['url']}",
                kind=cfg.get("kind", "notice"),
                title=e["title"],
                url=e["url"],
                body=body,
                course=ctx.source.course,
                published_at=published,
                deadline_at=dl.at.timestamp() if dl else None,
                attrs={"category": e.get("category", ""), "deadline_text": dl.text if dl else ""},
                alias_keys=[url_alias(e["url"])],
            )
        )
    return FetchResult("ok", items, complete=len(entries) <= limit)


async def _detail(ctx: Context, url: str, selector: str) -> str:
    text, nm = await ctx.get(url, auth=bool(ctx.session))
    if nm and ctx.cached(url) is not None:
        return str(ctx.cached(url))
    if text is None:
        return ""
    soup = BeautifulSoup(text, "lxml")
    node = soup.select_one(selector)
    body = node.get_text("\n", strip=True) if node else ""
    ctx.remember(url, body)
    return body


async def fetch_rss(ctx: Context) -> FetchResult:
    """RSS / Atom：自研 HTTP 客户端取字节，feedparser 只做解析。"""
    url = ctx.source.endpoint
    text, nm = await ctx.get(url, auth=False)
    if nm:
        return FetchResult("not_modified", complete=False)
    assert text is not None
    feed = feedparser.parse(text.encode("utf-8"))
    items: list[Snapshot] = []
    import datetime as dt

    for e in feed.entries[:50]:
        link = normalize_url(e.get("link", "")) if e.get("link") else ""
        published = time.mktime(e.published_parsed) if e.get("published_parsed") else None
        body = BeautifulSoup(e.get("summary", ""), "lxml").get_text(" ", strip=True)
        ref = dt.datetime.fromtimestamp(published, TZ) if published else None
        dl = extract_deadline(f"{e.get('title', '')} {body}", ref)
        items.append(
            Snapshot(
                key=f"rss:{e.get('id') or link}",
                kind="notice",
                title=e.get("title", "(无标题)"),
                url=link,
                body=body,
                course=ctx.source.course,
                published_at=published,
                deadline_at=dl.at.timestamp() if dl else None,
                attrs={
                    "category": ", ".join(t.get("term", "") for t in e.get("tags", [])),
                    "feed": feed.feed.get("title", ""),
                },
                alias_keys=[url_alias(link)] if link else [],
            )
        )
    return FetchResult("ok", items, complete=False)


async def fetch_teachers(ctx: Context) -> FetchResult:
    """学校官网教师信息：列表页 + 每位老师的详情页（办公室、电话、邮箱、课程）。"""
    url = ctx.source.endpoint
    cfg = ctx.source.config
    text, nm = await ctx.get(url, auth=False)
    links: list[str]
    if nm and ctx.cached(url) is not None:
        links = ctx.cached(url)
    else:
        assert text is not None
        soup = BeautifulSoup(text, "lxml")
        links = [
            normalize_url(urljoin(url, a["href"]))
            for a in soup.select(cfg.get("link_selector", ".faculty-list a[href]"))
        ]
        ctx.remember(url, links)
    items = []
    for link in links[:200]:
        t, nm2 = await ctx.get(link, auth=False)
        info: dict[str, Any]
        if nm2 and ctx.cached(link) is not None:
            info = ctx.cached(link)
        else:
            assert t is not None
            s = BeautifulSoup(t, "lxml")

            def pick(sel: str, s: BeautifulSoup = s) -> str:
                n = s.select_one(sel)
                return n.get_text(" ", strip=True) if n else ""

            info = {
                "name": pick(".name, h1"),
                "title": pick(".title"),
                "office": pick(".office"),
                "phone": pick(".phone"),
                "email": pick(".email"),
                "courses": [c for c in re.split(r"[、,，;；\s]+", pick(".courses")) if c],
            }
            ctx.remember(link, info)
        items.append(
            Snapshot(
                key=f"teacher:{link}",
                kind="teacher",
                title=info["name"],
                url=link,
                body=f"{info['title']} · {info['office']}",
                attrs=info,
            )
        )
    return FetchResult("ok", items, complete=True)
