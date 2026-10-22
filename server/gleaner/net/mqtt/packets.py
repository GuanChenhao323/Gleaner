"""MQTT 3.1.1 报文编解码（OASIS MQTT v3.1.1 第 2、3 章）。

固定报头（§2.2）：

    byte 1   : 报文类型(4 bit) | 标志(4 bit)
    byte 2.. : 剩余长度，变长编码，每字节低 7 位为数据、最高位为延续标志，最多 4 字节
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum


class PacketType(IntEnum):
    CONNECT = 1
    CONNACK = 2
    PUBLISH = 3
    PUBACK = 4
    PUBREC = 5
    PUBREL = 6
    PUBCOMP = 7
    SUBSCRIBE = 8
    SUBACK = 9
    UNSUBSCRIBE = 10
    UNSUBACK = 11
    PINGREQ = 12
    PINGRESP = 13
    DISCONNECT = 14


class ConnackCode(IntEnum):
    ACCEPTED = 0
    BAD_PROTOCOL = 1
    ID_REJECTED = 2
    UNAVAILABLE = 3
    BAD_CREDENTIALS = 4
    NOT_AUTHORIZED = 5


class MQTTProtocolError(Exception):
    pass


MAX_REMAINING = 268_435_455  # §2.2.3


def encode_remaining_length(n: int) -> bytes:
    if n < 0 or n > MAX_REMAINING:
        raise ValueError("remaining length out of range")
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            return bytes(out)


def decode_remaining_length(buf: bytes | bytearray, offset: int = 1) -> tuple[int, int] | None:
    """返回 (长度, 占用字节数)；数据不足返回 None。"""
    mult = 1
    value = 0
    for i in range(4):
        if offset + i >= len(buf):
            return None
        b = buf[offset + i]
        value += (b & 0x7F) * mult
        if not b & 0x80:
            return value, i + 1
        mult *= 128
    raise MQTTProtocolError("malformed remaining length")


def _str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _bin(b: bytes) -> bytes:
    return struct.pack("!H", len(b)) + b


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def u8(self) -> int:
        if self.pos + 1 > len(self.data):
            raise MQTTProtocolError("truncated")
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self) -> int:
        if self.pos + 2 > len(self.data):
            raise MQTTProtocolError("truncated")
        v = struct.unpack_from("!H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def binary(self) -> bytes:
        n = self.u16()
        if self.pos + n > len(self.data):
            raise MQTTProtocolError("truncated string")
        v = self.data[self.pos : self.pos + n]
        self.pos += n
        return v

    def string(self) -> str:
        raw = self.binary()
        if b"\x00" in raw:
            raise MQTTProtocolError("null character in string")  # §1.5.3
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise MQTTProtocolError("invalid utf-8") from e

    def rest(self) -> bytes:
        v = self.data[self.pos :]
        self.pos = len(self.data)
        return v

    @property
    def remaining(self) -> int:
        return len(self.data) - self.pos


# ---- 报文 -----------------------------------------------------------------------


@dataclass
class Connect:
    client_id: str
    clean_session: bool = True
    keepalive: int = 60
    username: str | None = None
    password: bytes | None = None
    will_topic: str | None = None
    will_message: bytes = b""
    will_qos: int = 0
    will_retain: bool = False
    protocol_level: int = 4

    def encode(self) -> bytes:
        flags = 0x02 if self.clean_session else 0
        payload = _str(self.client_id)
        if self.will_topic is not None:
            flags |= 0x04 | (self.will_qos << 3) | (0x20 if self.will_retain else 0)
            payload += _str(self.will_topic) + _bin(self.will_message)
        if self.username is not None:
            flags |= 0x80
            payload += _str(self.username)
        if self.password is not None:
            flags |= 0x40
            payload += _bin(self.password)
        var = _str("MQTT") + bytes([self.protocol_level, flags]) + struct.pack("!H", self.keepalive)
        return _packet(PacketType.CONNECT, 0, var + payload)


@dataclass
class Connack:
    session_present: bool
    code: int

    def encode(self) -> bytes:
        return _packet(PacketType.CONNACK, 0, bytes([1 if self.session_present else 0, self.code]))


@dataclass
class Publish:
    topic: str
    payload: bytes
    qos: int = 0
    retain: bool = False
    dup: bool = False
    packet_id: int | None = None

    def encode(self) -> bytes:
        flags = (0x08 if self.dup else 0) | (self.qos << 1) | (0x01 if self.retain else 0)
        body = _str(self.topic)
        if self.qos > 0:
            assert self.packet_id is not None
            body += struct.pack("!H", self.packet_id)
        return _packet(PacketType.PUBLISH, flags, body + self.payload)


@dataclass
class PacketId:
    """PUBACK / PUBREC / PUBREL / PUBCOMP / UNSUBACK：只有报文标识符。"""

    type: PacketType
    packet_id: int

    def encode(self) -> bytes:
        flags = 0x02 if self.type == PacketType.PUBREL else 0
        return _packet(self.type, flags, struct.pack("!H", self.packet_id))


@dataclass
class Subscribe:
    packet_id: int
    topics: list[tuple[str, int]] = field(default_factory=list)

    def encode(self) -> bytes:
        body = struct.pack("!H", self.packet_id) + b"".join(
            _str(t) + bytes([q]) for t, q in self.topics
        )
        return _packet(PacketType.SUBSCRIBE, 0x02, body)


@dataclass
class Suback:
    packet_id: int
    codes: list[int]

    def encode(self) -> bytes:
        return _packet(PacketType.SUBACK, 0, struct.pack("!H", self.packet_id) + bytes(self.codes))


@dataclass
class Unsubscribe:
    packet_id: int
    topics: list[str]

    def encode(self) -> bytes:
        return _packet(
            PacketType.UNSUBSCRIBE,
            0x02,
            struct.pack("!H", self.packet_id) + b"".join(_str(t) for t in self.topics),
        )


@dataclass
class Simple:
    """PINGREQ / PINGRESP / DISCONNECT。"""

    type: PacketType

    def encode(self) -> bytes:
        return _packet(self.type, 0, b"")


Packet = Connect | Connack | Publish | PacketId | Subscribe | Suback | Unsubscribe | Simple


def _packet(ptype: int, flags: int, body: bytes) -> bytes:
    return bytes([(ptype << 4) | flags]) + encode_remaining_length(len(body)) + body


# 固定报头中保留标志位必须取的值（§2.2.2 表 2.2）
_REQUIRED_FLAGS = {
    PacketType.CONNECT: 0,
    PacketType.CONNACK: 0,
    PacketType.PUBACK: 0,
    PacketType.PUBREC: 0,
    PacketType.PUBREL: 2,
    PacketType.PUBCOMP: 0,
    PacketType.SUBSCRIBE: 2,
    PacketType.SUBACK: 0,
    PacketType.UNSUBSCRIBE: 2,
    PacketType.UNSUBACK: 0,
    PacketType.PINGREQ: 0,
    PacketType.PINGRESP: 0,
    PacketType.DISCONNECT: 0,
}


def decode_packet(ptype_flags: int, body: bytes) -> Packet:
    try:
        ptype = PacketType(ptype_flags >> 4)
    except ValueError as e:
        raise MQTTProtocolError(f"reserved packet type {ptype_flags >> 4}") from e
    flags = ptype_flags & 0x0F
    if ptype != PacketType.PUBLISH and flags != _REQUIRED_FLAGS[ptype]:
        raise MQTTProtocolError(f"bad flags for {ptype.name}")
    r = _Reader(body)
    if ptype == PacketType.CONNECT:
        name = r.string()
        level = r.u8()
        if name != "MQTT":
            raise MQTTProtocolError("bad protocol name")
        cflags = r.u8()
        if cflags & 0x01:
            raise MQTTProtocolError("reserved connect flag set")  # §3.1.2.3
        keepalive = r.u16()
        client_id = r.string()
        c = Connect(
            client_id=client_id,
            clean_session=bool(cflags & 0x02),
            keepalive=keepalive,
            protocol_level=level,
        )
        if cflags & 0x04:
            c.will_qos = (cflags >> 3) & 0x03
            if c.will_qos == 3:
                raise MQTTProtocolError("will qos 3")
            c.will_retain = bool(cflags & 0x20)
            c.will_topic = r.string()
            c.will_message = r.binary()
        elif cflags & 0x38:
            raise MQTTProtocolError("will flags without will")
        if cflags & 0x80:
            c.username = r.string()
        if cflags & 0x40:
            if not cflags & 0x80:
                raise MQTTProtocolError("password without username")  # §3.1.2.9
            c.password = r.binary()
        return c
    if ptype == PacketType.CONNACK:
        return Connack(bool(r.u8() & 1), r.u8())
    if ptype == PacketType.PUBLISH:
        qos = (flags >> 1) & 0x03
        if qos == 3:
            raise MQTTProtocolError("qos 3")
        topic = r.string()
        if "+" in topic or "#" in topic:
            raise MQTTProtocolError("wildcard in publish topic")  # §3.3.2.1
        pid = r.u16() if qos else None
        if qos and pid == 0:
            raise MQTTProtocolError("packet id 0")
        return Publish(
            topic, r.rest(), qos=qos, retain=bool(flags & 1), dup=bool(flags & 8), packet_id=pid
        )
    if ptype in (
        PacketType.PUBACK,
        PacketType.PUBREC,
        PacketType.PUBREL,
        PacketType.PUBCOMP,
        PacketType.UNSUBACK,
    ):
        return PacketId(ptype, r.u16())
    if ptype == PacketType.SUBSCRIBE:
        pid = r.u16()
        topics: list[tuple[str, int]] = []
        while r.remaining:
            t = r.string()
            q = r.u8()
            if q > 2:
                raise MQTTProtocolError("bad requested qos")
            topics.append((t, q))
        if not topics:
            raise MQTTProtocolError("subscribe without topics")  # §3.8.3
        return Subscribe(pid, topics)
    if ptype == PacketType.SUBACK:
        return Suback(r.u16(), list(r.rest()))
    if ptype == PacketType.UNSUBSCRIBE:
        pid = r.u16()
        ts: list[str] = []
        while r.remaining:
            ts.append(r.string())
        if not ts:
            raise MQTTProtocolError("unsubscribe without topics")
        return Unsubscribe(pid, ts)
    return Simple(ptype)


class PacketReader:
    """增量切分 MQTT 报文，处理粘包与拆包。"""

    def __init__(self, max_packet: int = 1024 * 1024) -> None:
        self._buf = bytearray()
        self.max_packet = max_packet

    def feed(self, data: bytes) -> list[Packet]:
        self._buf += data
        out: list[Packet] = []
        while len(self._buf) >= 2:
            rl = decode_remaining_length(self._buf, 1)
            if rl is None:
                break
            length, nbytes = rl
            if length > self.max_packet:
                raise MQTTProtocolError("packet too large")
            total = 1 + nbytes + length
            if len(self._buf) < total:
                break
            first = self._buf[0]
            body = bytes(self._buf[1 + nbytes : total])
            del self._buf[:total]
            out.append(decode_packet(first, body))
        return out
