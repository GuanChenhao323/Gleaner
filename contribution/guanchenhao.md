# 个人贡献记录｜关辰浩（GitHub：GuanChenhao323）

更新：2026-11-09。依据：仓库 `main` 分支的提交历史（截至 `9927609`）、`docs/` 下的里程碑、评估、审查与决策记录。本文按时间和模块记录本人完成的工作；数字均可用文末命令复核。

## 0. 概览

| 项目 | 数据 |
| --- | --- |
| 分工 | HTTP API、数据库、LLM 接口调用、服务端通信、数据持久化、各模块之间的调用（不负责具体的信息处理规则）；早期按组长要求实现了全部核心技术模块 |
| 提交数 | 仓库共 39 个提交，本人 32 个（另两位组员分别为 4 个、3 个，均为文档） |
| 改动量 | 本人非合并提交共涉及 473 个文件次，新增 55,573 行，删除 1,947 行（含 Flutter 客户端约 2.3 万行与测试） |
| 当前代码规模 | 服务端 `server/gleaner` 约 15,800 行；服务端测试约 4,600 行（206 个用例）；开发与评估工具 `devtools` 约 3,500 行；Flutter 客户端 `client/lib` 约 5,500 行；浏览器插件约 220 行 |
| 最近一次验证（2026-11-09） | `pytest -q` 202 通过、3 跳过（随后新增 1 个网关实测用例，所在文件 11 项通过）；`ruff check`、`ruff format --check` 通过；PostgreSQL 16 数据库相关测试 68 项通过 |

开发方式：代码与文档在 Claude Code（AI 编程助手）辅助下完成，由本人确定需求与方案、审阅改动、运行验证并提交。

## 1. 时间线

| 日期 | 提交 | 内容 | 规模（文件 / +行 / −行） |
| --- | --- | --- | --- |
| 10-22 | `1260ef9` | M1 协议基础：HTTP/1.1、WebSocket、手写反应器、二进制总线、指标 | 37 / +5,949 |
| 10-22 | `7493187` | M4 MQTT 3.1.1 Broker | 8 / +1,425 |
| 10-22 | `c27a243` | M5 邮件协议：IMAP IDLE、SMTP STARTTLS、POP3 | 11 / +1,319 |
| 10-22 | `323e917` | M7 自研 DNS 解析器 | 4 / +475 |
| 10-22 | `d8fa7de` | M2–M7 业务层：采集、流水线、推送节点、网关、邮件服务、扫码传输、本地代理 | 46 / +8,711 |
| 10-22 | `a33e071` | M2–M7 Flutter 客户端 | 83 / +22,710 |
| 10-22 | `bb81c87` | M8 部署与运维：Docker Compose、Prometheus、Grafana、CI | 13 / +730 |
| 10-22 | `3a1eaa1`、`77be2be`、`bbd926e`、`c123083` | M9 评估工具与三轮实验数据（Windows、无 Docker、WSL 2） | 47 / +3,276 |
| 10-22 | `8d91c31` | 性能优化：总线订阅改为精确主题哈希查找 | 2 / +69 / −10 |
| 10-22 | `3a8caae` | 修复网关多 worker：在创建事件循环之前 fork | 1 / +3 / −1 |
| 10-22 | `6efe4b8`、`452abfe`、`e267a26` | M8 compose 实测修复、客户端离线缓存容错、官方 Autobahn | 28 / +1,143 / −85 |
| 10-22、10-23 | `57b1e1b`、`c807b79` | README、里程碑、决策记录、待确认问题 | 6 / +186 / −4 |
| 10-26 | `20a6e32` | 合入前端组员的改版（侧栏悬停展开、日历并入作业页、紧急事项整行着色）并适配 | 17 / +885 / −601 |
| 10-26 | `0ec00ce`、`d926692`、`cbf3d2e` | M11 MUST Moodle 接入：授权登记、站点探测、粘贴安全密钥登录 | 24 / +479 / −53 |
| 10-26 | `5efd44e`、`eec109e` | M12 Chrome／Edge 浏览器插件 | 24 / +786 / −11 |
| 11-05 | `5fde273` | 审查修复第 1、2 批：接口健壮性与安全 | 34 / +2,160 / −508 |
| 11-05 | `d44cf11` | 审查修复第 3 批：数据库与持久化 | 23 / +1,320 / −283 |
| 11-05 | `e082ab4` | 审查修复第 4 批：大模型调用 | 7 / +504 / −50 |
| 11-05 | `e6a2914` | 审查修复第 5 批：总线与模块调用 | 18 / +722 / −146 |
| 11-05 | `d798dba` | 合并组员的文档整理（产品定义、归档、架构图），解决冲突 | 合并提交 |
| 11-06 | `d57e912` | 新产品基线的后端设计：接口契约 IC-001／IC-002、执行计划、决策 D19–D25 | 5 / +358 / −2 |
| 11-06 | `0bfc89a` | 后端 R1–R3：批量采集、三类事项与状态、用户修改与冲突、事项级监测、LLM 开关 | 20 / +1,575 / −41 |
| 11-09 | `9927609` | 通信层补强：Cookie 存储校验、跨源重定向凭证、robots（RFC 9309）、Retry-After、网关 Host 白名单 | 15 / +788 / −94 |

## 2. 自研网络协议（课程技术交付 C01、C02、C04）

全部基于 `socket`、`selectors` 或 asyncio streams 编写，`server/` 不使用 requests、aiohttp、websockets、paho-mqtt、imaplib 等现成库（由 ruff banned-api 自动检查）。每个协议在 `docs/protocols/` 有设计文档。

### 2.1 HTTP/1.1（`net/http/`，约 1,600 行；文档 `docs/protocols/http.md`）
- sans-IO 解析器（RFC 9112）：请求行、头部、`Content-Length` 与 `chunked` 编码；支持逐字节到达、粘包与管线化；畸形请求返回 4xx。
- 服务端：keep-alive、请求体上限、超时、TLS（最低 TLS 1.2）。
- 客户端：按 (scheme, host, port) 的连接池、每主机与全局并发上限、连接与读取超时分开、错误分类、空闲连接被关闭时自动重试一次幂等请求、1xx、重定向、gzip／deflate、可注入自研 DNS。
- 条件请求（ETag／If-Modified-Since，RFC 9110 §13）与 Range（单段、416、If-Range，§14）。
- Cookie Jar（RFC 6265 子集），2026-11-09 补齐 §5.3 存储模型校验（见第 9 节）。
- 出站访问防 SSRF（`net/egress.py`）：先解析再连接解析出的 IP，拒绝回环、私有、链路本地地址，防 DNS 重绑定。

### 2.2 WebSocket（`net/websocket/`，约 1,000 行；RFC 6455）
- 握手、帧编解码、掩码、分片、ping／pong、关闭握手、UTF-8 校验与快速失败、单条消息上限可配置。
- 两套实现：asyncio 版（网关、本地代理）与手写反应器版（推送节点）。
- 官方 Autobahn Testsuite 25.10.1，301 个用例：asyncio 版 0 失败；反应器版文本类用例全部通过，失败的 35 个都是二进制回显（推送节点只收发文本帧）。另写了不需要 Docker 的精简版 `devtools/autobahn_lite.py`（38 个用例）。

### 2.3 手写反应器（`net/reactor.py`）
- 基于 `selectors`，epoll／poll／select 可切换（`GLEANER_PUSH_SELECTOR`），推送节点接入层可选反应器或 asyncio（`GLEANER_PUSH_IO`）。

### 2.4 节点间二进制总线（`net/bus/`，约 900 行；文档 `docs/protocols/bus.md`，Magic = 0x474C）
- 帧格式、压缩（有解压上限防压缩炸弹）、序号、ACK、去重、重传、心跳、Hub 广播在线节点 `$nodes`。
- 2026-11-05 第 5 批修复后（见第 7.5 节）：每成员收件箱与独立处理协程、背压、发件箱上限、HMAC 入网认证与防重放、会话号变化时清空去重表、端到端入库确认。

### 2.5 MQTT 3.1.1 Broker（`broker/` 与 `net/mqtt/`，约 1,000 行；文档 `docs/protocols/mqtt.md`）
- CONNECT／PUBLISH／SUBSCRIBE 等报文编解码，QoS 0／1、重发与 DUP、持久会话、保留消息、主题通配符（`+`、`#`）、按用户的主题访问控制、keepalive、会话接管、WebSocket 传输。

### 2.6 邮件客户端（`net/mail/`，约 770 行；文档 `docs/protocols/mail.md`）
- IMAP（含 IDLE）、POP3、SMTP（含 STARTTLS、AUTH、附件）；MIME 只用标准库 `email` 解析与组装（已获老师同意）。
- 邮件服务 `mailsvc/`：平台发信、用户邮箱发信、防重复发送（幂等键）。

### 2.7 DNS 解析器（`net/dns/`，约 340 行；文档 `docs/protocols/dns.md`）
- UDP 报文编解码、名字压缩、CNAME 跟随、NXDOMAIN、缓存（TTL）、超时重试。

### 2.8 扫码传输与本地采集代理（`transfer/`；文档 `docs/protocols/transfer-and-agent.md`）
- 配对码换令牌、分块上传、断点续传（HTTP Range）、SHA-256 完整性校验。
- 本地采集代理与云端之间的 WebSocket 长连接、心跳与断线重连。

## 3. 服务端业务与分布式部分（C03）

| 模块 | 内容 |
| --- | --- |
| 网关 `gateway/`（约 590 行） | 反向代理；core 与推送节点的一致性哈希负载均衡；主动与被动健康检查（只把连接错误和 502／503／504 算作失败）；按 IP 与按用户的令牌桶限流；CORS 白名单；安全响应头；多 worker（SO_REUSEPORT）；`/metrics`、`/gateway/status` 只对内网或管理令牌开放 |
| 采集 `collector/`（约 1,370 行） | 网页、RSS、Moodle（Web Service 与网页解析）、教师页、IMAP／POP3 邮箱等连接器；条件请求与解析缓存；去中心化调度（各采集节点按一致性哈希认领来源）；自适应检查间隔、熔断、退避 |
| 业务流水线 `core/pipeline.py` | 去重、跨渠道合并（同一作业的 Moodle 页与提醒邮件只保留一条）、个人来源按用户隔离、版本比较与重要变更判定、截止时间抽取、规则打分、分级投递 |
| 推送节点 `push/` | WebSocket 接入、投递序号、断线补发（积压超过 500 条改发 `resync_hint`）、MQTT 系统通知 |
| HTTP API `core/api.py`（约 1,900 行） | 账号与会话、收件箱、事项与状态、来源、发信、看板、规则、统计等 40 余个接口；文档 `docs/protocols/rest-api-and-sync.md` |
| 数据库 `storage/`（约 870 行；文档 `docs/database.md`） | 同一套 SQL 支持 SQLite 与 PostgreSQL；连接池、事务、断线重连、带版本号的迁移（共 7 个）、数据保留与清理、凭据 AES-256-GCM 加密与密钥轮换、每日备份 |
| 可观测性 `obs/` | 自研 Prometheus 文本格式指标（计数器、直方图），未使用 prometheus_client |
| 大模型摘要 `core/summarize.py`（文档 `docs/llm.md`） | 经自研 HTTP 客户端调用 OpenAI 兼容或 Anthropic 接口；失败回退到规则提取 |

## 4. Flutter 客户端（`a33e071`，`client/lib` 约 5,500 行）

- 收件箱、作业与日历、来源管理（含来源登录）、看板编辑、设置、扫码传输等页面。
- WebSocket 实时推送、投递序号增量同步、离线缓存（drift）与离线操作队列回放。
- `452abfe`：浏览器本地数据库不可用时，只影响离线浏览，实时连接与操作照常。
- `20a6e32`：合入前端组员提供的改版（侧栏悬停展开、日历并入作业页、紧急事项整行着色），本人负责合并与适配。
- 2026-11-05 配合“立即检查”的新返回值修改了来源页提示（`sources_page.dart`、`api.dart`）。

## 5. 部署、运维与评估（C03、C05）

### 5.1 部署（`bb81c87`、`6efe4b8`、`e267a26`）
- Docker Compose：PostgreSQL、业务服务、2 个推送节点、网关、Broker、采集、邮件服务、Prometheus、Grafana、fake_moodle、GreenMail 共 12 个容器；Grafana 面板与告警规则；CI 配置。
- 本地完整环境 `devtools/dev_all.py`（无需 Docker），演示账号与种子数据。
- 测试替身：`devtools/fake_moodle`（模拟 Moodle 页面、Web Service 与管理台）、`devtools/fake_mail`。
- compose 实测发现并修复 8 个只在真实部署中出现的问题，例如：
  - PostgreSQL 并发建表撞唯一约束 → 会话级咨询锁；
  - `CASE WHEN ?` 在 PostgreSQL 报类型错 → 统一写成 `= 1`；
  - 数据库断线后不重连 → 下一条语句自动重连；
  - 第二个用户看不到同一 Moodle 的作业 → 个人来源身份键加所有者前缀（决策第 9 条）；
  - 推送节点重启后收不到推送 → NODE_JOIN 携带 epoch；
  - 容器内 Python 3.12 拼接 Web Service 地址丢“?” → 统一 `moodle_ws_url`。

### 5.2 评估（`docs/evaluation/README.md`，工具在 `devtools/loadtest/`）

| 实验 | 结果 |
| --- | --- |
| 单推送节点并发连接 | 手写反应器（epoll）5,000 连接 0 失败，推送 P99 2.13 ms，内存 110 MB（比 asyncio 版少 34%）；达到“≥ 5,000 连接、P99 < 1 秒”目标 |
| 总线订阅优化 | 主题匹配改为精确哈希查找后，5,000 人全员扇出从 8.11 s 降到 1.57 s，CPU 从 57.6% 降到 19.4% |
| 连接池与 keep-alive | TCP 握手从 300 次降到 4 次，吞吐约提高 3.1 倍，P99 降低约 61% |
| 条件请求 | 304 占比 98.2%，节省流量 86.5%（目标 ≥ 70%） |
| 网关吞吐 | 多进程部署 `/api/templates` 1,334 req/s（目标 ≥ 1,000）；4 个 worker 时 `/health` 18,728 req/s；发现并修复“在事件循环内 fork 导致多 worker 不生效”的问题 |
| select 与 epoll | select 受 FD_SETSIZE 限制，900 连接以上无法测试；epoll 到 5,000 连接无此限制 |
| MQTT QoS 0／1 与丢包 | tc netem 5% 丢包下两种 QoS 送达率均为 100%，代价体现在 P99 延迟 |
| 单节点与三节点、网络中断 | 数据见评估文档 |

## 6. 真实平台与浏览器插件

### 6.1 MUST Moodle 接入（M11，`0ec00ce`、`d926692`、`cbf3d2e`）
- 制定真实平台访问规则（写入 `CLAUDE.md` 与 `docs/integrations/must-moodle.md`）：须登记授权；只用登记账号，登录由账号本人完成；只读、同主机请求间隔 ≥ 2 秒、遵守 robots；真实数据不入库；自动化测试只连 fake_moodle。
- `devtools/must_moodle_probe.py`：授权未登记时拒绝运行；完成站点探测，确认学校使用统一认证（CAS）。
- 方案 A（决策第 14 条）：用户粘贴 Moodle 安全密钥（偏好设置 → 安全密钥 → Moodle mobile web service），系统不经手统一认证密码；服务端先用 `core_webservice_get_site_info` 校验密钥。
- 修复容器里 Web Service 地址丢“?”的问题，并补回归测试。

### 6.2 浏览器插件（M12，`5efd44e`、`eec109e`，`extension/`）
- Chrome／Edge 共用 Manifest V3：保存当前页面（选中文字或正文）到收件箱、订阅页面更新（整页监测或 RSS）。
- 只在用户点开弹窗时读取当前标签页（`activeTab`），只对用户填写的服务器地址申请权限；登录过期时提示重新登录。
- 服务端 `POST /api/clips`：每人一个“网页收藏”个人来源，同一网址再次保存会记录新版本。

## 7. 2026-11-05 服务端全面审查与修复（`docs/review-2026-11.md`）

本人对服务端做了逐行审查，按 API／DB／LLM／BUS 编号逐条在代码中核实，分 5 批修复，每批先写测试。全部条目已修复，只有 3 条经评估决定不改并写明原因（API-25、DB-31/32 等）。

### 7.1 第 1 批：接口健壮性（`5fde273`）
- 坏 JSON、非对象请求体、类型不对的字段、非数字路径 id 原来都会变成 500，而网关连续 5 次 5xx 会摘除节点，几个坏请求就能让整个 API 不可用。新增 `core/validate.py` 统一校验，返回 400／422；网关只把连接错误和 502／503／504 记为失败。
- `state/batch` 一条坏操作让整批失败、离线队列卡死 → 每条单独返回结果；超过 500 条时明确返回 `truncated`。
- feed 分页游标与排序键不一致、`limit=0` 出错、并发注册同一邮箱出错、错误格式不统一等。

### 7.2 第 2 批：接口安全（`5fde273`）
- SSRF：预览、添加来源、自填 SMTP 主机可以访问内网与云元数据 → 出站地址校验。
- 发信的 cc／主题／附件类型可注入换行 → 校验与清理；异常后卡在 sending 的记录会被回收。
- 登录防爆破（限流与退避），用户不存在时也做哈希（防时间侧信道）；验证码接口防滥用、错误次数上限防并发绕过。
- 新增修改密码、找回密码、按设备查看与吊销会话；Cookie 加 Secure；带 Cookie 的修改请求做同源校验（CSRF）。
- 幂等键校验请求内容、客户端与服务端键分命名空间、先占位再执行；客户端时间戳设上下限；后写胜出。
- 删除账号改为原子操作、要求再次输入密码、删除磁盘上的传输文件。
- 越权：反馈接口校验归属、课程接口不再返回别人私有来源的教师事项；公共来源配置不再由第一个添加者决定。
- 每用户数量与请求体上限；管理接口加令牌；日志不再记录查询串里的令牌。

### 7.3 第 3 批：数据库与持久化（`d44cf11`）
- 每日备份（`deploy/backup/`、`devtools/backup.py`），2026-11-05 实测恢复后数据一致。
- 数据保留：邮件正文 30 天后清空；投递记录、幂等记录、事件、发信记录、过期验证码与会话、过期传输文件等定期清理。
- 补齐热点查询索引；扇出从每个订阅者约 10 次串行往返改为批量。
- 连接池（PostgreSQL 默认 4 条）替代“每进程一个连接 + 全局锁”；连接与语句超时；断线重连规则。
- 带版本号的迁移，失败回滚并中止启动（原来静默吞掉）；PostgreSQL 下用咨询锁串行化。
- 写入的原子性与唯一性交给数据库：公共来源唯一键、每人唯一的网页收藏来源、事务包裹多步写入。
- 凭据加密的密钥版本与轮换；生产环境未设密钥时告警或拒绝启动；过期会话凭据自动删除。
- CI 增加 PostgreSQL 任务；`GLEANER_TEST_PG` 让数据库测试可改跑 PostgreSQL。

### 7.4 第 4 批：大模型调用（`e082ab4`）
- 原来每次来源变化都会给全部未变的事项重新调用模型（结果随即丢弃）→ 先用规则比较，内容变了才调用。
- 异常响应（空 choices、null content、非 JSON）不再让整批采集结果丢失。
- 熔断（连续 3 次失败后冷却 60 秒）、429／5xx 有界重试并遵守 Retry-After、总时间预算。
- 防提示注入（正文与指令分离）、输出校验与清理、LRU 缓存、调用指标、记录模型与提示版本；拒绝把密钥发往明文 http 地址。

### 7.5 第 5 批：总线与模块调用（`e6a2914`）
- 慢处理阻塞 Hub 读循环、导致采集节点被误判下线 → 每成员收件箱 + 独立处理协程，收件箱满时不做心跳超时判定。
- 节点离线超过 60 秒后序号重来、去重表不清导致帧被全部丢弃 → 每个成员的会话号，变化时客户端清空去重表。
- 送达只保证到 ACK、入库失败的事项永远不会再入库 → 端到端确认：入库成功后才写入来源的内容哈希，否则下次重发。
- 无背压、发件箱无上限 → 高水位 drain、发件箱上限与丢弃计数。
- NODE_JOIN 无认证 → HMAC 认证、时间窗口与 nonce 防重放（`GLEANER_BUS_SECRET`）。
- 解压无上限、编码失败使心跳任务退出、重连后已取消的订阅恢复等。
- “立即检查”在没有采集节点时返回 202 并提示，不用 503（网关会把 503 算成 core 故障）。

## 8. 新产品基线（Campus Radar）的后端实现（2026-11-06）

组员在 11-01 至 11-03 把产品重新定义为 Campus Radar（插件勾选事项 → 本地后端 → Flutter 工作台）。本人负责其中后端部分的设计与实现。

### 8.1 设计（`d57e912`）
- 接口契约：[IC-001 插件 → 本地后端](../docs/architecture/IC-001-extension-to-backend.md)、[IC-002 本地后端 → 工作台](../docs/architecture/IC-002-backend-to-workbench.md)。
- [执行计划](../docs/exec-plans/2026-11-06-backend-r1-r3.md)（按组员提供的模板，含检验清单与完成证据）。
- 决策 D19–D25（`docs/decisions.md`），解决了待决问题 Q05、Q06 的后端部分：

| 编号 | 决定 |
| --- | --- |
| D19 | 事项身份 = 所有者 + 规范化页面网址 + 页内定位符 `locator` |
| D20 | 批量保存逐条返回结果，全部成功才报成功；请求不合法时整批拒绝 |
| D21 | 三种类型待办／日程／通知存为 `items.item_type`，插件建议优先，默认规则兜底，可替换 |
| D22 | 用户修改单独存表并记录修改时的来源值，来源更新不覆盖，变化后标冲突 |
| D23 | 按“用户 × 事项”记录监测状态；插件领取任务、回报结果；失败不更新最后成功时间 |
| D24 | 本地后端沿用账号登录与 Bearer 令牌，不新增云账户，不去掉鉴权 |
| D25 | LLM 需 `GLEANER_LLM_ENABLED=1` 显式开启，默认关闭 |

### 8.2 实现（`0bfc89a`）

| 功能 | 接口／位置 |
| --- | --- |
| 批量保存同页多条事项，逐条返回 `new`／`changed`／`unchanged`／`error` | `POST /api/captures` |
| 三种类型与状态（完成、已读、归档），按类型、状态、来源筛选 | `GET /api/feed?type=&status=&origin=`；`PUT /api/items/{id}/state` 新增 `done`、`archived` |
| 用户修改字段、恢复来源值、处理冲突 | `PATCH /api/items/{id}/fields`、`POST /api/items/{id}/fields/resolve` |
| 事项详情返回生效值、每个字段的修改明细、冲突列表、监测状态 | `GET /api/items/{id}` |
| 版本历史返回每版来源内容快照，供工作台显示差异 | `GET /api/items/{id}/versions` |
| 插件领取到期监测任务（租用 5 分钟）与回报结果；失败按次数退避 | `GET /api/monitor/due`、`POST /api/monitor/results` |
| 开关事项监测 | `PUT /api/items/{id}/monitor` |
| 数据库迁移 7：`items.item_type`、`user_item_state.archived_at`、`user_item_edits`、`item_monitors`，旧数据按规则回填，旧截止覆盖迁入用户修改 | `storage/migrations.py` |
| 截止提醒按用户修改后的截止时间 | `core/reminders.py` |
| LLM 显式开关 | `core/summarize.py` |
| 新模块 | `core/itemtypes.py`、`core/edits.py`、`core/monitor.py` |

兼容性：旧接口 `POST /api/clips` 保留；现有 Flutter 客户端忽略新字段，不受影响。测试 `tests/test_captures.py`（6 项）覆盖同页多事项、部分失败、整批拒绝、类型与状态筛选、用户修改与冲突、监测领取与失败、迁移回填。

## 9. 通信层补强（2026-11-09，`9927609`）

组员 11-07 提交的监测模块设计（IC-003）指出 HTTP 层的几处复用门槛，本人负责修复，并另外查出一个凭证泄露问题：

| 问题 | 修复 | 依据 |
| --- | --- | --- |
| 任何网站都能通过 `Domain` 属性给别的域名写 Cookie | Domain 必须与请求主机域匹配；拒绝顶级域、IP 上级域；明文响应不能设置或覆盖 Secure Cookie；拒绝控制字符；每域 50 条、总数 3,000 条上限；保存 SameSite | RFC 6265 §5.1.3、§5.3、§6.1 |
| 重定向到别的网站时仍携带 `Authorization`、`Cookie` 头（本人额外发现） | 跨源跳转时去掉凭证头与条件请求头（HTTP 客户端与抓取器两处） | RFC 9110 §15.4 |
| robots.txt 忽略 `Allow` 与通配符，`Disallow: /*.pdf` 不生效；取不到时当作全部允许 | 按分组、`Allow`、`*`／`$`、最长匹配解析；5xx 或网络错误时视为全部禁止，5 分钟后重取 | RFC 9309 |
| 重定向跳转与 robots.txt 请求不经过按主机限速 | 抓取器逐跳跟随重定向，所有请求共用同一个限速器 | IC-003 §6 |
| `Retry-After` 只识别秒数，且被截为 30 秒 | 支持 HTTP-date；长等待不缩短，记为该主机的最早访问时间，并推迟该来源的下次检查 | RFC 9110 §10.2.3 |
| 本地后端可被 DNS 重绑定的网页访问 | 网关 `GLEANER_ALLOWED_HOSTS` 白名单；CORS 支持 `http://localhost:*` 按端口通配，本地开发默认不再用 `*` | IC-003 §3.1 |

测试 `tests/test_fetch_compliance.py`（11 项），包括用真实套接字服务器验证重定向限速、凭证去除、Retry-After，以及启动真实网关验证 Host 白名单与 CORS。

## 10. 文档与协作

- 编写或维护的文档：`README.md`、`docs/protocols/` 下全部 8 份协议文档、`docs/database.md`、`docs/llm.md`、`docs/evaluation/README.md`、`docs/review-2026-11.md`、`docs/integrations/must-moodle.md`、旧版插件说明（现归档为 `docs/archive/browser-extension-2026-10-26.md`；现行 `docs/browser-extension.md` 由组员改写，本人补充了新接口就绪说明）、IC-001、IC-002、后端执行计划、决策 D9／D14／D19–D25 等。
- 合并组员工作：前端改版（`20a6e32`）；组员的产品定义与文档整理（`d798dba`，解决 `open-questions.md` 冲突，保留组员的新结构并补充本人 11-05 的确认记录）。
- 发现并记录团队待决问题 Q09：监测模块架构文档第 4 节“暂时不按 `CLAUDE.md`、使用现成网络库”与 `CLAUDE.md` 的禁用库规定、IC-003 第 1 节冲突，待组长确认。
- 在 IC-003 第 10 节补充了三项复用门槛的修复状态。

## 11. 尚未完成、需要其他组员配合的部分

| 事项 | 负责方 |
| --- | --- |
| 插件改用 `POST /api/captures`，为各页面类型给出稳定 `locator`，逐条显示结果；Spike 02 验证后实现后台监测调度 | 插件负责人 |
| 工作台显示类型、状态、冲突与监测状态，显示版本差异 | 工作台负责人 |
| 替换默认分类规则 | 分类负责人 |
| IC-003 监测模块本身（会话桥接、调度、站点适配器）及 Cookie 导入的站点白名单 | 监测模块负责人 |
| Q09 冲突的决定；MUST 授权书面材料（Q08） | 组长 |

上述完成前，里程碑 R1–R3 仍为“待核验”，产品定义的验收场景 A、B、C 尚未端到端运行。课程方面，云证书、CI 部署、真实用户（旧 M10）、跨机器扩容与 Wireshark 抓包仍未完成。

## 附：复核命令

```bash
git log --author=GuanChenhao323 --oneline            # 本人提交
git shortlog -sn                                     # 各成员提交数
git log --author=GuanChenhao323 --no-merges --shortstat --format= \
  | awk '{f+=$1; i+=$4; d+=$6} END {print f, i, d}'  # 文件次、新增、删除
cd server && pytest -q && ruff check . && ruff format --check .
```
