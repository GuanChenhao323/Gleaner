# Gleaner（拾课）开发约定

网络编程课程大作业，五人小组，老师已认定等级5（系数1.30）。完整需求见 `docs/proposal.md`，以它为准。
与本文件冲突或有任何不确定的地方，先问，不要自行假设。

## 评分硬约束（违反会直接影响成绩）

等级5的依据是"网络协议从 socket 层自研"。以下约束只针对 `server/`。

### 必须自研（基于 socket、selectors，或 asyncio 底层 streams/transports）

* HTTP/1.1 服务端与客户端：请求解析、chunked、keep-alive、条件请求（ETag / If-Modified-Since）
* WebSocket（RFC 6455）：握手、帧编解码、分片、ping/pong、关闭握手
* MQTT 3.1.1 Broker 子集：QoS 0/1、持久会话、保留消息、主题通配符、主题访问控制
* IMAP（含 IDLE）、SMTP（含 STARTTLS 与附件）、POP3 客户端
* 节点间二进制总线协议（帧格式见 proposal"内部二进制协议"，Magic = 0x474C）
* 负载均衡、主动与被动健康检查、一致性哈希、采集任务调度
* DNS 解析器：UDP 报文编解码、缓存、超时重试
* 跨设备扫码传输：分块传输、断点续传（HTTP Range）、完整性校验
* 本地采集代理与云端之间的长连接、心跳与断线重连
* 调用大模型 API 生成摘要时，同样走自研 HTTP 客户端

### server/ 禁止引入

requests、httpx、aiohttp、urllib3、h11、http.client、http.server、urllib.request、socketserver、websockets、wsproto、
tornado、fastapi、flask、django、starlette、uvicorn、gunicorn、paho-mqtt、gmqtt、amqtt、imaplib、smtplib、poplib、
aiosmtplib、aioimaplib、dnspython、prometheus_client。（`server/pyproject.toml` 的 ruff banned-api 会自动检查）

### server/ 允许使用

* 标准库：socket、selectors / select（epoll）、asyncio（streams/transports）、ssl、email（只用于解析和组装 MIME，已获老师同意）、
  hashlib、hmac、base64、struct、zlib、gzip、json
* 第三方：msgpack、feedparser（只传入字节，不让它自己联网）、beautifulsoup4 / lxml、psycopg、cryptography（AES-GCM）、argon2-cffi
* 需要其他库时先问。

### 不受限制的目录

* `server/tests/` 和 `devtools/`：鼓励用 paho-mqtt、websockets、requests 等现成库作为对照客户端，验证自研实现的互通性。
* `client/`（Flutter）：使用现成库。

## 工作方式

* 范围：proposal"功能设计"中 P0、P1、P2 全部功能，以及"网络编程核心技术方案"的全部模块。
* 按 `docs/milestones.md` 推进；每个里程碑都要能独立测试。
* 协议模块先写测试再实现。测试至少覆盖：正常流程、TCP 粘包与分片到达、畸形输入、超时与断线。
* 每个自研协议在 `docs/protocols/` 写一份设计文档：帧格式或报文格式、状态机、错误处理、对应 RFC 章节。
* 代码风格：全部加类型注解；用 ruff 格式化与检查；关键协议代码注释对应的 RFC 章节。
* 里程碑完成的标准：全部测试与 lint 通过；`docker compose up` 能跑通演示路径；更新 README、`docs/protocols/`、`docs/milestones.md`；提交一次 git commit。
* 开发和测试一律连接 `devtools/fake_moodle` 与本地测试邮件服务器，不要访问真实的学校系统。
* 不确定的需求记到 `docs/open-questions.md` 并告诉组长，不要自行发挥。

## 常用命令

```bash
# 服务端
cd server && pip install -e ".[dev]"
pytest -q
ruff check . && ruff format --check .

# 本地完整环境（无需 Docker）：浏览器打开 http://localhost:8080，演示账号 demo@gleaner.test / demo12345
python devtools/dev_all.py --seed

# Flutter（国内网络：PUB_HOSTED_URL=https://pub.flutter-io.cn FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn）
cd client && flutter pub get && dart run build_runner build
flutter analyze && flutter test
flutter build web --release --no-web-resources-cdn
flutter run -d chrome --dart-define=GLEANER_SERVER=http://localhost:8080

# Docker
docker compose -f deploy/docker-compose.yml --profile dev up --build
```
