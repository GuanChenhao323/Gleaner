# 决策记录

open-questions 中由组长拍板的事项记在这里：决定内容、原因、落地位置。

## 2026-10-22 · A 组（组长决定）

| # | 问题 | 决定 | 落地 |
| --- | --- | --- | --- |
| 1 | 提交方式 | 按里程碑拆分 commit（不区分成员） | git 历史重写为 M1–M7 若干提交 |
| 2 | 事件循环 | 推送节点接入层改为手写反应器；网关保留 asyncio | `server/gleaner/net/reactor.py`（selectors：epoll / poll / select 可切换）、`net/websocket/reactor_server.py`；`GLEANER_PUSH_IO=reactor\|asyncio`、`GLEANER_PUSH_SELECTOR=auto\|epoll\|poll\|select`；测试 `tests/test_reactor.py` |
| 3 | 采集调度 | 维持去中心化分配：Hub 汇总心跳并广播 `$nodes`，各采集节点用一致性哈希自行认领来源 | 代码不变；proposal 分工表与技术方案 7 已注明 |
| 4 | 低优先级通知 | 也经 WebSocket 实时推送，但带 `silent: true`，不弹提醒、不发 MQTT | `core/pipeline.py`；测试 `test_low_priority_delivery_is_pushed_silently` |
| 5 | 邮箱口令 | 加密保存应用专用密码（AES-GCM），界面与隐私说明明确要求用应用专用密码 | 注册页、设置页隐私说明；来源登录对话框 |
| 6 | 注册验证 | 任意邮箱 + 6 位验证码（自研 SMTP 经平台账号发送；10 分钟有效、60 秒限频、错 5 次作废、一次性） | `POST /api/auth/code`、注册校验；`GLEANER_REQUIRE_EMAIL_CODE`；测试 `test_register_requires_email_code` |
| 7 | 大模型 | 默认 OpenAI 兼容接口，接国内服务商；地址、模型、密钥三项齐全才启用，否则规则提取 | `core/summarize.py`、`deploy/.env.example`；测试 `tests/test_summarize.py` |
| 8 | 摘要邮件 | 增加可选邮件版，默认关闭，用户在设置里打开 | `users.digest_email`、`core/reminders.py`、设置页开关；测试 `test_digest_email_is_opt_in` |

## 2026-10-23 · compose 实测后（组长确认）

| # | 问题 | 决定 | 落地 |
| --- | --- | --- | --- |
| 9 | 个人来源的事项归属 | 个人来源（Moodle、个人邮箱）的事项按所有者各存一份，只与本人或公共来源（学院通知、教师页）的事项合并，不会并进别人的事项；公共来源仍全员共享一份。接受同一门课的作业有几个人登录就存几份 | `core/pipeline.py: _scope`（身份键与别名键加 `@<uid>/` 前缀）、`storage/schema.py` 迁移补齐已有数据；测试 `test_personal_sources_are_scoped_per_user`、`test_migration_scopes_existing_personal_keys` |

起因：compose 实测发现第二个同学登录同一个 Moodle 后看不到作业（身份键全局唯一），且按链接合并时个人邮件可能并进别人的事项。

## 2026-10-26 · 真实平台接入（组长决定）

| # | 问题 | 决定 | 落地 |
| --- | --- | --- | --- |
| 10 | 真实平台接入范围与顺序 | 在 P0–P2 之外新增真实平台接入（M11）。先接澳门科技大学（MUST）Moodle，之后视情况接飞书、X、Facebook | `docs/integrations/`；`docs/milestones.md` M11 |
| 11 | 访问真实学校系统的规则 | 只对 MUST Moodle 开放，且必须先取得书面授权并登记；只用登记的测试账号，登录由组员本人完成；只读、限速、遵守 robots；真实数据不入库；自动化测试与 CI 仍只连 fake_moodle | `CLAUDE.md`“工作方式”；`docs/integrations/must-moodle.md`；授权未登记时 `devtools/must_moodle_probe.py` 拒绝运行 |

### 仍需提供的信息

- 平台发信账号（SMTP 服务器、端口、账号、授权码）：验证码、摘要邮件、告警都用它。开发期发到本地假邮件服务器。
- 大模型服务商、接口地址、模型名与密钥。
- MUST Moodle：地址、测试账号（只登记账号名）、学校书面授权（填写 `docs/integrations/must-moodle.md` 第 1 节）。
