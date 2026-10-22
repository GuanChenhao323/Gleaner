import asyncio
import datetime as dt
import hashlib
import os
import time

import pytest

from gleaner import security
from gleaner.common.hashring import HashRing
from gleaner.core.changes import classify, diff
from gleaner.core.extract import TZ, clean_title, extract_deadline, extract_facts, summarize
from gleaner.core.scoring import UserProfile, in_quiet_hours, s_deadline, score_item
from gleaner.gateway.ratelimit import TokenBucket
from gleaner.net.http import HTTPClient, HTTPServer, Router, ServerConfig
from gleaner.obs.metrics import Registry
from gleaner.storage.db import Database
from gleaner.transfer.service import TransferService

REF = dt.datetime(2026, 10, 21, 10, 0, tzinfo=TZ)  # 周三


@pytest.mark.parametrize(
    "text,expect",
    [
        ("请于10月30日23:59前提交", "2026-10-30 23:59"),
        ("本周五前提交实验报告", "2026-10-23 23:59"),
        ("Assignment due Oct 30, 11:59 PM", "2026-10-30 23:59"),
        ("截止日期 2026-10-30", "2026-10-30 23:59"),
        ("下周三下午3点前交", "2026-10-28 15:00"),
        ("明天晚上8点截止", "2026-10-22 20:00"),
        ("deadline: next Friday", "2026-10-30 23:59"),
        ("11月6日（周五）截止", "2026-11-06 23:59"),
        ("1月5日前提交", "2027-01-05 23:59"),
    ],
)
def test_deadline_extraction(text, expect):
    m = extract_deadline(text, REF)
    assert m is not None and m.at.strftime("%Y-%m-%d %H:%M") == expect


def test_no_deadline_without_context():
    assert extract_deadline("下周三的课调整到周四", REF) is None
    assert extract_deadline("今天天气不错", REF) is None


def test_title_summary_facts():
    assert clean_title("【CS3001】关于第三次作业调整的通知") == "第三次作业调整"
    assert clean_title("Re: 关于期中考试安排的通知") == "期中考试安排"
    s = summarize("第一句话。第二句话！第三句话。")
    assert s == "第一句话。第二句话！"
    f = extract_facts("面向2024级计算机学院本科生，地点：教三201")
    assert "2024级" in f["grades"] and f["places"] == ["教三201"]


def test_scoring_formula_and_tiers():
    now = time.time()
    p = UserProfile(1, grade="2024级", major="计算机", courses=["网络编程"])
    item = {
        "title": "实验一 截止",
        "summary": "",
        "deadline_at": now + 3600,
        "course": "CS3105 网络编程",
        "kind": "assignment",
    }
    s = score_item(item, p, source_id=1, source_weight=1.0, now=now)
    # 100 × (0.30×1 + 0.25×0.5 + 0.25×1 + 0.20×1) = 87.5
    assert s.total == 88 and s.priority == "urgent"
    low = score_item(
        {"title": "图书馆讲座", "summary": ""}, p, source_id=2, source_weight=0.4, now=now
    )
    assert low.priority == "low"
    # 重要变更：距截止不足 7 天升为紧急
    imp = score_item(
        {"title": "x", "deadline_at": now + 3 * 86400},
        p,
        source_id=2,
        source_weight=0.1,
        important_change=True,
        now=now,
    )
    assert imp.priority == "urgent"
    p.block_words = ["讲座"]
    assert score_item({"title": "讲座"}, p, source_id=2, source_weight=1, now=now).total == 0
    assert s_deadline(now + 4 * 86400, now) == pytest.approx(0.5)


def test_quiet_hours_wraps_midnight():
    p = UserProfile(1, quiet_start="23:00", quiet_end="07:00")
    at = lambda h: dt.datetime(2026, 10, 21, h, 30, tzinfo=TZ).timestamp()  # noqa: E731
    assert in_quiet_hours(p, at(23)) and in_quiet_hours(p, at(2)) and not in_quiet_hours(p, at(12))


def test_change_classification():
    d = diff(
        {"deadline_at": 2000000.0, "attachments": [{"name": "a.pdf"}]},
        {"deadline_at": 2000000.0 - 2 * 86400, "attachments": [{"name": "b.pdf"}]},
    )
    important, note = classify(d)
    assert important and "截止提前 2 天" in note and "附件替换" in note
    important, note = classify(diff({"body": "请  提交"}, {"body": "请提交报告"}))
    assert not important and note == "内容措辞调整"
    assert diff({"body": "a  b"}, {"body": "a b"}) == {}


def test_hash_ring_balance_and_failover():
    ring = HashRing(["push-1", "push-2", "push-3"])
    counts = {}
    for u in range(3000):
        n = ring.get(f"user:{u}")
        counts[n] = counts.get(n, 0) + 1
    assert all(700 < c < 1300 for c in counts.values())
    before = {u: ring.get(f"user:{u}") for u in range(1000)}
    ring.remove("push-2")
    moved = sum(1 for u, n in before.items() if n != "push-2" and ring.get(f"user:{u}") != n)
    assert moved == 0  # 只有原先在 push-2 上的用户被迁移
    assert ring.get("user:1", exclude={"push-1", "push-3"}) is None


def test_token_bucket():
    b = TokenBucket(rate=10, burst=3)
    assert [b.allow("k")[0] for _ in range(4)] == [True, True, True, False]
    time.sleep(0.11)
    assert b.allow("k")[0]


def test_tokens_and_encryption():
    t = security.sign_token({"uid": 5, "tv": 1}, ttl=60)
    assert security.verify_token(t)["uid"] == 5
    assert security.verify_token(t[:-2] + "xx") is None
    assert security.verify_token(security.sign_token({"uid": 5}, ttl=-1)) is None
    blob = security.encrypt({"cookie": "abc"}, aad=b"1:2")
    assert security.decrypt(blob, aad=b"1:2") == {"cookie": "abc"}
    from cryptography.exceptions import InvalidTag

    with pytest.raises(InvalidTag):
        security.decrypt(blob, aad=b"1:3")  # 密文不能挪用到别的用户或来源
    h = security.hash_password("password1")
    assert security.verify_password(h, "password1") and not security.verify_password(h, "x")


def test_metrics_exposition_format():
    r = Registry()
    c = r.counter("x_total", "help", ("a",))
    c.inc(2, 'q"1')
    h = r.histogram("lat_seconds", "lat", buckets=(0.1, 1))
    h.observe(0.05)
    h.observe(5)
    text = r.render()
    assert 'x_total{a="q\\"1"} 2' in text
    assert 'lat_seconds_bucket{le="0.1"} 1' in text and 'lat_seconds_bucket{le="+Inf"} 2' in text
    assert "lat_seconds_count 2" in text


async def test_transfer_chunked_resume_and_range(tmp_path):
    db = await Database(f"sqlite:///{tmp_path / 't.db'}").connect()
    uid = await db.insert(
        "users", {"email": "a@b.c", "password_hash": "x", "created_at": time.time()}
    )
    notes = []

    async def user_of(req):
        return {"id": uid} if req.headers.get("X-User") else None

    async def notify(u, p):
        notes.append(p["status"])

    router = Router()
    TransferService(db, str(tmp_path), user_of, notify).register(router)
    srv = HTTPServer(router, ServerConfig(host="127.0.0.1", port=0))
    await srv.start()
    base = f"http://127.0.0.1:{srv.port}/api/transfer"
    data = os.urandom(300_000)
    sha = hashlib.sha256(data).hexdigest()
    async with HTTPClient() as c:
        created = (await c.post(base, headers={"X-User": "1"})).json()
        code = created["code"]
        joined = (await c.post(f"{base}/{code}/join", json_body={"device": "Pixel"})).json()
        th = {"X-Transfer-Token": joined["token"]}
        assert (await c.get(f"{base}/{code}")).status == 403
        fid = (
            await c.post(
                f"{base}/{code}/files",
                json_body={"name": "a.bin", "size": len(data), "sha256": sha},
                headers=th,
            )
        ).json()["id"]
        chunk = 100_000
        # 先传两块，模拟断线
        for start in (0, chunk):
            r = await c.request(
                "PUT",
                f"{base}/{code}/files/{fid}",
                body=data[start : start + chunk],
                headers={**th, "Content-Range": f"bytes {start}-{start + chunk - 1}/{len(data)}"},
            )
            assert r.status == 200
        # 跳块上传被拒绝，返回已接收字节数
        r = await c.request(
            "PUT",
            f"{base}/{code}/files/{fid}",
            body=b"x",
            headers={**th, "Content-Range": f"bytes 250000-250000/{len(data)}"},
        )
        assert r.status == 409 and r.json()["received"] == 2 * chunk
        # 断点续传：查询进度后继续
        received = (await c.get(f"{base}/{code}/files/{fid}", headers=th)).json()["received"]
        r = await c.request(
            "PUT",
            f"{base}/{code}/files/{fid}",
            body=data[received:],
            headers={**th, "Content-Range": f"bytes {received}-{len(data) - 1}/{len(data)}"},
        )
        assert r.json()["status"] == "done"
        # Range 断点下载
        r = await c.get(
            f"{base}/{code}/files/{fid}/content", headers={**th, "Range": "bytes=100-199"}
        )
        assert r.status == 206 and r.body == data[100:200]
        full = await c.get(f"{base}/{code}/files/{fid}/content", headers=th)
        assert hashlib.sha256(full.body).hexdigest() == r.headers.get("X-Content-SHA256") == sha
    assert notes[:2] == ["paired", "file"] and notes[-1] == "done"
    await srv.close()
    await db.close()


async def test_db_transaction_rollback(tmp_path):
    db = await Database(f"sqlite:///{tmp_path / 'r.db'}").connect()
    uid = await db.insert("users", {"email": "z@b.c", "password_hash": "x", "created_at": 0})
    with pytest.raises(RuntimeError):
        async with db.transaction():
            await db.execute("UPDATE users SET next_seq = 99 WHERE id = ?", uid)
            raise RuntimeError
    assert await db.fetchval("SELECT next_seq FROM users WHERE id = ?", uid) == 0

    async def bump():
        async with db.transaction():
            await db.execute("UPDATE users SET next_seq = next_seq + 1 WHERE id = ?", uid)
            return await db.fetchval("SELECT next_seq FROM users WHERE id = ?", uid)

    seqs = await asyncio.gather(*(bump() for _ in range(20)))
    assert sorted(seqs) == list(range(1, 21))  # 并发分配的 seq 不重复
    await db.close()


async def test_low_priority_delivery_is_pushed_silently(tmp_path):
    from gleaner.core.pipeline import Pipeline

    db = await Database(f"sqlite:///{tmp_path / 'p.db'}").connect()
    uid = await db.insert("users", {"email": "s@b.c", "password_hash": "x", "created_at": 0})
    sid = await db.insert(
        "sources", {"type": "web", "name": "讲座", "endpoint": "http://x/", "created_at": 0}
    )
    await db.execute(
        "INSERT INTO subscriptions (user_id, source_id, weight, created_at) VALUES (?, ?, 0.1, 0)",
        uid,
        sid,
    )
    routed = []

    async def route(topic, payload):
        routed.append((topic, payload))

    pipe = Pipeline(db, route)
    await pipe.ingest(
        {
            "source_id": sid,
            "status": "ok",
            "items": [
                {"key": "web:1", "kind": "notice", "title": "图书馆讲座", "url": "http://x/1"}
            ],
        }
    )
    [(topic, p)] = [r for r in routed if r[0].startswith("u.")]
    assert topic == f"u.{uid}" and p["priority"] == "low" and p["silent"] is True
    assert not [r for r in routed if r[0] == "mqtt.publish"]
    await db.close()


async def test_digest_email_is_opt_in(tmp_path, monkeypatch):
    import datetime as dt

    from gleaner.core import reminders
    from gleaner.core.extract import TZ
    from gleaner.core.pipeline import Pipeline

    sent = []

    async def fake_send(to, subject, text, **kw):
        sent.append((to, subject, text))
        return True

    monkeypatch.setattr(reminders, "send_platform_mail", fake_send)
    db = await Database(f"sqlite:///{tmp_path / 'd.db'}").connect()
    for email, opt in (("a@x.com", 1), ("b@x.com", 0)):
        await db.insert(
            "users",
            {
                "email": email,
                "password_hash": "x",
                "digest_time": "08:00",
                "digest_email": opt,
                "created_at": 0,
            },
        )
    routed = []

    async def route(topic, payload):
        routed.append(topic)

    now = dt.datetime(2026, 10, 22, 8, 0, tzinfo=TZ).timestamp()
    assert await reminders.publish_digests(db, Pipeline(db, route), now) == 2
    assert [s[0] for s in sent] == ["a@x.com"] and "每日摘要" in sent[0][1]
    assert routed.count("mqtt.publish") == 2
    # 同一天不会重复发送
    assert await reminders.publish_digests(db, Pipeline(db, route), now + 30) == 0
    await db.close()
