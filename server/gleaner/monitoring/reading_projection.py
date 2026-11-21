"""Project a verified Moodle assignment detail into an existing browser reading recipe."""

from __future__ import annotations

import copy
import hashlib
import hmac
import re
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .models import MonitorError
from .pages import HTMLSnapshot


def project_assignment(
    recipe: dict[str, Any],
    baseline: dict[str, Any],
    snapshot: HTMLSnapshot,
    challenge: str,
    proof: str,
) -> dict[str, Any]:
    url = recipe["url"]
    targets = baseline.get("targets", [])
    intent = recipe["intent"]
    if (
        snapshot.requested_url != url
        or snapshot.final_url != url
        or recipe["source"] != "moodle"
        or len(targets) != 1
        or recipe.get("view")
        or recipe.get("choice")
        or intent.get("fields")
        or intent.get("current")
        or intent.get("kind") not in ("auto", "assignments")
        or (intent.get("kind") == "assignments" and intent.get("target"))
    ):
        raise MonitorError("unsupported")
    entity = parse_qs(urlsplit(url).query).get("id", [""])[0]
    target = targets[0]
    if (
        target["entity_id"] != "assignment:" + entity
        or target["locator"]["url"] != url
        or not entity.isdigit()
    ):
        raise MonitorError("unsupported")
    soup = BeautifulSoup(snapshot.body, "lxml")
    account = soup.select_one("body[data-userid],.usermenu[data-userid],body[data-account-id]")
    native = account.get("data-userid") or account.get("data-account-id") if account else None
    if not native:
        anchor = soup.select_one(
            '.usermenu a[href*="/user/profile.php"],.logininfo a[href*="/user/profile.php"]'
        )
        profile = urlsplit(urljoin(url, str(anchor["href"]))) if anchor else None
        if (
            profile
            and profile.netloc == urlsplit(url).netloc
            and profile.path == "/user/profile.php"
        ):
            native = parse_qs(profile.query).get("id", [""])[0]
    if not native or not str(native).isdigit():
        raise MonitorError("account_unknown")
    actual = hashlib.sha256(f"{challenge}|moodle|{native}".encode()).hexdigest()
    if not hmac.compare_digest(actual, proof):
        raise MonitorError("account_mismatch")
    body = soup.body
    root = soup.select_one("#region-main")
    if (
        not root
        or not body
        or body.get("id") != "page-mod-assign-view"
        or "cmid-" + entity not in body.get("class", [])
    ):
        raise MonitorError("unsupported")
    heading = root.select_one("h2") or root.select_one("h1")
    title = heading.get_text(" ", strip=True) if heading else ""
    if not title:
        raise MonitorError("unsupported")
    term = intent.get("keyword") or intent.get("target") or ""
    lab = re.fullmatch(r"lab\s*[-_]?\s*(\d+)", term, re.I)
    if lab:
        match = re.search(r"\blab[\s_-]*0*" + str(int(lab[1])) + r"(?!\d)", title, re.I)
    else:
        match = (
            unicodedata.normalize("NFKC", term).casefold()
            in unicodedata.normalize("NFKC", title).casefold()
        )
    if not match:
        raise MonitorError("no_match")
    fields = {"course": "", "subtype": "moodle_assignment"}
    names = {
        "submission status": "submission_status",
        "提交状态": "submission_status",
        "提交狀態": "submission_status",
        "grading status": "grading_status",
        "评分状态": "grading_status",
        "評分狀態": "grading_status",
        "due date": "due_text",
        "截止日期": "due_text",
        "time remaining": "time_remaining",
        "剩余时间": "time_remaining",
        "剩餘時間": "time_remaining",
    }
    for label in root.select(
        '[data-region="activity-dates"] strong,.activity-dates strong,[data-region="activity-dates"] b,.activity-dates b'
    ):
        label_text = label.get_text(" ", strip=True)
        if re.fullmatch(r"due(?: date)?|截止(?:时间|時間|日期)?", label_text.rstrip(":： "), re.I):
            value = label.parent.get_text(" ", strip=True).removeprefix(label_text).lstrip(":： ")
            if value:
                fields["due_text"] = value
    for row in root.select("table tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2 or (cells[0].name != "th" and cells[0].get("scope") != "row"):
            continue
        key = names.get(cells[0].get_text(" ", strip=True).rstrip(":：").casefold())
        if key and cells[1].get_text(strip=True):
            fields.setdefault(key, cells[1].get_text(" ", strip=True))
    lines = [
        label + "：" + fields[k]
        for k, label in (("submission_status", "提交状态"), ("grading_status", "评分状态"))
        if fields.get(k)
    ]
    intro = root.select_one("#intro.activity-description,.activity-description,#intro")
    old_body = target["raw"]["text"]
    old_intro = old_body.split("附件（未读取正文）：", 1)[0]
    old_intro = "\n".join(
        line
        for line in old_intro.splitlines()
        if not line.startswith(("提交状态：", "评分状态：", "截止时间：", "剩余时间："))
    ).strip()
    if (
        old_intro
        and old_intro != target["raw"]["title"]
        and (not intro or not intro.get_text(strip=True))
    ):
        raise MonitorError("unsupported")
    if "附件（未读取正文）：" in old_body and not root.select_one(
        'a[href*="/mod_assign/introattachment/"]'
    ):
        raise MonitorError("unsupported")
    if intro:
        for node in intro.select("script,style,noscript,form,[hidden],[aria-hidden=true]"):
            node.decompose()
        lines.extend(n.strip() for n in intro.get_text("\n", strip=True).splitlines() if n.strip())
    for anchor in root.select('a[href*="/mod_assign/introattachment/"]'):
        link = urljoin(url, str(anchor["href"]))
        if urlsplit(link).netloc != urlsplit(url).netloc:
            raise MonitorError("unsupported")
        lines.append("附件（未读取正文）：" + anchor.get_text(" ", strip=True) + "\n" + link)
    previous = target["raw"]["fields"]
    # Unknown or missing sections cannot establish parity with the saved browser observation.
    if (
        previous.get("course")
        or set(previous) - set(fields)
        or (not lines and not fields.get("due_text"))
    ):
        raise MonitorError("unsupported")
    updated = copy.deepcopy(target)
    updated["raw"] = {"title": title, "text": "\n".join(lines) or title, "fields": fields}
    return {"binding": recipe["binding"], "targets": [updated]}
