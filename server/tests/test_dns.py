import asyncio
import struct

import pytest

from gleaner.net.dns import (
    TYPE_A,
    TYPE_CNAME,
    DNSError,
    Resolver,
    decode_message,
    encode_name,
    encode_query,
)


def build_response(query: bytes, answers, rcode=0, tc=False):
    qid = struct.unpack_from("!H", query)[0]
    qsection = query[12:]
    flags = 0x8180 | rcode | (0x0200 if tc else 0)
    out = struct.pack("!HHHHHH", qid, flags, 1, len(answers), 0, 0) + qsection
    for rtype, ttl, rdata in answers:
        # 名字用压缩指针指向问题段（偏移 12）
        if rtype == TYPE_A:
            rd = bytes(int(x) for x in rdata.split("."))
        else:
            rd = encode_name(rdata)
        out += b"\xc0\x0c" + struct.pack("!HHIH", rtype, 1, ttl, len(rd)) + rd
    return out


class FakeDNS(asyncio.DatagramProtocol):
    def __init__(self, table, drop_first=0):
        self.table = table
        self.drop = drop_first
        self.count = 0

    def connection_made(self, transport):
        self.t = transport

    def datagram_received(self, data, addr):
        self.count += 1
        if self.drop > 0:
            self.drop -= 1
            return
        msg = decode_message(data)
        name = msg.questions[0][0]
        entry = self.table.get(name)
        if entry is None:
            self.t.sendto(build_response(data, [], rcode=3), addr)
        else:
            self.t.sendto(build_response(data, entry), addr)


async def start_fake(table, drop_first=0):
    loop = asyncio.get_running_loop()
    t, p = await loop.create_datagram_endpoint(
        lambda: FakeDNS(table, drop_first), local_addr=("127.0.0.1", 0)
    )
    return t, p, t.get_extra_info("sockname")[1]


def test_encode_decode_query():
    _qid, q = encode_query("moodle.example.edu", TYPE_A, qid=0x1234)
    m = decode_message(q)
    assert m.id == 0x1234 and m.questions == [("moodle.example.edu", 1, 1)] and m.flags & 0x0100


def test_decode_compression_and_malformed():
    _, q = encode_query("a.b.c")
    r = build_response(q, [(TYPE_CNAME, 60, "x.y"), (TYPE_A, 30, "1.2.3.4")])
    m = decode_message(r)
    assert (
        m.answers[0].data == "x.y"
        and m.answers[1].data == "1.2.3.4"
        and m.answers[1].name == "a.b.c"
    )
    with pytest.raises(DNSError):
        decode_message(b"\x00" * 5)
    loop = bytearray(r)
    loop[12:14] = b"\xc0\x0c"  # 指针指向自己 → 循环
    with pytest.raises(DNSError):
        decode_message(bytes(loop))
    with pytest.raises(DNSError):
        decode_message(r[:-3])


async def test_resolve_cache_cname_nxdomain_retry():
    table = {
        "moodle.test": [(TYPE_CNAME, 60, "real.test")],
        "real.test": [(TYPE_A, 300, "10.0.0.5")],
    }
    t, p, port = await start_fake(table, drop_first=1)
    r = Resolver(["127.0.0.1"], port=port, timeout=0.2, use_hosts=False)
    assert await r.resolve("moodle.test") == ["10.0.0.5"]
    assert r.stats.timeouts == 1  # 第一次丢包后重试成功
    before = p.count
    assert await r("moodle.test") == "10.0.0.5"
    assert p.count == before and r.stats.cache_hits == 1
    with pytest.raises(DNSError, match="NXDOMAIN"):
        await r.resolve("nope.test")
    with pytest.raises(DNSError, match="cached"):
        await r.resolve("nope.test")
    t.close()


async def test_all_servers_timeout():
    t, _p, port = await start_fake({}, drop_first=100)
    r = Resolver(["127.0.0.1"], port=port, timeout=0.05, attempts=2, use_hosts=False)
    with pytest.raises(DNSError):
        await r.resolve("x.test")
    assert r.stats.timeouts == 2
    t.close()
