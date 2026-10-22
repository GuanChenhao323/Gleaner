"""规则提取：截止时间、精简标题、摘要、适用对象（proposal“截止时间抽取”“精简标题与摘要”）。"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("GLEANER_TZ", "Asia/Shanghai"))

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        1,
    )
    for m in names
}
_WEEKDAY_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_WEEKDAY_EN = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# 截止语境关键词：只有出现在这些词附近的日期才算截止时间
_DUE_HINT = re.compile(
    r"(截止|截至|之前|以前|(?<=[点时分日号天五六一二三四\d])前|due|deadline|before|by|提交时间|报名时间|ddl)",
    re.I,
)

_TIME = r"(?:\s*(?P<ampm1>上午|下午|晚上|中午)?\s*(?P<h>\d{1,2})(?:[:：点时](?P<mi>\d{2})?分?)?\s*(?P<ampm2>[ap]\.?m\.?)?)?"

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "iso",
        re.compile(
            r"(?P<y>20\d{2})[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})(?:[ T]+(?P<h>\d{1,2}):(?P<mi>\d{2}))?"
        ),
    ),
    (
        "cn_full",
        re.compile(
            r"(?:(?P<y>20\d{2})\s*年\s*)?(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日号]"
            + r"(?:\s*[（(]?(?:周|星期)[一二三四五六日天][)）]?)?"
            + _TIME
        ),
    ),
    (
        "en",
        re.compile(
            r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<y>20\d{2}))?"
            r"(?:,?\s*(?:at\s*)?(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ampm2>[ap]\.?m\.?)?)?",
            re.I,
        ),
    ),
    (
        "cn_week",
        re.compile(r"(?P<rel>本|这|下下|下)?\s*(?:周|星期|礼拜)(?P<wd>[一二三四五六日天])" + _TIME),
    ),
    (
        "en_week",
        re.compile(r"(?P<rel>next|this)?\s*(?P<wd>mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I),
    ),
    ("cn_rel", re.compile(r"(?P<rd>今天|明天|后天|今晚|明晚)" + _TIME)),
]


@dataclass
class DeadlineMatch:
    at: dt.datetime
    text: str
    kind: str
    has_time: bool
    pos: int = 0


def _hour(h: int, ampm: str | None) -> int:
    if not ampm:
        return h
    a = ampm.lower().replace(".", "")
    if a in ("pm", "下午", "晚上") and h < 12:
        return h + 12
    if a == "am" and h == 12:
        return 0
    return h


def _end_of_day(d: dt.date) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, 23, 59, tzinfo=TZ)


def find_deadlines(text: str, published: dt.datetime | None = None) -> list[DeadlineMatch]:
    """找出文本中所有日期，相对日期按发布时间换算。没写时刻的默认 23:59。"""
    ref = (published or dt.datetime.now(TZ)).astimezone(TZ)
    out: list[DeadlineMatch] = []
    taken: list[tuple[int, int]] = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            g = m.groupdict()
            try:
                when, has_time = _resolve(kind, g, ref)
            except (ValueError, KeyError):
                continue
            if when is None:
                continue
            taken.append((m.start(), m.end()))
            out.append(DeadlineMatch(when, m.group(0).strip(), kind, has_time, m.start()))
    out.sort(key=lambda d: d.pos)
    return out


def _resolve(
    kind: str, g: dict[str, str | None], ref: dt.datetime
) -> tuple[dt.datetime | None, bool]:
    h = int(g["h"]) if g.get("h") else None
    mi = int(g["mi"]) if g.get("mi") else 0
    ampm = g.get("ampm1") or g.get("ampm2")
    if kind in ("iso", "cn_full", "en"):
        month = _MONTHS[g["mon"].lower().rstrip(".")] if kind == "en" else int(g["m"] or 0)  # type: ignore[union-attr]
        day = int(g["d"] or 0)
        year = int(g["y"]) if g.get("y") else ref.year
        d = dt.date(year, month, day)
        if not g.get("y") and d < ref.date() - dt.timedelta(days=60):
            d = dt.date(year + 1, month, day)  # “1月5日”在 12 月发布时指明年
    elif kind == "cn_week":
        target = _WEEKDAY_CN[g["wd"]]  # type: ignore[index]
        rel = g.get("rel") or ""
        monday = ref.date() - dt.timedelta(days=ref.weekday())
        offset = {"": 0, "本": 0, "这": 0, "下": 7, "下下": 14}[rel]
        d = monday + dt.timedelta(days=offset + target)
        if rel == "" and d < ref.date():
            d += dt.timedelta(days=7)
    elif kind == "en_week":
        target = _WEEKDAY_EN[g["wd"][:3].lower()]  # type: ignore[index]
        rel = (g.get("rel") or "").lower()
        if rel == "next":
            monday_next = ref.date() - dt.timedelta(days=ref.weekday()) + dt.timedelta(days=7)
            d = monday_next + dt.timedelta(days=target)
        else:
            d = ref.date() + dt.timedelta(days=(target - ref.weekday()) % 7)
    elif kind == "cn_rel":
        rd = g["rd"]
        days = {"今天": 0, "今晚": 0, "明天": 1, "明晚": 1, "后天": 2}[rd]  # type: ignore[index]
        d = ref.date() + dt.timedelta(days=days)
        if rd in ("今晚", "明晚") and h is not None and h < 12:
            h += 12
    else:
        return None, False
    if h is None:
        return _end_of_day(d), False
    hh = _hour(h, ampm)
    if not 0 <= hh <= 24 or not 0 <= mi < 60:
        return None, False
    if hh == 24:
        return _end_of_day(d), True
    return dt.datetime(d.year, d.month, d.day, hh, mi, tzinfo=TZ), True


def extract_deadline(text: str, published: dt.datetime | None = None) -> DeadlineMatch | None:
    """优先选择出现在“截止/due/前”等语境附近的日期；没有语境时不认定为截止时间。"""
    cands = find_deadlines(text, published)
    best: DeadlineMatch | None = None
    for c in cands:
        pos = c.pos
        window = text[max(0, pos - 12) : pos + len(c.text) + 8]
        if _DUE_HINT.search(window):
            if best is None or (c.has_time and not best.has_time):
                best = c
            if best.has_time:
                break
    return best


# ---- 标题与摘要 ----------------------------------------------------------------

_COURSE_CODE = re.compile(r"^\s*[\[【(（]?\s*[A-Z]{2,5}\s?\d{3,5}[A-Z]?\s*[\]】)）]?\s*[-:：|]?\s*")
_NOISE = re.compile(r"^(关于|有关)|(的)?(通知|公告|启事)$")
_SENT = re.compile(r"(?<=[。！？!?；;])|(?<=\.)\s+")


def clean_title(title: str) -> str:
    """去掉课程代码、“关于”“通知”等冗余词。"""
    t = re.sub(r"\s+", " ", title).strip()
    t = _COURSE_CODE.sub("", t)
    t = re.sub(r"^(Re|Fwd|回复|转发)[:：]\s*", "", t, flags=re.I)
    prev = None
    while prev != t:
        prev = t
        t = _NOISE.sub("", t).strip(" ：:-")
    return t or title.strip()


def summarize(text: str, max_sentences: int = 2, max_chars: int = 140) -> str:
    """规则摘要：正文前两句。"""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    parts = [p.strip() for p in _SENT.split(text) if p and p.strip()]
    out = ""
    for p in parts[:max_sentences]:
        if len(out) + len(p) > max_chars and out:
            break
        out += p if out.endswith(("。", "！", "？")) or not out else " " + p
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "…"
    return out


_GRADE = re.compile(r"(20\d{2}级|大[一二三四]|研[一二三]|本科生|研究生|博士生|新生)")
_MAJOR = re.compile(r"([一-龥]{2,10}(?:专业|学院))")
_PLACE = re.compile(r"(?:地点|地址|教室|会议室)[:：]\s*([^\s，。,;；]{2,30})")


def extract_facts(text: str) -> dict[str, list[str]]:
    """抽出适用对象（年级、专业）与地点，用于相关性匹配和摘要展示。"""
    return {
        "grades": sorted(set(_GRADE.findall(text))),
        "majors": sorted(set(_MAJOR.findall(text)))[:5],
        "places": _PLACE.findall(text)[:3],
    }
