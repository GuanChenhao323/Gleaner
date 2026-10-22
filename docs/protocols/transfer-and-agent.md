# 跨设备扫码传输 与 本地采集代理

## 一、扫码传输（P2）

实现：`server/gleaner/transfer/service.py`、`client/lib/features/transfer/transfer_page.dart`。
测试：`server/tests/test_core.py::test_transfer_chunked_resume_and_range`。

```
电脑  POST /api/transfer                  → {code: "K7Q2MZ", token, expires_at}   二维码内容：<服务器>/#/transfer/K7Q2MZ
手机  POST /api/transfer/{code}/join       → {token}                               电脑经 WebSocket 收到 {"type":"transfer","status":"paired"}
任一端 POST .../files {name,size,sha256}    → {id, received: 0, chunk_max}
      PUT  .../files/{id}  Content-Range: bytes a-b/total  （每块 ≤ 4 MiB，客户端用 512 KiB）
      ……网络中断……
      GET  .../files/{id}                  → {received}                            断点续传：从 received 继续
      最后一块写入后服务器计算 SHA-256：一致 → done，不一致 → corrupt
另一端 GET .../files/{id}/content  Range: bytes=…   → 206 断点下载（ETag = SHA-256 前缀，X-Content-SHA256）
```

- 配对码 6 位，去掉易混淆字符（0/O/1/I），30 分钟有效。
- 鉴权：发起人的登录会话，或配对后获得的 `X-Transfer-Token`（手机无需注册账号）。
- 只接受从已接收位置继续的块：起点不等于已接收字节数时返回 409 与当前进度；重复的旧块幂等忽略。
- 单文件上限 512 MiB；文件名取 basename 防路径穿越。

## 二、本地采集代理（P2）

实现：`agent/gleaner_agent.py`（代理）、`server/gleaner/core/agent_hub.py`（云端入口）、网关 `/agent` 转发。
测试：`server/tests/test_e2e.py::test_local_agent_long_connection`。

只能在校园网内访问的来源（`via_agent = 1`）由用户电脑上的代理采集后上传。代理复用服务端的连接器与自研 HTTP 客户端；
**校内账号登录得到的会话只保存在本机 `~/.gleaner-agent.json`**，不上传到云端。

```
代理 ──自研 WebSocket──▶ 网关 /agent?token= ──▶ 业务服务
→ {"type":"hello","token","agent_id","version"}
← {"type":"welcome","sources":[...]}
→ {"type":"result","source_id","status","items",...}        按各来源的 interval_s 定时检查
← {"type":"ack","source_id","counts"}
← {"type":"fetch","source_id"}                               用户在界面点“立即检查”
↔ {"type":"ping"} / {"type":"pong"}                          应用层心跳 20 s；另有服务端 WebSocket ping
```

- 60 s 没收到任何数据视为断线；断线后指数退避 1 s → 60 s（带抖动）重连。
- 用法：`python agent/gleaner_agent.py --server https://… --email … --password …`；
  在本机登录某来源：`--login <source_id> <用户名> <密码>`。
