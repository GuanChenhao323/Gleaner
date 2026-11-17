# Campus Radar（Gleaner 仓库）

面向本校学生的校园信息管理应用：通过 Chrome 插件按条件提取普通网页当前 DOM 的匹配片段，并保留 Moodle 和指定校园网页的专用规则，自动结构化为个人事项，在 Flutter 工作台管理状态、追溯来源并查看变化。结构化优先使用插件与程序，效果不足时再考虑 LLM；监测以 Chrome 运行且本地后端可用为条件。

**当前产品范围唯一依据：[产品定义](docs/product-definition.md)。** 新定义已取代旧产品范围；[项目提案](docs/proposal.md) 保留独立课程技术交付，[里程碑](docs/milestones.md) 记录新基线进度，[待决问题](docs/open-questions.md) 记录尚未确认的选择。

后端团队交接入口：[四节模板接口报告](docs/architecture/browser-extraction-interface-report-v1.md)、[完整数据流与交接说明](docs/architecture/browser-data-handoff-v1.md)（2026-11-17，扩展0.13.1基线）。汇总渲染DOM与HTML边界、三类保存请求、字段与合成报文、来源检查、持久化和客户端消费；当前上传结构化JSON，不上传整页HTML／DOM树或Cookie。

Campus Radar 是当前产品名称；Gleaner／拾课保留为仓库、代码包、配置及历史实现名称。仓库包含多协议网关、邮件、云部署等既有课程实现；这些模块存在不代表当前产品承诺提供对应功能。当前 MVP 尚待按新基线验收，首发 Flutter 平台尚待确认。

## 当前产品组成

Chrome 插件（按条件提取与预览保存）→ 本地后端（结构化、分类、存储与监测协作）→ Flutter 工作台（查看、编辑、状态与来源变化）。具体流程和边界引用产品定义；候选采集、持久后台和浏览器来源契约见 [插件说明](docs/browser-extension.md)。通用网页片段采用整组资料和明确保存后版本更新；默认保存后绑定当前专用标签页，自动刷新验证并定期检查，同页多规则共享刷新，原站会话留在Chrome。保留仅保存一次，旧来源需显式启动；校园事项沿用原生身份。通用合成夹具见 `http://127.0.0.1:8098/generic`，接口见 [通用快照契约](docs/architecture/universal-web-capture-v1.md)。真实学校／Gmail DOM 和认证仍须另行验收。

0.13.1修复“资料已保存、首次监测持续检查中”的结果契约冲突：兼容旧快照，检查拒绝明确记录失败，工作台独立显示保存与检查状态，原资料无需重建。

已删除的条件来源现可在“信息源 → 已删除来源 → 彻底删除”中永久清理：先核对关联资料、版本和规则影响，再确认。清理后该账号的旧采集预览统一失效，重新提取即可保存同网页与条件；学校 Cookie 不清理。详见[永久删除契约](docs/architecture/source-permanent-delete-v1.md)。

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

需要脱离当前终端持续运行时，可从仓库根目录执行（不重置／seed现有数据库）：

```bash
.venv/bin/python devtools/local_service.py start all
.venv/bin/python devtools/local_service.py status all
.venv/bin/python devtools/local_service.py stop all
```

`all`包含本地完整栈与8098结构夹具；日志及PID记录在`data/local-services/`。只停止该启动器创建且命令／启动时间匹配的进程，端口占用不自动结束他人服务。启动后仍须核对HTTP与登录。QA可显式加`--fixture-reading-interval 60`，仅加速loopback来源且工作台显示测试标记，不改变真实网站周期；日常启动不要加此参数。

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


## 当前来源检查（0.9.0）

插件输入原关键词、预览并保存后，在工作台“信息源”保留资料、原条件和来源会话关联。统一横向卡片提供资料／版本差异、检查日志及设置；原站入口收进“从网页采集”，旧资料与演示订阅折叠保留。

先在工作台测试后台重读，再选择手动或30／60／120分钟定期检查。Chrome、扩展与本地后端运行时可关闭原网页，后台沿同条件重读；会话留在Chrome，不复制Cookie。未知私人账号、登录失效、视图／路由改变和零匹配均明确反馈，不覆盖成功资料或个人修改。最低Chrome110、既有DOM提取和依赖保持不变。详见[条件来源契约](docs/architecture/condition-monitoring-v1.md)。

## 来源账号与回收站（0.11.0）

插件将原站登录要求与来源别名分开；私人普通网页提取后可单独“核对当前网页账号”，确认脱敏标识后保存。明确账号控件无法识别时仍保留手动快照，不把正文邮箱或别名当认证。后台沿同一账号控件复核；已知登录型邮箱拒绝公开声明。所有资料仅自己可见，权限与依赖不变，未新增 Cookie／debugger 权限。

收件箱和详情新增移入回收站、撤销／恢复；资料与历史保留，最后一份关联资料移入时暂停检查。来源卡片“删除来源”默认保留资料，可选同时移入个人回收站；“已删除来源”支持手动恢复，恢复后暂停并重新验证。旧任务／保存重试不能恢复墓碑。删除按钮采用在线严格确认；不提供永久清除。完整语义见 [接口契约](docs/architecture/source-identity-and-lifecycle-v1.md)。本地 HTTP 模拟端口验收可运行 `node devtools/source_lifecycle_smoke.mjs`（生成独立合成资料，不访问真实平台）。

## Timeline 摘要资料（0.10.0）

Moodle Dashboard 输入 Timeline／时间线 → 重新提取 → 核对活动摘要 → 保存为一份活动摘要 → 工作台查看资料及活动详情链接。保留当前已加载的标题、课程、时间原文和链接，不冒充完整作业，不自动打开详情。原条件及学校账号关联，重复保存和后台检查均更新原资料版本。安装旧版本后须在 chrome://extensions 重新加载扩展；旧冻结预览须重新提取，工作台刷新页面加载新构建。契约见 [Timeline 摘要保存](docs/architecture/timeline-summary-v1.md)。

## 当前网页读取入口（0.8.1）

在普通 HTTP(S) 或学校原网页点插件 → 输入条件 → 提取 → 弹窗内核对预览 → 明确保存。采集面板采用520px雾白浅色布局，不随系统暗色切换。连接设置、当前页、条件、预览和保存反馈均在单框内完成；匹配位置直接可见，不再打开独立双栏页。普通片段保存前明确选择公开来源或确认私人标签。零匹配不回退整页；同名课程先确认范围；无需逐条勾选。草稿保留在本机，满足身份与账号条件的详情可显式保存快照，不自动监测。详见 [采集面板契约](docs/architecture/capture-panel-v1.md)。真实学校页面质量与后台重入仍须单独验收。

普通课程词（如“人工智能”）可预览当前课程卡片和已加载信息，显式“课程名的作业”只读作业，“Timeline”逐条预览当前已加载活动；“Moodle Support 的邮箱”提取联系字段。课程、明确关联的作业分组，原活动标题与课程上下文分开。课程入口、区块和附件元信息标为仅预览，未识别结构会明确报错。完整事项才可整批保存。

扩展 0.8.1 只使用渲染 DOM；已移除 AX 读取、选项与构建入口，不申请 debugger 权限。安装、权限与边界见 [插件说明](docs/browser-extension.md)，对象契约见 [IC-EXTRACTION-001](docs/architecture/page-extraction-v1.md)。

## 兼容的浏览器采集开发闭环（0.2）

扩展 0.2.0 按 [IC-BROWSER-001](docs/architecture/browser-capture-v1.md) 接入 Core 和 Flutter，旧剪藏接口兼容保留。结构夹具启动：`.venv/bin/python devtools/campus_fixture/app.py --port 8098`，入口 `http://localhost:8098/`；Chrome 加载 `extension/` 后按 [本地复现步骤](devtools/campus_fixture/README.md) 操作。学校账号在原站自行登录，未验证的生产结构不会被声明为已支持。

```bash
npm --prefix extension ci
npm --prefix extension test
.venv/bin/python -m pytest -q server/tests/test_browser_capture.py
```

上述自动测试只访问本地／合成数据；真实 Chrome 权限和会话验证与模拟 API 结果分别记录。
