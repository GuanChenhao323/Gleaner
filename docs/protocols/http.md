# HTTP/1.1 服务端与客户端

实现：`server/gleaner/net/http/`（`parser.py` 解析器、`server.py` 服务端、`client.py` 客户端、`cookies.py`、`static.py`）。
测试：`server/tests/test_http.py`（与 `requests` 库互通、逐字节到达、流水线、畸形报文、超时、陈旧连接重试）。

## 1. 解析器（sans-IO，RFC 9112）

解析器只吃字节、吐完整消息，不做 I/O；服务端、客户端、网关的 WebSocket 转发共用同一个实现。

```
HEAD ──Content-Length──▶ BODY_LENGTH ──读满──▶ HEAD
  │──Transfer-Encoding: chunked──▶ CHUNK_SIZE ⇄ CHUNK_DATA → CHUNK_CRLF ──size=0──▶ TRAILERS ──空行──▶ HEAD
  │──（仅响应）无长度──▶ BODY_EOF ──连接关闭──▶ DONE
```

| 规则 | RFC | 处理 |
| --- | --- | --- |
| 消息体长度判定顺序 | 9112 §6.3 | HEAD 请求 / 1xx / 204 / 304 无正文 → chunked → Content-Length → 读到关闭 |
| TE 与 CL 同时出现 | 9112 §6.3 第 3 条 | 拒绝（400），防请求走私 |
| 多个不一致的 Content-Length | 9112 §6.3 | 拒绝 |
| 头部字段名与冒号间有空白 | 9112 §5.1 | 拒绝 |
| obs-fold 折行 | 9112 §5.2 | 拒绝 |
| HTTP/1.1 缺 Host | 9112 §3.2 | 拒绝 |
| chunk-ext | 9112 §7.1.1 | 忽略 |
| trailer | 9112 §7.1.2 | 解析后丢弃 |
| 请求间多余空行 | 9112 §2.2 | 容忍 |

限制：头部 64 KiB（超出 431）、100 个字段、消息体 32 MiB（超出 413）。
`ParseError.status` 携带建议的状态码，服务端据此回错误并关闭连接。

## 2. 服务端

- asyncio streams；Linux 上事件循环底层是 epoll（`select.epoll` 经 `selectors.DefaultSelector`）。
- keep-alive（RFC 9112 §9.3）：HTTP/1.1 默认持久，HTTP/1.0 需 `Connection: keep-alive`；
  空闲超时 15 s；读到半条请求后改用头部超时 10 s（防 slowloris），超时回 408。
- 每连接最多 1000 个请求；流水线请求按序处理。
- 响应：`Content-Length` 或 chunked 流式（`Response.stream`）；文本类、≥1 KiB 且客户端接受时 gzip。
- 协议升级：处理器返回 `Response(101, upgrade=callback)`，服务端发出 101 后把原始 reader/writer 与解析器剩余字节交给回调（WebSocket）。
- `SO_REUSEPORT` + 多进程：`GLEANER_WORKERS=N` 时网关 fork N 个进程共享端口（Linux）。
- TLS：标准库 `ssl` 包装监听 socket，最低 TLS 1.2。

## 3. 客户端

- 连接池按 `(scheme, host, port)` 复用 keep-alive 连接，空闲 30 s 回收；每主机并发上限 + 全局并发上限（信号量）。
- 连接超时与读取超时分开；错误分类：`connect` / `timeout` / `dns` / `tls` / `protocol`。
- 复用的空闲连接可能已被对端关闭（没收到任何响应字节就 EOF）：幂等方法自动换新连接重试一次。
- 自动处理 1xx、重定向（301/302/303 POST→GET）、gzip / deflate、Cookie Jar（RFC 6265 子集）。
- 可注入自研 DNS 解析器（`GLEANER_USE_OWN_DNS=1`）。
- 统计 `connections_opened` / `connections_reused`，用于“有无连接池”对比实验。

## 4. 条件请求与 Range（RFC 9110 §13、§14）

- `not_modified()`：`If-None-Match` 优先于 `If-Modified-Since`；弱比较。
- 采集引擎为每个 URL 保存 ETag / Last-Modified 与上次解析结果，304 时直接复用解析结果。
- `ranged_response()`：单段 `bytes=a-b`、`bytes=a-`、`bytes=-n`；越界回 416 + `Content-Range: bytes */size`；
  `If-Range` 不匹配时回完整内容。用于扫码传输的断点下载。

## 5. 静态文件

Flutter Web 构建产物由网关直接分发：ETag（mtime + size）、Last-Modified、304、gzip、Range。
`main.dart.js`、`index.html` 等文件名不含内容哈希，使用 `Cache-Control: no-cache`（每次协商，命中 304）；
`canvaskit/`、`assets/` 长缓存。路径穿越检查；无扩展名路径回退 `index.html`（SPA）。
