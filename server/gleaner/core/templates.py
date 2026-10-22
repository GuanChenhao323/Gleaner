"""校园模板：一键添加典型信息源，无需研究网页规则（定位“减少配置”）。

endpoint 中的 ``{moodle}``、``{college}`` 由环境变量替换，开发环境指向 devtools/fake_moodle。
"""

from __future__ import annotations

import os
from typing import Any

TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "moodle",
        "name": "Moodle 课程与作业",
        "type": "moodle",
        "endpoint": "{moodle}",
        "description": "登录一次即可汇总所有课程的作业、截止时间与附件。优先使用 Moodle Web Service，失败时解析网页。",
        "needs_login": True,
        "shared": False,
        "weight": 1.0,
        "config": {"mode": "auto"},
        "icon": "school",
    },
    {
        "id": "college_news",
        "name": "学院通知公告",
        "type": "web",
        "endpoint": "{college}/news/",
        "description": "学院官网的教务、竞赛、讲座通知，自动提取截止时间与适用对象。",
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
        "name": "学院通知（RSS）",
        "type": "rss",
        "endpoint": "{college}/news/rss.xml",
        "description": "如果学院网站提供 RSS，用它比解析网页更稳定。",
        "needs_login": False,
        "shared": True,
        "weight": 0.6,
        "config": {},
        "icon": "rss_feed",
    },
    {
        "id": "faculty",
        "name": "教师信息",
        "type": "teacher",
        "endpoint": "{college}/faculty/",
        "description": "从学校官网补充老师的办公室、电话和邮箱，显示在课程主页。",
        "needs_login": False,
        "shared": True,
        "weight": 0.3,
        "config": {"link_selector": ".faculty-list a[href]"},
        "icon": "badge",
    },
    {
        "id": "school_mail",
        "name": "学校邮箱（IMAP）",
        "type": "imap",
        "endpoint": "imap://{mail_host}:{imap_port}",
        "description": "IMAP IDLE 长连接，新邮件秒级到达；识别 Moodle 提醒邮件并与课程页的同一作业合并。请使用应用专用密码。",
        "needs_login": True,
        "shared": False,
        "weight": 0.8,
        "config": {"mailbox": "INBOX", "tls": False},
        "icon": "mail",
    },
    {
        "id": "school_mail_pop3",
        "name": "学校邮箱（POP3）",
        "type": "pop3",
        "endpoint": "pop3://{mail_host}:{pop3_port}",
        "description": "不支持 IMAP 的邮箱的兼容方案，定时拉取。",
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
