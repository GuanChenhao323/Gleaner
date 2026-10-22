"""最小 Cookie Jar（RFC 6265 子集）：解析 Set-Cookie、按域与路径回传。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from .message import parse_http_date


@dataclass
class Cookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    expires: float | None = None
    secure: bool = False
    http_only: bool = False
    host_only: bool = True

    def expired(self, now: float | None = None) -> bool:
        return self.expires is not None and self.expires <= (now or time.time())


class CookieJar:
    def __init__(self, cookies: list[Cookie] | None = None) -> None:
        self._cookies: dict[tuple[str, str, str], Cookie] = {}
        for c in cookies or []:
            self._cookies[(c.domain, c.path, c.name)] = c

    def __len__(self) -> int:
        return len(self._cookies)

    def set_from_header(self, header: str, request_host: str, request_path: str = "/") -> None:
        """RFC 6265 §5.2 解析 Set-Cookie。"""
        parts = [p.strip() for p in header.split(";")]
        if not parts or "=" not in parts[0]:
            return
        name, value = parts[0].split("=", 1)
        default_path = request_path.rsplit("/", 1)[0] or "/"
        c = Cookie(
            name=name.strip(), value=value.strip(), domain=request_host.lower(), path=default_path
        )
        max_age: int | None = None
        for attr in parts[1:]:
            k, _, v = attr.partition("=")
            k = k.strip().lower()
            v = v.strip()
            if k == "expires":
                c.expires = parse_http_date(v)
            elif k == "max-age":
                try:
                    max_age = int(v)
                except ValueError:
                    pass
            elif k == "domain" and v:
                c.domain = v.lstrip(".").lower()
                c.host_only = False
            elif k == "path" and v.startswith("/"):
                c.path = v
            elif k == "secure":
                c.secure = True
            elif k == "httponly":
                c.http_only = True
        if max_age is not None:  # Max-Age 优先于 Expires（§5.3 第 3 步）
            c.expires = time.time() + max_age
        key = (c.domain, c.path, c.name)
        if c.expired():
            self._cookies.pop(key, None)
        else:
            self._cookies[key] = c

    def header_for(self, host: str, path: str, secure: bool) -> str | None:
        host = host.lower()
        now = time.time()
        picked: list[Cookie] = []
        for key, c in list(self._cookies.items()):
            if c.expired(now):
                del self._cookies[key]
                continue
            if c.host_only:
                if host != c.domain:
                    continue
            elif host != c.domain and not host.endswith("." + c.domain):
                continue
            if not (path == c.path or path.startswith(c.path.rstrip("/") + "/") or c.path == "/"):
                continue
            if c.secure and not secure:
                continue
            picked.append(c)
        if not picked:
            return None
        picked.sort(key=lambda c: -len(c.path))
        return "; ".join(f"{c.name}={c.value}" for c in picked)

    def clear(self) -> None:
        self._cookies.clear()

    def to_list(self) -> list[dict[str, Any]]:
        return [asdict(c) for c in self._cookies.values()]

    @classmethod
    def from_list(cls, items: list[dict[str, Any]]) -> CookieJar:
        return cls([Cookie(**d) for d in items])
