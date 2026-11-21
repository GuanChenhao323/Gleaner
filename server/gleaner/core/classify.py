"""三类事项的程序化分类与字段补全（产品定义 2.3、2.5 节，F03／US03，决策 D17、D21）。

只用规则，不调用大模型；判断不了的字段保持为空，不编造日期。规则按优先级：

1. 来源或插件给出的类型（``hint``）优先，例如 Moodle 作业、测验由插件判为待办。
2. 有“截止／due”语境的日期 → 待办。
3. 标题是说明文／公告（须知、公告、公示……） → 通知。
4. 标题出现待办类关键词（作业、报名、提交……） → 待办。
5. 标题出现活动类关键词（讲座、考试、比赛……）且正文有带时刻的日期 → 日程，取该时间为开始时间。
6. 其余 → 通知。

字段补全：
- 截止时间：先找“截止／due”语境的日期；判为待办但没有语境、全文恰好只有一个日期时（例如 Moodle 作业列表
  一行里的 Due date 列），取这个日期。
- 开始／结束时间：日程取“时间／Time／于”附近或第一个带时刻的日期；同一天的“14:00-16:00”“14:00至16:00”给出结束时间。
- 地点：“地点／地址／教室／Location／Venue：X”，或“在 X 举行／考试／召开”。
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .extract import TZ, DeadlineMatch, extract_deadline, find_deadlines
from .itemtypes import ITEM_TYPES

EVENT_WORDS = re.compile(
    r"讲座|报告会|研讨会|座谈|宣讲|考试|期中|期末|测验|答辩|活动|比赛|竞赛|大赛|会议|培训|开幕|典礼|演出|学术|赛|"
    r"音乐会|展览|招聘会|沙龙|论坛|晚会|运动会|纳新|招新|迎新|献血|义卖|募捐|义诊|球赛|马拉松|夜跑|"
    r"英语角|读书会|分享会|双选会|学位授予|研学|支教|志愿者|补考|缓考|展|lecture|seminar|workshop|exam|"
    r"midterm|final|talk|meeting|conference|ceremony|webinar|competition|concert|exhibition|forum",
    re.I,
)
TODO_WORDS = re.compile(
    r"作业|实验报告|提交|上交|报名|申请|填写|填报|缴费|交费|选课|截止|问卷|缴纳|注册|报到|申报|签到|打卡|"
    r"补办|备案|assignment|homework|submit|submission|deadline|due|register|registration|apply|"
    r"application|survey",
    re.I,
)
# 说明文／公告类标题（须知、公告、公示）本身就是通知，不再按其中的活动词判成日程
NOTICE_WORDS = re.compile(r"须知|公告|公示", re.I)
_TIME_LABEL = re.compile(r"(时间|日期|time|date|when|于)\s*[:：]?", re.I)
_RANGE_END = re.compile(r"^\s*(?:-|－|—|–|~|～|至|到|to)\s*(?P<h>\d{1,2})[:：](?P<mi>\d{2})", re.I)
_PLACE = re.compile(
    r"(?:地点|地址|教室|会议室|考场|场地|location|venue|room|place)\s*[:：]\s*"
    r"(?P<p>[^\n，。,;；|]{2,40})",
    re.I,
)
_PLACE_VERB = re.compile(r"在\s*(?P<p>[^\s，。,;；]{2,20}?)\s*(?:举行|举办|召开|考试|进行|开展)")


@dataclass
class Classified:
    item_type: str
    deadline_at: float | None
    start_at: float | None
    end_at: float | None
    location: str


def _first_timed(cands: list[DeadlineMatch], text: str) -> DeadlineMatch | None:
    """活动时间：优先“时间：”等标签之后的日期，其次第一个带时刻的日期。"""
    for c in cands:
        before = text[max(0, c.pos - 8) : c.pos]
        if _TIME_LABEL.search(before):
            return c
    return next((c for c in cands if c.has_time), None)


def _end_of(c: DeadlineMatch, text: str) -> float | None:
    m = _RANGE_END.match(text[c.pos + len(c.text) :])
    if not m:
        return None
    h, mi = int(m.group("h")), int(m.group("mi"))
    if not (0 <= h <= 23 and 0 <= mi < 60):
        return None
    end = c.at.replace(hour=h, minute=mi)
    return end.timestamp() if end > c.at else None


def _location(text: str) -> str:
    m = _PLACE.search(text) or _PLACE_VERB.search(text)
    return m.group("p").strip() if m else ""


def classify(
    title: str,
    text: str,
    *,
    hint: str | None = None,
    kind: str = "",
    published: float | None = None,
    deadline_at: float | None = None,
    start_at: float | None = None,
) -> Classified:
    """返回类型与补全后的字段。已明确给出的 ``deadline_at``／``start_at`` 原样保留。"""
    full = f"{title}\n{text}"
    pub = dt.datetime.fromtimestamp(published, TZ) if published else None
    cands = find_deadlines(full, pub)
    due = deadline_at
    if due is None:
        m = extract_deadline(full, pub)
        due = m.at.timestamp() if m else None

    item_type = hint if hint in ITEM_TYPES else None
    event_at: DeadlineMatch | None = None
    if item_type is None:
        if kind == "assignment":
            item_type = "todo"
        elif start_at is not None:
            item_type = "event"
        elif due is not None:
            item_type = "todo"
        elif NOTICE_WORDS.search(title):
            item_type = "notice"
        elif TODO_WORDS.search(title):
            item_type = "todo"
        elif EVENT_WORDS.search(title) and (event_at := _first_timed(cands, full)):
            item_type = "event"
        else:
            item_type = "notice"

    if item_type == "todo" and due is None and len(cands) == 1:
        due = cands[0].at.timestamp()  # 作业列表一行里只有一个日期：就是截止时间

    start, end = start_at, None
    if item_type == "event" and start is None:
        event_at = event_at or _first_timed(cands, full)
        if event_at is not None:
            start = event_at.at.timestamp()
            end = _end_of(event_at, full)
    if item_type == "event" and due is not None and start is not None and abs(due - start) < 60:
        due = None  # 活动时间被当成了“前”之类的截止语境：不重复记录
    return Classified(item_type, due, start, end, _location(full) if item_type == "event" else "")
