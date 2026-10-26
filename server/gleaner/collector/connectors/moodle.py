"""Moodle 连接器：优先 Web Service（mod_assign_get_assignments），失败时回退网页解析。"""

from __future__ import annotations

import html as _html
import re
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..fetcher import FetchError
from ..session import moodle_ws_url
from .base import Context, FetchResult, Snapshot, normalize_url, url_alias


def parse_moodle_date(text: str) -> float | None:
    """解析 Moodle 默认日期格式，例如 ``Friday, 6 November 2026, 11:59 PM``。"""
    text = " ".join(text.replace("\xa0", " ").split())
    for fmt in (
        "%A, %d %B %Y, %I:%M %p",
        "%d %B %Y, %I:%M %p",
        "%A, %d %B %Y, %H:%M",
        "%Y年%m月%d日 %H:%M",
    ):
        try:
            return time.mktime(time.strptime(text, fmt))
        except ValueError:
            continue
    return None


def _strip_html(s: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


async def fetch_moodle(ctx: Context) -> FetchResult:
    if ctx.session is None:
        raise FetchError("need_login", "尚未登录该 Moodle 来源")
    mode = ctx.source.config.get("mode", "auto")
    if ctx.session.ws_token and mode in ("auto", "ws"):
        try:
            return await _via_ws(ctx)
        except FetchError as e:
            if mode == "ws" or (e.kind == "need_login" and not ctx.session.cookies):
                raise
    return await _via_html(ctx)


async def _via_ws(ctx: Context) -> FetchResult:
    assert ctx.session
    base = ctx.source.endpoint
    r = await ctx.fetcher.fetch(
        moodle_ws_url(base, ctx.session.ws_token or "", "mod_assign_get_assignments")
    )
    ctx.requests += 1
    ctx.bytes += len(r.body)
    data = r.json()
    if isinstance(data, dict) and data.get("errorcode"):
        if data["errorcode"] in ("invalidtoken", "accessexception"):
            raise FetchError(
                "need_login", f"Web Service：{data.get('message') or data['errorcode']}"
            )
        raise FetchError("parse", str(data.get("message")))
    wanted = set(ctx.source.config.get("courses") or [])
    host = urlsplit(base).netloc
    items: list[Snapshot] = []
    for c in data.get("courses", []):
        if wanted and c["id"] not in wanted and c["shortname"] not in wanted:
            continue
        for a in c.get("assignments", []):
            view = urljoin(base, f"/mod/assign/view.php?id={a['cmid']}")
            intro = _strip_html(a.get("intro", ""))
            req = ""
            m = re.search(r"提交要求[:：]\s*(.+)$", intro)
            if m:
                req = m.group(1).strip()
                intro = intro[: m.start()].strip()
            items.append(
                Snapshot(
                    key=f"moodle:{host}:assign:{a['cmid']}",
                    kind="assignment",
                    title=a["name"],
                    url=view,
                    body=intro,
                    course=f"{c['shortname']} {c['fullname']}",
                    deadline_at=float(a["duedate"]) if a.get("duedate") else None,
                    attachments=[
                        {
                            "name": f["filename"],
                            "url": urljoin(base, f["fileurl"]),
                            "size": f.get("filesize"),
                        }
                        for f in a.get("introattachments", [])
                    ],
                    requirements=req,
                    attrs={
                        "via": "webservice",
                        "course_id": c["id"],
                        "timemodified": a.get("timemodified"),
                    },
                    alias_keys=[url_alias(view)],
                )
            )
    return FetchResult("ok", items, complete=True)


async def _via_html(ctx: Context) -> FetchResult:
    base = ctx.source.endpoint
    dash, _ = await ctx.get(urljoin(base, "/my/"), conditional=False)
    assert dash is not None
    soup = BeautifulSoup(dash, "lxml")
    course_links = [
        (a.get_text(" ", strip=True), urljoin(base, a["href"]))
        for a in soup.select("a.coursename, .course-listitem a[href*='course/view.php']")
    ]
    wanted = set(str(x) for x in ctx.source.config.get("courses") or [])
    items: list[Snapshot] = []
    host = urlsplit(base).netloc
    for cname, curl in course_links:
        cid = re.search(r"id=(\d+)", curl)
        if not cid:
            continue
        if wanted and cid.group(1) not in wanted and not any(w in cname for w in wanted):
            continue
        idx_url = urljoin(base, f"/mod/assign/index.php?id={cid.group(1)}")
        text, nm = await ctx.get(idx_url)
        rows: list[dict[str, Any]]
        if nm and ctx.cached(idx_url) is not None:
            rows = ctx.cached(idx_url)
        else:
            assert text is not None
            rows = _parse_index(text, base)
            ctx.remember(idx_url, rows)
        for row in rows:
            detail = await _detail(ctx, row["url"])
            items.append(
                Snapshot(
                    key=f"moodle:{host}:assign:{row['cmid']}",
                    kind="assignment",
                    title=row["name"],
                    url=row["url"],
                    body=detail.get("intro", ""),
                    course=cname,
                    deadline_at=detail.get("due") or row.get("due"),
                    attachments=detail.get("attachments", []),
                    requirements=detail.get("requirements", ""),
                    attrs={"via": "html"},
                    alias_keys=[url_alias(row["url"])],
                )
            )
    return FetchResult("ok", items, complete=True)


def _parse_index(text: str, base: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(text, "lxml")
    rows = []
    for tr in soup.select("table.generaltable tbody tr"):
        a = tr.select_one("td.c1 a, td a[href*='mod/assign/view.php']")
        if not a:
            continue
        url = normalize_url(urljoin(base, a["href"]))
        m = re.search(r"id=(\d+)", url)
        due_cell = tr.select_one("td.c2")
        rows.append(
            {
                "name": a.get_text(" ", strip=True),
                "url": url,
                "cmid": m.group(1) if m else url,
                "due": parse_moodle_date(due_cell.get_text(" ", strip=True)) if due_cell else None,
            }
        )
    return rows


async def _detail(ctx: Context, url: str) -> dict[str, Any]:
    text, nm = await ctx.get(url)
    if nm and ctx.cached(url) is not None:
        return ctx.cached(url)
    assert text is not None
    soup = BeautifulSoup(text, "lxml")
    out: dict[str, Any] = {}
    for div in soup.select(".activity-dates div, [data-region=activity-dates] div"):
        t = div.get_text(" ", strip=True)
        if t.lower().startswith(("due:", "截止")):
            out["due"] = parse_moodle_date(t.split(":", 1)[1])
    intro = soup.select_one("#intro .no-overflow, .activity-description .no-overflow")
    out["intro"] = intro.get_text("\n", strip=True) if intro else ""
    req = soup.select_one(".submission-requirements")
    out["requirements"] = (
        req.get_text(" ", strip=True).removeprefix("Submission:").strip() if req else ""
    )
    out["attachments"] = [
        {"name": a.get_text(strip=True), "url": urljoin(ctx.source.endpoint, a["href"])}
        for a in soup.select("#assign_files_tree a, .fileattachments a")
    ]
    ctx.remember(url, out)
    return out
