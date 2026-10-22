# 内部二进制总线协议（Gleaner Bus）

实现：`server/gleaner/net/bus/frame.py`（编解码）、`server/gleaner/net/bus/node.py`（Hub 与节点）。
测试：`server/tests/test_bus.py`（往返、粘包拆包随机分段、CRC 篡改、截断、去重、心跳超时、断线补发）。

## 1. 帧格式

全部字段为网络字节序（大端）。

| 偏移 | 字段 | 长度 | 说明 |
| --- | --- | --- | --- |
| 0 | Magic | 2 | 固定 `0x474C`（"GL"），不匹配立即断开 |
| 2 | Version | 1 | 当前为 1 |
| 3 | Type | 1 | 见下表 |
| 4 | Flags | 1 | bit0 `COMPRESSED`：负载经 zlib 压缩；bit1 `NEED_ACK`：接收方需回 ACK |
| 5 | Seq | 4 | 发送方序号（逐跳），用于确认与去重 |
| 9 | Length | 4 | Payload 字节数，上限 16 MiB |
| 13 | Payload | N | MessagePack 编码的消息体（可能已压缩） |
| 13+N | CRC32 | 4 | 覆盖 Magic 到 Payload 末尾 |

负载 ≥ 4 KiB 且压缩后更小时自动压缩。

| Type | 值 | Payload |
| --- | --- | --- |
| PUBLISH | 1 | `{"topic": str, "data": any, "from"?: str, "to"?: str}` |
| ACK | 2 | 无；Seq 等于被确认帧的 Seq |
| HEARTBEAT | 3 | 无或 `{"t": 时间戳}` |
| NODE_JOIN | 4 | 节点 → Hub：`{"node", "role", "meta", "topics", "epoch_seen"}`；Hub → 节点：`{"node", "epoch"}` |
| NODE_LEAVE | 5 | `{"node"}` |
| SUBSCRIBE | 6 | `{"topics": [pattern, ...]}` |
| UNSUBSCRIBE | 7 | `{"topics": [pattern, ...]}` |

主题模式：`a.b` 精确匹配；`a.*` 前缀匹配（同时匹配 `a`）；`*` 匹配全部。

## 2. 定界与校验

解码器维护接收缓冲：凑够 13 字节头 → 校验 Magic、Version、Length 上限 → 凑够 `13 + Length + 4` → 校验 CRC32 →
解压 → MessagePack 解码。任何一步失败抛出 `BusProtocolError`，连接立即断开，由客户端退避重连。
因为长度前缀定界，TCP 的粘包与拆包对解码器透明（测试中以 1–300 字节随机分段喂入 50 帧验证）。

## 3. 拓扑与主题

星型：业务服务（core）内嵌 Hub，其他进程作为节点接入。

| 主题 | 发布者 → 订阅者 | 内容 |
| --- | --- | --- |
| `extract.result` | 采集 / 邮件 → core | 一个来源的检查结果与事项快照 |
| `u.<uid>` | core → 推送节点 | 该用户的投递（推送节点只订阅在线用户） |
| `mqtt.publish` | core → Broker | `{"topic", "payload", "qos", "retain"}` |
| `client.state` | 推送节点 → core | 客户端经 WebSocket 发来的个人状态操作 |
| `collector.fetch` | core → 采集节点 | 立即检查某来源（由哈希环上的负责节点执行） |
| `mail.sources` | core → 邮件节点 | 邮箱来源有变化，重新对账长连接 |
| `$nodes` | Hub → 所有节点 | 存活成员 `{"push": [...], "collector": [...], ...}` |

## 4. 可靠性：逐跳至少一次 + 去重

```
发送方                                 接收方
  PUBLISH(seq=n, NEED_ACK)  ───────▶   回 ACK(seq=n)
  记入 outbox                          (节点, n) 已见过？→ 丢弃（duplicates+1）
  ack_timeout 内无 ACK → 重发（退避）      否则处理
  收到 ACK → 从 outbox 移除
```

- 去重键：`(发送节点, Seq)`，LRU 保存最近 5 万个。
- 断线重连后，双方重发 outbox 中未确认的帧。
- Hub 为刚下线的节点保留 outbox `retention`（默认 60 s）：节点在此期间重连即补发，超时清理。
- Hub 每次启动生成随机 `epoch`；节点在 NODE_JOIN 中带上上次见到的 epoch，不一致说明 Hub 重启过，
  双方清空去重表（序号重新开始）。

## 5. 心跳与故障检测

- 节点每 5 s 发 HEARTBEAT；Hub 收到后回 HEARTBEAT。
- 任一方 15 s 没收到任何帧即判定对端下线：Hub 标记成员死亡并广播 `$nodes`；节点断开并指数退避重连（0.2 s → 10 s，带抖动）。
- 采集节点收到 `$nodes` 后重建一致性哈希环，来源自动重新分配（`collector/engine.py: Scheduler.set_nodes`）。

## 6. 状态机（节点侧）

```
DISCONNECTED ──connect ok──▶ JOINING ──收到 NODE_JOIN(epoch)──▶ CONNECTED
     ▲                                                    │
     └──── EOF / CRC 错误 / 15 s 无数据 / 写失败 ◀──────────┘   （退避后重连，重发 outbox）
```
