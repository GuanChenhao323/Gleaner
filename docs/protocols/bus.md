# 内部二进制总线协议（Gleaner Bus）

实现：`server/gleaner/net/bus/frame.py`（编解码）、`server/gleaner/net/bus/node.py`（Hub 与节点）。
测试：`server/tests/test_bus.py`（往返、粘包拆包随机分段、CRC 篡改、截断、解压炸弹、去重、心跳超时、断线补发、
慢处理器、成员重建、HMAC 认证与防重放、超大负载、发件箱上限、重连不恢复已取消的订阅）。

## 1. 帧格式

全部字段为网络字节序（大端）。

| 偏移 | 字段 | 长度 | 说明 |
| --- | --- | --- | --- |
| 0 | Magic | 2 | 固定 `0x474C`（"GL"），不匹配立即断开 |
| 2 | Version | 1 | 当前为 1 |
| 3 | Type | 1 | 见下表 |
| 4 | Flags | 1 | bit0 `COMPRESSED`：负载经 zlib 压缩；bit1 `NEED_ACK`：接收方需回 ACK |
| 5 | Seq | 4 | 发送方序号（逐跳），用于确认与去重 |
| 9 | Length | 4 | Payload 字节数，上限 16 MiB（解压后同样不超过 16 MiB） |
| 13 | Payload | N | MessagePack 编码的消息体（可能已压缩） |
| 13+N | CRC32 | 4 | 覆盖 Magic 到 Payload 末尾 |

负载 ≥ 4 KiB 且压缩后更小时自动压缩。

| Type | 值 | Payload |
| --- | --- | --- |
| PUBLISH | 1 | `{"topic": str, "data": any, "from"?: str, "to"?: str}` |
| ACK | 2 | 无；Seq 等于被确认帧的 Seq |
| HEARTBEAT | 3 | 无或 `{"t": 时间戳}` |
| NODE_JOIN | 4 | 节点 → Hub：`{"node", "role", "meta", "topics", "epoch", "epoch_seen", "ts", "nonce", "mac"}`；Hub → 节点（欢迎帧）：`{"node", "epoch", "session", "mac"}` |
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
  编码（超过 16 MiB 直接报错）            回 ACK(seq=n)
  PUBLISH(seq=n, NEED_ACK)  ───────▶   (节点, n) 已见过？→ 丢弃（duplicates+1）
  记入 outbox                          否则处理
  ack_timeout 内无 ACK → 重发（退避，最多 8 倍）
  收到 ACK → 从 outbox 移除
```

- 去重键：`(发送节点, Seq)`，LRU 保存最近 5 万个。
- 帧先编码再进发件箱，重发时直接用编码好的字节。编码失败（超过 16 MiB、无法序列化）：
  客户端 `publish` 抛 `BusProtocolError`；Hub 只跳过这一个目标并计 `encode_errors`。心跳与维护任务都不会因此退出。
- 断线重连后，双方重发 outbox 中未确认的帧。例外：节点未确认的 SUBSCRIBE / UNSUBSCRIBE 不重发，
  因为 NODE_JOIN 已带上当前完整的订阅；否则一个已经取消的订阅会被旧的 SUBSCRIBE 加回来。
- Hub 为刚下线的节点保留成员记录与 outbox `retention`（默认 60 s），节点在此期间重连即补发。
  超时后删除成员记录，但该节点还有未处理完的消息时不删。
- **三种“序号重新开始”的情况**，都靠随机标识识别：
  | 情况 | 标识 | 处理 |
  | --- | --- | --- |
  | Hub 重启 | Hub 的 `epoch`（欢迎帧） | 节点清空去重表；节点在 NODE_JOIN 里带上 `epoch_seen`，Hub 发现不是自己的 epoch 就清空给它的 outbox |
  | 节点进程重启（同名） | 节点的 `epoch`（NODE_JOIN） | Hub 清空该成员的去重表。compose 实测：不清的话，重启后的推送节点 SUBSCRIBE 会被吞掉，用户收不到推送 |
  | Hub 删除成员记录后又重建 | 成员的 `session`（欢迎帧） | 节点清空去重表：新成员记录给它的序号从 1 开始 |
  同一进程断线重连时这些标识都不变，去重表保留，重发的帧仍按重复丢弃。
- **端到端确认（采集结果）**：逐跳 ACK 只说明 Hub 收到了，不说明已入库。所以来源的内容哈希 `sources.content_hash`
  由 core 在 `Pipeline.ingest` 全部写入成功后才写；采集端只记“已发出的哈希” `stats.published_hash`。
  两者不一致，说明上次结果没有入库（core 宕机、入库异常），下次检查就不用 HTTP 条件请求缓存、也不按哈希跳过，重新发出完整结果。
  入库按身份键幂等，重发不会产生重复事项。

## 5. 处理与背压

- **Hub 的读循环不执行处理器**：只做解码、ACK、去重与判活。PUBLISH 进入该节点自己的队列（上限 1000），
  由该节点的工作协程按顺序路由与处理（入库、调用大模型可能要几秒）。同一节点的消息保持顺序，节点之间互不阻塞。
  队列满时读循环等待，即暂停读这个连接，由 TCP 把背压传回发送方。这段时间不判该节点超时：是 Hub 自己忙，不是对端失联。
- **客户端**：发件箱上限 1 万帧，满了 `publish` 等待 ACK 腾出空间，采集、邮件节点随之放慢。
  写缓冲区超过 4 MiB 时，`publish` 等待 `drain`。
- **Hub**：写缓冲区超过 4 MiB 时不再写入可靠帧，帧留在发件箱，由维护任务稍后重发（这时可能乱序，靠 Seq 去重，
  业务上推送有 `deliveries.seq`）。每个成员的发件箱上限 2 万帧，满了丢最旧的帧并计 `dropped`：
  推送消息有投递记录兜底，客户端重连后会按 last_seq 补齐。
- core 的“立即检查”在没有在线采集节点（也没有本地采集代理）时返回 202 `{"checking": false, "message": …}`。
  来源已排队，采集节点恢复后最先检查。不用 503，因为网关把上游 503 计为被动健康检查失败，会误把 core 摘除。

## 6. 节点认证（NODE_JOIN）

- 密钥：`GLEANER_BUS_SECRET`；未设置时由 `GLEANER_SECRET` 派生（`security.bus_secret()`）。所有服务共享。
- 节点 → Hub：`mac = HMAC-SHA256(密钥, "join|node|role|epoch|ts|nonce")`。Hub 检查以下三项，任何一项不通过就计 `auth_failures` 并断开：
  - 时间差不超过 120 s；
  - nonce 长度 8–64，且 240 s 内没用过（防重放）；
  - mac 用常数时间比较。
- Hub → 节点：欢迎帧带 `mac = HMAC-SHA256(密钥, "welcome|hub|epoch|session|节点的 nonce")`。节点验证通过才进入 CONNECTED，
  以防连上冒充的 Hub。
- 密钥为空时不认证，只用于单元测试里直接写原始帧。服务进程（`services.py`）一律带密钥。
- 总线端口 7400 只在 compose 内部网络开放；HMAC 防的是同一网络里的其他进程冒充节点、订阅全部用户的消息。
  它不加密内容：内部网络不可信时，应再套 TLS 或 WireGuard。

## 7. 心跳与故障检测

- 节点每 5 s 发 HEARTBEAT；Hub 收到后回 HEARTBEAT。
- 任一方 15 s 没收到任何字节即判定对端下线：
  - Hub 标记成员死亡，并广播 `$nodes`；
  - 节点断开，并指数退避重连（0.2 s → 10 s，带抖动）。只有完成握手的连接才把退避重置，认证失败会持续退避。
- 采集节点收到 `$nodes` 后重建一致性哈希环，来源自动重新分配（`collector/engine.py: Scheduler.set_nodes`）。

## 8. 状态机（节点侧）

```
DISCONNECTED ──connect ok──▶ JOINING ──收到欢迎帧且 HMAC 正确──▶ CONNECTED
     ▲                          │                                │
     │                    HMAC 错误 / 其他帧                     │
     └──── EOF / CRC 错误 / 15 s 无数据 / 写失败 ◀───────────────┘   （退避后重连；NODE_JOIN 带全部订阅，再重发 outbox）
```

## 9. 推送节点断线补发上限

推送节点收到 WebSocket `hello{last_seq}` 时，先补发 last_seq 之后的投递。积压超过 500 条时不逐条补发，
改发 `{"type": "resync_hint", "since": last_seq}`，客户端走 REST `/api/sync` 按页拉取。超出保留期时，REST 返回 `reset`，客户端全量刷新。
这样一个长时间离线的用户重连时，不会占满推送节点的发送缓冲、拖慢同节点的其他用户。
