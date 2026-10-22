"""自研异步 DNS 解析器（RFC 1035）。

- 报文编解码：头部（§4.1.1）、问题段（§4.1.2）、资源记录（§4.1.3）、名字压缩指针（§4.1.4）
- UDP 查询，超时后按服务器列表轮换并指数退避重试；TC 位置位时改走 TCP（§4.2.2）
- 按 TTL 缓存，同时缓存 NXDOMAIN（负缓存，RFC 2308）
- 跟随 CNAME 链
"""

from __future__ import annotations

import asyncio
import os
import random
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_AAAA = 28
CLASS_IN = 1

RCODE_NXDOMAIN = 3


class DNSError(Exception):
    pass


@dataclass
class Record:
    name: str
    type: int
    cls: int
    ttl: int
    data: str | bytes


@dataclass
class DNSMessage:
    id: int
    flags: int
    questions: list[tuple[str, int, int]] = field(default_factory=list)
    answers: list[Record] = field(default_factory=list)
    authority: list[Record] = field(default_factory=list)
    additional: list[Record] = field(default_factory=list)

    @property
    def rcode(self) -> int:
        return self.flags & 0x0F

    @property
    def truncated(self) -> bool:
        return bool(self.flags & 0x0200)

    @property
    def is_response(self) -> bool:
        return bool(self.flags & 0x8000)


def encode_name(name: str) -> bytes:
    out = bytearray()
    for label in name.rstrip(".").split("."):
        if not label:
            continue
        b = label.encode("idna") if not label.isascii() else label.encode()
        if len(b) > 63:
            raise DNSError("label too long")
        out.append(len(b))
        out += b
    out.append(0)
    if len(out) > 255:
        raise DNSError("name too long")
    return bytes(out)


def encode_query(name: str, qtype: int = TYPE_A, qid: int | None = None) -> tuple[int, bytes]:
    qid = random.getrandbits(16) if qid is None else qid
    # 标志：RD=1（期望递归，§4.1.1）
    header = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    return qid, header + encode_name(name) + struct.pack("!HH", qtype, CLASS_IN)


def _decode_name(data: bytes, off: int) -> tuple[str, int]:
    labels: list[str] = []
    jumped = False
    end = off
    hops = 0
    while True:
        if off >= len(data):
            raise DNSError("name out of bounds")
        n = data[off]
        if n & 0xC0 == 0xC0:  # 压缩指针（§4.1.4）
            if off + 1 >= len(data):
                raise DNSError("truncated pointer")
            ptr = ((n & 0x3F) << 8) | data[off + 1]
            if not jumped:
                end = off + 2
            jumped = True
            hops += 1
            if hops > 64 or ptr >= len(data):
                raise DNSError("pointer loop")
            off = ptr
            continue
        if n & 0xC0:
            raise DNSError("bad label type")
        off += 1
        if n == 0:
            break
        if off + n > len(data):
            raise DNSError("label out of bounds")
        labels.append(data[off : off + n].decode("ascii", errors="replace"))
        off += n
    return ".".join(labels), (end if jumped else off)


def decode_message(data: bytes) -> DNSMessage:
    if len(data) < 12:
        raise DNSError("short message")
    qid, flags, qd, an, ns, ar = struct.unpack_from("!HHHHHH", data)
    msg = DNSMessage(qid, flags)
    off = 12
    for _ in range(qd):
        name, off = _decode_name(data, off)
        if off + 4 > len(data):
            raise DNSError("truncated question")
        qt, qc = struct.unpack_from("!HH", data, off)
        off += 4
        msg.questions.append((name, qt, qc))
    for section, count in ((msg.answers, an), (msg.authority, ns), (msg.additional, ar)):
        for _ in range(count):
            name, off = _decode_name(data, off)
            if off + 10 > len(data):
                raise DNSError("truncated rr")
            rtype, rcls, ttl, rdlen = struct.unpack_from("!HHIH", data, off)
            off += 10
            if off + rdlen > len(data):
                raise DNSError("truncated rdata")
            raw = data[off : off + rdlen]
            rdata: str | bytes = raw
            if rtype == TYPE_A and rdlen == 4:
                rdata = ".".join(str(b) for b in raw)
            elif rtype == TYPE_AAAA and rdlen == 16:
                rdata = ":".join(f"{raw[i] << 8 | raw[i + 1]:x}" for i in range(0, 16, 2))
            elif rtype in (TYPE_CNAME, TYPE_NS):
                rdata, _ = _decode_name(data, off)
            off += rdlen
            section.append(Record(name, rtype, rcls, ttl, rdata))
    return msg


def system_nameservers() -> list[str]:
    env = os.environ.get("GLEANER_DNS_SERVERS")
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]
    p = Path("/etc/resolv.conf")
    servers: list[str] = []
    if p.exists():
        for line in p.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "nameserver":
                servers.append(parts[1])
    return servers or ["223.5.5.5", "8.8.8.8"]


def _hosts_file() -> dict[str, str]:
    path = (
        Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/drivers/etc/hosts"
        if os.name == "nt"
        else Path("/etc/hosts")
    )
    out: dict[str, str] = {}
    try:
        for line in path.read_text(errors="ignore").splitlines():
            line = line.split("#", 1)[0].split()
            if len(line) >= 2 and "." in line[0]:
                for h in line[1:]:
                    out.setdefault(h.lower(), line[0])
    except OSError:
        pass
    return out


class _UDP(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.waiters: dict[int, asyncio.Future[bytes]] = {}

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) >= 2:
            qid = struct.unpack_from("!H", data)[0]
            fut = self.waiters.pop(qid, None)
            if fut and not fut.done():
                fut.set_result(data)

    def error_received(self, exc: Exception) -> None:
        for f in self.waiters.values():
            if not f.done():
                f.set_exception(exc)
        self.waiters.clear()


@dataclass
class ResolverStats:
    queries: int = 0
    cache_hits: int = 0
    timeouts: int = 0
    tcp_fallbacks: int = 0


class Resolver:
    def __init__(
        self,
        servers: list[str] | None = None,
        *,
        port: int = 53,
        timeout: float = 2.0,
        attempts: int = 3,
        use_hosts: bool = True,
    ) -> None:
        self.servers = servers or system_nameservers()
        self.port = port
        self.timeout = timeout
        self.attempts = attempts
        self.hosts = _hosts_file() if use_hosts else {}
        self.cache: dict[tuple[str, int], tuple[float, list[str]]] = {}
        self.stats = ResolverStats()

    async def __call__(self, host: str) -> str:
        """供 HTTPClient 注入：返回一个 IPv4 地址。"""
        addrs = await self.resolve(host, TYPE_A)
        if not addrs:
            raise DNSError(f"no A record for {host}")
        return addrs[0]

    async def resolve(self, name: str, qtype: int = TYPE_A) -> list[str]:
        name = name.lower().rstrip(".")
        if name in self.hosts and qtype == TYPE_A:
            return [self.hosts[name]]
        key = (name, qtype)
        hit = self.cache.get(key)
        if hit and hit[0] > time.monotonic():
            self.stats.cache_hits += 1
            if not hit[1]:
                raise DNSError(f"NXDOMAIN {name} (cached)")
            return hit[1]
        target = name
        for _ in range(8):  # 跟随 CNAME，最多 8 跳
            msg = await self._query(target, qtype)
            if msg.rcode == RCODE_NXDOMAIN:
                ttl = min((r.ttl for r in msg.authority), default=60)
                self.cache[key] = (time.monotonic() + ttl, [])
                raise DNSError(f"NXDOMAIN {name}")
            if msg.rcode:
                raise DNSError(f"rcode {msg.rcode} for {name}")
            addrs = [str(r.data) for r in msg.answers if r.type == qtype]
            if addrs:
                ttl = min(r.ttl for r in msg.answers if r.type == qtype)
                self.cache[key] = (time.monotonic() + max(ttl, 1), addrs)
                return addrs
            cnames = [str(r.data) for r in msg.answers if r.type == TYPE_CNAME]
            if not cnames:
                self.cache[key] = (time.monotonic() + 30, [])
                return []
            target = cnames[0]
        raise DNSError("CNAME chain too long")

    async def _query(self, name: str, qtype: int) -> DNSMessage:
        self.stats.queries += 1
        loop = asyncio.get_running_loop()
        last: Exception | None = None
        for attempt in range(self.attempts):
            server = self.servers[attempt % len(self.servers)]
            qid, packet = encode_query(name, qtype)
            transport, proto = await loop.create_datagram_endpoint(
                _UDP, remote_addr=(server, self.port)
            )
            fut: asyncio.Future[bytes] = loop.create_future()
            proto.waiters[qid] = fut
            try:
                transport.sendto(packet)
                data = await asyncio.wait_for(fut, self.timeout * (2**attempt))
                msg = decode_message(data)
                if msg.id != qid or not msg.is_response:
                    raise DNSError("mismatched response")
                if msg.truncated:
                    self.stats.tcp_fallbacks += 1
                    return await self._query_tcp(server, name, qtype)
                return msg
            except TimeoutError as e:
                self.stats.timeouts += 1
                last = e
            except (OSError, DNSError) as e:
                last = e
            finally:
                transport.close()
        raise DNSError(f"query {name} failed: {last!r}")

    async def _query_tcp(self, server: str, name: str, qtype: int) -> DNSMessage:
        """TCP 报文前加 2 字节长度（§4.2.2）。"""
        _qid, packet = encode_query(name, qtype)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, self.port), self.timeout
        )
        try:
            writer.write(struct.pack("!H", len(packet)) + packet)
            await writer.drain()
            n = struct.unpack("!H", await asyncio.wait_for(reader.readexactly(2), self.timeout))[0]
            return decode_message(await asyncio.wait_for(reader.readexactly(n), self.timeout))
        finally:
            writer.close()
