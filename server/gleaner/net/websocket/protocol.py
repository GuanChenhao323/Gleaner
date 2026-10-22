"""WebSocket（RFC 6455）sans-IO 实现：握手、帧编解码、分片重组、控制帧、关闭握手。

帧格式（§5.2）：

     0                   1                   2                   3
    +-+-+-+-+-------+-+-------------+-------------------------------+
    |F|R|R|R| opcode|M| Payload len |    Extended payload length    |
    |I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
    |N|V|V|V|       |S|             |                               |
    +-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
    |   Masking-key (0 or 4 bytes)  |          Payload Data         |
    +-------------------------------+-------------------------------+
"""

from __future__ import annotations

import base64
import codecs
import hashlib
import os
import struct
from dataclasses import dataclass
from enum import Enum, IntEnum

from ..http.message import Headers, Request, Response

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # §1.3


class Opcode(IntEnum):
    CONT = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


class CloseCode(IntEnum):
    NORMAL = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    UNSUPPORTED = 1003
    NO_STATUS = 1005
    ABNORMAL = 1006
    INVALID_DATA = 1007
    POLICY = 1008
    TOO_BIG = 1009
    INTERNAL = 1011


class State(Enum):
    OPEN = "open"
    CLOSING = "closing"  # 已发送 close，等待对端回应
    CLOSED = "closed"


class WSProtocolError(Exception):
    def __init__(self, message: str, code: int = CloseCode.PROTOCOL_ERROR) -> None:
        super().__init__(message)
        self.code = code


# ---- 握手（§4） ----------------------------------------------------------------


def accept_key(key: str) -> str:
    """Sec-WebSocket-Accept = base64(SHA-1(key + GUID))（§4.2.2 第 5.4 步）。"""
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def validate_handshake(req: Request) -> str:
    """校验客户端握手，返回 Sec-WebSocket-Key。失败抛 ValueError。（§4.2.1）"""
    h = req.headers
    if req.method != "GET":
        raise ValueError("method must be GET")
    if "websocket" not in h.tokens("Upgrade"):
        raise ValueError("missing Upgrade: websocket")
    if "upgrade" not in h.tokens("Connection"):
        raise ValueError("missing Connection: Upgrade")
    if h.get("Sec-WebSocket-Version") != "13":
        raise ValueError("unsupported version")
    key = h.get("Sec-WebSocket-Key", "")
    try:
        if len(base64.b64decode(key, validate=True)) != 16:
            raise ValueError
    except Exception as e:
        raise ValueError("bad Sec-WebSocket-Key") from e
    return key


def handshake_response(req: Request, subprotocol: str | None = None) -> Response:
    try:
        key = validate_handshake(req)
    except ValueError as e:
        resp = Response.error(400, str(e))
        resp.headers["Sec-WebSocket-Version"] = "13"
        return resp
    h = Headers(
        {"Upgrade": "websocket", "Connection": "Upgrade", "Sec-WebSocket-Accept": accept_key(key)}
    )
    if subprotocol:
        h["Sec-WebSocket-Protocol"] = subprotocol
    return Response(101, headers=h)


def client_handshake(
    host: str, path: str, extra: dict[str, str] | None = None
) -> tuple[Request, str]:
    key = base64.b64encode(os.urandom(16)).decode()
    h = Headers(
        {
            "Host": host,
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": key,
            "Sec-WebSocket-Version": "13",
        }
    )
    for k, v in (extra or {}).items():
        h[k] = v
    return Request("GET", path, headers=h), accept_key(key)


# ---- 帧编解码（§5） --------------------------------------------------------------


def mask_bytes(data: bytes, key: bytes) -> bytes:
    """按 §5.3 做 XOR 掩码；用大整数一次异或，比逐字节循环快两个数量级。"""
    if not data:
        return b""
    n = len(data)
    k = (key * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "little") ^ int.from_bytes(k, "little")).to_bytes(n, "little")


def encode_frame(
    opcode: int, payload: bytes, *, fin: bool = True, mask: bool = False, rsv: int = 0
) -> bytes:
    b0 = (0x80 if fin else 0) | (rsv << 4) | opcode
    n = len(payload)
    mbit = 0x80 if mask else 0
    if n < 126:
        head = struct.pack("!BB", b0, mbit | n)
    elif n < 1 << 16:
        head = struct.pack("!BBH", b0, mbit | 126, n)
    else:
        head = struct.pack("!BBQ", b0, mbit | 127, n)
    if mask:
        key = os.urandom(4)
        return head + key + mask_bytes(payload, key)
    return head + payload


@dataclass
class Frame:
    fin: bool
    opcode: int
    payload: bytes
    rsv: int = 0


@dataclass
class Message:
    """完整消息或控制帧事件。"""

    opcode: Opcode
    data: bytes

    @property
    def text(self) -> str:
        return self.data.decode("utf-8")


@dataclass
class Closed:
    code: int
    reason: str


class FrameDecoder:
    """把字节流切成帧，处理三种长度编码与掩码。"""

    def __init__(self, *, expect_mask: bool, max_frame: int) -> None:
        self.expect_mask = expect_mask
        self.max_frame = max_frame
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        self._buf += data
        frames: list[Frame] = []
        while True:
            f = self._one()
            if f is None:
                return frames
            frames.append(f)

    def _one(self) -> Frame | None:
        buf = self._buf
        if len(buf) < 2:
            return None
        b0, b1 = buf[0], buf[1]
        fin = bool(b0 & 0x80)
        rsv = (b0 >> 4) & 0x7
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        n = b1 & 0x7F
        off = 2
        if n == 126:
            if len(buf) < 4:
                return None
            n = struct.unpack_from("!H", buf, 2)[0]
            off = 4
        elif n == 127:
            if len(buf) < 10:
                return None
            n = struct.unpack_from("!Q", buf, 2)[0]
            if n >> 63:
                raise WSProtocolError("64-bit length MSB set")
            off = 10
        # 尽早校验，避免为非法帧缓冲大量数据
        if rsv:
            raise WSProtocolError("RSV bits set without extension")
        if opcode not in (0, 1, 2, 8, 9, 10):
            raise WSProtocolError(f"reserved opcode {opcode}")
        if opcode >= 8 and (not fin or n > 125):
            raise WSProtocolError("control frame fragmented or too long")  # §5.5
        if masked != self.expect_mask:
            raise WSProtocolError("mask bit mismatch")  # §5.1：客户端必须掩码，服务端不得掩码
        if n > self.max_frame:
            raise WSProtocolError("frame too big", CloseCode.TOO_BIG)
        if masked:
            if len(buf) < off + 4 + n:
                return None
            key = bytes(buf[off : off + 4])
            payload = mask_bytes(bytes(buf[off + 4 : off + 4 + n]), key)
            del buf[: off + 4 + n]
        else:
            if len(buf) < off + n:
                return None
            payload = bytes(buf[off : off + n])
            del buf[: off + n]
        return Frame(fin, opcode, payload, rsv)


class WSConnection:
    """一端的 WebSocket 状态机。``receive_data`` 产出 Message / Closed 事件，``send_*`` 返回待发送字节。"""

    def __init__(self, *, is_client: bool = False, max_message: int = 4 * 1024 * 1024) -> None:
        self.is_client = is_client
        self.max_message = max_message
        self.state = State.OPEN
        self._decoder = FrameDecoder(expect_mask=not is_client, max_frame=max_message)
        self._frag_opcode: int | None = None
        self._frag: list[bytes] = []
        self._frag_len = 0
        self._utf8 = codecs.getincrementaldecoder("utf-8")()
        self.close_code: int | None = None
        self.close_reason = ""

    # -- 发送 --------------------------------------------------------------------

    def _frame(self, opcode: int, payload: bytes, fin: bool = True) -> bytes:
        return encode_frame(opcode, payload, fin=fin, mask=self.is_client)

    def send_text(self, text: str) -> bytes:
        return self._frame(Opcode.TEXT, text.encode("utf-8"))

    def send_binary(self, data: bytes) -> bytes:
        return self._frame(Opcode.BINARY, data)

    def send_fragmented(self, opcode: Opcode, data: bytes, size: int) -> bytes:
        """把一条消息拆成多帧：首帧带 opcode，后续为 CONT，末帧 FIN=1（§5.4）。"""
        parts = [data[i : i + size] for i in range(0, len(data), size)] or [b""]
        out = b""
        for i, p in enumerate(parts):
            out += self._frame(opcode if i == 0 else Opcode.CONT, p, fin=i == len(parts) - 1)
        return out

    def send_ping(self, data: bytes = b"") -> bytes:
        return self._frame(Opcode.PING, data[:125])

    def send_pong(self, data: bytes = b"") -> bytes:
        return self._frame(Opcode.PONG, data[:125])

    def send_close(self, code: int = CloseCode.NORMAL, reason: str = "") -> bytes:
        if self.state is not State.OPEN:
            return b""
        self.state = State.CLOSING
        payload = (
            b"" if code == CloseCode.NO_STATUS else struct.pack("!H", code) + reason.encode()[:123]
        )
        return self._frame(Opcode.CLOSE, payload)

    # -- 接收 --------------------------------------------------------------------

    def receive_data(self, data: bytes) -> tuple[list[Message | Closed], bytes]:
        """返回 (事件列表, 需要立即回写的字节)：pong 与 close 回应由状态机自动生成。"""
        events: list[Message | Closed] = []
        reply = b""
        if self.state is State.CLOSED:
            return events, reply
        try:
            frames = self._decoder.feed(data)
            for f in frames:
                ev, out = self._handle(f)
                reply += out
                if ev is not None:
                    events.append(ev)
                if self.state is State.CLOSED:
                    break
        except WSProtocolError as e:
            reply += self.send_close(e.code, str(e)[:100])
            self.state = State.CLOSED
            self.close_code = e.code
            events.append(Closed(e.code, str(e)))
        return events, reply

    def _handle(self, f: Frame) -> tuple[Message | Closed | None, bytes]:
        op = f.opcode
        if op == Opcode.PING:
            return Message(Opcode.PING, f.payload), self.send_pong(f.payload)
        if op == Opcode.PONG:
            return Message(Opcode.PONG, f.payload), b""
        if op == Opcode.CLOSE:
            return self._on_close(f.payload)
        # 数据帧与分片（§5.4）
        if op == Opcode.CONT:
            if self._frag_opcode is None:
                raise WSProtocolError("continuation without start")
        else:
            if self._frag_opcode is not None:
                raise WSProtocolError("new data frame during fragmented message")
            self._frag_opcode = op
            self._frag, self._frag_len = [], 0
            self._utf8.reset()
        self._frag_len += len(f.payload)
        if self._frag_len > self.max_message:
            raise WSProtocolError("message too big", CloseCode.TOO_BIG)
        self._frag.append(f.payload)
        if self._frag_opcode == Opcode.TEXT:
            # 增量校验 UTF-8，使非法文本尽早失败（§8.1）
            try:
                self._utf8.decode(f.payload, final=f.fin)
            except UnicodeDecodeError as e:
                raise WSProtocolError("invalid utf-8", CloseCode.INVALID_DATA) from e
        if not f.fin:
            return None, b""
        msg = Message(Opcode(self._frag_opcode), b"".join(self._frag))
        self._frag_opcode = None
        self._frag = []
        return msg, b""

    def _on_close(self, payload: bytes) -> tuple[Closed, bytes]:
        """关闭握手（§5.5.1、§7.4）：校验状态码，回应 close 后进入 CLOSED。"""
        if len(payload) == 1:
            raise WSProtocolError("close payload of length 1")
        code = CloseCode.NO_STATUS
        reason = ""
        if len(payload) >= 2:
            code = struct.unpack("!H", payload[:2])[0]
            if not (
                code in (1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011)
                or 3000 <= code <= 4999
            ):
                raise WSProtocolError(f"invalid close code {code}")
            try:
                reason = payload[2:].decode("utf-8")
            except UnicodeDecodeError as e:
                raise WSProtocolError(
                    "invalid utf-8 in close reason", CloseCode.INVALID_DATA
                ) from e
        reply = b""
        if self.state is State.OPEN:
            reply = self.send_close(code if code != CloseCode.NO_STATUS else CloseCode.NORMAL)
        self.state = State.CLOSED
        self.close_code = int(code)
        self.close_reason = reason
        return Closed(int(code), reason), reply
