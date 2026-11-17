"""三类事项的规则分类与字段补全（core/classify.py，F03／US03）。"""

import asyncio
import datetime as dt
import time

from gleaner.core.classify import classify
from gleaner.core.extract import TZ, find_deadlines
from gleaner.core.pipeline import Pipeline
from gleaner.storage.db import Database


def ts(y: int, mo: int, d: int, h: int = 23, mi: int = 59) -> float:
    return dt.datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


def test_moodle_english_dates_parse():
    got = find_deadlines("Lab 1 Friday, 13 November 2026, 11:59 PM")
    assert [(g.kind, g.at.timestamp()) for g in got] == [("en_dmy", ts(2026, 11, 13))]
    # "November 2026" 不能被误读成 11 月 20 日
    assert [g.at.day for g in find_deadlines("Opened: 6 November 2026, 9:00 AM")] == [6]


def test_three_types_and_fields():
    c = classify("学术讲座：网络协议设计", "时间：2026年11月12日 14:00-16:00，地点：A101")
    assert c.item_type == "event" and c.start_at == ts(2026, 11, 12, 14, 0)
    assert c.end_at == ts(2026, 11, 12, 16, 0) and c.location == "A101"
    assert c.deadline_at is None

    c = classify("期中考试安排", "2026年11月18日 9:00 在 B203 考试")
    assert c.item_type == "event" and c.start_at == ts(2026, 11, 18, 9, 0) and c.location == "B203"

    c = classify("实验报告提交", "请于 2026年11月20日 18:00 前提交到 Moodle")
    assert c.item_type == "todo" and c.deadline_at == ts(2026, 11, 20, 18, 0)

    # 插件判为待办、一行里只有一个日期（Moodle 作业列表的 Due date 列）：就是截止时间
    c = classify("Lab 1", "Topic 1 Lab 1 Friday, 13 November 2026, 11:59 PM", hint="todo")
    assert c.item_type == "todo" and c.deadline_at == ts(2026, 11, 13)

    c = classify("教学楼停电通知", "本周六全天停电，请提前做好安排")
    assert c.item_type == "notice" and c.deadline_at is None and c.start_at is None

    # 活动关键词但没有带时刻的日期：不猜开始时间，按通知处理
    c = classify("讲座回顾", "上周的讲座录像已上传")
    assert c.item_type == "notice" and c.start_at is None

    # 待办关键词、没有日期：待办，截止时间为空（不编造）
    c = classify("提交作业的注意事项", "请按格式提交")
    assert c.item_type == "todo" and c.deadline_at is None

    # 明确给出的类型与时间优先
    c = classify("随便什么", "2026年11月12日 14:00", hint="notice")
    assert c.item_type == "notice"
    c = classify("x", "", start_at=ts(2026, 12, 1, 10, 0))
    assert c.item_type == "event" and c.start_at == ts(2026, 12, 1, 10, 0)


def test_campus_keyword_coverage():
    """校园高频活动／待办词能正确分类（分类负责人扩充的关键词表）。"""
    cases = [
        ("无偿献血活动", "2026年11月20日 9:00-16:00 在体育馆门口", "event"),
        ("爱心义卖", "本周六 10:00 在操场举行义卖", "event"),
        ("社团纳新", "本周三 12:30 在学生活动中心", "event"),
        ("新生注册通知", "请于2026年11月25日前完成注册", "todo"),
        ("健康打卡提醒", "每天 8:00 前完成健康打卡", "todo"),
        ("学费缴纳", "请于2026年12月1日前缴纳学费", "todo"),
        ("毕业答辩安排", "答辩时间：2026年12月5日 9:00", "event"),
    ]
    for title, text, want in cases:
        assert classify(title, text).item_type == want, (title, text)


async def test_rules_do_not_create_versions_for_unchanged_items(db_url):
    """已有事项标题与正文没变时，规则新推断出的字段不产生新版本；来源明确删除截止时间仍能发现。"""
    db = await Database(db_url("cls.db")).connect()
    pipe = Pipeline(db, lambda *_: asyncio.sleep(0))
    try:
        sid = await db.insert(
            "sources",
            {"type": "web", "name": "n", "endpoint": "http://n/", "created_at": time.time()},
        )
        body = "时间：2026年11月12日 14:00，地点：A101"
        snap = {
            "key": "n:1",
            "kind": "notice",
            "title": "学术讲座",
            "url": "http://n/1",
            "body": body,
        }
        assert (await pipe.ingest({"source_id": sid, "status": "ok", "items": [snap]}))["new"] == 1
        # 模拟“旧规则时代”存下的事项：没有活动时间、类型是通知
        await db.execute("UPDATE items SET item_type = 'notice', attrs = '{}'")
        counts = await pipe.ingest({"source_id": sid, "status": "ok", "items": [snap]})
        assert counts["changed"] == 0
        row = await db.fetchone("SELECT version, item_type FROM items")
        assert row["version"] == 1 and row["item_type"] == "notice"
        # 正文变了：重新分类，记新版本
        snap2 = {**snap, "body": body.replace("14:00", "15:00")}
        assert (await pipe.ingest({"source_id": sid, "status": "ok", "items": [snap2]}))[
            "changed"
        ] == 1
        row = await db.fetchone("SELECT version, item_type FROM items")
        assert row["version"] == 2 and row["item_type"] == "event"

        # 来源明确给出的截止时间被删掉：即使正文没变也要记录变化
        a = {
            "key": "a:1",
            "kind": "assignment",
            "title": "Lab",
            "body": "intro",
            "deadline_at": 2e9,
        }
        await pipe.ingest({"source_id": sid, "status": "ok", "items": [a]})
        counts = await pipe.ingest(
            {"source_id": sid, "status": "ok", "items": [{**a, "deadline_at": None}]}
        )
        assert counts["changed"] == 1
    finally:
        await db.close()
