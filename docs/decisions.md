# 决策记录

记录决定、原因、适用范围及替代关系。当前产品以 [产品定义](product-definition.md) 为准。

## 2026-11-03 · 当前有效范围决策

| 编号 | 决定 | 替代关系与落地 |
| --- | --- | --- |
| D16 | 新产品定义取代旧产品范围；课程技术交付独立保留 | 旧提案及旧 M1–M12 不再定义当前或最终产品交付；见产品定义、提案与新里程碑 R0–R4 |
| D17 | 自动结构化与分类为 P0，优先插件与程序；效果不足才考虑 LLM | 替代旧第 7 条模型策略；先评估程序方案质量 |
| D18 | 产品名称沿用当前基线 Campus Radar，Gleaner／拾课作为仓库及历史实现名称 | 保留代码包、配置键和协议标识；不执行代码重命名 |

## 2026-11-06 · 后端实施设计（后端负责人确认）

由负责 HTTP API、数据库、LLM 调用与模块通信的组员确认，解决 Q05 及 Q06 的后端部分。接口细节见 [IC-001](architecture/IC-001-extension-to-backend.md)、[IC-002](architecture/IC-002-backend-to-workbench.md)，实施计划见 [执行计划](exec-plans/2026-11-06-backend-r1-r3.md)。分类规则、插件页面识别和 Flutter 界面仍由对应负责人决定，下列决定只约定数据和接口。

| 编号 | 决定 | 原因与落地 |
| --- | --- | --- |
| D19 | 事项身份 = 所有者 + 规范化页面网址 + 页内定位符 `locator`。定位符由插件适配器给出（如 Moodle `cmid:123`、DOM 元素 id）；没有稳定标识时用规范化标题的哈希 `t:<前 12 位>` | 一个网页可以有多条事项（产品定义第 6 节）。同一定位符再次采集是同一事项，内容变了记新版本，不新建记录。旧 `POST /api/clips` 保留，相当于定位符为空的整页事项 |
| D20 | 批量保存逐条返回结果：每条 `new`／`changed`／`unchanged`／`error`；整批顶层 `ok` 只有全部成功才为 true。单条失败不影响其他条，不虚报成功 | US02。请求本身不合法（网址、条数、重复定位符）整批返回 4xx，什么都不保存 |
| D21 | 三种信息类型 `todo`／`event`／`notice` 存为 `items.item_type`（来源侧判定），用户可改。旧类型映射：`assignment` → `todo`，其余 → `notice`。插件给出的类型优先；没给时后端用最小默认规则（有活动时间 → 日程，有截止时间 → 待办，否则通知），规则可由分类负责人替换 | 状态：待办 = `todo_status` 是否为 `done`；通知 = `read_at`；日程新增 `archived_at`。原有 `todo` 三态、已读、收藏、隐藏照常可用 |
| D22 | 用户修改单独存一张表 `user_item_edits`，每个字段一行，同时记下修改时的来源值 `base`。来源更新只写 `items`，从不改这张表。来源值与 `base` 不同时标为冲突，两边都返回；用户选择“保留我的”或“采用来源”后冲突消失 | 产品定义 2.4 节。可修改字段：标题、摘要、类型、截止时间、开始／结束时间、地点、要求。旧的 `deadline_override` 视为截止时间的用户修改，继续兼容 |
| D23 | 监测状态按“用户 × 事项”记录在 `item_monitors`：是否支持、是否启用、间隔、最后检查与最后成功时间、最近结果、错误码。插件采集的事项由插件按 `GET /api/monitor/due` 领取到期任务、在浏览器里重新获取后回报 `POST /api/monitor/results`；后端比较内容并记版本。失败不更新最后成功时间，也不显示成无变化 | 方案 A 以 Chrome 运行为前提，登录后的 Moodle 页面只有浏览器能取（Spike 02 验证）。插件未声明 `supported` 的事项显示“暂不支持监测”。订阅来源的事项沿用服务端采集，监测状态取自来源 |
| D24 | P0 本地后端沿用现有账号登录与 Bearer 令牌（含会话吊销、令牌版本），插件只对用户填写的后端地址申请权限；会话失效统一返回 401，插件与工作台提示重新登录。不新增云账户功能，也不去掉鉴权 | Q06 的后端部分。即使只在本机运行，监听端口仍可能被同机其他程序访问；插件权限、会话体验的前端细节由插件负责人跟进 |
| D25 | LLM 需显式打开：`GLEANER_LLM_ENABLED=1` 且三项配置齐全才调用；默认关闭 | D17 与产品定义 2.5 节：具备模型配置不代表自动启用 |

## 技术实现决策

以下决定仍供协议开发、排障和课程验证使用，保留原编号。已结束的提交安排、被替代的模型策略、旧平台接入计划和旧插件流程已移至 [归档](archive/superseded-decisions.md)。

### 2026-10-22 · A 组（组长决定）

| # | 问题 | 决定 | 落地 |
| --- | --- | --- | --- |
| 2 | 事件循环 | 推送节点接入层改为手写反应器；网关保留 asyncio | `server/gleaner/net/reactor.py`（selectors：epoll / poll / select 可切换）、`net/websocket/reactor_server.py`；`GLEANER_PUSH_IO=reactor\|asyncio`、`GLEANER_PUSH_SELECTOR=auto\|epoll\|poll\|select`；测试 `tests/test_reactor.py` |
| 3 | 采集调度 | 维持去中心化分配：Hub 汇总心跳并广播 `$nodes`，各采集节点用一致性哈希自行认领来源 | 代码不变；旧 proposal 分工表与技术方案 7 已注明（见归档） |
| 4 | 低优先级通知 | 也经 WebSocket 实时推送，但带 `silent: true`，不弹提醒、不发 MQTT | `core/pipeline.py`；测试 `test_low_priority_delivery_is_pushed_silently` |
| 5 | 邮箱口令 | 加密保存应用专用密码（AES-GCM），界面与隐私说明明确要求用应用专用密码 | 注册页、设置页隐私说明；来源登录对话框 |
| 6 | 注册验证 | 任意邮箱 + 6 位验证码（自研 SMTP 经平台账号发送；10 分钟有效、60 秒限频、错 5 次作废、一次性） | `POST /api/auth/code`、注册校验；`GLEANER_REQUIRE_EMAIL_CODE`；测试 `test_register_requires_email_code` |
| 8 | 摘要邮件 | 增加可选邮件版，默认关闭，用户在设置里打开 | `users.digest_email`、`core/reminders.py`、设置页开关；测试 `test_digest_email_is_opt_in` |

### 2026-10-23 · compose 实测后（组长确认）

| # | 问题 | 决定 | 落地 |
| --- | --- | --- | --- |
| 9 | 个人来源的事项归属 | 个人来源（Moodle、个人邮箱）的事项按所有者各存一份，只与本人或公共来源（学院通知、教师页）的事项合并，不会并进别人的事项；公共来源仍全员共享一份。接受同一门课的作业有几个人登录就存几份 | `core/pipeline.py: _scope`（身份键与别名键加 `@<uid>/` 前缀）、`storage/schema.py` 迁移补齐已有数据；测试 `test_personal_sources_are_scoped_per_user`、`test_migration_scopes_existing_personal_keys` |

起因：compose 实测发现第二个同学登录同一个 Moodle 后看不到作业（身份键全局唯一），且按链接合并时个人邮件可能并进别人的事项。

### 2026-10-26 · 真实平台接入（组长决定）

| # | 问题 | 决定 | 落地 |
| --- | --- | --- | --- |
| 11 | 访问真实学校系统的规则 | 只对 MUST Moodle 开放，且必须先取得书面授权并登记；只用登记的测试账号，登录由组员本人完成；只读、限速、遵守 robots；真实数据不入库；自动化测试与 CI 仍只连 fake_moodle | `CLAUDE.md`“真实平台访问”；`docs/integrations/must-moodle.md`；授权未登记时 `devtools/must_moodle_probe.py` 拒绝运行 |
| 14 | MUST Moodle 登录方式 | 方案 A：用户粘贴 Moodle 安全密钥（偏好设置 → 安全密钥 → Moodle mobile web service），拾课不经手统一认证密码；Moodle 来源的登录框默认用这种方式，仍保留账号密码方式给非统一认证的站点 | `POST /api/sources/{id}/login` 的 `token` 字段；`collector/session.py: moodle_token_session`；客户端登录框；测试 `test_moodle_login_with_pasted_security_key` |
