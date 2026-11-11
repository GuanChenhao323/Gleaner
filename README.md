# Campus Radar（Gleaner 仓库）

面向本校学生的校园信息管理应用：通过 Chrome 插件选择 Moodle 和指定校园网页中的信息，自动结构化为个人事项，在 Flutter 工作台管理状态、追溯来源并查看变化。结构化优先使用插件与程序，效果不足时再考虑 LLM；监测以 Chrome 运行且本地后端可用为条件。

**当前产品范围唯一依据：[产品定义](docs/product-definition.md)。** 新定义已取代旧产品范围；[项目提案](docs/proposal.md) 保留独立课程技术交付，[里程碑](docs/milestones.md) 记录新基线进度，[待决问题](docs/open-questions.md) 记录尚未确认的选择。

Campus Radar 是当前产品名称；Gleaner／拾课保留为仓库、代码包、配置及历史实现名称。仓库包含多协议网关、邮件、云部署等既有课程实现；这些模块存在不代表当前产品承诺提供对应功能。当前 MVP 尚待按新基线验收，首发 Flutter 平台尚待确认。

## 当前产品组成

Chrome 插件（按条件提取与预览保存）→ 本地后端（结构化、分类、存储与监测协作）→ Flutter 工作台（查看、编辑、状态与来源变化）。具体流程和边界引用产品定义；候选采集、持久后台和浏览器来源契约见 [插件说明](docs/browser-extension.md)。三来源结构夹具已接线，真实学校 DOM 和认证须另行授权验收。

## 既有课程技术架构

下图和目录表描述已有实现，用于复用与技术评估，不是当前 MVP 的部署要求。

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
| `extension/` | Chrome MV3 插件：条件输入与匹配预览、一次持久保存、关联来源重读（见 `docs/browser-extension.md`） |
| `devtools/` | fake_moodle、fake_mail、压测与对比实验、一键开发环境、三来源结构夹具与插件模拟测试 |
| `deploy/` | docker-compose、Prometheus、Grafana、Autobahn |
| `docs/protocols/` | 每个自研协议的设计文档 |
| `docs/integrations/` | 真实平台接入的授权登记与接入步骤（目前：MUST Moodle） |
| `docs/exec-plans` | 用于记录未完成和已完成的计划，文档的内容需要严格参考 `docs/exec-plans/template.md`|

## 既有实现的开发命令

以下 Web、Compose 和多节点流程服务于当前代码及课程验证，不代表新产品已完成或已承诺多端交付。

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

## 既有课程演示路径

此处验证协议推送与故障恢复；当前产品演示和验收使用产品定义第 7 节的场景 A/B/C。

1. **扫码加入**：投屏登录页，同学用手机打开 Web 版注册，用校园模板订阅；Grafana 在线连接数上升。
2. **作业变更秒级送达**：在 fake_moodle 管理台点“提前 2 天”→ 客户端弹出“重要变更 · 截止提前 2 天”，日历移动，修改历史多一个版本，手机收到 MQTT 通知。
3. **断网与故障恢复**：结束一个推送节点进程（或断网）→ 客户端显示离线、可浏览缓存、可加待办 → 恢复后自动重连到另一节点，补齐消息，待办只生效一次。


## 当前网页读取入口（0.3.0）

在学校原网页点插件 → 输入条件（例如“网络编程的作业”）→ 抓取匹配内容 → 核对整组预览 → 一次保存。零匹配不回退整页；同名课程先确认范围；无需逐条勾选。读取草稿保留在本机，默认不创建事项；满足身份与账号条件的详情可显式保存快照，不自动监测。Flutter 信息源始终提供三个真实入口，原有本地演示订阅另行说明。真实学校页面质量与后台重入仍须单独验收。

扩展 0.4.0 只使用渲染 DOM；已移除 AX 读取、选项与构建入口，不申请 debugger 权限。安装、权限与边界见 [插件说明](docs/browser-extension.md)，对象契约见 [IC-EXTRACTION-001](docs/architecture/page-extraction-v1.md)。

## 兼容的浏览器采集开发闭环（0.2）

扩展 0.2.0 按 [IC-BROWSER-001](docs/architecture/browser-capture-v1.md) 接入 Core 和 Flutter，旧剪藏接口兼容保留。结构夹具启动：`.venv/bin/python devtools/campus_fixture/app.py --port 8098`，入口 `http://localhost:8098/`；Chrome 加载 `extension/` 后按 [本地复现步骤](devtools/campus_fixture/README.md) 操作。学校账号在原站自行登录，未验证的生产结构不会被声明为已支持。

```bash
npm --prefix extension ci
npm --prefix extension test
.venv/bin/python -m pytest -q server/tests/test_browser_capture.py
```

上述自动测试只访问本地／合成数据；真实 Chrome 权限和会话验证与模拟 API 结果分别记录。
