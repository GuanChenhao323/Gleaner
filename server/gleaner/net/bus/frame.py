"""Gleaner 内部总线帧格式（见 docs/protocols/bus.md）。

    +--------+---------+------+-------+-----+--------+---------+-------+
    | Magic  | Version | Type | Flags | Seq | Length | Payload | CRC32 |
    | 2B     | 1B      | 1B   | 1B    | 4B  | 4B     | N B     | 4B    |
    +--------+---------+------+-------+-----+--------+---------+-------+

全部为网络字节序。CRC32 覆盖从 Magic 到 Payload 末尾的全部字节。
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum, IntFlag
from typing import Any

import msgpack

MAGIC = 0x474C  # "GL"
VERSION = 1
HEADER = struct.Struct("!HBBBII")  # 13 字节
CRC = struct.Struct("!I")
MAX_PAYLOAD = 16 * 1024 * 1024


class FrameType(IntEnum):
    PUBLISH = 1
    ACK = 2
    HEARTBEAT = 3
    NODE_JOIN = 4
    NODE_LEAVE = 5
    SUBSCRIBE = 6
    UNSUBSCRIBE = 7


class Flags(IntFlag):
    NONE = 0
    COMPRESSED = 0x01  # 负载经 zlib 压缩
    NEED_ACK = 0x02  # 接收方需回复 ACK（Seq 相同）


class BusProtocolError(Exception):
    pass


@dataclass
class BusFrame:
    type: FrameType
    seq: int
    payload: Any = None
    flags: Flags = Flags.NONE

    def encode(self, compress_threshold: int = 4096) -> bytes:
        body = msgpack.packb(self.payload, use_bin_type=True) if self.payload is not None else b""
        flags = self.flags & ~Flags.COMPRESSED
        if len(body) >= compress_threshold:
            z = zlib.compress(body, 6)
            if len(z) < len(body):
                body = z
                flags |= Flags.COMPRESSED
        if len(body) > MAX_PAYLOAD:
            raise BusProtocolError("payload too large")
        head = HEADER.pack(
            MAGIC, VERSION, int(self.type), int(flags), self.seq & 0xFFFFFFFF, len(body)
        )
        data = head + body
        return data + CRC.pack(zlib.crc32(data) & 0xFFFFFFFF)


class FrameDecoder:
    """长度前缀定界：先读 13 字节头，再读 Length + 4 字节。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[BusFrame]:
        self._buf += data
        out: list[BusFrame] = []
        while len(self._buf) >= HEADER.size:
            magic, ver, ftype, flags, seq, length = HEADER.unpack_from(self._buf)
            if magic != MAGIC:
                raise BusProtocolError(f"bad magic 0x{magic:04x}")
            if ver != VERSION:
                raise BusProtocolError(f"unsupported version {ver}")
            if length > MAX_PAYLOAD:
                raise BusProtocolError("payload too large")
            total = HEADER.size + length + CRC.size
            if len(self._buf) < total:
                break
            frame_bytes = bytes(self._buf[: total - CRC.size])
            (crc,) = CRC.unpack_from(self._buf, total - CRC.size)
            if zlib.crc32(frame_bytes) & 0xFFFFFFFF != crc:
                raise BusProtocolError("crc mismatch")
            del self._buf[:total]
            body = frame_bytes[HEADER.size :]
            if flags & Flags.COMPRESSED:
                try:
                    body = zlib.decompress(body)
                except zlib.error as e:
                    raise BusProtocolError("bad compressed payload") from e
            try:
                ft = FrameType(ftype)
            except ValueError as e:
                raise BusProtocolError(f"unknown type {ftype}") from e
            try:
                payload = msgpack.unpackb(body, raw=False) if body else None
            except Exception as e:
                raise BusProtocolError("bad msgpack payload") from e
            out.append(BusFrame(ft, seq, payload, Flags(flags)))
        return out
