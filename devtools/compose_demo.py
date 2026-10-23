"""对已启动的 compose 环境跑一遍演示路径（在 Docker 所在的机器上运行）：

    docker compose -f deploy/docker-compose.yml --profile dev up -d --build
    python devtools/compose_demo.py

步骤：注册（验证码经 GreenMail 收取）→ Moodle 模板登录 → WebSocket 与 MQTT 订阅 → 老师把截止提前 2 天
→ 两路同时收到“截止提前” → 停掉该用户所在的推送节点 → 重连到另一节点并补发 → 学校邮箱来源 → Prometheus / Grafana。
用现成库（requests、websockets、paho-mqtt、imaplib）做对照客户端。结果写入 docs/evaluation/results/compose_demo.json。
"""

from __future__ import annotations

import asyncio
import imaplib
import json
import os
import platform
import re
import subprocess
import time
import uuid
from collections.abc import Callable
from email import message_from_bytes
from email.header import decode_header, make_header
from pathlib import Path
from typing import Any

import paho.mqtt.client as paho
import requests
import websockets

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy" / "docker-compose.yml"), "--profile", "dev"]
HOST = os.environ.get("DEMO_HOST", "localhost")
GW = f"http://{HOST}:8080"
MOODLE = f"http://{HOST}:8090"

s = requests.Session()
s.trust_env = False  # 不走系统代理
steps: list[dict[str, Any]] = []


def step(name: str, ok: bool, detail: str = "", t0: float | None = None) -> None:
    row = {"步骤": name, "结果": "通过" if ok else "失败", "说明": detail}
    if t0 is not None:
        row["耗时 s"] = round(time.time() - t0, 2)
    steps.append(row)
    print(("  ok  " if ok else "  FAIL") + f" {name}  {detail}", flush=True)
    if not ok:
        raise SystemExit(1)


def until(fn: Callable[[], Any], timeout: float, interval: float = 0.5) -> Any:
    end = time.time() + timeout
    while time.time() < end:
        try:
            r = fn()
        except (requests.RequestException, OSError, imaplib.IMAP4.error):
            r = None
        if r:
            return r
        time.sleep(interval)
    return None


def mail_code(email: str) -> str:
    """GreenMail 收到发往未知地址的邮件时自动建账号，用户名和密码都是邮箱地址。"""
    m = imaplib.IMAP4(HOST, 3143)
    try:
        m.login(email, email)
        m.select("INBOX")
        _, data = m.search(None, "ALL")
        for num in reversed(data[0].split()):
            _, msg = m.fetch(num, "(RFC822)")
            subject = str(make_header(decode_header(message_from_bytes(msg[0][1])["Subject"])))
            if found := re.search(r"(\d{6})", subject):
                return found.group(1)
    finally:
        m.logout()
    return ""


async def recv_until(ws: Any, pred: Callable[[dict[str, Any]], bool], timeout: float) -> dict[str, Any]:
    async with asyncio.timeout(timeout):
        while True:
            m = json.loads(await ws.recv())
            if pred(m):
                return m


async def ws_hello(token: str, last_seq: int) -> tuple[Any, list[dict[str, Any]]]:
    ws = await websockets.connect(f"ws://{HOST}:8080/ws?token={token}", proxy=None, open_timeout=10)
    await ws.send(json.dumps({"type": "hello", "token": token, "last_seq": last_seq}))
    got = [await recv_until(ws, lambda m: m["type"] in ("welcome", "change"), 10)]
    while got[-1]["type"] != "welcome":
        got.append(await recv_until(ws, lambda m: m["type"] in ("welcome", "change"), 10))
    return ws, got


async def main() -> None:
    t0 = time.time()
    ok = until(lambda: s.get(f"{GW}/health", timeout=3).ok, 60)
    step("网关健康检查", bool(ok), GW, t0)
    # fake_moodle 恢复初始数据，否则多次运行会把同一作业的截止时间一路提前到过去
    s.post(f"{MOODLE}/admin/api/reset", json={}, timeout=5)

    # 1) 注册：验证码经平台发信账号（compose 中指向 GreenMail）发出
    email = f"demo-{uuid.uuid4().hex[:6]}@gleaner.test"
    t0 = time.time()
    r = s.post(f"{GW}/api/auth/code", json={"email": email}, timeout=10)
    code = until(lambda: mail_code(email), 30, 1.0)
    step("注册验证码邮件", r.ok and bool(code), f"{email} 收到 {code}", t0)
    body = {"email": email, "password": "demo12345", "name": "小林", "grade": "2024级", "major": "计算机", "code": code}
    r = s.post(f"{GW}/api/auth/register", json=body, timeout=10)
    step("注册", r.status_code == 201, f"HTTP {r.status_code}")
    token = r.json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    me = s.get(f"{GW}/api/me", headers=auth, timeout=10).json()

    # 2) Moodle 模板一键添加并登录一次，等采集出 7 个作业
    t0 = time.time()
    sid = s.post(f"{GW}/api/sources", json={"template": "moodle"}, headers=auth, timeout=10).json()["source"]["id"]
    r = s.post(f"{GW}/api/sources/{sid}/login", json={"username": "student", "password": "moodle123"}, headers=auth, timeout=30)
    feed = until(
        lambda: (f := s.get(f"{GW}/api/feed?kind=assignment", headers=auth, timeout=10).json()) and len(f["items"]) >= 7 and f,
        60,
    )
    step("Moodle 登录与采集", r.ok and bool(feed), f"作业 {len(feed['items']) if feed else 0} 个", t0)
    lab1 = next(i for i in feed["items"] if i["title"].startswith("实验一"))

    # 3) WebSocket（经网关到推送节点）与 MQTT（Broker）同时订阅
    ws, got = await ws_hello(token, 0)
    welcome = got[-1]
    step("WebSocket 经网关接入推送节点", True, f"节点 {welcome['node']}，补发 {welcome['replayed']} 条")
    mq_msgs: list[str] = []
    mq = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=f"demo-{me['id']}", clean_session=False)
    mq.username_pw_set(me["mqtt"]["username"], me["mqtt"]["password"])
    mq.on_connect = lambda cl, u, f, rc, p=None: cl.subscribe(f"gleaner/u/{me['id']}/#", 1)
    mq.on_message = lambda cl, u, m: mq_msgs.append(m.topic)
    mq.connect(HOST, 1883)
    mq.loop_start()
    time.sleep(1)

    # 4) 老师把截止时间提前 2 天 → 同一事项更新，WebSocket 与 MQTT 同时收到
    t0 = time.time()
    s.post(f"{MOODLE}/admin/api/assignments/1001", json={"shift_days": -2}, timeout=5)
    s.post(f"{GW}/api/sources/{sid}/refresh", headers=auth, timeout=10)
    ch = await recv_until(ws, lambda m: m["type"] == "change" and m["item_id"] == lab1["id"], 30)
    step("WebSocket 收到“截止提前”", ch["important"] and "截止提前" in ch["note"], ch["note"], t0)
    urgent = until(lambda: any(t.endswith("/urgent") for t in mq_msgs), 15)
    step("MQTT 收到紧急推送", bool(urgent), ", ".join(sorted(set(mq_msgs))))

    # 5) 停掉该用户所在的推送节点 → 重连到另一节点，补发宕机期间的变化
    node = welcome["node"]
    svc = node.replace("-", "")  # push-1 → compose 服务名 push1
    t0 = time.time()
    subprocess.run([*COMPOSE, "stop", svc], check=True, capture_output=True)
    try:
        await recv_until(ws, lambda m: False, 10)
    except websockets.ConnectionClosed:
        pass
    s.post(f"{MOODLE}/admin/api/assignments/1101", json={"requirements": "改为纸质版提交"}, timeout=5)
    s.post(f"{GW}/api/sources/{sid}/refresh", headers=auth, timeout=10)

    def changed_offline() -> bool:
        # 等这次变化落库（出现第 2 个版本）后再重连，才能验证“宕机期间的消息被补发”
        for i in feed["items"]:
            if i["id"] != lab1["id"]:
                v = s.get(f"{GW}/api/items/{i['id']}/versions", headers=auth, timeout=5).json()
                if len(v["versions"]) >= 2:
                    return True
        return False

    stored = until(changed_offline, 60, 1.0)
    step("宕机期间的变化已入库", bool(stored), "", t0)
    res = None
    for _ in range(30):
        try:
            res = await ws_hello(token, ch["seq"])
            break
        except (OSError, TimeoutError, websockets.WebSocketException):
            await asyncio.sleep(0.5)
    assert res is not None
    ws2, got2 = res
    welcome2 = got2[-1]
    replayed = welcome2["replayed"] + sum(m["type"] == "change" for m in got2)
    step(
        "推送节点故障转移与补发",
        welcome2["node"] != node and replayed >= 1,
        f"{node} 停止后接入 {welcome2['node']}，补发 {replayed} 条",
        t0,
    )
    subprocess.run([*COMPOSE, "start", svc], check=True, capture_output=True)
    await ws.close()
    await ws2.close()
    mq.loop_stop()
    mq.disconnect()

    # 6) 学校邮箱来源（IMAP 连 GreenMail）
    t0 = time.time()
    mid = s.post(f"{GW}/api/sources", json={"template": "school_mail"}, headers=auth, timeout=10).json()["source"]["id"]
    r = s.post(f"{GW}/api/sources/{mid}/login", json={"username": "student@test.local", "password": "secret"}, headers=auth, timeout=30)
    step("学校邮箱来源登录（IMAP）", r.ok and r.json().get("ok", False), f"HTTP {r.status_code}", t0)

    # 7) 监控
    # 刚重启的推送节点要等下一个抓取周期才变回 up
    def targets() -> list[dict[str, Any]]:
        return s.get(f"http://{HOST}:9090/api/v1/targets", timeout=5).json()["data"]["activeTargets"]

    up = until(lambda: all(t["health"] == "up" for t in targets()), 40, 2)
    detail = " ".join(f"{t['labels'].get('instance')}:{t['health']}" for t in targets())
    step("Prometheus 抓取目标全部 up", bool(up), detail)
    g = s.get(f"http://{HOST}:3000/api/health", timeout=5)
    step("Grafana", g.ok, g.json().get("database", ""))

    out = ROOT / "docs" / "evaluation" / "results" / "compose_demo.json"
    env = {"platform": platform.platform(), "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    out.write_text(json.dumps({"env": env, "rows": steps}, ensure_ascii=False, indent=2), "utf-8")
    print(f"全部通过，结果写入 {out.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
