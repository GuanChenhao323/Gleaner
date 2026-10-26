"""MUST Moodle 接入前探测（手动运行，不进 pytest / CI）：

    python devtools/must_moodle_probe.py

只读站点级公开信息：robots.txt、移动端公开配置（登录方式、版本、是否开放移动端服务）、
不带账号访问 /login/token.php 时的错误类型（判断 Web Service 是否开启）。不登录、不读任何个人数据。

运行前必须在 docs/integrations/must-moodle.md 里把授权状态改为“已获授权”并填写 Moodle 地址，否则直接退出。
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "integrations" / "must-moodle.md"
INTERVAL = 2.0  # 同一主机请求间隔不少于 2 秒（CLAUDE.md）
UA = "Gleaner-probe/1.0 (course project; contact via MUST Moodle integration doc)"


def registered_site() -> str:
    text = DOC.read_text("utf-8")
    if not re.search(r"^授权状态：已获授权\s*$", text, re.M):
        sys.exit(f"{DOC.relative_to(ROOT)} 的授权状态不是“已获授权”，不访问真实站点。")
    m = re.search(r"^\| Moodle 地址 \| `(https?://[^`]+)` \|", text, re.M)
    if not m:
        sys.exit("授权文档里没有登记 Moodle 地址（格式：| Moodle 地址 | `https://...` |）。")
    return m.group(1).rstrip("/")


class Probe:
    def __init__(self, base: str) -> None:
        self.base = base
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self._last = 0.0

    def _wait(self) -> None:
        delay = self._last + INTERVAL - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def get(self, path: str, **kw: Any) -> requests.Response:
        self._wait()
        return self.s.get(self.base + path, timeout=20, allow_redirects=False, **kw)

    def post(self, path: str, **kw: Any) -> requests.Response:
        self._wait()
        return self.s.post(self.base + path, timeout=20, allow_redirects=False, **kw)


LOGIN_TYPES = {1: "账号密码（App 内登录）", 2: "浏览器 SSO", 3: "内嵌浏览器 SSO"}


def main() -> None:
    base = registered_site()
    p = Probe(base)
    out: dict[str, Any] = {"site": base, "time": time.strftime("%Y-%m-%d %H:%M:%S")}

    r = p.get("/robots.txt")
    out["robots_status"] = r.status_code
    disallow = [
        ln.split(":", 1)[1].strip()
        for ln in r.text.splitlines()
        if ln.lower().startswith("disallow:")
    ]
    out["robots_disallow"] = disallow if r.ok else []

    body = [{"index": 0, "methodname": "tool_mobile_get_public_config", "args": {}}]
    r = p.post("/lib/ajax/service-nologin.php?info=tool_mobile_get_public_config", json=body)
    cfg: dict[str, Any] = {}
    try:
        data = r.json()
        if isinstance(data, list) and data and not data[0].get("error"):
            cfg = data[0]["data"]
    except ValueError:
        pass
    out["public_config_status"] = r.status_code
    if cfg:
        out["release"] = cfg.get("release")
        out["version"] = cfg.get("version")
        out["sitename"] = cfg.get("sitename")
        out["typeoflogin"] = LOGIN_TYPES.get(cfg.get("typeoflogin"), cfg.get("typeoflogin"))
        out["launchurl"] = cfg.get("launchurl")
        out["identityproviders"] = [i.get("name") for i in cfg.get("identityproviders") or []]
        out["enablewebservices"] = cfg.get("enablewebservices")
        out["enablemobilewebservice"] = cfg.get("enablemobilewebservice")
    else:
        out["public_config"] = "不可用（可能未开放移动端服务，或接口被禁用）"

    # 不带账号请求 token：invalidlogin 说明服务开着；enablewsdescription / servicenotavailable 说明没开
    r = p.post(
        "/login/token.php", data={"username": "", "password": "", "service": "moodle_mobile_app"}
    )
    try:
        out["token_endpoint"] = r.json().get("errorcode") or "unexpected"
    except ValueError:
        out["token_endpoint"] = f"HTTP {r.status_code}，非 JSON（可能被重定向到统一认证）"

    r = p.get("/login/index.php")
    out["login_page_status"] = r.status_code
    out["login_page_redirect"] = r.headers.get("Location", "")

    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("\n把以上结果整理进 docs/integrations/must-moodle.md 第 4 节（只含站点级信息）。")


if __name__ == "__main__":
    main()
