"""事项版本比较与重要变更判定（proposal 技术方案 8）。"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from .extract import TZ

# 参与比较的字段；仅措辞调整（summary/body）只记入历史
TRACKED = (
    "title",
    "deadline_at",
    "attachments",
    "requirements",
    "summary",
    "body",
    "url",
    "course",
)
IMPORTANT_FIELDS = ("attachments", "requirements")


def snapshot_hash(snap: dict[str, Any]) -> str:
    keyed = {k: snap.get(k) for k in TRACKED}
    return hashlib.sha256(
        json.dumps(keyed, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for k in TRACKED:
        a, b = old.get(k), new.get(k)
        if _norm(a) != _norm(b):
            out[k] = [a, b]
    return out


def _norm(v: Any) -> Any:
    if isinstance(v, str):
        return " ".join(v.split())
    if isinstance(v, list):
        return sorted(json.dumps(x, sort_keys=True, ensure_ascii=False) for x in v)
    if isinstance(v, float):
        return round(v)
    return v


def _fmt_day(ts: float) -> str:
    d = dt.datetime.fromtimestamp(ts, TZ)
    return d.strftime("%m-%d %H:%M")


def classify(changed: dict[str, list[Any]]) -> tuple[bool, str]:
    """返回 (是否重要, 人类可读的变化说明)。

    重要：截止时间提前、附件替换、提交要求变化；新增截止时间也视为重要。
    """
    notes: list[str] = []
    important = False
    if "deadline_at" in changed:
        a, b = changed["deadline_at"]
        if a and b:
            days = (b - a) / 86400
            if days < 0:
                important = True
                notes.append(f"截止提前 {_human_days(-days)}（{_fmt_day(a)} → {_fmt_day(b)}）")
            else:
                notes.append(f"截止推迟 {_human_days(days)}（{_fmt_day(a)} → {_fmt_day(b)}）")
        elif b and not a:
            important = True
            notes.append(f"新增截止时间 {_fmt_day(b)}")
        else:
            notes.append("截止时间被移除")
    if "attachments" in changed:
        important = True
        old = {a.get("name") for a in changed["attachments"][0] or [] if isinstance(a, dict)}
        new = {a.get("name") for a in changed["attachments"][1] or [] if isinstance(a, dict)}
        added, removed = new - old, old - new
        if added and removed:
            notes.append("附件替换：" + "、".join(sorted(str(x) for x in added)))
        elif added:
            notes.append("新增附件：" + "、".join(sorted(str(x) for x in added)))
        elif removed:
            notes.append("附件被移除：" + "、".join(sorted(str(x) for x in removed)))
        else:
            notes.append("附件内容更新")
    if "requirements" in changed:
        important = True
        notes.append("提交要求变化")
    if "title" in changed:
        notes.append("标题修改")
    if not notes and changed:
        notes.append("内容措辞调整")
    return important, "；".join(notes)


def _human_days(days: float) -> str:
    if days >= 1:
        n = round(days)
        return f"{n} 天"
    hours = round(days * 24)
    return f"{max(hours, 1)} 小时"
