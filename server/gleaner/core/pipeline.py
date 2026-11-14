"""业务流水线：采集结果 → 去重与跨渠道合并 → 版本比较 → 打分 → 投递（proposal“一条通知的端到端流程”）。"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..obs.metrics import REGISTRY
from ..storage.db import Database, loads
from .changes import classify, diff
from .extract import TZ, extract_deadline, extract_facts
from .scoring import UserProfile, in_quiet_hours, score_item
from .summarize import Summarizer

log = logging.getLogger(__name__)

ITEMS_NEW = REGISTRY.counter("gleaner_items_new_total", "新事项数", ("kind",))
ITEMS_CHANGED = REGISTRY.counter("gleaner_items_changed_total", "事项变更数", ("important",))
ITEMS_MERGED = REGISTRY.counter("gleaner_items_merged_total", "跨渠道合并次数")
DELIVERIES = REGISTRY.counter("gleaner_deliveries_total", "投递数", ("priority",))

# route(topic, payload)：发往总线（推送节点订阅 u.<uid>，Broker 订阅 mqtt.*）
Route = Callable[[str, dict[str, Any]], Awaitable[None]]


def dedupe_hash(source_id: int, url: str, title: str) -> str:
    """来源 + 链接 + 标题 的哈希，重复内容不入库（技术方案 5）。"""
    return hashlib.sha1(f"{source_id}|{url}|{title.strip()}".encode()).hexdigest()


def owner_prefix(owner_id: int) -> str:
    """个人来源的身份键与别名键前缀；采集器给出的键本身不会以 @ 开头。"""
    return f"@{owner_id}/"


def _scope(source: dict[str, Any], snap: dict[str, Any]) -> dict[str, Any]:
    """个人来源（Moodle、个人邮箱）按所有者隔离身份键与别名键：

    两个同学登录同一个 Moodle，作业的 cmid 相同，不加隔离会被当成同一条事项，
    后登录的人看不到；邮件按链接别名合并时也可能并进别人的事项。公共来源保持全局键，
    个人来源仍可以按原始别名与公共来源的事项合并（shared_alias_keys）。
    """
    owner = source.get("owner_id")
    if owner is None:
        return snap
    p = owner_prefix(int(owner))
    aliases = snap.get("alias_keys") or []
    return {
        **snap,
        "key": p + snap["key"],
        "alias_keys": [p + a for a in aliases],
        "shared_alias_keys": aliases,
    }


def item_public(
    row: dict[str, Any], state: dict[str, Any] | None = None, source: dict[str, Any] | None = None
) -> dict[str, Any]:
    """事项对外的 JSON 形状（REST 与 WebSocket 共用）。"""
    attrs = loads(row.get("attrs"), {})
    out = {
        "id": row["id"],
        "kind": row["kind"],
        "course": row.get("course", ""),
        "title": row["title"],
        "raw_title": row.get("raw_title") or row["title"],
        "summary": row.get("summary", ""),
        "url": row.get("url", ""),
        "deadline_at": row.get("deadline_at"),
        "published_at": row.get("published_at"),
        "version": row.get("version", 1),
        "deleted": bool(row.get("deleted")),
        "source_id": row["source_id"],
        "first_seen_at": row.get("first_seen_at"),
        "updated_at": row.get("updated_at"),
        "attachments": attrs.get("attachments", []),
        "requirements": attrs.get("requirements", ""),
        "channels": attrs.get("channels", []),
        "facts": attrs.get("facts", {}),
        "category": attrs.get("category", ""),
        "change_note": attrs.get("change_note", ""),
        "important_change": bool(attrs.get("important_change")),
        "summary_by": attrs.get("summary_by", "rule"),
        "source_fields": attrs.get("raw_fields", {}),
        "web_capture": attrs.get("web_capture"),
    }
    if source is not None:
        out["source"] = {
            "id": source["id"],
            "name": source["name"],
            "type": source["type"],
            "last_success_at": source.get("last_success_at"),
            "status": source.get("status"),
        }
    if state is not None:
        out["state"] = {
            "read": state.get("read_at") is not None,
            "starred": bool(state.get("starred")),
            "todo": state.get("todo_status") or "",
            "hidden": bool(state.get("hidden")),
            "deadline_override": state.get("deadline_override"),
            "note": state.get("note", ""),
        }
        out["score"] = state.get("score", 0)
        out["priority"] = state.get("priority", "low")
        out["reasons"] = loads(state.get("reasons"), [])
    return out


async def load_profile(db: Database, user: dict[str, Any]) -> UserProfile:
    rules = await db.fetch("SELECT kind, pattern, boost FROM rules WHERE user_id = ?", user["id"])
    subs = await db.fetch(
        "SELECT source_id, weight FROM subscriptions WHERE user_id = ?", user["id"]
    )
    return UserProfile(
        user_id=user["id"],
        grade=user.get("grade") or "",
        major=user.get("major") or "",
        courses=loads(user.get("courses"), []),
        quiet_start=user.get("quiet_start") or "23:00",
        quiet_end=user.get("quiet_end") or "07:00",
        boost_words=[
            (r["pattern"], float(r["boost"]))
            for r in rules
            if r["kind"] == "keyword" and r["boost"] > 0
        ],
        block_words=[r["pattern"] for r in rules if r["kind"] == "keyword" and r["boost"] <= 0],
        sender_whitelist=[r["pattern"] for r in rules if r["kind"] == "sender" and r["boost"] > 0],
        source_weights={s["source_id"]: float(s["weight"]) for s in subs},
    )


class Pipeline:
    def __init__(self, db: Database, route: Route, summarizer: Summarizer | None = None) -> None:
        self.db = db
        self.route = route
        self.summarizer = summarizer or Summarizer()

    # -- 入口 --------------------------------------------------------------------

    async def ingest(self, msg: dict[str, Any]) -> dict[str, int]:
        sid = int(msg["source_id"])
        source = await self.db.fetchone("SELECT * FROM sources WHERE id = ?", sid)
        if source is None:
            return {}
        counts = {"new": 0, "changed": 0, "merged": 0, "removed": 0, "duplicate": 0}
        await self._status_transition(source, msg)
        if msg.get("status") != "ok":
            return counts
        seen: set[str] = set()
        for snap in msg.get("items", []):
            snap = _scope(source, snap)
            seen.add(snap["key"])
            kind = await self._upsert(source, snap)
            if kind:
                counts[kind] += 1
        if msg.get("complete"):
            counts["removed"] = await self._detect_removed(source, seen)
        return counts

    async def _status_transition(self, source: dict[str, Any], msg: dict[str, Any]) -> None:
        """来源状态变化时通知订阅者：需要重新登录、检查失败、恢复正常。"""
        new = {
            "ok": "ok",
            "not_modified": "ok",
            "failed": "failed",
            "need_login": "need_login",
        }.get(msg.get("status", ""), "failed")
        prev = msg.get("prev_status") or source.get("status")
        if new == prev or (new == "ok" and prev == "pending"):
            return
        if new == "failed" and (source.get("fail_count") or 0) < 3:
            return  # 偶发失败不打扰，连续 3 次才提示
        payload = {
            "type": "source_status",
            "source_id": source["id"],
            "name": source["name"],
            "status": new,
            "error": msg.get("error", ""),
            "last_success_at": source.get("last_success_at"),
        }
        for sub in await self.db.fetch(
            "SELECT user_id FROM subscriptions WHERE source_id = ?", source["id"]
        ):
            prio = "urgent" if new == "need_login" else "normal"
            await self._deliver(
                sub["user_id"],
                None,
                None,
                "source_status",
                0,
                prio,
                payload,
                mqtt_topic="status" if new == "need_login" else None,
            )

    # -- 事项 --------------------------------------------------------------------

    async def _find(self, snap: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
        row = await self.db.fetchone("SELECT * FROM items WHERE identity_key = ?", snap["key"])
        if row:
            return row, False
        for alias in snap.get("alias_keys") or []:
            a = await self.db.fetchone(
                "SELECT item_id FROM item_aliases WHERE alias_key = ?", alias
            )
            if a:
                return await self.db.fetchone(
                    "SELECT * FROM items WHERE id = ?", a["item_id"]
                ), True
        # 个人来源还可以与公共来源（学院通知等）的同一事项合并，但不会匹配到别人的个人事项
        for alias in snap.get("shared_alias_keys") or []:
            a = await self.db.fetchone(
                "SELECT al.item_id FROM item_aliases al JOIN items i ON i.id = al.item_id "
                "JOIN sources s ON s.id = i.source_id WHERE al.alias_key = ? AND s.owner_id IS NULL",
                alias,
            )
            if a:
                return await self.db.fetchone(
                    "SELECT * FROM items WHERE id = ?", a["item_id"]
                ), True
        return None, False

    async def _enrich(self, source: dict[str, Any], snap: dict[str, Any]) -> dict[str, Any]:
        body = snap.get("body") or ""
        published = snap.get("published_at")
        deadline = snap.get("deadline_at")
        dl_text = (snap.get("attrs") or {}).get("deadline_text", "")
        if (
            deadline is None
            and not (snap.get("attrs") or {}).get("suppress_deadline")
            and snap.get("kind")
            in (
                "notice",
                "mail",
                "assignment",
                "rss",
                "clip",
                "page",
            )
        ):
            m = extract_deadline(
                f"{snap.get('title', '')} {body} {(snap.get('attrs') or {}).get('raw_fields', {}).get('datetime_text', '')}",
                dt.datetime.fromtimestamp(published, TZ) if published else None,
            )
            if m:
                deadline, dl_text = m.at.timestamp(), m.text
        s = (
            await self.summarizer.summarize(snap.get("title", ""), body)
            if snap.get("kind") != "teacher"
            else self.summarizer.rule(snap["title"], body)
        )
        attrs = dict(snap.get("attrs") or {})
        attrs.update(
            {
                "attachments": snap.get("attachments") or [],
                "requirements": snap.get("requirements") or "",
                "facts": extract_facts(f"{snap.get('title', '')} {body}"),
                "summary_by": s.by,
                "deadline_text": dl_text,
                "channels": [source["type"]],
            }
        )
        return {
            "kind": snap.get("kind", "notice"),
            "course": snap.get("course") or source.get("course") or "",
            "title": s.title
            if snap.get("kind") in ("notice", "mail", "rss")
            else snap.get("title", ""),
            "raw_title": snap.get("title", ""),
            "summary": s.summary,
            "body": body[:20000],
            "url": snap.get("url", ""),
            "deadline_at": deadline,
            "published_at": published,
            "attrs": attrs,
        }

    async def _upsert(self, source: dict[str, Any], snap: dict[str, Any]) -> str | None:
        now = time.time()
        existing, via_alias = await self._find(snap)
        if existing and via_alias and existing["source_id"] != source["id"]:
            return await self._merge(source, existing, snap)
        if existing is None:
            h = dedupe_hash(source["id"], snap.get("url", ""), snap.get("title", ""))
            if await self.db.fetchone(
                "SELECT id FROM items WHERE content_hash = ? AND source_id = ?", h, source["id"]
            ):
                return "duplicate"
            fields = await self._enrich(source, snap)
            item_id = await self.db.insert(
                "items",
                {
                    "source_id": source["id"],
                    "identity_key": snap["key"],
                    "content_hash": h,
                    **{k: v for k, v in fields.items()},
                    "version": 1,
                    "first_seen_at": now,
                    "updated_at": now,
                },
            )
            await self.db.insert(
                "item_versions",
                {
                    "item_id": item_id,
                    "version": 1,
                    "snapshot": _snapshot(fields),
                    "changed_fields": {},
                    "important": 0,
                    "detected_at": now,
                },
            )
            for alias in snap.get("alias_keys") or []:
                await self.db.execute(
                    "INSERT INTO item_aliases (alias_key, item_id, source_id, created_at) VALUES (?, ?, ?, ?) ON CONFLICT (alias_key) DO NOTHING",
                    alias,
                    item_id,
                    source["id"],
                    now,
                )
            ITEMS_NEW.inc(1, fields["kind"])
            row = await self.db.fetchone("SELECT * FROM items WHERE id = ?", item_id)
            assert row
            if fields["kind"] != "teacher":
                await self._fanout(source, row, kind="item")
            return "new"
        # 已有事项：逐字段比较
        fields = await self._enrich(source, snap)
        old_attrs = loads(existing.get("attrs"), {})
        old_snap = {
            "source_fields": old_attrs.get("raw_fields", {}),
            "title": existing["raw_title"] or existing["title"],
            "deadline_at": existing.get("deadline_at"),
            "attachments": old_attrs.get("attachments", []),
            "requirements": old_attrs.get("requirements", ""),
            "body": existing.get("body", ""),
            "url": existing.get("url", ""),
            "course": existing.get("course", ""),
        }
        new_snap = {
            "source_fields": fields["attrs"].get("raw_fields", {}),
            "title": fields["raw_title"],
            "deadline_at": fields["deadline_at"],
            "attachments": fields["attrs"]["attachments"],
            "requirements": fields["attrs"]["requirements"],
            "body": fields["body"],
            "url": fields["url"],
            "course": fields["course"],
        }
        changed = diff(old_snap, new_snap)
        if not changed and not existing.get("deleted"):
            return None
        important, note = classify(changed) if changed else (False, "重新出现")
        version = int(existing["version"]) + 1
        attrs = {
            **old_attrs,
            **fields["attrs"],
            "channels": sorted(
                set(old_attrs.get("channels", [])) | set(fields["attrs"]["channels"])
            ),
            "change_note": note,
            "important_change": important,
        }
        await self.db.execute(
            "UPDATE items SET title = ?, raw_title = ?, summary = ?, body = ?, url = ?, course = ?, deadline_at = ?, attrs = ?, version = ?, deleted = 0, updated_at = ? WHERE id = ?",
            fields["title"],
            fields["raw_title"],
            fields["summary"],
            fields["body"],
            fields["url"],
            fields["course"],
            fields["deadline_at"],
            json.dumps(attrs, ensure_ascii=False, default=str),
            version,
            now,
            existing["id"],
        )
        await self.db.insert(
            "item_versions",
            {
                "item_id": existing["id"],
                "version": version,
                "snapshot": _snapshot({**fields, "attrs": attrs}),
                "changed_fields": changed,
                "important": int(important),
                "change_note": note,
                "detected_at": now,
            },
        )
        ITEMS_CHANGED.inc(1, str(important).lower())
        row = await self.db.fetchone("SELECT * FROM items WHERE id = ?", existing["id"])
        assert row
        if row["kind"] != "teacher":
            await self._fanout(
                source, row, kind="change", changed=changed, important=important, note=note
            )
        return "changed"

    async def _merge(
        self, source: dict[str, Any], item: dict[str, Any], snap: dict[str, Any]
    ) -> str:
        """跨渠道合并：例如 Moodle 提醒邮件与课程页上的同一作业只保留一条事项（场景 3）。"""
        now = time.time()
        attrs = loads(item.get("attrs"), {})
        channels = set(attrs.get("channels", []))
        if source["type"] in channels and await self.db.fetchone(
            "SELECT 1 FROM item_aliases WHERE alias_key = ?", snap["key"]
        ):
            return "duplicate"
        channels.add(source["type"])
        attrs["channels"] = sorted(channels)
        attrs.setdefault("merged_from", []).append(
            {"source_id": source["id"], "title": snap.get("title"), "at": now}
        )
        await self.db.execute(
            "UPDATE items SET attrs = ? WHERE id = ?",
            json.dumps(attrs, ensure_ascii=False, default=str),
            item["id"],
        )
        await self.db.execute(
            "INSERT INTO item_aliases (alias_key, item_id, source_id, created_at) VALUES (?, ?, ?, ?) ON CONFLICT (alias_key) DO NOTHING",
            snap["key"],
            item["id"],
            source["id"],
            now,
        )
        ITEMS_MERGED.inc()
        # 新渠道的订阅者如果原本没订阅原始来源，也应该看到该事项
        row = await self.db.fetchone("SELECT * FROM items WHERE id = ?", item["id"])
        assert row
        orig = await self.db.fetchone("SELECT * FROM sources WHERE id = ?", item["source_id"])
        await self._fanout(source, row, kind="item", only_new_users=True, origin_source=orig)
        return "merged"

    async def _detect_removed(self, source: dict[str, Any], seen: set[str]) -> int:
        rows = await self.db.fetch(
            "SELECT * FROM items WHERE source_id = ? AND deleted = 0 AND kind != 'mail'",
            source["id"],
        )
        n = 0
        now = time.time()
        for row in rows:
            if row["identity_key"] in seen:
                continue
            version = int(row["version"]) + 1
            attrs = loads(row.get("attrs"), {})
            attrs["change_note"] = "来源已删除该事项"
            await self.db.execute(
                "UPDATE items SET deleted = 1, version = ?, attrs = ?, updated_at = ? WHERE id = ?",
                version,
                json.dumps(attrs, ensure_ascii=False),
                now,
                row["id"],
            )
            await self.db.insert(
                "item_versions",
                {
                    "item_id": row["id"],
                    "version": version,
                    "snapshot": "{}",
                    "changed_fields": {"deleted": [False, True]},
                    "important": 0,
                    "change_note": "来源已删除该事项",
                    "detected_at": now,
                },
            )
            row = {
                **row,
                "deleted": 1,
                "version": version,
                "attrs": json.dumps(attrs, ensure_ascii=False),
            }
            await self._fanout(
                source,
                row,
                kind="change",
                changed={"deleted": [False, True]},
                important=False,
                note="来源已删除该事项",
            )
            n += 1
        return n

    # -- 投递 --------------------------------------------------------------------

    async def _fanout(
        self,
        source: dict[str, Any],
        item: dict[str, Any],
        *,
        kind: str,
        changed: dict[str, Any] | None = None,
        important: bool = False,
        note: str = "",
        only_new_users: bool = False,
        origin_source: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        subs = await self.db.fetch(
            "SELECT u.*, s.weight AS sub_weight, s.muted AS sub_muted FROM subscriptions s JOIN users u ON u.id = s.user_id WHERE s.source_id = ?",
            source["id"],
        )
        if only_new_users and origin_source:
            already = {
                r["user_id"]
                for r in await self.db.fetch(
                    "SELECT user_id FROM subscriptions WHERE source_id = ?", origin_source["id"]
                )
            }
            subs = [s for s in subs if s["id"] not in already]
        attrs = loads(item.get("attrs"), {})
        for user in subs:
            if user.get("sub_muted"):
                continue
            profile = await load_profile(self.db, user)
            state = await self.db.fetchone(
                "SELECT * FROM user_item_state WHERE user_id = ? AND item_id = ?",
                user["id"],
                item["id"],
            )
            if state and state.get("not_important") and not important:
                continue
            sc = score_item(
                {**item, "facts": attrs.get("facts"), "attrs": attrs},
                profile,
                source_id=source["id"],
                source_weight=float(user.get("sub_weight") or 0.7),
                important_change=important,
                now=now,
            )
            await self.db.execute(
                """INSERT INTO user_item_state (user_id, item_id, score, priority, reasons, updated_at) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (user_id, item_id) DO UPDATE SET score = excluded.score, priority = excluded.priority, reasons = excluded.reasons""",
                user["id"],
                item["id"],
                sc.total,
                sc.priority,
                json.dumps(sc.reasons, ensure_ascii=False),
                now,
            )
            state = await self.db.fetchone(
                "SELECT * FROM user_item_state WHERE user_id = ? AND item_id = ?",
                user["id"],
                item["id"],
            )
            pub = item_public(item, state, origin_source or source)
            if kind == "item":
                payload: dict[str, Any] = {"type": "item", "priority": sc.priority, "item": pub}
            else:
                payload = {
                    "type": "change",
                    "item_id": item["id"],
                    "version": item["version"],
                    "important": important,
                    "changed": changed or {},
                    "note": note,
                    "priority": sc.priority,
                    "item": pub,
                }
            quiet = in_quiet_hours(profile, now)
            mqtt = "urgent" if sc.priority == "urgent" else None
            # 低优先级照常实时推送但静默（不提醒、不发 MQTT）；免打扰时段内普通级同样静默
            payload["silent"] = sc.priority == "low" or (quiet and sc.priority != "urgent")
            await self._deliver(
                user["id"],
                item["id"],
                item["version"],
                kind,
                sc.total,
                sc.priority,
                payload,
                mqtt_topic=mqtt,
            )

    async def _deliver(
        self,
        user_id: int,
        item_id: int | None,
        version: int | None,
        kind: str,
        score: int,
        priority: str,
        payload: dict[str, Any],
        *,
        mqtt_topic: str | None = None,
    ) -> int:
        """为用户分配下一个 seq 并写投递记录；按优先级路由到推送节点与 MQTT。"""
        now = time.time()
        async with self.db.transaction():
            await self.db.execute("UPDATE users SET next_seq = next_seq + 1 WHERE id = ?", user_id)
            seq = int(await self.db.fetchval("SELECT next_seq FROM users WHERE id = ?", user_id))
            payload = {**payload, "seq": seq}
            channel = "ws+mqtt" if mqtt_topic else ("ws" if priority != "low" else "ws-silent")
            await self.db.insert(
                "deliveries",
                {
                    "user_id": user_id,
                    "seq": seq,
                    "item_id": item_id,
                    "version": version,
                    "kind": kind,
                    "score": score,
                    "priority": priority,
                    "channel": channel,
                    "payload": payload,
                    "created_at": now,
                },
            )
        DELIVERIES.inc(1, priority)
        payload["created_at"] = now
        # 所有投递都实时推送到在线客户端；< 40 分带 silent 标记，只更新界面不提醒（组长决定，见 docs/decisions.md）
        await self.route(f"u.{user_id}", payload)
        if mqtt_topic:
            await self.route(
                "mqtt.publish",
                {
                    "topic": f"gleaner/u/{user_id}/{mqtt_topic}",
                    "qos": 1,
                    "retain": False,
                    "payload": _mqtt_payload(payload),
                },
            )
        return seq


def _snapshot(fields: dict[str, Any]) -> str:
    return json.dumps(
        {
            k: fields.get(k)
            for k in ("title", "raw_title", "deadline_at", "url", "course", "summary", "attrs")
        },
        ensure_ascii=False,
        default=str,
    )


def _mqtt_payload(p: dict[str, Any]) -> dict[str, Any]:
    """MQTT 只带系统通知所需的精简字段。"""
    item = p.get("item") or {}
    title = item.get("title") or p.get("name") or "拾课提醒"
    if p.get("type") == "source_status":
        body = f"「{p.get('name')}」需要重新登录"
    elif p.get("type") == "change":
        body = p.get("note") or "事项有变化"
    elif p.get("type") == "reminder":
        body = p.get("text", "")
    else:
        body = item.get("summary", "")[:80]
    return {
        "seq": p.get("seq"),
        "type": p.get("type"),
        "title": title,
        "body": body,
        "item_id": item.get("id") or p.get("item_id"),
        "url": item.get("url", ""),
    }
