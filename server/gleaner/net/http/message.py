"""HTTP/1.1 消息模型：头部、请求、响应（RFC 9110 / RFC 9112）。"""

from __future__ import annotations

import calendar
import json
import time
from collections.abc import AsyncIterator, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

REASONS: dict[int, str] = {
    100: "Continue",
    101: "Switching Protocols",
    200: "OK",
    201: "Created",
    202: "Accepted",
    204: "No Content",
    206: "Partial Content",
    301: "Moved Permanently",
    302: "Found",
    303: "See Other",
    304: "Not Modified",
    307: "Temporary Redirect",
    308: "Permanent Redirect",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    409: "Conflict",
    411: "Length Required",
    412: "Precondition Failed",
    413: "Content Too Large",
    416: "Range Not Satisfiable",
    422: "Unprocessable Content",
    426: "Upgrade Required",
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
    505: "HTTP Version Not Supported",
}


class Headers:
    """大小写不敏感、保留顺序、允许重复字段的头部集合（RFC 9110 §5）。"""

    __slots__ = ("_items",)

    def __init__(self, items: Iterable[tuple[str, str]] | dict[str, str] | None = None) -> None:
        self._items: list[tuple[str, str]] = []
        if isinstance(items, dict):
            items = items.items()
        for k, v in items or ():
            self._items.append((k, v))

    def get(self, name: str, default: str | None = None) -> str | None:
        lname = name.lower()
        for k, v in self._items:
            if k.lower() == lname:
                return v
        return default

    def get_all(self, name: str) -> list[str]:
        lname = name.lower()
        return [v for k, v in self._items if k.lower() == lname]

    def tokens(self, name: str) -> set[str]:
        """逗号分隔列表字段的小写 token 集合，例如 Connection、Transfer-Encoding。"""
        out: set[str] = set()
        for v in self.get_all(name):
            out.update(t.strip().lower() for t in v.split(",") if t.strip())
        return out

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.get(name) is not None

    def __getitem__(self, name: str) -> str:
        v = self.get(name)
        if v is None:
            raise KeyError(name)
        return v

    def __setitem__(self, name: str, value: str) -> None:
        self.remove(name)
        self._items.append((name, value))

    def add(self, name: str, value: str) -> None:
        self._items.append((name, value))

    def setdefault(self, name: str, value: str) -> None:
        if name not in self:
            self._items.append((name, value))

    def remove(self, name: str) -> None:
        lname = name.lower()
        self._items = [(k, v) for k, v in self._items if k.lower() != lname]

    def items(self) -> list[tuple[str, str]]:
        return list(self._items)

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def copy(self) -> Headers:
        return Headers(self._items)

    def __repr__(self) -> str:
        return f"Headers({self._items!r})"


_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def http_date(ts: float | None = None) -> str:
    """IMF-fixdate，例如 ``Sun, 06 Nov 1994 08:49:37 GMT``（RFC 9110 §5.6.7）。"""
    t = time.gmtime(ts if ts is not None else time.time())
    return (
        f"{_DAYS[t.tm_wday]}, {t.tm_mday:02d} {_MONTHS[t.tm_mon - 1]} {t.tm_year} "
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d} GMT"
    )


def parse_http_date(value: str | None) -> float | None:
    """解析三种 HTTP-date 格式：IMF-fixdate、RFC 850、asctime（RFC 9110 §5.6.7）。"""
    if not value:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S GMT", "%A, %d-%b-%y %H:%M:%S GMT", "%a %b %d %H:%M:%S %Y"):
        try:
            return float(calendar.timegm(time.strptime(value.strip(), fmt)))
        except ValueError:
            continue
    return None


@dataclass
class Request:
    method: str
    target: str
    version: str = "HTTP/1.1"
    headers: Headers = field(default_factory=Headers)
    body: bytes = b""
    # 由服务端填入
    params: dict[str, str] = field(default_factory=dict)
    peer: tuple[str, int] | None = None
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> str:
        return unquote(urlsplit(self.target).path) or "/"

    @property
    def query_string(self) -> str:
        return urlsplit(self.target).query

    @property
    def query(self) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(self.query_string, keep_blank_values=True).items()}

    @property
    def keep_alive(self) -> bool:
        """RFC 9112 §9.3：HTTP/1.1 默认持久连接，HTTP/1.0 需显式 keep-alive。"""
        conn = self.headers.tokens("Connection")
        if "close" in conn:
            return False
        if self.version == "HTTP/1.0":
            return "keep-alive" in conn
        return True

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))

    def cookies(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self.headers.get_all("Cookie"):
            for part in line.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    out[k.strip()] = v.strip()
        return out

    def encode_head(self) -> bytes:
        lines = [f"{self.method} {self.target} {self.version}"]
        lines += [f"{k}: {v}" for k, v in self.headers]
        return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


@dataclass
class Response:
    status: int = 200
    headers: Headers = field(default_factory=Headers)
    body: bytes = b""
    version: str = "HTTP/1.1"
    reason: str = ""
    # 流式响应体：存在时以 chunked 发送（RFC 9112 §7.1）
    stream: AsyncIterator[bytes] | None = None
    # 协议升级回调（WebSocket 等），由服务端在发送 101 后接管连接
    upgrade: Any = None

    def __post_init__(self) -> None:
        if not self.reason:
            self.reason = REASONS.get(self.status, "Unknown")

    @property
    def keep_alive(self) -> bool:
        conn = self.headers.tokens("Connection")
        if "close" in conn:
            return False
        if self.version == "HTTP/1.0":
            return "keep-alive" in conn
        return True

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else None

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")

    def encode_head(self) -> bytes:
        lines = [f"{self.version} {self.status} {self.reason}"]
        lines += [f"{k}: {v}" for k, v in self.headers]
        return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")

    @classmethod
    def json_body(
        cls, data: Any, status: int = 200, headers: dict[str, str] | None = None
    ) -> Response:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        h = Headers(headers or {})
        h["Content-Type"] = "application/json; charset=utf-8"
        return cls(status=status, headers=h, body=body)

    @classmethod
    def text_body(
        cls, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8"
    ) -> Response:
        return cls(
            status=status, headers=Headers({"Content-Type": content_type}), body=text.encode()
        )

    @classmethod
    def error(cls, status: int, message: str = "", code: str = "") -> Response:
        return cls.json_body(
            {"error": code or REASONS.get(status, "error"), "message": message}, status
        )
