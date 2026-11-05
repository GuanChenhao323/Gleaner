"""接口入参校验：把“客户端传错了”变成 400 / 422，而不是 500。

网关把 5xx 记为上游被动失败（连续多次会摘除节点），所以坏输入绝不能冒成 500。
处理器里用这些函数取参数；校验失败抛 ``BadRequest``，由 ``guard`` 统一转成错误响应。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable
from typing import Any

from ..net.http import Request, Response

log = logging.getLogger(__name__)

_MISSING: Any = object()


class BadRequest(Exception):
    def __init__(self, status: int, message: str, code: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code

    def response(self) -> Response:
        return Response.error(self.status, self.message, self.code)


def invalid(name: str, why: str) -> BadRequest:
    return BadRequest(422, f"参数 {name} {why}", "invalid")


def body_of(req: Request) -> dict[str, Any]:
    """请求体必须是 JSON 对象（空请求体视为 {}）。"""
    try:
        data = req.json()
    except (ValueError, UnicodeDecodeError) as e:
        raise BadRequest(400, "请求体不是合法的 JSON", "bad_json") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise BadRequest(400, "请求体必须是 JSON 对象", "bad_body")
    return data


def path_id(req: Request, name: str = "id") -> int:
    """路径里的数字 id；不是正整数时按“不存在”处理。"""
    raw = str(req.params.get(name, ""))
    if not raw.isdigit() or len(raw) > 18:
        raise BadRequest(404, "资源不存在", "not_found")
    return int(raw)


def as_int(
    v: Any, name: str, *, default: Any = _MISSING, lo: int | None = None, hi: int | None = None
) -> int:
    if v is None or v == "":
        if default is _MISSING:
            raise invalid(name, "不能为空")
        return default
    if isinstance(v, bool):
        raise invalid(name, "应为整数")
    try:
        n = int(v) if not isinstance(v, float) or v.is_integer() else None
    except (TypeError, ValueError):
        n = None
    if n is None:
        raise invalid(name, "应为整数")
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        raise invalid(name, f"超出范围 [{lo}, {hi}]")
    return n


def as_float(
    v: Any,
    name: str,
    *,
    default: Any = _MISSING,
    lo: float | None = None,
    hi: float | None = None,
    clamp: bool = False,
) -> float:
    if v is None or v == "":
        if default is _MISSING:
            raise invalid(name, "不能为空")
        return default
    if isinstance(v, bool):
        raise invalid(name, "应为数字")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise invalid(name, "应为数字") from None
    if not math.isfinite(x):
        raise invalid(name, "应为有限数字")
    if clamp:
        if lo is not None:
            x = max(lo, x)
        if hi is not None:
            x = min(hi, x)
    elif (lo is not None and x < lo) or (hi is not None and x > hi):
        raise invalid(name, f"超出范围 [{lo}, {hi}]")
    return x


def as_str(v: Any, name: str, *, max_len: int, default: Any = _MISSING) -> str:
    if v is None:
        if default is _MISSING:
            raise invalid(name, "不能为空")
        return default
    if not isinstance(v, str | int | float) or isinstance(v, bool):
        raise invalid(name, "应为字符串")
    s = str(v)
    if len(s) > max_len:
        raise invalid(name, f"超过 {max_len} 个字符")
    return s


def as_dict(v: Any, name: str, *, default: Any = _MISSING) -> dict[str, Any]:
    if v is None:
        if default is _MISSING:
            raise invalid(name, "不能为空")
        return default
    if not isinstance(v, dict):
        raise invalid(name, "应为对象")
    return v


def as_list(v: Any, name: str, *, max_len: int, default: Any = _MISSING) -> list[Any]:
    if v is None:
        if default is _MISSING:
            raise invalid(name, "不能为空")
        return default
    if not isinstance(v, list):
        raise invalid(name, "应为数组")
    if len(v) > max_len:
        raise invalid(name, f"最多 {max_len} 项")
    return v


Handler = Callable[[Request], Awaitable[Response]]


def guard(fn: Handler) -> Handler:
    """统一把校验错误转成 4xx；遗漏的类型错误也按 422 返回并记录堆栈，便于补校验。"""

    async def h(req: Request) -> Response:
        try:
            return await fn(req)
        except BadRequest as e:
            return e.response()
        except (ValueError, KeyError, TypeError, AttributeError):
            log.exception("unvalidated input on %s %s", req.method, req.path)
            return Response.error(422, "参数格式不正确", "invalid")

    return h
