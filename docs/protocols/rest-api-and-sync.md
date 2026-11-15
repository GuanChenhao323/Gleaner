# REST API、投递与离线同步

实现：`server/gleaner/core/api.py`、`pipeline.py`、`client/lib/core/store.dart`。

## 1. 鉴权

`POST /api/auth/login` 返回 `{token, user}`，同时设置 HttpOnly Cookie `gl_session`。
令牌 = `base64url(JSON{uid, tv, exp}).base64url(HMAC-SHA256)`；网关、推送节点用共享密钥本地验证，无需查库。
`tv`（token_version）递增即可让所有设备下线。

## 2. 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /api/auth/code | 发送注册验证码（6 位，10 分钟有效，60 秒内只发一次） |
| POST | /api/auth/register · /login · /logout | 注册（需验证码、同意隐私说明）、登录、退出（`all_devices`） |
| GET / PUT | /api/me | 资料、免打扰、摘要时间、课程；返回 MQTT 口令 |
| DELETE | /api/account | 删除账号与全部数据 |
| GET | /api/feed?cursor=&kind=&filter=&q=&limit= | 收件箱，键集分页（cursor = `排序时间:id`） |
| GET | /api/sync?cursor= | seq 大于 cursor 的投递，每次最多 500 条 |
| GET | /api/items/{id} · /versions | 详情（含正文）、修改历史 |
| PUT | /api/items/{id}/state | 已读 / 收藏 / 待办 / 隐藏 / 修正截止 / 备注（`Idempotency-Key`） |
| POST | /api/state/batch | 离线操作队列按顺序回放 |
| POST | /api/items/{id}/feedback | “不重要”：降低来源权重 |
| GET | /api/deadlines?from=&to= | 日历数据 |
| GET | /api/courses | 课程主页（作业、通知、教师信息） |
| GET | /api/templates | 校园模板 |
| GET / POST | /api/sources | 我的来源（含状态、304 命中率）/ 添加（模板或自定义网址，可 `via_agent`） |
| POST | /api/sources/preview | 首次采集预览（不保存） |
| PUT / DELETE | /api/sources/{id} | 权重、静音、名称 / 取消订阅 |
| POST | /api/clips | 浏览器插件“保存到收件箱”：`{url, title, text}`，进入个人来源“网页收藏”；同一网址再存记新版本（旧接口；当前多事项选择流程的迁移差距见 [插件说明](../browser-extension.md)） |
| POST | /api/sources/{id}/login · /refresh | 登录来源（只保存会话）/ 立即检查。请求体 `{username, password}`；Moodle 还可以用 `{token}`（用户从“偏好设置 → 安全密钥”复制的 32 位密钥，用于统一认证学校：先用 `core_webservice_get_site_info` 校验，格式错 422、无效 401） |
| POST | /api/mail/send | 经已连接邮箱发信（`Idempotency-Key`） |
| GET | /api/mail/sent | 发信记录 |
| GET / PUT | /api/dashboard · /api/rules | 看板布局、个性化规则 |
| * | /api/transfer/... | 扫码传输（见 transfer-and-agent.md） |
| GET | /api/stats | 运营指标：用户数、日活、人均订阅、不重要比例、打开率 |
| GET | /health · /metrics | 健康检查、Prometheus 指标 |

错误统一为 `{"error": 代码, "message": 中文说明}`。

## 3. 注册验证码

`POST /api/auth/code {email}` 生成 6 位数字，只保存 `HMAC(secret, email:code)`，经平台发信账号用自研 SMTP 发出。
有效期 10 分钟；同一邮箱 60 秒内重复请求返回 429 与 `Retry-After`；连续错 5 次作废；注册成功后立即删除（一次性）。
`GLEANER_REQUIRE_EMAIL_CODE=0` 可关闭校验（仅限测试）。

## 4. 投递序号 seq

每条投递在事务内执行 `UPDATE users SET next_seq = next_seq + 1` 分配用户内单调递增的 seq，写入 `deliveries`。
- 分数 ≥ 80：WebSocket + MQTT（QoS 1）；40–79：WebSocket；< 40：WebSocket，带 `silent: true` 不提醒。
- 免打扰时段内非紧急投递带 `silent: true`，客户端不弹提醒。
- 重要变更至少普通级；距截止不足 7 天升为紧急。

## 5. 客户端同步（离线优先）

1. 启动先读本地 drift 数据库（Web 端 SQLite-WASM，存储在 OPFS / IndexedDB），立即可浏览。
2. 首次（cursor = 0）分页拉取 `/api/feed`，记下 `sync_cursor`。
3. WebSocket `hello{last_seq: cursor}`，推送节点补发期间的投递，然后实时推送；收到消息更新本地库与游标，0.4 s 合并 ACK。
4. 发现 seq 缺口（如背压丢弃）或收到 `resync_hint` 时调用 `/api/sync`。
5. 个人状态乐观更新：写本地库 + 写入离线操作队列（每个操作一个 UUID 幂等键）→ 在线时立即 PUT；
   离线时保留，重连 `welcome` 后 `/api/state/batch` 按顺序回放，服务端按幂等键去重，重复提交不会产生副作用。
6. 冲突：个人状态以最后修改时间为准（客户端带操作时间 `ts`，比服务器上的更旧则不覆盖）；来源内容以服务端最新版本为准。
7. 断线：指数退避 1 s → 30 s 加抖动重连；界面左下角圆点显示 在线 / 连接中 / 离线（含待同步操作数）。


## 浏览器事项采集与任务 v1（2026-11-05）

已实现的权威数据契约为 [IC-BROWSER-001](../architecture/browser-capture-v1.md)，实现 `server/gleaner/core/monitors.py`，由 Core 注册到既有自研 HTTP 网关。`POST /api/v1/captures` 接收所选目标，按 owner/request_id 幂等并逐项返回关联 item/monitor；`GET /api/v1/captures/{request_id}` 查询持久回执。`GET /api/v1/monitors` 与 `PUT/DELETE /api/v1/monitors/{id}` 负责列表／暂停／停止；`POST /api/v1/monitors/{id}/check` 请求检查，`GET .../checks` 查询检查记录。

Chrome 通过 `POST /api/v1/monitor-jobs/claim` 领取后端计划中的一项租约任务，向 `POST /api/v1/monitor-jobs/{id}/result` 提交并确认结果。当前只支持主 frame；认证来源由 Chrome 原会话重入，不把学校密码／Cookie 发给服务端，也不让 Python collector 同时调度 browser 来源。所有 v1 成功响应含 schema_version=1、ok=true，逐项结果／租约另校验；401 鉴权错误沿用原 API 格式，其他契约错误非 2xx。历史 `/api/clips` 与 `/api/sources` 保持兼容，新扩展不再用互不关联的 clip/page 流程。

事项详情额外返回 `browser_monitor` 和 `source_fields`；版本 changed 字典可含 `source_fields` 的前后值。个人 note/deadline_override 继续经原 `/api/items/{id}/state` 管理，不随来源覆盖。新注册账号不再自动订阅公共演示来源；演示 seed 仍显式创建演示订阅。

2026-11-11：[条件先行读取／预览契约 v2](../architecture/page-extraction-v1.md)，读取／预览不调用网络保存接口。只有明确保存才走上述 captures，recipe.version=2、strategy=snapshot 表示仅快照保存，后端强制 supported=false、enabled=false，不进入调度。v1 recipe 与信封 schema_version=1 保持兼容；recipe 改变仍需显式重绑，未自动迁移。事项详情中的监测布尔字段不再返回数据库整数。

2026-11-14：[通用 DOM 资料契约](../architecture/universal-web-capture-v1.md) 增加 POST `/api/v1/web-captures`、GET `/api/v1/web-captures/{request_id}`、GET `/api/v1/web-captures`。整组片段作为一份资料，按 owner＋来源标签＋URL＋条件＋范围合并，明确保存后更新版本，不产生监测配置。信封 schema_version=1，提交回执的 candidate_ids 必须覆盖全部片段，results 恰有一项集合结果；读取回执仅对 owner 可见。事项字段 `web_capture` 提供来源、条件、范围、片段及依据，兼容旧事项的 null。资料列表返回当前 owner 最近100份的摘要，不返回片段正文。


## 原条件来源与 Chrome 检查（2026-11-15）

[IC-READING-SOURCE-001](../architecture/condition-monitoring-v1.md) 在既有两类保存接口兼容增加可选 `reading`，事务关联 `reading_source_id`；缺省继续旧语义。GET `/api/v1/reading-sources`、PUT `.../{id}` 管理原条件来源；POST `.../{id}/check` 排队 verify/check，GET `.../{id}/checks` 读日志；POST `/api/v1/reading-devices/heartbeat`、`/api/v1/reading-jobs/claim`、`.../{id}/result` 负责同 owner 设备心跳、180秒租约和严格确认。

默认手动，验证后可启用1800／3600／7200秒周期，暂停仍可单次。验证不更新内容基线或成功检查时间；检查变化复用已有保存服务关联原资料／版本。重复上报幂等，配置修订撤销旧租约，已删除来源不自动复活。原生 v2 snapshot 与旧 v1 计划不迁移；学校 Cookie／密码不传到本接口。来源、设备与资料均按当前 owner 隔离。

### Timeline 活动摘要集合（2026-11-16）

POST `/api/v1/timeline-captures`，GET同路径列表及 `/{request_id}` 回执。Bearer与schema_version=1／ok信封沿用集合保存；专用来源账号和summary字段严格校验，强制原条件关联，返回capture_type=timeline_summary及一个collection结果。与captures原生事项、web-captures通用快照分开。后台沿reading-sources租约及representation重读，失败保护不变。完整字段、身份和兼容见 [Timeline 摘要契约](../architecture/timeline-summary-v1.md)。
