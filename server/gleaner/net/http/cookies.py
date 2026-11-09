"""Cookie Jar（RFC 6265 子集）：解析 Set-Cookie、按域与路径回传。

按 §5.3 存储模型做必要的校验，服务器不能给别的域种 Cookie：
- Domain 属性必须与请求主机域匹配（§5.1.3、§5.3 第 6 步），否则整条忽略；IP 地址只能是 host-only。
- 不接受顶级域或单标签域作 Domain（没有公共后缀表时的最小保护，相当于 §5.3 第 5 步）。
- 从非 https 响应设置的 Secure Cookie 忽略，也不能覆盖已有的 Secure Cookie（RFC 6265bis §5.7）。
- 名称为空、名称或值含控制字符时忽略（§5.2 / RFC 6265bis）。
- 每个域最多 ``MAX_PER_DOMAIN`` 条，总数最多 ``MAX_TOTAL`` 条，超出时淘汰最早的（§6.1 允许实现设上限）。
"""

from __future__ import annotations

import ipaddress
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .message import parse_http_date

MAX_PER_DOMAIN = 50
MAX_TOTAL = 3000
MAX_COOKIE_BYTES = 4096  # 名称 + 值（§6.1 建议至少支持 4096 字节）
_CTL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")  # 允许水平制表符（%x09），其余控制字符一律拒绝


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
    same_site: str = ""
    created: float = field(default_factory=time.time)

    def expired(self, now: float | None = None) -> bool:
        return self.expires is not None and self.expires <= (now or time.time())


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def domain_match(host: str, domain: str) -> bool:
    """RFC 6265 §5.1.3：相同，或 host 以 ``.domain`` 结尾且 host 不是 IP 地址。"""
    host, domain = host.lower(), domain.lower()
    return host == domain or (not _is_ip(host) and host.endswith("." + domain))


def default_path(request_path: str) -> str:
    """RFC 6265 §5.1.4：去掉最后一个 / 之后的部分；不以 / 开头或只有一个 / 时为 /。"""
    path = request_path.split("?", 1)[0]
    if not path.startswith("/") or path.count("/") == 1:
        return "/"
    return path[: path.rfind("/")]


def path_match(request_path: str, cookie_path: str) -> bool:
    """RFC 6265 §5.1.4 路径匹配。"""
    if request_path == cookie_path:
        return True
    if request_path.startswith(cookie_path):
        return cookie_path.endswith("/") or request_path[len(cookie_path)] == "/"
    return False


class CookieJar:
    def __init__(self, cookies: list[Cookie] | None = None) -> None:
        self._cookies: dict[tuple[str, str, str], Cookie] = {}
        for c in cookies or []:
            self._cookies[(c.domain, c.path, c.name)] = c

    def __len__(self) -> int:
        return len(self._cookies)

    def set_from_header(
        self,
        header: str,
        request_host: str,
        request_path: str = "/",
        secure_request: bool = True,
    ) -> bool:
        """RFC 6265 §5.2 解析、§5.3 存储；返回是否接受。``secure_request`` 为响应是否经 https 到达。"""
        parts = header.split(";")
        first = parts[0]
        if "=" not in first:
            return False  # §5.2 第 2 步：没有 = 的整条忽略
        name, value = (x.strip(" \t") for x in first.split("=", 1))
        if not name or _CTL.search(name) or _CTL.search(value) or ";" in value:
            return False
        if len(name) + len(value) > MAX_COOKIE_BYTES:
            return False
        host = request_host.lower().rstrip(".")
        c = Cookie(name=name, value=value, domain=host, path=default_path(request_path))
        max_age: float | None = None
        domain_attr = ""
        for attr in parts[1:]:
            k, _, v = attr.partition("=")
            k = k.strip(" \t").lower()
            v = v.strip(" \t")
            if k == "expires":
                t = parse_http_date(v)
                if t is not None:
                    c.expires = t
            elif k == "max-age":
                # §5.2.2：首字符须为数字或 -，其余全是数字；否则忽略该属性
                if re.fullmatch(r"-?\d+", v):
                    n = int(v)
                    max_age = n if n > 0 else -1  # ≤ 0：立即过期
            elif k == "domain":
                domain_attr = v.lstrip(".").lower().rstrip(".")  # §5.2.3：去掉开头的点
            elif k == "path":
                c.path = v if v.startswith("/") else default_path(request_path)  # §5.2.4
            elif k == "secure":
                c.secure = True
            elif k == "httponly":
                c.http_only = True
            elif k == "samesite":
                c.same_site = v.lower() if v.lower() in ("strict", "lax", "none") else ""
        if max_age is not None:  # Max-Age 优先于 Expires（§5.3 第 3 步）
            c.expires = time.time() + max_age if max_age > 0 else 0.0
        if domain_attr:
            if domain_attr == host:
                pass  # 与主机相同：仍按 domain cookie 处理（§5.3 第 6 步）
            elif _is_ip(host) or not domain_match(host, domain_attr) or "." not in domain_attr:
                return False  # 给别的域、IP 的上级、顶级域种 Cookie：整条忽略
            c.domain = domain_attr
            c.host_only = False
        if c.secure and not secure_request:
            return False  # 非安全来源不能设置 Secure Cookie
        key = (c.domain, c.path, c.name)
        old = self._cookies.get(key)
        if old is not None:
            if old.secure and not secure_request:
                return False  # 非安全来源不能覆盖 Secure Cookie
            c.created = old.created  # §5.3 第 11 步：保留原创建时间
        if c.expired():
            self._cookies.pop(key, None)
            return True
        self._cookies[key] = c
        self._evict(c.domain)
        return True

    def _evict(self, domain: str) -> None:
        now = time.time()
        for key, c in list(self._cookies.items()):
            if c.expired(now):
                del self._cookies[key]
        same = [k for k, c in self._cookies.items() if c.domain == domain]
        if len(same) > MAX_PER_DOMAIN:
            same.sort(key=lambda k: self._cookies[k].created)
            for k in same[: len(same) - MAX_PER_DOMAIN]:
                del self._cookies[k]
        if len(self._cookies) > MAX_TOTAL:
            keys = sorted(self._cookies, key=lambda k: self._cookies[k].created)
            for k in keys[: len(self._cookies) - MAX_TOTAL]:
                del self._cookies[k]

    def header_for(self, host: str, path: str, secure: bool) -> str | None:
        """RFC 6265 §5.4：按域、路径、Secure 选取，路径长的在前，同长度先创建的在前。"""
        host = host.lower().rstrip(".")
        path = path.split("?", 1)[0] or "/"
        now = time.time()
        picked: list[Cookie] = []
        for key, c in list(self._cookies.items()):
            if c.expired(now):
                del self._cookies[key]
                continue
            if c.host_only:
                if host != c.domain:
                    continue
            elif not domain_match(host, c.domain):
                continue
            if not path_match(path, c.path):
                continue
            if c.secure and not secure:
                continue
            picked.append(c)
        if not picked:
            return None
        picked.sort(key=lambda c: (-len(c.path), c.created))
        return "; ".join(f"{c.name}={c.value}" for c in picked)

    def clear(self) -> None:
        self._cookies.clear()

    def to_list(self) -> list[dict[str, Any]]:
        return [asdict(c) for c in self._cookies.values()]

    @classmethod
    def from_list(cls, items: list[dict[str, Any]]) -> CookieJar:
        """从保存的会话恢复；忽略未知字段，兼容旧格式（没有 same_site、created）。"""
        names = set(Cookie.__dataclass_fields__)
        return cls([Cookie(**{k: v for k, v in d.items() if k in names}) for d in items])
