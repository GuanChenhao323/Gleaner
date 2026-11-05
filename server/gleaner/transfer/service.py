"""跨设备扫码传输（P2）。

流程：电脑 ``POST /api/transfer`` 生成配对码与二维码 → 手机扫码 ``POST /api/transfer/{code}/join``
→ 任一端 ``POST .../files`` 声明文件（大小 + SHA-256）→ ``PUT .../files/{id}`` 按 Content-Range
分块上传，断线后 ``GET .../files/{id}`` 取已接收字节数继续 → 另一端 ``GET .../content`` 用 Range 断点下载。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from ..core.validate import as_int, as_str, body_of, guard
from ..net.http import Headers, Request, Response, Router, parse_range
from ..storage.db import Database, is_unique_violation

CHUNK_MAX = 4 * 1024 * 1024
FILE_MAX = 512 * 1024 * 1024
FILES_PER_TRANSFER = 50
TRANSFER_MAX = 2 * 1024 * 1024 * 1024
PAIR_TTL = 30 * 60
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉易混淆的 0/O/1/I
_CR = re.compile(r"bytes (\d+)-(\d+)/(\d+)")

UserOf = Callable[[Request], Awaitable[dict[str, Any] | None]]
Notify = Callable[[int, dict[str, Any]], Awaitable[None]]


class TransferService:
    def __init__(self, db: Database, data_dir: str, user_of: UserOf, notify: Notify) -> None:
        self.db = db
        self.root = Path(data_dir) / "transfers"
        self.root.mkdir(parents=True, exist_ok=True)
        self.user_of = user_of
        self.notify = notify

    def register(self, r: Router) -> None:
        for method, path, handler in (
            ("POST", "/api/transfer", self.create),
            ("POST", "/api/transfer/{code}/join", self.join),
            ("GET", "/api/transfer/{code}", self.status),
            ("POST", "/api/transfer/{code}/files", self.declare),
            ("GET", "/api/transfer/{code}/files/{fid}", self.file_status),
            ("PUT", "/api/transfer/{code}/files/{fid}", self.upload_chunk),
            ("GET", "/api/transfer/{code}/files/{fid}/content", self.download),
        ):
            r.add(method, path, guard(handler))

    async def _session(self, req: Request) -> dict[str, Any] | Response:
        code = req.params["code"].upper()
        t = await self.db.fetchone("SELECT * FROM transfers WHERE pair_code = ?", code)
        if not t or t["expires_at"] < time.time():
            return Response.error(404, "配对码不存在或已过期", "transfer_expired")
        user = await self.user_of(req)
        tok = req.headers.get("X-Transfer-Token") or req.query.get("t")
        if not (
            (user and user["id"] == t["user_id"])
            or (tok and secrets.compare_digest(tok, t["token"]))
        ):
            return Response.error(403, "无权访问该传输会话", "forbidden")
        return t

    async def create(self, req: Request) -> Response:
        user = await self.user_of(req)
        if not user:
            return Response.error(401, "请先登录", "unauthorized")
        token = secrets.token_urlsafe(24)
        now = time.time()
        for attempt in range(5):  # 配对码有唯一约束：撞上旧码就换一个
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
            try:
                tid = await self.db.insert(
                    "transfers",
                    {
                        "user_id": user["id"],
                        "pair_code": code,
                        "token": token,
                        "status": "waiting",
                        "created_at": now,
                        "expires_at": now + PAIR_TTL,
                    },
                )
                break
            except Exception as e:
                if not is_unique_violation(e) or attempt == 4:
                    raise
        return Response.json_body(
            {
                "id": tid,
                "code": code,
                "token": token,
                "expires_at": now + PAIR_TTL,
                "join_path": f"/#/transfer/{code}",
            },
            201,
        )

    async def join(self, req: Request) -> Response:
        code = req.params["code"].upper()
        t = await self.db.fetchone("SELECT * FROM transfers WHERE pair_code = ?", code)
        if not t or t["expires_at"] < time.time():
            return Response.error(404, "配对码不存在或已过期", "transfer_expired")
        # 配对码只能用一次：看到二维码的第二个人不能再用它换到访问令牌
        took = await self.db.execute(
            "UPDATE transfers SET status = 'paired' WHERE id = ? AND status = 'waiting'", t["id"]
        )
        if not took:
            return Response.error(409, "该配对码已被使用，请在电脑上重新生成", "already_paired")
        device = as_str(body_of(req).get("device"), "device", max_len=200, default="手机")[:40]
        await self.notify(
            t["user_id"], {"type": "transfer", "code": code, "status": "paired", "device": device}
        )
        return Response.json_body({"code": code, "token": t["token"], "status": "paired"})

    async def status(self, req: Request) -> Response:
        t = await self._session(req)
        if isinstance(t, Response):
            return t
        files = await self.db.fetch(
            "SELECT id, name, size, sha256, received, direction, status, created_at FROM transfer_files WHERE transfer_id = ? ORDER BY id",
            t["id"],
        )
        return Response.json_body(
            {
                "code": t["pair_code"],
                "status": t["status"],
                "expires_at": t["expires_at"],
                "files": files,
            }
        )

    async def declare(self, req: Request) -> Response:
        t = await self._session(req)
        if isinstance(t, Response):
            return t
        body = body_of(req)
        size = as_int(body.get("size"), "size", lo=0, hi=FILE_MAX)
        sha = as_str(body.get("sha256"), "sha256", max_len=64).lower()
        name = os.path.basename(as_str(body.get("name"), "name", max_len=1000))[:200] or "file"
        direction = as_str(body.get("direction"), "direction", max_len=10, default="up")
        if not re.fullmatch(r"[0-9a-f]{64}", sha) or direction not in ("up", "down"):
            return Response.error(422, "校验和或方向格式错误", "invalid")
        agg = await self.db.fetchone(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS total FROM transfer_files WHERE transfer_id = ?",
            t["id"],
        )
        if agg and (agg["n"] >= FILES_PER_TRANSFER or agg["total"] + size > TRANSFER_MAX):
            return Response.error(
                413, f"一次传输最多 {FILES_PER_TRANSFER} 个文件、共 2 GB", "too_large"
            )
        d = self.root / str(t["id"])
        d.mkdir(parents=True, exist_ok=True)
        fid = await self.db.insert(
            "transfer_files",
            {
                "transfer_id": t["id"],
                "name": name,
                "size": size,
                "sha256": sha,
                "received": 0,
                "direction": direction,
                "status": "uploading" if size else "done",
                "path": "",
                "created_at": time.time(),
            },
        )
        path = d / f"{fid}.part"
        path.write_bytes(b"")
        await self.db.execute("UPDATE transfer_files SET path = ? WHERE id = ?", str(path), fid)
        await self.notify(
            t["user_id"],
            {
                "type": "transfer",
                "code": t["pair_code"],
                "status": "file",
                "file_id": fid,
                "name": name,
                "size": size,
            },
        )
        return Response.json_body({"id": fid, "received": 0, "chunk_max": CHUNK_MAX}, 201)

    async def _file(self, t: dict[str, Any], fid: str) -> dict[str, Any] | None:
        if not fid.isdigit() or len(fid) > 18:
            return None
        return await self.db.fetchone(
            "SELECT * FROM transfer_files WHERE id = ? AND transfer_id = ?", int(fid), t["id"]
        )

    async def file_status(self, req: Request) -> Response:
        t = await self._session(req)
        if isinstance(t, Response):
            return t
        f = await self._file(t, req.params["fid"])
        if not f:
            return Response.error(404, "文件不存在", "not_found")
        return Response.json_body(
            {k: f[k] for k in ("id", "name", "size", "sha256", "received", "status")}
        )

    async def upload_chunk(self, req: Request) -> Response:
        """``Content-Range: bytes start-end/total``。只接受从已接收位置继续的块，重复块幂等忽略。"""
        t = await self._session(req)
        if isinstance(t, Response):
            return t
        f = await self._file(t, req.params["fid"])
        if not f:
            return Response.error(404, "文件不存在", "not_found")
        m = _CR.fullmatch(req.headers.get("Content-Range", ""))
        if not m:
            return Response.error(400, "缺少 Content-Range", "bad_range")
        start, end, total = (int(x) for x in m.groups())
        if (
            total != f["size"]
            or end < start
            or end - start + 1 != len(req.body)
            or len(req.body) > CHUNK_MAX
        ):
            return Response.error(400, "Content-Range 与数据不一致", "bad_range")
        received = int(f["received"])
        if end < received:
            return Response.json_body({"received": received, "status": f["status"]})  # 重传的旧块
        if start != received:
            return _offset_mismatch(received)
        # 按偏移写入并截断到 end+1（而不是追加）：即使上次写文件后、更新数据库前崩溃，
        # 文件里多出的半块也会被覆盖，续传不会错位
        await asyncio.to_thread(_write_at, f["path"], start, req.body)
        # 比较并交换：两个并发的同偏移请求只有一个能把 received 往前推
        moved = await self.db.execute(
            "UPDATE transfer_files SET received = ? WHERE id = ? AND received = ?",
            end + 1,
            f["id"],
            received,
        )
        if not moved:
            cur = await self.db.fetchval(
                "SELECT received FROM transfer_files WHERE id = ?", f["id"]
            )
            return _offset_mismatch(int(cur or 0))
        received = end + 1
        status = "uploading"
        if received == f["size"]:
            digest = await asyncio.to_thread(_sha256, f["path"])
            status = "done" if digest == f["sha256"] else "corrupt"
            final = Path(f["path"]).with_suffix("")
            os.replace(f["path"], final)
            await self.db.execute(
                "UPDATE transfer_files SET path = ? WHERE id = ?", str(final), f["id"]
            )
            await self.notify(
                t["user_id"],
                {
                    "type": "transfer",
                    "code": t["pair_code"],
                    "status": status,
                    "file_id": f["id"],
                    "name": f["name"],
                },
            )
        await self.db.execute(
            "UPDATE transfer_files SET received = ?, status = ? WHERE id = ?",
            received,
            status,
            f["id"],
        )
        return Response.json_body({"received": received, "status": status})

    async def download(self, req: Request) -> Response:
        t = await self._session(req)
        if isinstance(t, Response):
            return t
        f = await self._file(t, req.params["fid"])
        if not f or f["status"] != "done":
            return Response.error(404, "文件尚未传完", "not_ready")
        h = Headers(
            {
                "Content-Type": "application/octet-stream",
                "ETag": f'"{f["sha256"][:32]}"',
                "Content-Disposition": f"attachment; filename*=UTF-8''{_quote(f['name'])}",
                "X-Content-SHA256": f["sha256"],
            }
        )
        return file_response(req, f["path"], h)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for block in iter(lambda: fp.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _quote(s: str) -> str:
    from urllib.parse import quote

    return quote(s)


def _offset_mismatch(received: int) -> Response:
    resp = Response.json_body(
        {
            "error": "offset_mismatch",
            "message": "上传位置不一致，请从 received 继续",
            "received": received,
        },
        409,
    )
    resp.headers["Range"] = f"bytes=0-{received - 1}" if received else "bytes=0-0"
    return resp


def _write_at(path: str, offset: int, data: bytes) -> None:
    with open(path, "r+b") as fp:
        fp.seek(offset)
        fp.write(data)
        fp.truncate(offset + len(data))


def _read_at(path: str, offset: int, n: int) -> bytes:
    with open(path, "rb") as fp:
        fp.seek(offset)
        return fp.read(n)


def file_response(req: Request, path: str, headers: Headers) -> Response:
    """从磁盘按 Range 流式发送（不把整个文件读进内存；最大 512 MB）。"""
    size = os.path.getsize(path)
    headers["Accept-Ranges"] = "bytes"
    r = parse_range(req.headers.get("Range"), size)
    if_range = req.headers.get("If-Range")
    if r is not None and if_range and if_range != headers.get("ETag"):
        r = None  # If-Range 不匹配时发送完整内容（RFC 9110 §13.1.5）
    if r == "invalid":
        headers["Content-Range"] = f"bytes */{size}"
        return Response(416, headers=headers)
    if size == 0:
        return Response(200, headers=headers)
    if r is None:
        start, end, status = 0, size - 1, 200
    else:
        assert isinstance(r, tuple)
        start, end = r
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    async def body() -> AsyncIterator[bytes]:
        pos = start
        while pos <= end:
            chunk = await asyncio.to_thread(_read_at, path, pos, min(256 * 1024, end - pos + 1))
            if not chunk:
                return
            pos += len(chunk)
            yield chunk

    return Response(status, headers=headers, stream=body())
