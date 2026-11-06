"""用户修改与来源值分开保存（产品定义 2.4 节，决策 D22）。

``user_item_edits`` 每个被改过的字段一行：``value`` 是用户的值，``base`` 是用户修改时的来源值（都存 JSON）。
来源更新只写 ``items``，从不碰这张表；读取时比较当前来源值与 ``base``：不同说明用户改过之后来源又变了，
标为冲突，两边都返回，由用户选择保留自己的值还是采用来源的新值。
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..storage.db import Database, loads
from .itemtypes import ITEM_TYPES
from .validate import BadRequest, as_float, as_str, invalid

# 可修改字段及校验：时间为 Unix 秒或 null，文本有长度上限
EDITABLE = (
    "title",
    "summary",
    "type",
    "deadline_at",
    "start_at",
    "end_at",
    "location",
    "requirements",
)
TIME_FIELDS = ("deadline_at", "start_at", "end_at")
TEXT_LIMITS = {"title": 300, "summary": 2000, "location": 200, "requirements": 4000}
MAX_TS = 4_102_444_800  # 2100-01-01


def source_values(row: dict[str, Any]) -> dict[str, Any]:
    """事项行里的来源值（采集或插件提供、经流水线处理后的结果）。"""
    attrs = row.get("attrs")
    attrs = attrs if isinstance(attrs, dict) else loads(attrs, {})
    return {
        "title": row.get("title") or "",
        "summary": row.get("summary") or "",
        "type": row.get("item_type") or "notice",
        "deadline_at": row.get("deadline_at"),
        "start_at": attrs.get("start_at"),
        "end_at": attrs.get("end_at"),
        "location": attrs.get("location") or "",
        "requirements": attrs.get("requirements") or "",
    }


def check_value(field: str, value: Any) -> Any:
    """校验并规范化一个字段值；不合法抛 422。"""
    if field not in EDITABLE:
        raise invalid("field", f"不能修改 {field}")
    if field in TIME_FIELDS:
        return None if value is None else as_float(value, field, lo=0, hi=MAX_TS)
    if field == "type":
        if value not in ITEM_TYPES:
            raise invalid("type", "只能是 todo / event / notice")
        return value
    s = (
        " ".join(as_str(value, field, max_len=TEXT_LIMITS[field]).split())
        if field == "title"
        else (as_str(value, field, max_len=TEXT_LIMITS[field]).strip())
    )
    if field == "title" and not s:
        raise invalid("title", "不能为空")
    return s


def _same(a: Any, b: Any) -> bool:
    """比较来源值：时间精确到秒，文本忽略空白差异。"""
    if isinstance(a, int | float) and isinstance(b, int | float):
        return round(a) == round(b)
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.split()) == " ".join(b.split())
    return a == b


async def load(
    db: Database, uid: int, item_ids: list[int]
) -> dict[int, dict[str, tuple[Any, Any]]]:
    """批量读取用户修改：{item_id: {field: (value, base)}}。"""
    out: dict[int, dict[str, tuple[Any, Any]]] = {}
    if not item_ids:
        return out
    for i in range(0, len(item_ids), 500):
        chunk = item_ids[i : i + 500]
        marks = ",".join("?" * len(chunk))
        for r in await db.fetch(
            f"SELECT item_id, field, value, base FROM user_item_edits WHERE user_id = ? AND item_id IN ({marks})",
            uid,
            *chunk,
        ):
            out.setdefault(r["item_id"], {})[r["field"]] = (
                loads(r["value"], None),
                loads(r["base"], None),
            )
    return out


def effective(
    row: dict[str, Any], edits: dict[str, tuple[Any, Any]], deadline_override: Any = None
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[str]]:
    """返回 (生效值, 每个字段的明细, 冲突字段)。

    旧接口的 ``deadline_override`` 没有对应的修改行时，也当作截止时间的用户修改（没有基准，不判冲突）。
    """
    src = source_values(row)
    values: dict[str, Any] = {}
    detail: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = []
    for f in EDITABLE:
        if f in edits:
            value, base = edits[f]
            conflict = not _same(base, src[f])
            edited = True
        elif f == "deadline_at" and deadline_override is not None:
            value, conflict, edited = deadline_override, False, True
        else:
            value, conflict, edited = src[f], False, False
        values[f] = value
        detail[f] = {"value": value, "source": src[f], "edited": edited, "conflict": conflict}
        if conflict:
            conflicts.append(f)
    return values, detail, conflicts


async def apply(
    db: Database, uid: int, row: dict[str, Any], set_: dict[str, Any], reset: list[str]
) -> None:
    """写入修改：``set_`` 为字段新值，``reset`` 为恢复来源值的字段。截止时间同步到旧的 deadline_override。"""
    vals = {f: check_value(f, v) for f, v in set_.items()}
    for f in reset:
        if f not in EDITABLE:
            raise invalid("reset", f"不能修改 {f}")
    if not vals and not reset:
        raise invalid("set", "至少修改一个字段")
    if set(vals) & set(reset):
        raise invalid("reset", "同一字段不能同时修改和恢复")
    src = source_values(row)
    now = time.time()
    async with db.transaction():
        for f, v in vals.items():
            await db.execute(
                "INSERT INTO user_item_edits (user_id, item_id, field, value, base, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (user_id, item_id, field) "
                "DO UPDATE SET value = excluded.value, base = excluded.base, updated_at = excluded.updated_at",
                uid,
                row["id"],
                f,
                json.dumps(v, ensure_ascii=False),
                json.dumps(src[f], ensure_ascii=False),
                now,
            )
        for f in reset:
            await db.execute(
                "DELETE FROM user_item_edits WHERE user_id = ? AND item_id = ? AND field = ?",
                uid,
                row["id"],
                f,
            )
        if "deadline_at" in vals or "deadline_at" in reset:
            # 截止提醒与旧客户端读 deadline_override；用户明确清空截止时间时这里也只能存空
            await _ensure_state(db, uid, row["id"], now)
            await db.execute(
                "UPDATE user_item_state SET deadline_override = ? WHERE user_id = ? AND item_id = ?",
                vals.get("deadline_at"),
                uid,
                row["id"],
            )


async def sync_deadline_override(db: Database, uid: int, row: dict[str, Any], value: Any) -> None:
    """旧接口改 deadline_override 时同步成截止时间的用户修改（清空则撤销修改）。"""
    if value is None:
        await db.execute(
            "DELETE FROM user_item_edits WHERE user_id = ? AND item_id = ? AND field = 'deadline_at'",
            uid,
            row["id"],
        )
        return
    await db.execute(
        "INSERT INTO user_item_edits (user_id, item_id, field, value, base, updated_at) "
        "VALUES (?, ?, 'deadline_at', ?, ?, ?) ON CONFLICT (user_id, item_id, field) "
        "DO UPDATE SET value = excluded.value, base = excluded.base, updated_at = excluded.updated_at",
        uid,
        row["id"],
        json.dumps(value),
        json.dumps(source_values(row)["deadline_at"]),
        time.time(),
    )


async def resolve(db: Database, uid: int, row: dict[str, Any], field: str, keep: str) -> None:
    """处理冲突：mine 保留用户值并以当前来源值为新基准；source 采用来源值并删除修改。"""
    if field not in EDITABLE:
        raise invalid("field", f"不能修改 {field}")
    if keep not in ("mine", "source"):
        raise invalid("keep", "只能是 mine 或 source")
    edits = (await load(db, uid, [row["id"]])).get(row["id"], {})
    _, _, conflicts = effective(row, edits)
    if field not in conflicts:
        raise BadRequest(409, "该字段没有冲突", "no_conflict")
    if keep == "source":
        await apply(db, uid, row, {}, [field])
        return
    await db.execute(
        "UPDATE user_item_edits SET base = ?, updated_at = ? WHERE user_id = ? AND item_id = ? AND field = ?",
        json.dumps(source_values(row)[field], ensure_ascii=False),
        time.time(),
        uid,
        row["id"],
        field,
    )


async def _ensure_state(db: Database, uid: int, item_id: int, now: float) -> None:
    await db.execute(
        "INSERT INTO user_item_state (user_id, item_id, updated_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
        uid,
        item_id,
        now,
    )
