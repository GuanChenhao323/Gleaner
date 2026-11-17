"""本地一条命令启动完整开发环境（不需要 Docker）：

    python devtools/dev_all.py            # 然后浏览器打开 http://localhost:8080

包含：fake_moodle（:8090，管理台 /admin）、假邮件服务器（SMTP :2525 / IMAP :1143 / POP3 :1110）、
业务服务 + 总线 Hub、2 个推送节点、网关（托管 client/build/web）、MQTT Broker（:1883，WebSocket :8083）、
采集服务、邮件服务。数据在 ./data/dev.db，删掉即可重置。

可选：--seed 自动注册演示账号 demo@gleaner.test / demo12345 并添加 Moodle、学院通知、教师信息、学校邮箱。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "devtools"))

os.environ.setdefault("GLEANER_MOODLE_URL", "http://localhost:8090")
os.environ.setdefault("GLEANER_COLLEGE_URL", "http://localhost:8090")
os.environ.setdefault("GLEANER_MAIL_HOST", "127.0.0.1")
os.environ.setdefault("GLEANER_IMAP_PORT", "1143")
os.environ.setdefault("GLEANER_POP3_PORT", "1110")
os.environ.setdefault("GLEANER_SMTP_HOST", "127.0.0.1")
os.environ.setdefault("GLEANER_SMTP_PORT", "2525")
os.environ.setdefault("GLEANER_SMTP_INSECURE", "1")
os.environ.setdefault("GLEANER_MIN_INTERVAL", "30")
os.environ.setdefault("GLEANER_MAX_INTERVAL", "300")
os.environ.setdefault("GLEANER_HOST_INTERVAL", "0.1")
os.environ.setdefault("GLEANER_DB", f"sqlite:///{ROOT / 'data' / 'dev.db'}")
os.environ.setdefault("GLEANER_DATA_DIR", str(ROOT / "data"))
os.environ.setdefault("GLEANER_STATIC_DIR", str(ROOT / "client" / "build" / "web"))
# 本地后端只接受本机来源与本机 Host（防 DNS 重绑定，IC-003 §3.1）；flutter run 的端口不固定
os.environ.setdefault("GLEANER_CORS_ORIGINS", "http://localhost:*,http://127.0.0.1:*")
os.environ.setdefault("GLEANER_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
# 本地开发连 127.0.0.1 上的 fake_moodle 与假邮件服务器：允许内网地址（生产环境默认禁止，防 SSRF）
os.environ.setdefault("GLEANER_EGRESS_ALLOW_PRIVATE", "1")
# 平台发信账号（注册验证码、每日摘要邮件）：开发期发到假邮件服务器
os.environ.setdefault("GLEANER_PLATFORM_SMTP_USER", "noreply@gleaner.test")
os.environ.setdefault("GLEANER_PLATFORM_SMTP_PASS", "secret")
os.environ.setdefault("FAKE_MOODLE_SMTP_PORT", "2525")
os.environ.setdefault("FAKE_MOODLE_SMTP_USER", "student@test.local")
os.environ.setdefault("FAKE_MOODLE_SMTP_PASS", "secret")


def latest_code(mail: object, email: str) -> str:
    """从假邮件服务器里取最近一封发给 email 的验证码（开发环境方便注册）。"""
    import re

    from gleaner.net.mail import parse_mail

    for _, rcpts, raw in reversed(mail.sent):  # type: ignore[attr-defined]
        if email in rcpts:
            m = re.search(r"(\d{6})", parse_mail(raw).subject)
            if m:
                return m.group(1)
    return ""


async def seed(gateway: str, mail: object) -> None:
    from gleaner.net.http import HTTPClient

    async with HTTPClient() as c:
        body = {
            "email": "demo@gleaner.test",
            "password": "demo12345",
            "name": "小林",
            "grade": "2024级",
            "major": "计算机",
            "courses": ["网络编程", "操作系统"],
            "agree_privacy": True,
        }
        r = await c.post(f"{gateway}/api/auth/code", json_body={"email": body["email"]})
        if r.status != 409:
            body["code"] = latest_code(mail, body["email"])
        r = await c.post(f"{gateway}/api/auth/register", json_body=body)
        if r.status == 409:
            print("seed: demo account already exists")
            return
        auth = {"Authorization": f"Bearer {r.json()['token']}"}
        sid = (
            await c.post(
                f"{gateway}/api/sources", json_body={"template": "moodle"}, headers=auth
            )
        ).json()["source"]["id"]
        await c.post(
            f"{gateway}/api/sources/{sid}/login",
            json_body={"username": "student", "password": "moodle123"},
            headers=auth,
        )
        for t in ("college_news", "faculty"):
            await c.post(
                f"{gateway}/api/sources", json_body={"template": t}, headers=auth
            )
        mid = (
            await c.post(
                f"{gateway}/api/sources",
                json_body={"template": "school_mail"},
                headers=auth,
            )
        ).json()["source"]["id"]
        await c.post(
            f"{gateway}/api/sources/{mid}/login",
            json_body={"username": "student@test.local", "password": "secret"},
            headers=auth,
        )
        print("seed: demo@gleaner.test / demo12345 ready")


async def main(do_seed: bool) -> None:
    from fake_mail.server import FakeMailServer
    from fake_moodle import app as fm
    from gleaner.__main__ import _dev
    from gleaner.config import Config, setup_logging

    setup_logging()
    (ROOT / "data").mkdir(exist_ok=True)
    srv = fm.serve(8090)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    mail = FakeMailServer(
        {
            "student@test.local": "secret",
            "demo@gleaner.test": "secret",
            "noreply@gleaner.test": "secret",
        }
    )
    await mail.start("127.0.0.1", 2525, 1143, 1110)
    print(
        "fake_moodle http://localhost:8090 (admin /admin) · fake mail smtp 2525 imap 1143 pop3 1110"
    )
    cfg = Config()
    task = asyncio.create_task(_dev(cfg, 2))
    if do_seed:
        await asyncio.sleep(2)
        await seed(f"http://127.0.0.1:{cfg.gateway_port}", mail)
    await task


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true")
    ap.add_argument(
        "--fixture-reading-interval",
        type=int,
        choices=[60],
        help="QA only: loopback reading sources every 60 seconds",
    )
    a = ap.parse_args()
    if a.fixture_reading_interval:
        os.environ["GLEANER_FIXTURE_READING_INTERVAL"] = str(a.fixture_reading_interval)
    try:
        asyncio.run(main(a.seed))
    except KeyboardInterrupt:
        pass
