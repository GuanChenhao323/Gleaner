"""增量式 HTTP/1.1 解析器（sans-IO）。

只消费字节、产出完整消息，不做任何 I/O，因此 TCP 粘包、拆包对它没有区别：
调用方每收到一段数据就 ``feed()``，解析器内部缓冲直到凑齐一条消息。

状态机（RFC 9112）：

    HEAD ──(Content-Length)──> BODY_LENGTH ──> HEAD
      │ ──(chunked)──> CHUNK_SIZE ⇄ CHUNK_DATA ──(size=0)──> TRAILERS ──> HEAD
      │ ──(仅响应：无长度)──> BODY_EOF ──(连接关闭)──> DONE
"""

from __future__ import annotations

import re
from collections import deque
from enum import Enum, auto

from .message import Headers, Request, Response

# RFC 9110 §5.6.2 token
_TOKEN = re.compile(rb"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_VERSION = re.compile(rb"^HTTP/1\.[01]$")


class ParseError(Exception):
    """畸形报文。``status`` 是服务端应返回的状态码。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class _State(Enum):
    HEAD = auto()
    BODY_LENGTH = auto()
    CHUNK_SIZE = auto()
    CHUNK_DATA = auto()
    CHUNK_CRLF = auto()
    TRAILERS = auto()
    BODY_EOF = auto()
    DONE = auto()


class HTTPParser:
    """解析请求（``kind="request"``）或响应（``kind="response"``）。"""

    def __init__(
        self,
        kind: str = "request",
        *,
        max_header_bytes: int = 64 * 1024,
        max_headers: int = 100,
        max_body_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        assert kind in ("request", "response")
        self.kind = kind
        self.max_header_bytes = max_header_bytes
        self.max_headers = max_headers
        self.max_body_bytes = max_body_bytes
        self._buf = bytearray()
        self._state = _State.HEAD
        self._msg: Request | Response | None = None
        self._body = bytearray()
        self._remaining = 0
        # 响应解析需要知道对应请求的方法（HEAD 的响应没有正文，RFC 9110 §9.3.2）
        self._pending_methods: deque[str] = deque()

    # -- 公共接口 ----------------------------------------------------------------

    def expect_response(self, method: str) -> None:
        self._pending_methods.append(method.upper())

    @property
    def buffered(self) -> int:
        return len(self._buf)

    @property
    def idle(self) -> bool:
        """当前没有半条消息在解析中。"""
        return self._state is _State.HEAD and not self._buf

    def take_buffer(self) -> bytes:
        """取走尚未解析的剩余字节（协议升级后交给 WebSocket 使用）。"""
        data = bytes(self._buf)
        self._buf.clear()
        return data

    def feed(self, data: bytes) -> list[Request | Response]:
        if self._state is _State.DONE:
            if data:
                raise ParseError("data after connection close")
            return []
        self._buf += data
        out: list[Request | Response] = []
        while True:
            msg = self._step()
            if msg is None:
                break
            out.append(msg)
            # 升级后的字节不属于 HTTP，交给调用方
            if isinstance(msg, Request) and msg.headers.get("Upgrade"):
                break
            if isinstance(msg, Response) and msg.status == 101:
                break
        return out

    def feed_eof(self) -> list[Request | Response]:
        """对端关闭连接。读到关闭为止的响应体在此结束（RFC 9112 §6.3 第 8 条）。"""
        if self._state is _State.BODY_EOF and self._msg is not None:
            msg = self._finish()
            self._state = _State.DONE
            return [msg]
        if self._state is not _State.HEAD or self._buf:
            raise ParseError("connection closed mid-message")
        return []

    # -- 状态机 ------------------------------------------------------------------

    def _step(self) -> Request | Response | None:
        st = self._state
        if st is _State.HEAD:
            return self._parse_head()
        if st is _State.BODY_LENGTH:
            take = min(self._remaining, len(self._buf))
            self._body += self._buf[:take]
            del self._buf[:take]
            self._remaining -= take
            return self._finish() if self._remaining == 0 else None
        if st is _State.CHUNK_SIZE:
            idx = self._buf.find(b"\r\n")
            if idx < 0:
                if len(self._buf) > 1024:
                    raise ParseError("chunk size line too long")
                return None
            line = bytes(self._buf[:idx]).split(b";", 1)[0].strip()  # 忽略 chunk-ext（§7.1.1）
            del self._buf[: idx + 2]
            try:
                size = int(line, 16)
            except ValueError as e:
                raise ParseError("bad chunk size") from e
            if size < 0:
                raise ParseError("bad chunk size")
            if size == 0:
                self._state = _State.TRAILERS
            else:
                self._check_body(len(self._body) + size)
                self._remaining = size
                self._state = _State.CHUNK_DATA
            return self._step()
        if st is _State.CHUNK_DATA:
            take = min(self._remaining, len(self._buf))
            self._body += self._buf[:take]
            del self._buf[:take]
            self._remaining -= take
            if self._remaining:
                return None
            self._state = _State.CHUNK_CRLF
            return self._step()
        if st is _State.CHUNK_CRLF:
            if len(self._buf) < 2:
                return None
            if self._buf[:2] != b"\r\n":
                raise ParseError("missing CRLF after chunk")
            del self._buf[:2]
            self._state = _State.CHUNK_SIZE
            return self._step()
        if st is _State.TRAILERS:
            # trailer-section 以空行结束（§7.1.2），这里解析后丢弃
            idx = self._buf.find(b"\r\n")
            if idx < 0:
                return None
            del self._buf[: idx + 2]
            if idx == 0:
                return self._finish()
            return self._step()
        if st is _State.BODY_EOF:
            self._check_body(len(self._body) + len(self._buf))
            self._body += self._buf
            self._buf.clear()
            return None
        return None

    def _parse_head(self) -> Request | Response | None:
        # 容忍消息之间多余的空行（RFC 9112 §2.2）
        while self._buf.startswith(b"\r\n"):
            del self._buf[:2]
        end = self._buf.find(b"\r\n\r\n")
        if end < 0:
            if len(self._buf) > self.max_header_bytes:
                raise ParseError("header section too large", 431)
            return None
        if end > self.max_header_bytes:
            raise ParseError("header section too large", 431)
        head = bytes(self._buf[:end])
        del self._buf[: end + 4]
        lines = head.split(b"\r\n")
        if len(lines) - 1 > self.max_headers:
            raise ParseError("too many header fields", 431)
        headers = self._parse_fields(lines[1:])
        msg: Request | Response
        if self.kind == "request":
            parts = lines[0].split(b" ")
            if len(parts) != 3 or not _TOKEN.match(parts[0]) or not parts[1]:
                raise ParseError("bad request line")
            if not _VERSION.match(parts[2]):
                raise ParseError("unsupported HTTP version", 505)
            msg = Request(
                method=parts[0].decode("ascii"),
                target=parts[1].decode("latin-1"),
                version=parts[2].decode("ascii"),
                headers=headers,
            )
            if msg.version == "HTTP/1.1" and "Host" not in headers:
                raise ParseError("missing Host header")  # RFC 9112 §3.2
        else:
            parts = lines[0].split(b" ", 2)
            if len(parts) < 2 or not _VERSION.match(parts[0]) or not parts[1].isdigit():
                raise ParseError("bad status line")
            msg = Response(
                status=int(parts[1]),
                version=parts[0].decode("ascii"),
                reason=parts[2].decode("latin-1") if len(parts) > 2 else "",
                headers=headers,
            )
        self._msg = msg
        self._body = bytearray()
        return self._select_body(msg)

    def _parse_fields(self, lines: list[bytes]) -> Headers:
        headers = Headers()
        for raw in lines:
            if not raw:
                continue
            if raw[:1] in (b" ", b"\t"):
                raise ParseError("obsolete line folding")  # RFC 9112 §5.2
            if b":" not in raw:
                raise ParseError("bad header line")
            name, value = raw.split(b":", 1)
            if not _TOKEN.match(name):
                raise ParseError("bad header name")  # 名字与冒号之间不允许空白（§5.1）
            headers.add(name.decode("ascii"), value.strip(b" \t").decode("latin-1"))
        return headers

    def _select_body(self, msg: Request | Response) -> Request | Response | None:
        """按 RFC 9112 §6.3 决定消息体长度。"""
        h = msg.headers
        if isinstance(msg, Response):
            method = self._pending_methods.popleft() if self._pending_methods else "GET"
            if method == "HEAD" or msg.status in (204, 304) or 100 <= msg.status < 200:
                return self._finish()
            if method == "CONNECT" and 200 <= msg.status < 300:
                return self._finish()
        te = h.get_all("Transfer-Encoding")
        cl = h.get_all("Content-Length")
        if te:
            if cl:
                # 同时出现视为走私攻击风险，直接拒绝（§6.3 第 3 条）
                raise ParseError("both Transfer-Encoding and Content-Length")
            codings = [t.strip().lower() for v in te for t in v.split(",")]
            if codings[-1] != "chunked":
                if isinstance(msg, Request):
                    raise ParseError("unsupported transfer coding", 501)
                self._state = _State.BODY_EOF
                return None
            self._state = _State.CHUNK_SIZE
            return self._step()
        if cl:
            values = {v.strip() for line in cl for v in line.split(",")}
            if len(values) != 1 or not next(iter(values)).isdigit():
                raise ParseError("bad Content-Length")
            n = int(values.pop())
            self._check_body(n)
            if n == 0:
                return self._finish()
            self._remaining = n
            self._state = _State.BODY_LENGTH
            return self._step()
        if isinstance(msg, Request):
            return self._finish()
        self._state = _State.BODY_EOF
        return self._step()

    def _check_body(self, n: int) -> None:
        if n > self.max_body_bytes:
            raise ParseError("body too large", 413)

    def _finish(self) -> Request | Response:
        assert self._msg is not None
        msg = self._msg
        msg.body = bytes(self._body)
        self._msg = None
        self._body = bytearray()
        self._state = _State.HEAD
        return msg
