# Campus Radar（Gleaner 仓库）开发约定

## 工作方式：先建立上下文，再按需查阅

1. 先阅读 `README.md`，了解项目概况、目录结构和运行方式。
2. 再阅读 `docs/product-definition.md`，理解产品目标、核心概念、功能范围和验收标准。
3. 根据当前任务，阅读相关模块的开发协议与实现文档：协议和接口查 `docs/protocols/`，插件查 `docs/browser-extension.md`，真实平台接入查 `docs/integrations/`。只读取任务相关的文档，无需通读全部协议。

涉及排期或进度时查 `docs/milestones.md`；涉及课程交付时查 `docs/proposal.md`；需要了解决策原因或待决问题时查 `docs/decisions.md`、`docs/open-questions.md`。归档仅在追溯历史时查阅。

产品范围统一在产品定义中维护。本文件维护开发约束，具体实现同时核对代码与测试；遇到影响任务的定义冲突或缺失，先确认再实施。


### 必须自研（基于 socket、selectors，或 asyncio 底层 streams/transports）

* HTTP/1.1 服务端与客户端：请求解析、chunked、keep-alive、条件请求（ETag / If-Modified-Since）
* WebSocket（RFC 6455）：握手、帧编解码、分片、ping/pong、关闭握手
* MQTT 3.1.1 Broker 子集：QoS 0/1、持久会话、保留消息、主题通配符、主题访问控制
* IMAP（含 IDLE）、SMTP（含 STARTTLS 与附件）、POP3 客户端
* 节点间二进制总线协议（帧格式见 `docs/protocols/bus.md`，Magic = 0x474C）
* 负载均衡、主动与被动健康检查、一致性哈希、采集任务调度
* DNS 解析器：UDP 报文编解码、缓存、超时重试
* 跨设备扫码传输：分块传输、断点续传（HTTP Range）、完整性校验
* 本地采集代理与云端之间的长连接、心跳与断线重连
* 仅在程序化提取效果不足且决定采用 LLM 后，调用其 API 同样走自研 HTTP 客户端；模型配置存在不代表产品应默认启用

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

## 开发与验证

* 按 `docs/milestones.md` 推进；每个里程碑都要能独立测试。
* 协议模块先写测试再实现。测试至少覆盖：正常流程、TCP 粘包与分片到达、畸形输入、超时与断线。
* 每个自研协议在 `docs/protocols/` 写一份设计文档：帧格式或报文格式、状态机、错误处理、对应 RFC 章节。
* 代码风格：全部加类型注解；用 ruff 格式化与检查；关键协议代码注释对应的 RFC 章节。
* 里程碑完成的标准：对应用户验收及相关测试、lint 通过，记录环境与结果；按改动更新 README、协议文档与里程碑。完成实施里程碑后按原约定提交一次 git commit。

## 真实平台访问

* 接入代码同样受 server/ 约束：OAuth、REST 都走自研 HTTP 客户端，不引入平台 SDK。
* 开发和自动化测试一律连接 `devtools/fake_moodle` 与本地测试邮件服务器；pytest、CI、压测都不得访问真实站点。
* 唯一的例外是**澳门科技大学（MUST）Moodle**（2026-10-26 组长决定，作为第一个真实平台接入），必须同时满足：
  * `docs/integrations/must-moodle.md` 里的授权状态为“已获授权”，并写明授权人、范围与有效期；否则一律不访问。
  * 只用该文档登记的测试账号；登录由组员本人在客户端界面完成，Claude 不输入密码、不保存密码（系统只存会话）。
  * 只访问该文档“允许访问范围”中列出的页面与 Web Service 函数；遵守 robots.txt；同一主机请求间隔不少于 2 秒。
  * 真实站点抓到的页面、作业、姓名、邮箱等数据不得提交进仓库，也不得写进测试夹具；解析规则用脱敏后的结构样本写测试。
  * 真实站点的检查只通过手动运行的脚本进行，不放进 pytest 与 CI。
* Lark、X、Facebook 不在当前产品范围；其他真实平台须先通过范围决策并获得授权，在 `docs/integrations/` 登记后才可访问。

## 既有实现的开发命令

以下命令用于已有技术环境；Flutter Web 的构建命令不代表当前产品首发平台已经确定。

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
