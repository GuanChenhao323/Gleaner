"""MIME 解析（标准库 email，只做内容解析）：多层 multipart、Base64 / QP、RFC 2047 标题。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime


@dataclass
class ParsedMail:
    message_id: str
    subject: str
    sender: str
    sender_name: str
    to: list[str]
    date: float | None
    text: str
    html: str
    links: list[str] = field(default_factory=list)
    attachments: list[tuple[str, int]] = field(default_factory=list)  # (文件名, 大小)
    headers: dict[str, str] = field(default_factory=dict)


_LINK = re.compile(r"https?://[^\s<>\"')]+")
_TAG = re.compile(r"<[^>]+>")


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html)
    text = _TAG.sub("", html)
    import html as _html

    return re.sub(r"\n\s*\n+", "\n\n", _html.unescape(text)).strip()


def parse_mail(raw: bytes) -> ParsedMail:
    msg = message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    text = ""
    html = ""
    atts: list[tuple[str, int]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = part.get_content_disposition()
        ctype = part.get_content_type()
        if disp == "attachment" or (part.get_filename() and disp != "inline"):
            payload = part.get_payload(decode=True) or b""
            atts.append((part.get_filename() or "attachment", len(payload)))
            continue
        try:
            content = part.get_content()
        except (LookupError, KeyError):
            content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if ctype == "text/plain" and not text:
            text = str(content)
        elif ctype == "text/html" and not html:
            html = str(content)
    if not text and html:
        text = html_to_text(html)
    sender_name, sender = (getaddresses([str(msg.get("From", ""))]) or [("", "")])[0]
    date = None
    if msg.get("Date"):
        try:
            date = parsedate_to_datetime(str(msg["Date"])).timestamp()
        except (TypeError, ValueError):
            date = None
    links = list(dict.fromkeys(_LINK.findall(text + " " + html)))
    return ParsedMail(
        message_id=str(msg.get("Message-ID", "")).strip(),
        subject=str(msg.get("Subject", "")),
        sender=sender.lower(),
        sender_name=sender_name,
        to=[a for _, a in getaddresses([str(v) for v in msg.get_all("To", [])])],
        date=date,
        text=text.strip(),
        html=html,
        links=links,
        attachments=atts,
        headers={k: str(v) for k, v in msg.items()},
    )
