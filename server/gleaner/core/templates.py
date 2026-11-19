"""校园模板：一键添加典型信息源，无需研究网页规则（定位“减少配置”）。

endpoint 中的 ``{moodle}``、``{college}`` 由环境变量替换，开发环境指向 devtools/fake_moodle。
"""

from __future__ import annotations

import os
from typing import Any

TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "moodle",
        "name": "Moodle courses & assignments",
        "type": "moodle",
        "endpoint": "{moodle}",
        "description": "Sign in once to collect assignments, deadlines, and attachments across courses. Prefers Moodle Web Service; falls back to HTML.",
        "needs_login": True,
        "shared": False,
        "weight": 1.0,
        "config": {"mode": "auto"},
        "icon": "school",
    },
    {
        "id": "college_news",
        "name": "College notices",
        "type": "web",
        "endpoint": "{college}/news/",
        "description": "Academic, contest, and lecture notices from the college site, with deadlines and audience when available.",
        "needs_login": False,
        "shared": True,
        "weight": 0.6,
        "config": {
            "item_selector": "ul.news-list li",
            "link_selector": "a[href]",
            "date_selector": ".date",
            "category_selector": ".cat",
            "detail_selector": ".arti-content",
            "limit": 30,
        },
        "icon": "campaign",
    },
    {
        "id": "college_rss",
        "name": "College notices (RSS)",
        "type": "rss",
        "endpoint": "{college}/news/rss.xml",
        "description": "Prefer RSS when the college site offers it; more stable than HTML scraping.",
        "needs_login": False,
        "shared": True,
        "weight": 0.6,
        "config": {},
        "icon": "rss_feed",
    },
    {
        "id": "faculty",
        "name": "Faculty directory",
        "type": "teacher",
        "endpoint": "{college}/faculty/",
        "description": "Office, phone, and email from the faculty pages, shown on course home.",
        "needs_login": False,
        "shared": True,
        "weight": 0.3,
        "config": {"link_selector": ".faculty-list a[href]"},
        "icon": "badge",
    },
    {
        "id": "school_mail",
        "name": "School mail (IMAP)",
        "type": "imap",
        "endpoint": "imap://{mail_host}:{imap_port}",
        "description": "IMAP IDLE for near-instant mail; merges Moodle reminder mail with the same assignment. Use an app password.",
        "needs_login": True,
        "shared": False,
        "weight": 0.8,
        "config": {"mailbox": "INBOX", "tls": False},
        "icon": "mail",
    },
    {
        "id": "school_mail_pop3",
        "name": "School mail (POP3)",
        "type": "pop3",
        "endpoint": "pop3://{mail_host}:{pop3_port}",
        "description": "Fallback for mailboxes without IMAP; polls on a schedule.",
        "needs_login": True,
        "shared": False,
        "weight": 0.8,
        "config": {"tls": False},
        "icon": "mark_email_unread",
    },
]


def _vars() -> dict[str, str]:
    return {
        "moodle": os.environ.get("GLEANER_MOODLE_URL", "http://localhost:8090"),
        "college": os.environ.get("GLEANER_COLLEGE_URL", "http://localhost:8090"),
        "mail_host": os.environ.get("GLEANER_MAIL_HOST", "localhost"),
        "imap_port": os.environ.get("GLEANER_IMAP_PORT", "1143"),
        "pop3_port": os.environ.get("GLEANER_POP3_PORT", "1110"),
    }


def render(t: dict[str, Any]) -> dict[str, Any]:
    out = dict(t)
    out["endpoint"] = t["endpoint"].format(**_vars())
    return out


def list_templates() -> list[dict[str, Any]]:
    return [render(t) for t in TEMPLATES]


def get_template(tid: str) -> dict[str, Any] | None:
    for t in TEMPLATES:
        if t["id"] == tid:
            return render(t)
    return None
