"""代用户发信：幂等键 + 唯一 Message-ID 防重复，4xx 退避重试。"""

from __future__ import annotations

import logging
import os
import ssl
import time
import uuid
from typing import Any

from .. import security
from ..net.mail import Attachment, MailError, OutgoingMail, send_with_retry
from ..storage.db import Database

log = logging.getLogger(__name__)


def smtp_settings(secret: dict[str, Any]) -> dict[str, Any]:
    smtp = secret.get("smtp") or {}
    return {
        "host": smtp.get("host") or os.environ.get("GLEANER_SMTP_HOST", "localhost"),
        "port": int(smtp.get("port") or os.environ.get("GLEANER_SMTP_PORT", "587")),
        "security": smtp.get("security") or os.environ.get("GLEANER_SMTP_SECURITY", "starttls"),
        "username": smtp.get("username") or secret.get("username"),
        "password": smtp.get("password") or secret.get("password"),
    }


def _ssl_ctx() -> ssl.SSLContext | None:
    if os.environ.get("GLEANER_SMTP_INSECURE") == "1":
        # 仅开发环境：本地测试邮件服务器使用自签名证书
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


async def send_user_mail(
    db: Database,
    user: dict[str, Any],
    key: str,
    account_source_id: int,
    to: list[str],
    cc: list[str],
    subject: str,
    text: str,
    attachments: list[tuple[str, bytes, str]],
) -> tuple[int, dict[str, Any]]:
    prev = await db.fetchone(
        "SELECT * FROM sent_mails WHERE user_id = ? AND idempotency_key = ?", user["id"], key
    )
    if prev:
        return (200 if prev["status"] != "sending" else 202), {
            "id": prev["id"],
            "status": prev["status"],
            "message_id": prev["message_id"],
            "error": prev["error"],
            "duplicate": True,
        }
    q = "SELECT c.secret_encrypted, c.source_id FROM credentials c JOIN sources s ON s.id = c.source_id WHERE c.user_id = ? AND s.type IN ('imap','pop3')"
    args: list[Any] = [user["id"]]
    if account_source_id:
        q += " AND s.id = ?"
        args.append(account_source_id)
    cred = await db.fetchone(q + " ORDER BY c.updated_at DESC LIMIT 1", *args)
    if not cred:
        return 422, {"error": "no_account", "message": "请先在“来源”中连接学校邮箱"}
    secret = security.decrypt(
        cred["secret_encrypted"], aad=f"{user['id']}:{cred['source_id']}".encode()
    )
    sender = secret.get("username") or user["email"]
    domain = sender.split("@", 1)[-1] if "@" in sender else "gleaner.local"
    message_id = f"<{uuid.uuid5(uuid.NAMESPACE_URL, f'{user["id"]}:{key}').hex}@{domain}>"  # 同一幂等键永远得到同一 Message-ID
    now = time.time()
    try:
        mid = await db.insert(
            "sent_mails",
            {
                "user_id": user["id"],
                "idempotency_key": key,
                "message_id": message_id,
                "recipients": to + cc,
                "subject": subject,
                "status": "sending",
                "created_at": now,
            },
        )
    except Exception:
        # 并发的同键请求：唯一约束冲突
        return 202, {"status": "sending", "duplicate": True}
    mail = OutgoingMail(
        sender=sender,
        to=to,
        cc=cc,
        subject=subject,
        text=text,
        attachments=[Attachment(n, c, m) for n, c, m in attachments],
        message_id=message_id,
    )
    st = smtp_settings(secret)
    try:
        res = await send_with_retry(mail=mail, ssl_context=_ssl_ctx(), **st)
        await db.execute(
            "UPDATE sent_mails SET status = 'sent', sent_at = ? WHERE id = ?", time.time(), mid
        )
        return 200, {
            "id": mid,
            "status": "sent",
            "message_id": message_id,
            "accepted": res.accepted,
            "rejected": res.rejected,
        }
    except (MailError, OSError) as e:
        await db.execute(
            "UPDATE sent_mails SET status = 'failed', error = ? WHERE id = ?", str(e)[:500], mid
        )
        return 502, {"id": mid, "status": "failed", "error": str(e)}


def platform_settings() -> dict[str, Any]:
    """平台自己的发信账号（验证码、每日摘要、运维告警），未配置时沿用 GLEANER_SMTP_*。"""
    env = os.environ.get
    return {
        "host": env("GLEANER_PLATFORM_SMTP_HOST") or env("GLEANER_SMTP_HOST", "localhost"),
        "port": int(env("GLEANER_PLATFORM_SMTP_PORT") or env("GLEANER_SMTP_PORT", "587")),
        "security": env("GLEANER_PLATFORM_SMTP_SECURITY")
        or env("GLEANER_SMTP_SECURITY", "starttls"),
        "username": env("GLEANER_PLATFORM_SMTP_USER") or None,
        "password": env("GLEANER_PLATFORM_SMTP_PASS") or None,
    }


async def send_platform_mail(to: str, subject: str, text: str, *, attempts: int = 3) -> bool:
    """经平台账号发一封通知邮件；失败只记日志，不影响调用方主流程。"""
    st = platform_settings()
    sender = (
        os.environ.get("GLEANER_PLATFORM_MAIL_FROM") or st["username"] or "noreply@gleaner.local"
    )
    try:
        await send_with_retry(
            mail=OutgoingMail(sender=sender, to=[to], subject=subject, text=text),
            attempts=attempts,
            base_delay=0.5,
            ssl_context=_ssl_ctx(),
            **st,
        )
        return True
    except (MailError, OSError) as e:
        log.warning("platform mail to %s failed: %s", to, e)
        return False


async def send_alert(subject: str, text: str) -> bool:
    """运维告警：节点下线或抓取失败率过高时发邮件，复用自研 SMTP。"""
    to = os.environ.get("GLEANER_ALERT_TO")
    if not to:
        return False
    return await send_platform_mail(to, f"[拾课告警] {subject}", text, attempts=2)
