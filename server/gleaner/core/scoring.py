"""可解释的优先级打分与分级推送（proposal“个性化与通知分级策略”）。

score = 100 × (0.30·S_source + 0.25·S_keyword + 0.25·S_deadline + 0.20·S_match)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from .extract import TZ

DEFAULT_KEYWORDS = (
    "截止",
    "deadline",
    "due",
    "考试",
    "exam",
    "调课",
    "取消",
    "停课",
    "补交",
    "提前",
)

URGENT = 80
NORMAL = 40


@dataclass
class UserProfile:
    user_id: int
    grade: str = ""
    major: str = ""
    courses: list[str] = field(default_factory=list)
    quiet_start: str = "23:00"
    quiet_end: str = "07:00"
    boost_words: list[tuple[str, float]] = field(default_factory=list)
    block_words: list[str] = field(default_factory=list)
    sender_whitelist: list[str] = field(default_factory=list)
    source_weights: dict[int, float] = field(default_factory=dict)


@dataclass
class Score:
    total: int
    parts: dict[str, float]
    priority: str  # urgent / normal / low
    reasons: list[str]


def s_deadline(deadline_at: float | None, now: float) -> float:
    """24 小时内为 1，7 天以外为 0，中间线性；已过期为 0。"""
    if deadline_at is None:
        return 0.0
    hours = (deadline_at - now) / 3600
    if hours < 0:
        return 0.0
    if hours <= 24:
        return 1.0
    if hours >= 24 * 7:
        return 0.0
    return 1.0 - (hours - 24) / (24 * 6)


def s_keyword(text: str, profile: UserProfile) -> tuple[float, list[str]]:
    low = text.lower()
    hits = [k for k in DEFAULT_KEYWORDS if k.lower() in low]
    score = min(1.0, 0.5 * len(hits))
    for word, boost in profile.boost_words:
        if word.lower() in low:
            score = min(1.0, score + boost)
            hits.append(word)
    return score, hits


def s_match(item: dict[str, Any], profile: UserProfile) -> tuple[float, str]:
    """与课程、年级、专业的匹配：明确符合 1，明确不符合 0，未注明 0.5。"""
    course = item.get("course") or ""
    if course and profile.courses:
        if any(c and (c in course or course in c) for c in profile.courses):
            return 1.0, "你的课程"
    facts = item.get("facts") or {}
    grades = facts.get("grades") or []
    majors = facts.get("majors") or []
    if not grades and not majors:
        return (0.8, "课程事项") if item.get("kind") == "assignment" else (0.5, "")
    ok_grade = (
        not grades
        or not profile.grade
        or any(profile.grade in g or g in profile.grade for g in grades)
    )
    ok_major = (
        not majors
        or not profile.major
        or any(
            profile.major in m or m.replace("专业", "").replace("学院", "") in profile.major
            for m in majors
        )
    )
    if ok_grade and ok_major:
        return 1.0, "符合你的年级/专业"
    return 0.0, "面向其他年级或专业"


def in_quiet_hours(profile: UserProfile, now: float) -> bool:
    t = dt.datetime.fromtimestamp(now, TZ).strftime("%H:%M")
    a, b = profile.quiet_start, profile.quiet_end
    if a == b:
        return False
    return (a <= t < b) if a < b else (t >= a or t < b)


def score_item(
    item: dict[str, Any],
    profile: UserProfile,
    *,
    source_id: int,
    source_weight: float,
    important_change: bool = False,
    now: float,
) -> Score:
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    if any(b and b.lower() in text.lower() for b in profile.block_words):
        return Score(0, {}, "low", ["命中屏蔽词"])
    sw = profile.source_weights.get(source_id, source_weight)
    sender = (item.get("attrs") or {}).get("sender", "")
    if sender and sender in profile.sender_whitelist:
        sw = 1.0
    kw, hits = s_keyword(text, profile)
    sd = s_deadline(item.get("deadline_at"), now)
    sm, why_match = s_match(item, profile)
    parts = {
        "source": round(sw, 3),
        "keyword": round(kw, 3),
        "deadline": round(sd, 3),
        "match": round(sm, 3),
    }
    total = round(100 * (0.30 * sw + 0.25 * kw + 0.25 * sd + 0.20 * sm))
    reasons = []
    if hits:
        reasons.append("关键词：" + "、".join(dict.fromkeys(hits)))
    if sd >= 1:
        reasons.append("24 小时内截止")
    elif sd > 0:
        reasons.append("7 天内截止")
    if why_match:
        reasons.append(why_match)
    # 重要变更至少普通级；距截止不足 7 天升为紧急
    if important_change:
        reasons.append("重要变更")
        dl = item.get("deadline_at")
        if dl is not None and 0 < dl - now < 7 * 86400:
            total = max(total, URGENT)
        else:
            total = max(total, NORMAL)
    total = max(0, min(100, total))
    priority = "urgent" if total >= URGENT else "normal" if total >= NORMAL else "low"
    return Score(total, parts, priority, reasons)
