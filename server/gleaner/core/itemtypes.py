"""产品信息类型与处理状态（产品定义 2.3 节，决策 D21）。

三类：待办 todo（待完成／已完成）、日程 event（未归档／已归档）、通知 notice（未读／已读）。
``items.kind`` 仍是采集渠道（assignment、notice、clip……），与这里的产品类型分开。

默认分类规则只是兜底：插件给出的类型优先，规则以后由分类负责人替换 ``default_type``。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

ITEM_TYPES = ("todo", "event", "notice", "reference")

# 每种类型可用的状态值；第一个是初始状态
STATUSES: dict[str, tuple[str, str]] = {
    "todo": ("open", "done"),
    "event": ("active", "archived"),
    "notice": ("unread", "read"),
}
ALL_STATUSES = tuple(s for pair in STATUSES.values() for s in pair)


def default_type(kind: str, deadline_at: Any, start_at: Any) -> str:
    """没有插件建议时的兜底规则：有活动时间 → 日程；作业或有截止时间 → 待办；其余 → 通知。"""
    if start_at is not None:
        return "event"
    if kind == "assignment" or deadline_at is not None:
        return "todo"
    return "notice"


def status_of(item_type: str, state: dict[str, Any] | None) -> str:
    """按生效类型给出处理状态。"""
    st = state or {}
    if item_type == "todo":
        return "done" if st.get("todo_status") == "done" else "open"
    if item_type == "event":
        return "archived" if st.get("archived_at") is not None else "active"
    return "read" if st.get("read_at") is not None else "unread"


def status_sql(status: str, type_is: Callable[[str], str]) -> str:
    """把状态筛选写成 SQL 条件（别名约定：st = user_item_state）。``type_is(t)`` 给出“生效类型为 t”的条件。"""
    cond = {
        "open": ("todo", "COALESCE(st.todo_status, '') != 'done'"),
        "done": ("todo", "st.todo_status = 'done'"),
        "active": ("event", "st.archived_at IS NULL"),
        "archived": ("event", "st.archived_at IS NOT NULL"),
        "unread": ("notice", "st.read_at IS NULL"),
        "read": ("notice", "st.read_at IS NOT NULL"),
    }
    t, c = cond[status]
    types = f"({type_is(t)} OR {type_is('reference')})" if t == "notice" else type_is(t)
    return f"({types} AND {c})"
