"""MQTT 压测与对比实验 4：QoS 0 与 QoS 1 的吞吐，以及丢包环境（配合 tc netem）下的送达率。

    python devtools/loadtest/mqtt_load.py --port 1883 --subs 200 --messages 2000 --qos 1

使用 paho-mqtt 作为对照客户端（devtools 不受自研限制）。Broker 需要 GLEANER_MQTT_ADMIN_PASS
以便压测发布端用 admin 身份发布到任意 gleaner/u/<uid>/ 主题。
"""

from __future__ import annotations

import argparse
import os
import threading
import time

import paho.mqtt.client as paho


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--subs", type=int, default=100)
    ap.add_argument("--messages", type=int, default=1000)
    ap.add_argument("--qos", type=int, default=1)
    ap.add_argument("--admin-pass", default=os.environ.get("GLEANER_MQTT_ADMIN_PASS", "admin-dev"))
    a = ap.parse_args()
    received = 0
    lock = threading.Lock()
    latencies: list[float] = []

    def on_msg(c: paho.Client, u: object, m: paho.MQTTMessage) -> None:
        nonlocal received
        with lock:
            received += 1
            latencies.append(time.time() - float(m.payload.decode().split(":")[1]))

    subs = []
    for i in range(a.subs):
        c = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=f"lt-sub-{i}")
        c.username_pw_set("admin", a.admin_pass)
        c.on_message = on_msg
        c.connect(a.host, a.port, keepalive=60)
        c.subscribe("gleaner/u/load/#", a.qos)
        c.loop_start()
        subs.append(c)
    time.sleep(1)
    pub = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id="lt-pub")
    pub.username_pw_set("admin", a.admin_pass)
    pub.connect(a.host, a.port)
    pub.loop_start()
    t0 = time.time()
    for i in range(a.messages):
        pub.publish("gleaner/u/load/urgent", f"{i}:{time.time()}", qos=a.qos)
    expected = a.messages * a.subs
    while received < expected and time.time() - t0 < 60:
        time.sleep(0.2)
    dt = time.time() - t0
    latencies.sort()
    p99 = latencies[int(len(latencies) * 0.99) - 1] * 1000 if latencies else 0
    print(
        f"qos={a.qos} subs={a.subs} sent={a.messages} delivered={received}/{expected} ({received / expected:.1%}) throughput={received / dt:.0f} msg/s p99={p99:.1f}ms"
    )
    for c in [*subs, pub]:
        c.loop_stop()
        c.disconnect()


if __name__ == "__main__":
    main()
