"""收信：IMAP IDLE 长连接（秒级到达）与 POP3 轮询，产出 mail 事项交给业务服务。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from .. import security
from ..collector.connectors.base import url_alias
from ..net.mail import IMAPClient, MailError, POP3Client, parse_mail
from ..obs.metrics import REGISTRY
from ..storage.db import Database, loads

log = logging.getLogger(__name__)

MAILS_IN = REGISTRY.counter("gleaner_mail_received_total", "收到的邮件数", ("proto",))
IDLE_CONNS = REGISTRY.gauge("gleaner_imap_idle_connections", "IMAP IDLE 长连接数")

Publish = Callable[[dict[str, Any]], Awaitable[None]]

_ASSIGN_LINK = re.compile(r"/mod/assign/view\.php\?id=\d+")


def mail_snapshot(source_id: int, uid: str, raw: bytes) -> dict[str, Any]:
    p = parse_mail(raw)
    aliases = []
    kind = "mail"
    course = ""
    # Moodle 提醒邮件：带作业链接 → 用链接作为别名键与课程页上的同一作业合并
    for link in p.links:
        if _ASSIGN_LINK.search(link):
            aliases.append(url_alias(link))
    m = re.match(r"^([A-Z]{2,5}\d{3,5})[:：]", p.subject)
    if m:
        course = m.group(1)
    return {
        "key": f"mail:{source_id}:{p.message_id or uid}",
        "kind": kind,
        "title": p.subject or "(无主题)",
        "url": p.links[0] if p.links else "",
        "body": p.text[:5000],
        "course": course,
        "published_at": p.date,
        "attachments": [{"name": n, "size": s} for n, s in p.attachments],
        "attrs": {
            "sender": p.sender,
            "sender_name": p.sender_name,
            "message_id": p.message_id,
            "moodle_reminder": bool(aliases),
        },
        "alias_keys": aliases,
    }


def _hostport(endpoint: str, default: int) -> tuple[str, int]:
    u = urlsplit(endpoint)
    return u.hostname or "localhost", u.port or default


async def probe(src: dict[str, Any], secret: dict[str, Any]) -> tuple[bool, str]:
    """保存邮箱凭据前先试登录一次。"""
    cfg = loads(src.get("config"), {})
    try:
        if src["type"] == "imap":
            host, port = _hostport(src["endpoint"], 993)
            c = IMAPClient(host, port, tls=cfg.get("tls", port == 993), timeout=10)
            await c.connect()
            await c.login(secret["username"], secret["password"])
            await c.logout()
        else:
            host, port = _hostport(src["endpoint"], 995)
            p = POP3Client(host, port, tls=cfg.get("tls", port == 995), timeout=10)
            await p.connect()
            await p.login(secret["username"], secret["password"])
            await p.quit()
        return True, ""
    except (MailError, OSError) as e:
        return False, f"邮箱登录失败：{e}"


class MailboxWorker:
    def __init__(
        self, db: Database, publish: Publish, src: dict[str, Any], secret: dict[str, Any]
    ) -> None:
        self.db = db
        self.publish = publish
        self.src = src
        self.secret = secret
        self.cfg = loads(src.get("config"), {})
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.task = asyncio.get_running_loop().create_task(self.run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task

    async def _state(self) -> dict[str, Any]:
        row = await self.db.fetchone("SELECT stats FROM sources WHERE id = ?", self.src["id"])
        return loads(row["stats"] if row else None, {})

    async def _save(self, stats: dict[str, Any], status: str, error: str | None = None) -> None:
        now = time.time()
        await self.db.execute(
            "UPDATE sources SET stats = ?, status = ?, last_checked_at = ?, last_success_at = CASE WHEN ? = 'ok' THEN ? ELSE last_success_at END, last_error = ? WHERE id = ?",
            json.dumps(stats, ensure_ascii=False),
            status,
            now,
            status,
            now,
            error,
            self.src["id"],
        )

    async def _emit(
        self,
        items: list[dict[str, Any]],
        status: str = "ok",
        error: str = "",
        prev: str | None = None,
    ) -> None:
        await self.publish(
            {
                "source_id": self.src["id"],
                "prev_status": prev,
                "status": status,
                "error": error,
                "checked_at": time.time(),
                "complete": False,
                "items": items,
            }
        )

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                if self.src["type"] == "imap":
                    await self._imap_session()
                else:
                    await self._pop3_poll()
                    backoff = 1.0
                    await asyncio.sleep(float(self.cfg.get("interval", 120)))
                    continue
            except asyncio.CancelledError:
                raise
            except MailError as e:
                bad_login = (
                    "fail" in str(e).lower() or "credential" in str(e).lower() or "-ERR" in str(e)
                )
                status = "need_login" if bad_login else "failed"
                await self._save(await self._state(), status, str(e))
                await self._emit([], status, str(e), prev="ok")
                log.info("mailbox %s error: %s", self.src["id"], e)
                if bad_login:
                    return  # 等用户重新登录，不再反复尝试
            except OSError as e:
                await self._save(await self._state(), "failed", str(e))
            # 断线重连：指数退避 + 抖动
            await asyncio.sleep(backoff * (0.5 + random.random()))
            backoff = min(backoff * 2, 300)

    async def _imap_session(self) -> None:
        host, port = _hostport(self.src["endpoint"], 993)
        c = IMAPClient(host, port, tls=self.cfg.get("tls", port == 993), timeout=60)
        await c.connect()
        try:
            await c.login(self.secret["username"], self.secret["password"])
            info = await c.select(self.cfg.get("mailbox", "INBOX"))
            stats = await self._state()
            st = stats.setdefault("imap", {})
            if st.get("uidvalidity") != info.uidvalidity:
                # UIDVALIDITY 变化说明 UID 失效，只从最新几封重新开始（RFC 3501 §2.3.1.1）
                st["uidvalidity"] = info.uidvalidity
                st["last_uid"] = max(0, info.uidnext - 1 - int(self.cfg.get("initial", 20)))
            await self._save(stats, "ok")
            IDLE_CONNS.inc(1)
            try:
                while True:
                    await self._fetch_new(c, stats)
                    if "IDLE" in c.capabilities:
                        # 每 29 分钟重新发起 IDLE（RFC 2177）
                        await c.idle(timeout=float(self.cfg.get("idle_timeout", 29 * 60)))
                    else:
                        await asyncio.sleep(60)
                        await c.command("NOOP")
            finally:
                IDLE_CONNS.inc(-1)
        finally:
            await c.logout()

    async def _fetch_new(self, c: IMAPClient, stats: dict[str, Any]) -> None:
        st = stats["imap"]
        uids = [u for u in await c.uid_search(f"UID {st['last_uid'] + 1}:*") if u > st["last_uid"]]
        if not uids:
            return
        items = []
        for i in range(0, len(uids), 20):
            batch = await c.uid_fetch(uids[i : i + 20])
            for uid, (raw, _flags) in sorted(batch.items()):
                items.append(mail_snapshot(self.src["id"], str(uid), raw))
                st["last_uid"] = max(st["last_uid"], uid)
        MAILS_IN.inc(len(items), "imap")
        await self._save(stats, "ok")
        await self._emit(items)

    async def _pop3_poll(self) -> None:
        host, port = _hostport(self.src["endpoint"], 995)
        p = POP3Client(host, port, tls=self.cfg.get("tls", port == 995), timeout=30)
        await p.connect()
        try:
            await p.login(self.secret["username"], self.secret["password"])
            listing = await p.uidl()
            stats = await self._state()
            seen = set(stats.get("pop3_seen", []))
            first = not stats.get("pop3_seen")
            new = [(n, u) for n, u in listing.items() if u not in seen]
            if first:
                new = new[-int(self.cfg.get("initial", 20)) :]
            items = []
            for n, uid in new:
                items.append(mail_snapshot(self.src["id"], uid, await p.retr(n)))
            stats["pop3_seen"] = list(listing.values())[-2000:]
            MAILS_IN.inc(len(items), "pop3")
            await self._save(stats, "ok")
            if items:
                await self._emit(items)
        finally:
            await p.quit()


class MailService:
    def __init__(self, db: Database, publish: Publish, node_id: str) -> None:
        self.db = db
        self.publish = publish
        self.node_id = node_id
        self.workers: dict[int, MailboxWorker] = {}
        from ..common.hashring import HashRing

        self.ring = HashRing([node_id])

    def set_nodes(self, nodes: list[str]) -> None:
        from ..common.hashring import HashRing

        self.ring = HashRing(sorted(set(nodes) | {self.node_id}))

    async def reconcile(self) -> None:
        """启动本节点负责的邮箱长连接（按用户分片），停止不再负责或已删除的。"""
        rows = await self.db.fetch(
            "SELECT s.*, c.user_id AS cred_user, c.secret_encrypted, c.updated_at AS cred_at FROM sources s JOIN credentials c ON c.source_id = s.id WHERE s.type IN ('imap','pop3')"
        )
        wanted: dict[int, dict[str, Any]] = {}
        for r in rows:
            if self.ring.get(f"user:{r['cred_user']}") != self.node_id:
                continue
            wanted[r["id"]] = r
        for sid in list(self.workers):
            if sid not in wanted:
                await self.workers.pop(sid).stop()
        for sid, r in wanted.items():
            w = self.workers.get(sid)
            if w and w.src.get("cred_at") == r["cred_at"] and w.task and not w.task.done():
                continue
            if w:
                await w.stop()
            try:
                secret = security.decrypt(
                    r["secret_encrypted"], aad=f"{r['cred_user']}:{sid}".encode()
                )
            except Exception:
                continue
            nw = MailboxWorker(self.db, self.publish, r, secret)
            nw.start()
            self.workers[sid] = nw

    async def close(self) -> None:
        for w in self.workers.values():
            await w.stop()
