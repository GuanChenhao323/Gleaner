"""精简版 WebSocket 一致性测试（没有 Docker 时代替 Autobahn Testsuite 做初测）。

用原始 socket 手工构造帧，覆盖 Autobahn 第 1–7 类的代表性用例，对两套服务端实现各跑一遍：
asyncio 版（websocket_route）与手写反应器版（ReactorWSServer）。服务端都是回显。

    python devtools/autobahn_lite.py           # 结果写入 docs/evaluation/results/autobahn_lite.json

判定口径与 Autobahn 一致：回显正确 / 以规定的关闭码关闭 / 及时断开（FAIL FAST）。
正式结果仍以 Autobahn Testsuite（Docker）为准，见 deploy/autobahn。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from gleaner.net.http import HTTPServer, Router, ServerConfig  # noqa: E402
from gleaner.net.websocket import Opcode, websocket_route  # noqa: E402
from gleaner.net.websocket.reactor_server import ReactorWSServer  # noqa: E402

TEXT, BIN, CONT, CLOSE, PING, PONG = 1, 2, 0, 8, 9, 10


def frame(op: int, payload: bytes = b"", *, fin: bool = True, rsv: int = 0, mask: bool = True) -> bytes:
    b0 = (0x80 if fin else 0) | (rsv << 4) | op
    n = len(payload)
    mb = 0x80 if mask else 0
    if n < 126:
        head = struct.pack("!BB", b0, mb | n)
    elif n < 65536:
        head = struct.pack("!BBH", b0, mb | 126, n)
    else:
        head = struct.pack("!BBQ", b0, mb | 127, n)
    if not mask:
        return head + payload
    key = os.urandom(4)
    return head + key + bytes(b ^ key[i % 4] for i, b in enumerate(payload))


class Peer:
    """测试客户端：同步阻塞 socket，便于逐字节控制。"""

    def __init__(self, port: int) -> None:
        self.s = socket.create_connection(("127.0.0.1", port), timeout=3)
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        self.s.sendall(
            f"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self.buf += self.s.recv(4096)
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        assert b" 101 " in head, head

    def send(self, data: bytes, chunk: int = 0) -> None:
        if not chunk:
            self.s.sendall(data)
            return
        for i in range(0, len(data), chunk):  # 分段发送，模拟拆包
            self.s.sendall(data[i : i + chunk])
            time.sleep(0.001)

    def recv_frame(self) -> tuple[int, bytes] | None:
        """返回 (opcode, payload)；连接关闭返回 None。"""
        while True:
            if len(self.buf) >= 2:
                b0, b1 = self.buf[0], self.buf[1]
                n = b1 & 0x7F
                off = 2
                if n == 126:
                    if len(self.buf) < 4:
                        n = -1
                    else:
                        n, off = struct.unpack("!H", self.buf[2:4])[0], 4
                elif n == 127:
                    if len(self.buf) < 10:
                        n = -1
                    else:
                        n, off = struct.unpack("!Q", self.buf[2:10])[0], 10
                if n >= 0 and len(self.buf) >= off + n:
                    p = self.buf[off : off + n]
                    self.buf = self.buf[off + n :]
                    return b0 & 0x0F, p
            try:
                d = self.s.recv(65536)
            except (TimeoutError, OSError):
                return None
            if not d:
                return None
            self.buf += d

    def expect_close(self, codes: tuple[int, ...]) -> tuple[bool, str]:
        f = self.recv_frame()
        while f is not None and f[0] in (PING, PONG):
            f = self.recv_frame()
        if f is None:
            return (not codes or 1006 in codes), "connection dropped"
        if f[0] != CLOSE:
            return False, f"expected close, got opcode {f[0]}"
        code = struct.unpack("!H", f[1][:2])[0] if len(f[1]) >= 2 else 1005
        return code in codes, f"close {code}"

    def close(self) -> None:
        self.s.close()


Case = tuple[str, str, Callable[[Peer], tuple[bool, str]]]


def echo(op: int, payload: bytes, **kw: Any) -> Callable[[Peer], tuple[bool, str]]:
    def run(p: Peer) -> tuple[bool, str]:
        p.send(frame(op, payload), **kw)
        f = p.recv_frame()
        ok = f == (op, payload)
        return ok, "echo ok" if ok else f"got {f and (f[0], len(f[1]))}"

    return run


def violation(data: bytes, codes: tuple[int, ...] = (1002,)) -> Callable[[Peer], tuple[bool, str]]:
    def run(p: Peer) -> tuple[bool, str]:
        p.send(data)
        return p.expect_close(codes)

    return run


def fragmented(parts: list[tuple[int, bytes, bool]], expect: tuple[int, bytes], interleave_ping: bool = False) -> Callable[[Peer], tuple[bool, str]]:
    def run(p: Peer) -> tuple[bool, str]:
        for i, (op, pl, fin) in enumerate(parts):
            p.send(frame(op, pl, fin=fin))
            if interleave_ping and i == 0:
                p.send(frame(PING, b"mid"))
        got = []
        while True:
            f = p.recv_frame()
            if f is None:
                return False, "dropped"
            got.append(f)
            if f[0] in (TEXT, BIN):
                break
        pong_ok = not interleave_ping or (PONG, b"mid") in got
        ok = got[-1] == expect and pong_ok
        return ok, "reassembled" if ok else f"got {[(g[0], len(g[1])) for g in got]}"

    return run


def ping_pong(payload: bytes) -> Callable[[Peer], tuple[bool, str]]:
    def run(p: Peer) -> tuple[bool, str]:
        p.send(frame(PING, payload))
        f = p.recv_frame()
        return f == (PONG, payload), f"got {f and f[0]}"

    return run


def close_echo(code: int, reason: bytes = b"") -> Callable[[Peer], tuple[bool, str]]:
    def run(p: Peer) -> tuple[bool, str]:
        p.send(frame(CLOSE, struct.pack("!H", code) + reason))
        return p.expect_close((code,))

    return run


BAD_UTF8 = b"\xce\xba\xe1\xbd\xb9\xcf\x83\xce\xbc\xce\xb5\xed\xa0\x80edited"  # 含代理项 U+D800（非法）

CASES: list[Case] = [
    ("1.1.1", "空文本消息", echo(TEXT, b"")),
    ("1.1.2", "125 字节文本", echo(TEXT, b"*" * 125)),
    ("1.1.3", "126 字节文本（16 位长度）", echo(TEXT, b"*" * 126)),
    ("1.1.6", "65535 字节文本", echo(TEXT, b"*" * 65535)),
    ("1.1.7", "65536 字节文本（64 位长度）", echo(TEXT, b"*" * 65536)),
    ("1.1.8", "65536 字节、每次 997 字节分段到达", echo(TEXT, b"*" * 65536, chunk=997)),
    ("1.2.3", "126 字节二进制", echo(BIN, bytes(range(126)))),
    ("1.2.8", "1 MiB 二进制", echo(BIN, os.urandom(1 << 20))),
    ("2.1", "空 ping", ping_pong(b"")),
    ("2.3", "125 字节二进制 ping", ping_pong(bytes(range(125)))),
    ("2.5", "126 字节 ping（控制帧过长）", violation(frame(PING, b"x" * 126))),
    ("2.10", "连续 10 个 ping", lambda p: (all(ping_pong(str(i).encode())(p)[0] for i in range(10)), "10 pongs")),
    ("3.1", "RSV1 置位", violation(frame(TEXT, b"hi", rsv=1))),
    ("3.4", "RSV 全置位", violation(frame(TEXT, b"hi", rsv=7))),
    ("3.7", "控制帧 RSV 置位", violation(frame(CLOSE, b"", rsv=4))),
    ("4.1.1", "保留数据 opcode 3", violation(frame(3, b""))),
    ("4.2.1", "保留控制 opcode 11", violation(frame(11, b""))),
    ("5.1", "分片 ping（控制帧不得分片）", violation(frame(PING, b"a", fin=False) + frame(CONT, b"b"))),
    ("5.3", "两片文本", fragmented([(TEXT, b"frag", False), (CONT, b"ment", True)], (TEXT, b"fragment"))),
    ("5.6", "分片之间夹 ping", fragmented([(TEXT, b"frag", False), (CONT, b"ment", True)], (TEXT, b"fragment"), True)),
    ("5.9", "无起始帧的续帧", violation(frame(CONT, b"x"))),
    ("5.18", "两个未结束的文本起始帧", violation(frame(TEXT, b"a", fin=False) + frame(TEXT, b"b"))),
    ("5.20", "100 个 1 字节分片", fragmented([(TEXT, b"a", False)] + [(CONT, b"a", False)] * 98 + [(CONT, b"a", True)], (TEXT, b"a" * 100))),
    ("6.2.1", "合法 UTF-8 多字节", echo(TEXT, "κόσμε 拾课 😀".encode())),
    ("6.3.1", "非法 UTF-8", violation(frame(TEXT, BAD_UTF8), (1007,))),
    ("6.4.1", "分片中途出现非法 UTF-8（快速失败）", violation(frame(TEXT, "κόσμε".encode(), fin=False) + frame(CONT, b"\xf4\x90\x80\x80", fin=False), (1007,))),
    ("6.6.1", "被分片截断的多字节字符（合法）", fragmented([(TEXT, "拾".encode()[:2], False), (CONT, "拾".encode()[2:], True)], (TEXT, "拾".encode()))),
    ("7.1.1", "正常关闭握手", close_echo(1000)),
    ("7.3.1", "空关闭帧", lambda p: (p.send(frame(CLOSE, b"")) or p.expect_close((1000, 1005)))),
    ("7.3.2", "关闭帧负载 1 字节", violation(frame(CLOSE, b"\x03"))),
    ("7.5.1", "关闭原因非法 UTF-8", violation(frame(CLOSE, struct.pack("!H", 1000) + b"\xff\xfe"), (1007,))),
    ("7.7.1", "关闭码 1001", close_echo(1001)),
    ("7.7.10", "关闭码 3000（注册）", close_echo(3000)),
    ("7.7.12", "关闭码 4999（私有）", close_echo(4999)),
    ("7.9.1", "关闭码 0", violation(frame(CLOSE, struct.pack("!H", 0)))),
    ("7.9.5", "关闭码 1005（不得出现在帧里）", violation(frame(CLOSE, struct.pack("!H", 1005)))),
    ("7.9.9", "关闭码 1015", violation(frame(CLOSE, struct.pack("!H", 1015)))),
    ("9.x", "未掩码的客户端帧", violation(frame(TEXT, b"hi", mask=False))),
]


async def start(impl: str) -> tuple[int, Any]:
    if impl == "asyncio":

        async def on_ws(ws: Any, req: Any) -> None:
            async for m in ws:
                await ws.send(m.text if m.opcode == Opcode.TEXT else m.data)

        r = Router()
        r.add("GET", "/ws", websocket_route(on_ws))
        srv = HTTPServer(r, ServerConfig(host="127.0.0.1", port=0))
        await srv.start()
        return srv.port, srv

    async def on_open(peer: Any, req: Any) -> None:
        while (text := await peer.inbox.get()) is not None:
            peer.send_text(text)

    rs = ReactorWSServer("127.0.0.1", 0, on_open=on_open)
    return await rs.start(), rs


async def run_impl(impl: str) -> list[dict[str, Any]]:
    port, srv = await start(impl)
    rows = []
    for cid, desc, fn in CASES:
        if impl == "reactor" and cid.startswith("1.2"):
            # 手写反应器版回显只转发文本（推送节点只用文本帧），二进制回显用例只对 asyncio 版有意义
            rows.append({"实现": impl, "用例": cid, "说明": desc, "结果": "N/A", "详情": "推送节点只用文本帧"})
            continue
        try:
            peer = await asyncio.to_thread(Peer, port)
            ok, detail = await asyncio.to_thread(fn, peer)
            peer.close()
        except Exception as e:  # 用例本身出错也算失败
            ok, detail = False, f"{type(e).__name__}: {e}"
        rows.append({"实现": impl, "用例": cid, "说明": desc, "结果": "OK" if ok else "FAIL", "详情": detail})
    await srv.close()
    return rows


async def main() -> None:
    rows = await run_impl("asyncio") + await run_impl("reactor")
    out = ROOT / "docs" / "evaluation" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "autobahn_lite.json").write_text(json.dumps({"cases": len(CASES), "rows": rows}, ensure_ascii=False, indent=2), "utf-8")
    for impl in ("asyncio", "reactor"):
        rs = [r for r in rows if r["实现"] == impl]
        n_ok = sum(r["结果"] == "OK" for r in rs)
        n_na = sum(r["结果"] == "N/A" for r in rs)
        print(f"{impl}: {n_ok}/{len(rs) - n_na} OK" + (f"（{n_na} 个 N/A）" if n_na else ""))
        for r in rs:
            if r["结果"] == "FAIL":
                print(f"  FAIL {r['用例']} {r['说明']}: {r['详情']}")


if __name__ == "__main__":
    asyncio.run(main())
