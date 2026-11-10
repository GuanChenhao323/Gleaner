"""出站访问控制（防 SSRF）：用户填写的网址 / 邮箱服务器只能是公网地址。

采集预览、添加来源、自填 IMAP / SMTP 主机都会让服务端去连用户给的地址；不加限制时可以借此访问
内网服务（core:8081、postgres:5432、云厂商元数据 169.254.169.254）并把内容回显出来。

做法：先解析主机名，拒绝回环、私有、链路本地、组播、保留地址，然后**直接连接解析出的 IP**
（避免“检查时是公网、连接时被 DNS 重绑定到内网”）。HTTPS 仍用原主机名做 SNI 与证书校验。

配置（环境变量）：
- ``GLEANER_EGRESS_ALLOW_PRIVATE=1``：允许内网地址（本地开发、测试连 127.0.0.1 上的 fake_moodle）
- ``GLEANER_EGRESS_ALLOW_HOSTS=fake_moodle,greenmail``：按主机名放行（compose 开发环境的测试服务）
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from collections.abc import Awaitable, Callable

Resolve = Callable[[str], Awaitable[str]]


class EgressDenied(Exception):
    """目标地址不允许访问。"""


def _allow_private() -> bool:
    return os.environ.get("GLEANER_EGRESS_ALLOW_PRIVATE", "0") == "1"


def _allow_hosts() -> set[str]:
    raw = os.environ.get("GLEANER_EGRESS_ALLOW_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


async def checked_address(host: str, port: int, resolver: Resolve | None = None) -> str:
    """返回应当连接的第一个地址；目标是内网时抛 ``EgressDenied``。"""
    return (await checked_addresses(host, port, resolver))[0]


async def checked_addresses(host: str, port: int, resolver: Resolve | None = None) -> list[str]:
    """返回全部可以连接的地址（按解析顺序、去重）；任何一个是内网地址都拒绝（防 DNS 重绑定混入内网地址）。

    调用方应依次尝试：例如 ``localhost`` 先解析出 ``::1``，而服务只监听 IPv4 时要退到 ``127.0.0.1``
    （RFC 8305 第 4 节的顺序尝试，这里不做并发竞速）。
    """
    name = host.strip("[]").lower()
    if name in _allow_hosts():
        return [host]
    try:
        ipaddress.ip_address(name)
        ips = [name]
    except ValueError:
        if resolver is not None:
            ips = [await resolver(name)]
        else:
            infos = await asyncio.get_running_loop().getaddrinfo(
                name, port, type=socket.SOCK_STREAM
            )
            ips = [str(i[4][0]) for i in infos]
    if not ips:
        raise EgressDenied(f"{host}: 无法解析")
    if not _allow_private():
        bad = [ip for ip in ips if not is_public(ip)]
        if bad:
            raise EgressDenied(f"{host} 指向内网地址 {bad[0]}，不允许访问")
    return list(dict.fromkeys(ips))
