# REST API、投递与离线同步

实现：`server/gleaner/core/api.py`、`pipeline.py`、`client/lib/core/store.dart`。

## 1. 鉴权

`POST /api/auth/login` 返回 `{token, user}`，同时设置 HttpOnly Cookie `gl_session`（SameSite=Lax；经 HTTPS 访问或 `GLEANER_COOKIE_SECURE=1` 时加 Secure）。
令牌 = `base64url(JSON{uid, tv, sid, exp}).base64url(HMAC-SHA256)`；网关、推送节点用共享密钥本地验证，无需查库。

- **会话**：每次登录在 `sessions` 表建一条记录，令牌带会话 id `sid`。core 校验会话未被吊销，所以可以按设备退出、
  在 `/api/me/sessions` 查看与吊销。`tv`（token_version）递增让所有设备下线（退出全部设备、修改 / 重置密码）。
- **防爆破**：同一邮箱 15 分钟内失败 5 次、同一 IP 失败 30 次后返回 429（`Retry-After`），封禁时间逐次翻倍；
  邮箱不存在时同样做一次密码哈希校验，响应时间不泄露是否注册。验证码每个 IP 每小时最多发 10 封，错 5 次作废（原子计数）。
- **CSRF**：只凭 Cookie 鉴权的修改请求，请求体必须是 `application/json`（否则 415）；没有请求体时 `Origin` 必须与 Host 一致（否则 403）。
  Bearer 令牌（客户端默认）不受影响。

### 错误格式

所有 4xx / 5xx 都是 `{"error": "<机器可读代码>", "message": "<给用户看的说明>"}`。参数校验统一在 `core/validate.py`：
坏 JSON 400 `bad_json`、请求体不是对象 400 `bad_body`、字段类型或范围不对 422 `invalid`、路径 id 不是数字 404。
校验失败绝不返回 500——网关把 502/503/504 记为上游故障，业务 4xx/5xx 不会让 core 节点被摘除。

## 2. 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /api/auth/code | 发送注册验证码（6 位，10 分钟有效，60 秒内只发一次） |
| POST | /api/auth/register · /login · /logout | 注册（需验证码，`agree_privacy` 必须为 true）、登录、退出当前设备（`all_devices: true` 退出全部） |
| POST | /api/auth/reset/code · /api/auth/reset | 找回密码：向注册邮箱发验证码（邮箱未注册也返回成功）；`{email, code, new_password}` 重置，所有设备重新登录 |
| GET / PUT | /api/me | 资料、免打扰、摘要时间（HH:MM，00:00–23:59）、课程；返回 MQTT 口令 |
| PUT | /api/me/password | `{old_password, new_password}`；其他设备全部退出，返回当前设备的新令牌 |
| GET / DELETE | /api/me/sessions · /api/me/sessions/{id} | 已登录设备列表（标出当前设备）/ 吊销某个设备 |
| DELETE | /api/account | 删除账号与全部数据（请求体 `{password}` 再次确认；含磁盘上的传输文件与 Broker 会话） |
| GET | /api/feed?cursor=&kind=&filter=&q=&limit= | 收件箱，键集分页（cursor = `排序时间:id`） |
| GET | /api/sync?cursor= | seq 大于 cursor 的投递，每次最多 500 条 |
| GET | /api/items/{id} · /versions | 详情（含正文）、修改历史 |
| PUT | /api/items/{id}/state | 已读 / 收藏 / 待办 / 隐藏 / 修正截止 / 备注（`Idempotency-Key`；同一个键换了内容返回 422 `idempotency_mismatch`） |
| POST | /api/state/batch | 离线操作队列按顺序回放；每条单独返回 `status`，坏操作不影响其他操作；超过 500 条时 `truncated: true` |
| POST | /api/items/{id}/feedback | “不重要”：降低来源权重 |
| GET | /api/deadlines?from=&to= | 日历数据 |
| GET | /api/courses | 课程主页（作业、通知、教师信息） |
| GET | /api/templates | 校园模板 |
| GET / POST | /api/sources | 我的来源（含状态、304 命中率）/ 添加（模板或自定义网址，可 `via_agent`；复用已有公共来源时 `reused: true`；每人最多 200 个） |
| POST | /api/sources/preview | 首次采集预览（不保存）；失败 422，`error` 为 `fetch_<原因>`（内网地址为 `fetch_blocked`） |
| PUT / DELETE | /api/sources/{id} | 权重、静音、名称 / 取消订阅 |
| POST | /api/clips | 浏览器插件“保存到收件箱”：`{url, title, text}`，进入个人来源“网页收藏”；同一网址再存记新版本（旧接口；当前多事项选择流程的迁移差距见 [插件说明](../browser-extension.md)） |
| POST | /api/sources/{id}/login · /refresh | 登录来源（只保存会话）/ 立即检查。请求体 `{username, password}`；Moodle 还可以用 `{token}`（用户从“偏好设置 → 安全密钥”复制的 32 位密钥，用于统一认证学校：先用 `core_webservice_get_site_info` 校验，格式错 422、无效 401） |
| POST | /api/mail/send | 经已连接邮箱发信（`Idempotency-Key`） |
| GET | /api/mail/sent | 发信记录 |
| GET / PUT | /api/dashboard · /api/rules | 看板布局、个性化规则 |
| * | /api/transfer/... | 扫码传输（见 transfer-and-agent.md） |
| GET | /api/stats | 运营指标：用户数、日活、人均订阅、不重要比例、打开率（需要请求头 `X-Admin-Token` = `GLEANER_ADMIN_TOKEN`，缓存 60 秒） |
| GET | /health · /metrics | 健康检查、Prometheus 指标 |

错误统一为 `{"error": 代码, "message": 中文说明}`。

### 出站访问（防 SSRF）

预览、采集、自填 IMAP / POP3 / SMTP 主机都只允许连接公网地址（`net/egress.py`）：先解析主机名，拒绝回环、私有、链路本地等地址，
再直接连接解析出的 IP（防 DNS 重绑定）。本地开发与测试设 `GLEANER_EGRESS_ALLOW_PRIVATE=1`；compose 用
`GLEANER_EGRESS_ALLOW_HOSTS=fake_moodle,greenmail` 按主机名放行测试服务。本地采集代理（`agent/`）运行在用户电脑上，不受此限制。
公共来源不能“登录”，“立即检查”60 秒内只受理一次（大家共用，防止被用来刷第三方网站）。

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
