"""跨设备扫码传输（P2）。

流程：电脑 ``POST /api/transfer`` 生成配对码与二维码 → 手机扫码 ``POST /api/transfer/{code}/join``
→ 任一端 ``POST .../files`` 声明文件（大小 + SHA-256）→ ``PUT .../files/{id}`` 按 Content-Range
分块上传，断线后 ``GET .../files/{id}`` 取已接收字节数继续 → 另一端 ``GET .../content`` 用 Range 断点下载。
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..net.http import Headers, Request, Response, Router, ranged_response
from ..storage.db import Database

CHUNK_MAX = 4 * 1024 * 1024
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
        r.add("POST", "/api/transfer", self.create)
        r.add("POST", "/api/transfer/{code}/join", self.join)
        r.add("GET", "/api/transfer/{code}", self.status)
        r.add("POST", "/api/transfer/{code}/files", self.declare)
        r.add("GET", "/api/transfer/{code}/files/{fid}", self.file_status)
        r.add("PUT", "/api/transfer/{code}/files/{fid}", self.upload_chunk)
        r.add("GET", "/api/transfer/{code}/files/{fid}/content", self.download)

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
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        token = secrets.token_urlsafe(24)
        now = time.time()
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
        await self.db.execute("UPDATE transfers SET status = 'paired' WHERE id = ?", t["id"])
        device = (req.json() or {}).get("device", "手机")
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
        body = req.json() or {}
        try:
            size = int(body["size"])
            sha = str(body["sha256"]).lower()
            name = os.path.basename(str(body["name"]))[:200] or "file"
        except (KeyError, ValueError, TypeError):
            return Response.error(400, "需要 name、size、sha256", "bad_request")
        if size < 0 or size > 512 * 1024 * 1024 or not re.fullmatch(r"[0-9a-f]{64}", sha):
            return Response.error(400, "文件过大或校验和格式错误", "bad_request")
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
                "direction": body.get("direction", "up"),
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
        return await self.db.fetchone(
            "SELECT * FROM transfer_files WHERE id = ? AND transfer_id = ?", int(fid), t["id"]
        )

    async def file_status(self, req: Request) -> Response:
        t = await self._session(req)
        if isinstance(t, Response):
            return t
        f = await self._file(t, req.params["fid"])
        if not f:
            return Response.error(404, "文件不存在")
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
            return Response.error(404, "文件不存在")
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
            resp = Response.json_body({"received": received, "error": "offset_mismatch"}, 409)
            resp.headers["Range"] = f"bytes=0-{received - 1}" if received else "bytes=0-0"
            return resp
        with open(f["path"], "ab") as fp:
            fp.write(req.body)
        received = end + 1
        status = "uploading"
        if received == f["size"]:
            status = "done" if _sha256(f["path"]) == f["sha256"] else "corrupt"
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
            return Response.error(404, "文件尚未传完")
        data = Path(f["path"]).read_bytes()
        h = Headers(
            {
                "Content-Type": "application/octet-stream",
                "ETag": f'"{f["sha256"][:32]}"',
                "Content-Disposition": f"attachment; filename*=UTF-8''{_quote(f['name'])}",
                "X-Content-SHA256": f["sha256"],
            }
        )
        return ranged_response(req, data, h)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for block in iter(lambda: fp.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _quote(s: str) -> str:
    from urllib.parse import quote

    return quote(s)
