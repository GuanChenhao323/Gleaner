"""静态文件、条件请求与 Range 请求（RFC 9110 §13、§14）。"""

from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path

from .message import Headers, Request, Response, http_date, parse_http_date

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("application/json", ".json")


def make_etag(
    data: bytes | None = None, *, mtime: float | None = None, size: int | None = None
) -> str:
    if data is not None:
        return '"' + hashlib.sha1(data).hexdigest()[:20] + '"'
    return f'"{int(mtime or 0):x}-{size or 0:x}"'


def _etag_matches(header: str, etag: str, weak: bool = True) -> bool:
    if header.strip() == "*":
        return True
    norm = etag.removeprefix("W/")
    for tag in header.split(","):
        tag = tag.strip()
        if weak:
            tag = tag.removeprefix("W/")
        if tag == norm:
            return True
    return False


def not_modified(req: Request, etag: str | None, last_modified: float | None) -> bool:
    """条件 GET 判定：If-None-Match 优先于 If-Modified-Since（RFC 9110 §13.2.2）。"""
    inm = req.headers.get("If-None-Match")
    if inm is not None and etag:
        return _etag_matches(inm, etag)
    ims = parse_http_date(req.headers.get("If-Modified-Since"))
    if ims is not None and last_modified is not None:
        return int(last_modified) <= int(ims)
    return False


def parse_range(header: str | None, size: int) -> tuple[int, int] | str | None:
    """解析单段 ``bytes=start-end``。返回 (start, end_inclusive)、None（无 Range）或 "invalid"。"""
    if not header:
        return None
    if not header.startswith("bytes=") or "," in header:
        return "invalid"
    spec = header[6:].strip()
    start_s, _, end_s = spec.partition("-")
    try:
        if start_s == "":
            n = int(end_s)  # 后缀范围：最后 n 字节
            if n <= 0:
                return "invalid"
            return max(0, size - n), size - 1
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    except ValueError:
        return "invalid"
    if start >= size or start > end:
        return "invalid"
    return start, min(end, size - 1)


def ranged_response(req: Request, data: bytes, headers: Headers) -> Response:
    """对完整内容应用 Range（返回 206 / 416 / 200），用于断点续传下载。"""
    size = len(data)
    headers["Accept-Ranges"] = "bytes"
    r = parse_range(req.headers.get("Range"), size)
    if_range = req.headers.get("If-Range")
    if r is not None and if_range and if_range != headers.get("ETag"):
        r = None  # If-Range 不匹配时发送完整内容（§13.1.5）
    if r == "invalid":
        headers["Content-Range"] = f"bytes */{size}"
        return Response(416, headers=headers)
    if r is None:
        return Response(200, headers=headers, body=data)
    assert isinstance(r, tuple)
    start, end = r
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return Response(206, headers=headers, body=data[start : end + 1])


class StaticFiles:
    """Flutter Web 构建产物等静态资源。SPA 路由回退到 index.html。"""

    def __init__(
        self, root: str | os.PathLike[str], *, spa_fallback: bool = True, max_age: int = 86400
    ) -> None:
        self.root = Path(root).resolve()
        self.spa_fallback = spa_fallback
        self.max_age = max_age

    async def __call__(self, req: Request) -> Response:
        if req.method not in ("GET", "HEAD"):
            return Response.error(405)
        rel = req.path.lstrip("/") or "index.html"
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root):
            return Response.error(403, "path traversal")
        if path.is_dir():
            path = path / "index.html"
        if not path.is_file():
            if self.spa_fallback and "." not in rel.rsplit("/", 1)[-1]:
                path = self.root / "index.html"
            if not path.is_file():
                return Response.error(404, "not found")
        st = path.stat()
        etag = make_etag(mtime=st.st_mtime_ns / 1e9 * 1000, size=st.st_size)
        h = Headers()
        h["ETag"] = etag
        h["Last-Modified"] = http_date(st.st_mtime)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        h["Content-Type"] = ctype
        # Flutter Web 的文件名都不带内容哈希：index.html、main.dart.js，以及每次构建都会变的 assets/
        # （图标字体按用到的图标裁剪，新增图标后同名文件内容不同）一律协商缓存（ETag → 304），
        # 否则重新构建后浏览器还会用一天前的字体，新图标显示成空白。
        # 只有 canvaskit/ 随 Flutter 引擎版本发布、构建之间不变，可以长缓存。
        long_cache = rel.startswith("canvaskit/")
        h["Cache-Control"] = f"public, max-age={self.max_age}" if long_cache else "no-cache"
        if not_modified(req, etag, st.st_mtime):
            return Response(304, headers=h)
        return ranged_response(req, path.read_bytes(), h)
