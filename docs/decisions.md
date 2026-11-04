# 决策记录

记录决定、原因、适用范围及替代关系。当前产品以 [产品定义](product-definition.md) 为准。

## 2026-11-03 · 当前有效范围决策

| 编号 | 决定 | 替代关系与落地 |
| --- | --- | --- |
| D16 | 新产品定义取代旧产品范围；课程技术交付独立保留 | 旧提案及旧 M1–M12 不再定义当前或最终产品交付；见产品定义、提案与新里程碑 R0–R4 |
| D17 | 自动结构化与分类为 P0，优先插件与程序；效果不足才考虑 LLM | 替代旧第 7 条模型策略；先评估程序方案质量 |
| D18 | 产品名称沿用当前基线 Campus Radar，Gleaner／拾课作为仓库及历史实现名称 | 保留代码包、配置键和协议标识；不执行代码重命名 |

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
