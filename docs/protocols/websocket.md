# WebSocket（RFC 6455）与推送协议

实现：`server/gleaner/net/websocket/protocol.py`（sans-IO 状态机）、`stream.py`（asyncio 封装、客户端、心跳）、
`server/gleaner/push/node.py`（推送节点）、`server/gleaner/gateway/app.py`（转发）。
测试：`server/tests/test_websocket.py`（与 `websockets` 库双向互通、三种长度编码、分片中夹 ping、违规帧关闭码、心跳判死）。

## 1. 握手（§4）

服务端校验：方法 GET、`Upgrade: websocket`、`Connection` 含 `upgrade`、`Sec-WebSocket-Version: 13`、
`Sec-WebSocket-Key` 为 16 字节 Base64。`Sec-WebSocket-Accept = base64(SHA-1(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"))`。
支持子协议协商（`websocket_route(subprotocols=...)`，MQTT over WebSocket 使用 `mqtt`）。

## 2. 帧（§5）

```
FIN | RSV1-3 | opcode(4) | MASK | len(7) [+16 | +64] | mask-key(4) | payload
```

| 检查 | 违规时关闭码 |
| --- | --- |
| 客户端帧必须掩码、服务端帧不得掩码（§5.1） | 1002 |
| RSV 位未协商扩展却置位 | 1002 |
| 保留 opcode | 1002 |
| 控制帧分片或长度 > 125（§5.5） | 1002 |
| 64 位长度最高位为 1 | 1002 |
| CONT 帧没有起始帧 / 分片中出现新的数据帧（§5.4） | 1002 |
| 文本消息 UTF-8 非法（增量校验，跨分片）（§8.1） | 1007 |
| 消息超过 4 MiB | 1009 |
| close 负载长度为 1、非法关闭码、原因非 UTF-8（§7.4） | 1002 / 1007 |

掩码用大整数一次异或实现，比逐字节循环快两个数量级。

## 3. 状态机

```
OPEN ──send_close──▶ CLOSING ──收到 close──▶ CLOSED
  │──收到 close──▶ 自动回 close ──▶ CLOSED
  │──协议错误──▶ 发 close(code) ──▶ CLOSED
```

收到 ping 自动回 pong；`close()` 发送关闭帧后等待对端回应最多 2 s，再关闭 TCP（§7.1.2）。

## 4. 心跳

推送节点每 25 s 发 ping；60 s 内既无 pong 也无其他数据，判定连接已断并关闭（`WebSocket.start_heartbeat`）。

## 5. 推送应用协议（JSON 文本帧）

```json
→ {"type": "hello", "token": "…", "last_seq": 1287}
← {"type": "welcome", "cursor": 1291, "node": "push-1", "replayed": 4}
← {"type": "item",   "seq": 1290, "priority": "normal", "item": {...}}
← {"type": "change", "seq": 1291, "item_id": 5521, "version": 3, "important": true,
   "changed": {"deadline_at": [old, new]}, "note": "截止提前 2 天", "item": {...}}
← {"type": "reminder" | "source_status" | "state" | "digest" | "transfer" | "resync_hint", ...}
→ {"type": "ack", "seq": 1291}
→ {"type": "state", "op_id": "c7f3…", "item_id": 5521, "starred": true}
```

- hello 必须在 10 s 内到达且令牌有效，否则以 4401 / 1008 关闭。
- **断线补发**：hello 后先按 `seq > last_seq` 从数据库补发（`replay: true`），再进入实时推送；
  每个连接记录已发送的最大 seq，补发与实时消息的交叠部分不会重复发送。客户端也按 seq 去重。
- 所有投递都实时推送；分数 < 40 的带 `silent: true`，客户端只更新界面、不提醒（见 decisions.md 第 4 条）。客户端发现 seq 有缺口（例如背压丢弃）时调用 `GET /api/sync?cursor=` 补齐。
- **背压**：发送缓冲 > 256 KiB 时丢弃低/普通优先级消息并标记需要重新同步（数据仍在库中），
  回落后发 `resync_hint`；> 2 MiB 直接断开慢客户端，保护整个节点。
- ACK 合并 0.5 s 后批量写库（`deliveries.acked_at`）。

## 6. 推送节点的手写反应器（默认）

推送节点的客户端 socket 由手写反应器管理（`server/gleaner/net/reactor.py`、`net/websocket/reactor_server.py`），
业务逻辑（补发、数据库、总线）仍在 asyncio 线程。

```
            反应器线程（selectors：epoll / poll / select）                      asyncio 线程
 accept ──▶ _Conn: 非阻塞 recv ──▶ HTTPParser（握手）──▶ 101 ──▶ WSConnection（帧）
                                   │ 非 WebSocket 请求：/health、/metrics 同步应答后关闭
            文本消息 ─────────── loop.call_soon_threadsafe ─────────────▶ peer.inbox → PushNode.session()
            out 缓冲 ◀── reactor.call_soon_threadsafe（socketpair 唤醒 select）◀── peer.send_text()
            每秒巡检：握手超时 10 s、每 25 s ping、60 s 无数据判死
```

- 只在写缓冲非空时关注 `EVENT_WRITE`，避免水平触发的 epoll 空转。
- 背压读取 `peer.buffered`（已入队未写出 + 内核未接收的字节数）。
- `GLEANER_PUSH_IO=asyncio` 可切回 asyncio 接入层（同一套会话逻辑，见 `AsyncioPeer`），用于对比。
- 对比实验 1：`GLEANER_PUSH_SELECTOR=select` 与 `epoll` 分别压测推送节点（select 受 FD_SETSIZE=1024 限制）。

## 7. 网关转发与故障转移

网关校验令牌 → 按 `user:<uid>` 在一致性哈希环（每节点 160 个虚拟节点）上选推送节点，跳过不健康节点 →
把升级请求原样转发 → 拿到 101 后双向拼接字节流（`_pipe`）。
推送节点宕机：连接断开 → 客户端指数退避重连 → 网关主动 / 被动健康检查已摘除该节点 → 哈希环顺延到下一个节点 →
客户端带 `last_seq` 补发。端到端测试 `test_full_demo_path` 覆盖此流程。

## 8. Autobahn 一致性测试

```bash
python devtools/autobahn_echo.py                  # asyncio 版，:9001
python devtools/autobahn_echo.py --impl reactor   # 手写反应器版，:9002
docker compose -f deploy/docker-compose.yml --profile conformance run --rm autobahn
python devtools/autobahn_summary.py               # 汇总到 docs/evaluation/results/autobahn.json
# 报告：deploy/autobahn/reports/servers/index.html（排除 12.*、13.* permessage-deflate 用例）
```

2026-10-22 结果（详见 `docs/evaluation/README.md` 第三轮）：asyncio 版 301 个用例 0 失败；
手写反应器版只有 35 个二进制回显用例失败（推送节点只用文本帧），文本用例全部通过。
单条消息上限默认 4 MB（超出以 1009 关闭，§7.4.1），可用 `max_message` 参数调整。
