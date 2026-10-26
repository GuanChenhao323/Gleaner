# 拾课 Gleaner

面向学生的个性化信息聚合工作台：把 Moodle 作业、学院通知、学校邮箱整理成跨课程的作业列表、日历和收件箱；
原通知被修改时更新同一事项并标出变化，紧急事项秒级推送到浏览器和手机。

网络编程课程大作业（等级 5）。**所有网络协议都从 socket 层自研**：HTTP/1.1 网关与客户端、WebSocket、
MQTT 3.1.1 Broker、IMAP（IDLE）/ SMTP（STARTTLS）/ POP3 客户端、节点间二进制总线、DNS 解析器。
需求见 [docs/proposal.md](docs/proposal.md)，进度见 [docs/milestones.md](docs/milestones.md)，待确认问题见 [docs/open-questions.md](docs/open-questions.md)。

## 架构

```
 Flutter 客户端（Web / Android / 桌面）
     │ HTTPS · WSS /ws · WSS /mqtt · /agent              MQTT 1883/8883（手机、桌面）
     ▼                                                         │
 ┌─────────────── 网关 gateway ───────────────┐                 │
 │ 自研 HTTP/1.1 · TLS · 令牌桶限流 · 静态文件 │                 │
 │ 一致性哈希 + 主动/被动健康检查               │                 │
 └──┬───────────────────┬─────────────────────┘                 │
    │ /api/*            │ /ws（按 uid 哈希）                     │
    ▼                   ▼                                       ▼
 业务服务 core  ◀──总线──▶ 推送节点 push-1 / push-2      MQTT Broker
 REST · 流水线 · Hub      WebSocket 会话 · 补发 · 背压     QoS0/1 · 持久会话 · 保留 · ACL
    ▲  ▲                                                       ▲
    │  └───────────── 自研二进制总线（Magic 0x474C，至少一次 + 去重 + 心跳）─────────┘
    │
 采集节点 collector（最小堆调度 · 连接池 · 条件请求 · 熔断 · 会话）   邮件服务 mailsvc（IMAP IDLE · POP3）
    │                                                                      │
    ▼                                                                      ▼
 Moodle / 学院网站 / 教师页（开发期：devtools/fake_moodle）            学校邮箱（开发期：fake_mail / GreenMail）
```

| 目录 | 内容 |
| --- | --- |
| `server/gleaner/net/` | 自研协议：`http/` `websocket/` `mqtt/` `mail/` `bus/` `dns/` |
| `server/gleaner/gateway/` | 网关：反向代理、WebSocket 转发、负载均衡、健康检查、限流 |
| `server/gleaner/push/` | 推送节点 |
| `server/gleaner/broker/` | MQTT Broker（TCP 与 WebSocket 传输） |
| `server/gleaner/collector/` | 采集引擎与连接器（Moodle、网页、RSS、教师信息） |
| `server/gleaner/mailsvc/` | 收信长连接、代用户发信 |
| `server/gleaner/core/` | REST API、去重与跨渠道合并、版本比较、打分、截止抽取、摘要、提醒 |
| `server/gleaner/transfer/` | 跨设备扫码传输 |
| `server/gleaner/storage/` | SQLite / PostgreSQL 访问层与表结构 |
| `agent/` | 本地采集代理 |
| `client/` | Flutter 客户端 |
| `extension/` | Chrome / Edge 浏览器插件：保存当前页面、订阅页面更新（见 `docs/browser-extension.md`） |
| `devtools/` | fake_moodle、fake_mail、压测与对比实验、一键开发环境、插件弹窗测试页 |
| `deploy/` | docker-compose、Prometheus、Grafana、Autobahn |
| `docs/protocols/` | 每个自研协议的设计文档 |
| `docs/integrations/` | 真实平台接入的授权登记与接入步骤（目前：MUST Moodle） |

## 常用命令

### 服务端

```bash
cd server
pip install -e ".[dev]"
pytest -q                       # 全部测试（含与 requests / websockets / paho-mqtt 的互通测试和端到端测试）
ruff check . && ruff format --check .
```

### 本地完整环境（不需要 Docker）

```bash
python devtools/dev_all.py --seed
```

浏览器打开 http://localhost:8080 ，演示账号 `demo@gleaner.test` / `demo12345`。
fake_moodle 管理台 http://localhost:8090/admin 可以现场“提前截止时间”“替换附件”“发布通知”“发提醒邮件”“让会话失效”。

### Flutter 客户端

```bash
cd client
flutter pub get
dart run build_runner build          # 生成 drift 数据库代码
flutter analyze && flutter test
flutter build web --release --no-web-resources-cdn   # 产物在 client/build/web，由网关分发
flutter run -d chrome --dart-define=GLEANER_SERVER=http://localhost:8080   # 开发调试（网关已允许跨域）
```

国内网络可设置镜像：`PUB_HOSTED_URL=https://pub.flutter-io.cn`、`FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn`。
Windows 上构建 Android / Windows 版需要开启“开发者模式”。

### Docker Compose

```bash
cp deploy/.env.example deploy/.env       # 修改密钥
cd client && flutter build web --release --no-web-resources-cdn && cd ..
docker compose -f deploy/docker-compose.yml --profile dev up -d --build
python devtools/compose_demo.py           # 自动走一遍演示路径（注册、截止提前推送、推送节点故障转移等）
```

网关 :8080、Grafana :3000（面板“拾课 Gleaner 运行总览”）、Prometheus :9090、MQTT :1883、fake_moodle :8090。
注册验证码在 compose 的 dev 环境里发到 GreenMail：IMAP `localhost:3143`，用户名和密码都是注册邮箱。
WSL 2 里运行时，最后一个 WSL 会话退出后发行版会自动关闭，演示期间请保持一个 WSL 终端开着。

### 压测与一致性测试

见 [devtools/loadtest/README.md](devtools/loadtest/README.md) 与 [docs/protocols/websocket.md](docs/protocols/websocket.md#8-autobahn-一致性测试)。

## 演示路径

1. **扫码加入**：投屏登录页，同学用手机打开 Web 版注册，用校园模板订阅；Grafana 在线连接数上升。
2. **作业变更秒级送达**：在 fake_moodle 管理台点“提前 2 天”→ 客户端弹出“重要变更 · 截止提前 2 天”，日历移动，修改历史多一个版本，手机收到 MQTT 通知。
3. **断网与故障恢复**：结束一个推送节点进程（或断网）→ 客户端显示离线、可浏览缓存、可加待办 → 恢复后自动重连到另一节点，补齐消息，待办只生效一次。
