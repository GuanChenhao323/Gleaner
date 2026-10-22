# MQTT 3.1.1 Broker 子集

实现：`server/gleaner/net/mqtt/`（报文编解码、主题匹配）、`server/gleaner/broker/broker.py`（Broker）、
`server/gleaner/broker/ws_transport.py`（MQTT over WebSocket）。
测试：`server/tests/test_mqtt.py`（与 paho-mqtt 互通：发布订阅、保留消息、ACL、持久会话离线队列、QoS1 DUP 重发、Keep Alive、会话接管、遗嘱、WebSocket 传输）。

## 1. 报文

固定报头：`类型(4) | 标志(4)` + 剩余长度（变长编码，每字节 7 位，最多 4 字节，上限 268 435 455，§2.2.3）。

支持：CONNECT/CONNACK、PUBLISH、PUBACK、（为兼容回应 PUBREC/PUBCOMP）、SUBSCRIBE/SUBACK、UNSUBSCRIBE/UNSUBACK、PINGREQ/PINGRESP、DISCONNECT。

畸形输入一律断开：保留报文类型、固定报头保留标志位错误（§2.2.2）、CONNECT 保留位（§3.1.2.3）、
有口令无用户名（§3.1.2.9）、PUBLISH 主题含通配符（§3.3.2.1）、QoS 3、报文 ID 为 0、SUBSCRIBE 无主题、
字符串含 U+0000、非法 UTF-8、第二个 CONNECT。

## 2. 主题（§4.7）

- `#` 必须单独占最后一层，且匹配父层本身（`sport/#` 匹配 `sport`）。
- `+` 必须占满一层，可匹配空层（`a/+/b` 匹配 `a//b`）。
- 以通配符开头的过滤器不匹配 `$` 开头的主题；客户端不能发布 `$` 主题。
- 订阅树按层组织（同 mosquitto），一次查找 O(层数)；同一客户端多条重叠订阅取最大 QoS（§3.3.5）。

## 3. 会话

| 场景 | 行为 |
| --- | --- |
| Clean Session = 1 | 断开即丢弃会话 |
| Clean Session = 0 | 保留订阅、未确认的 QoS 1 消息与离线队列；CONNACK `session present = 1`；重连后以 DUP=1 重发未确认消息，再发离线队列（§4.4） |
| 同 ClientId 再次连接 | 断开旧连接（会话接管，§3.1.4） |
| 空 ClientId | Clean=1 时自动分配；Clean=0 时 CONNACK 2 |
| 持久化 | 持久会话与保留消息每 30 s 及关闭时写入 `data/mqtt-state.json`，重启后恢复 |
| 过期 | 离线超过 7 天的持久会话被清理 |

## 4. QoS

- QoS 0：最多一次，直接写出。
- QoS 1：分配报文 ID 记入 inflight（每会话最多 20 条，其余排队，队列上限 1000，满了丢最旧的）；
  未收到 PUBACK 按 `retry_interval × 2^(attempts-1)` 退避重发，DUP=1。
- 订阅请求 QoS 2 时降级授予 QoS 1。

## 5. 保留消息

每个主题保留一条；空负载 + RETAIN 表示删除；新订阅立即收到匹配的保留消息（RETAIN=1，QoS 取两者较小）；
正常转发时 RETAIN 置 0。每日摘要使用保留消息 `gleaner/u/{uid}/digest`。

## 6. Keep Alive

超过约定值 1.5 倍没有收到任何报文即断开（§3.1.2.10）；Keep Alive = 0 不检查。CONNECT 必须在连接后 10 s 内到达。
异常断开时发布遗嘱消息；正常 DISCONNECT 丢弃遗嘱（§3.14.4）。

## 7. 鉴权与主题访问控制

- 用户名 = 用户 ID，口令 = `HMAC(secret, "mqtt:{uid}:{token_version}")` 的前 18 字节，客户端登录后从 `/api/me` 取得；
  退出全部设备（token_version 递增）后旧口令失效。
- 内部服务以 `admin` + `GLEANER_MQTT_ADMIN_PASS` 登录。
- ACL：普通用户只能订阅 `gleaner/u/{自己的 uid}/` 下的主题，不能发布；越权订阅在 SUBACK 中返回 0x80。

| 主题 | QoS | 内容 |
| --- | --- | --- |
| `gleaner/u/{uid}/urgent` | 1 | 紧急通知、重要变更、截止提醒 |
| `gleaner/u/{uid}/normal` | 0 | 普通通知（预留） |
| `gleaner/u/{uid}/digest` | 1，保留 | 最新一期每日摘要 |
| `gleaner/u/{uid}/status` | 1 | 来源需要重新登录 |

## 8. 传输

TCP 1883；TLS 8883（`GLEANER_MQTT_TLS_PORT`）；WebSocket `ws://<网关>/mqtt`（子协议 `mqtt`，浏览器版 Flutter 使用）。
WebSocket 适配层把二进制消息喂给 `StreamReader`，粘包拆包仍由 `PacketReader` 处理。

互通测试：`mosquitto_sub -h localhost -u <uid> -P <口令> -t 'gleaner/u/<uid>/#' -q 1 -i phone -c`。
