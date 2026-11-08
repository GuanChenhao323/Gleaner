# IC-003｜本地监测模块接口契约

版本：0.1.0 · 2026-11-07 · 状态：提议，尚未实现。  
适用：Chrome 会话桥接、后端监测执行器、现有 Capture / Extractor / Item Service。  
机器可读 HTTP 定义：[`../protocols/monitoring-v1.openapi.yaml`](../protocols/monitoring-v1.openapi.yaml)。本文定义跨字段约束、内部交接与迁移；字段类型以 OpenAPI 为准，任何冲突均阻止实现验收。

## 1. 边界与前提

- V1 使用 Chrome 正常登录后的授权 Moodle 会话；Python 后端执行只读 HTTPS GET。没有 CAS 自动登录、密码保存、中央认证 Cookie 导出或云端转存。
- V1 只重新检查已保存的事项。新增条目发现、YouTube / RSS / OAuth 接入为扩展方向，不因接口存在而默认启用。`watch_mode` 当前只接受 `selected_items`。
- 认证、传输和站点解析独立。`browser_cookie` 是当前认证实现；公开网页可用 `none`。其他模式需新增契约版本及测试。
- 尊重 `CLAUDE.md` 的自研网络约束：生产流量使用 `server/gleaner/net/http/`；不引入 requests/httpx/FastAPI。复用必须先通过第 10 节安全验收。
- 用户提供的 2026-11-07 实测材料支持 MUST Moodle `sessiontimeout=7200`，指定课程 GET 更新服务端最后访问时间。材料中的匿名 MoodleSession 无 Expires/Max-Age；不能把 7200 写成 Cookie TTL，也不能推定所有路径、304 或无限持续续期都成立。跨 2 小时端到端验证仍为发布门槛。
- 本契约补充 IC-001 / IC-002。现有接口继续工作；新监测执行方式通过特性开关逐项迁移。本次文档提交不宣称端点已经上线，不更改产品需求基线。

## 2. 模块与交付责任

| 参与者 | 输入与输出 | 明确不负责 |
|---|---|---|
| B：Chrome 插件 | 用户同意后读取指定站点 Cookie；发送本地在线心跳；继续按 IC-001 采集 | 长时间任务调度、业务版本判断、导出密码或无关 Cookie |
| A：监测模块（本契约） | 来源登记、会话管理、调度、HTTP 获取、认证识别、故障分类；输出观察批次 | 自动修改用户字段、创建 deadline 提醒、全站爬取 |
| C：本地后端 | 本地鉴权、HTTP 路由、存储事务；保存事项后登记监测目标；连接既有提取流水线 | 把任意 URL 当作已获授权来源 |
| D：Extractor / Item Service | 字段抽取、事项身份匹配、业务差异、版本、用户覆盖和幂等应用 | 直接拿 Cookie 或自行重试网络 |
| E：Flutter 工作台 | 沿用 IC-002，显示最后成功检查时间、错误与暂停原因 | 读取网站 Cookie、把检查失败显示成无变化 |

这里是逻辑边界；A/C/D 可运行在同一个本地进程中，不要求新增网络服务。

## 3. 通信与安全约束

### 3.1 本地控制接口

前缀：`http://127.0.0.1:8080/api/monitor/v1`。仅监听回环；服务器地址只允许预先配置的本机地址，不能把凭证接口代理到远程主机。

全部接口复用已有 `Authorization: Bearer <local-backend-token>`；该令牌来自已有本地后端登录流程，与 Moodle Cookie 完全分离。所有资源从令牌推导 owner，禁止接受客户端自报 owner。

Cookie 写入和撤销仅允许已登记扩展的精确 `Origin: chrome-extension://<id>`，且上下文绑定该扩展安装实例和 Cookie Store。浏览器 Origin 缺失、null 或不在白名单时拒绝这些敏感操作。Origin 是额外校验，不能替代令牌鉴权。Flutter 原生调用其他控制端点可无 Origin，但必须有令牌。

必须校验 Host、来源 Origin、Content-Type、资源所有权、扩展实例绑定和请求体大小；CORS 不使用 `*`。OPTIONS 只响应允许的来源与头，不能泄露数据。Cookie 导入请求体最多 256 KiB，其他 JSON 请求最多 2 MiB。所有响应 `Cache-Control: no-store`。错误日志不包含 Authorization、Cookie、Set-Cookie、密码、CAS ticket 或完整 HTML。

扩展使用 service worker 发起本地请求；content script 不能读取凭证或调用任意 URL 代理。新增 `cookies` 和站点 host 权限需在明确同意后申请；原 IC-001 “不读 Cookie”约束只对这一经授权的桥接操作作受控扩展，普通采集路径保持不读 Cookie。不得申请整个学校域或 Google 全域 Cookie 权限。

### 3.2 幂等、时间和并发

时间统一为 UTC Unix 秒，null 表示未知；本地计时与租约有效性使用 monotonic clock，持久化截止时间使用 UTC，恢复时重新计算。

创建资源、导入 Cookie、手动检查必须带 `Idempotency-Key`（UUID）。作用域为 owner + method + path + key；同一键不同请求返回 `409 idempotency_conflict`。普通控制操作保留去重记录 24 小时；凭证导入的去重记录仅驻内存，绑定 `backend_epoch`，只保存 HMAC 摘要及脱敏响应，不保存请求体。

`expected_revision` 用于乐观并发控制，冲突返回 `409 revision_conflict`，不覆盖新状态。Cookie 撤销使用查询参数 `expected_revision`，避免 DELETE 请求体互通问题。撤销后执行中的旧请求不得恢复凭证或提交旧观察。

所有创建、回报和应用都以“至少一次 + 幂等”处理；不得宣称 exactly-once 网络投递。

## 4. HTTP 接口清单与语义

| 方法 / 路径（相对前缀） | 调用者 | 成功 | 行为 |
|---|---|---|---|
| GET `/capabilities` | B/C/E | 200 | 返回协议版本、后端启动 epoch、已安装适配器与真实能力 |
| PUT `/bridges/{bridge_id}/presence` | B | 200 | 注册/续期在线租约；不触发网站保活 |
| POST `/auth-contexts` | B | 201 | 创建指定 site/profile/store 的空认证上下文 |
| GET `/auth-contexts/{auth_id}` | B/E | 200 | 只返回状态与版本，永不返回 Cookie 值 |
| PUT `/auth-contexts/{auth_id}/cookies` | B | 202 | 原子接收候选 Cookie 快照；等待调度器验证，不等于登录有效 |
| DELETE `/auth-contexts/{auth_id}/cookies` | B | 204 | 本地撤销凭证并阻止后续执行，不退出用户 Chrome 的学校账号 |
| POST `/sources` | C/B | 201/200 | 将已保存 item_ids 登记为监测目标；重复来源追加目标，不产生副本 |
| GET `/sources` | B/E | 200 | 分页列出当前 owner 的监测来源 |
| GET `/sources/{source_id}` | B/E | 200 | 返回配置、运行状态与最近检查摘要 |
| PATCH `/sources/{source_id}` | B/E | 200 | 修改 enabled 或 interval_s；源 URL、身份和认证绑定不能原地替换 |
| POST `/sources/{source_id}/checks` | B/E | 202 | 合并重复手动检查，排队到下一个允许窗口；不绕过限流 |
| GET `/checks/{check_id}` | B/E | 200 | 查询执行/应用结果；网站认证失败在正文表达，不冒充本地 API 401 |

### 4.1 Capabilities 与站点白名单

适配器注册表由后端部署配置维护，不能由网页或 API 调用者随意扩展。每项提供 `site_key`、`adapter_id`、`origin`、`auth_mode`、`allowed_cookie_names`、`watch_modes`、`min_interval_s`、`monitoring_supported`。初期只有经验证的 MUST 页面和单独登记的校园网页。

`must_moodle` 建议配置：origin 为 `https://moodle.must.edu.mo`，auth_mode 为 `browser_cookie`，Cookie 名称以实际已验证结果为准，当前预期 `MoodleSession`。路径严格引用接入登记，只读 GET；禁止任意重定向进入 CAS。必须经过页面适配测试才能把 `monitoring_supported` 设为 true。

### 4.2 在线租约

扩展为安装实例保存随机 UUID `bridge_id`，并持久化递增 `sequence`，每 60 秒用 `chrome.alarms` 发送心跳。后端按收到请求的时刻发放 180 秒租约；重复 sequence 返回原租约而不延长，倒退返回 409。`monitoring_enabled=false` 立即停发新任务。

service worker 重启时重建必要 alarm；设备休眠和 alarm 延迟属于正常情况。租约到期暂停新远端请求，保留配置和已有结果；恢复只合并成一次最新检查。180 秒是容错门限，不代表准确探测 Chrome 关闭时刻。

### 4.3 认证上下文与 Cookie 导入

认证上下文身份为 owner + bridge_id + site_key + cookie_store_id + 逻辑账号。V1 每个绑定只支持一个学校账号；隐身和分区 Cookie 不在支持范围。切换账号必须创建新上下文和来源，不自动把旧事项移到新账号。

Cookie 快照完整保留 name/value/domain/path/host_only/secure/http_only/same_site/session/expires_at；session=true 时 expires_at 必须为 null。禁止使用 name→value 字典丢掉 Domain/Path 信息。重复 (domain,path,name) 拒绝。MUST 首版只接受精确主机、host_only=true、secure=true、已批准 Cookie 名称；不接收 login.must.edu.mo 的 SESSION 或其他中央认证凭证。

导入必须带当前 `backend_epoch`、`expected_revision`、`reason`。初次/重启/失效导入进入 unverified；有效会话只允许用户明确发起 `manual_reauthorize` 才能替换，后台 cookie change 事件不能覆盖它。替换时使旧执行代际失效，保留旧业务数据，候选会话验证通过前暂停该上下文。响应 202 只表示快照已接收。

`confirmed_same_account=true` 必须源自用户明确确认；初次导入可为 false。重新绑定时，适配器若能提取稳定用户标识，使用本地带密钥摘要比对；不一致返回 account_mismatch，要求新建上下文。无法可靠提取身份时，不得自动替换，必须用户确认同一账号。

后端只在内存中保存 Cookie Jar。进程重启生成新 backend_epoch，已有上下文改为 needs_credentials，由插件在仍有授权的前提下重新提供凭证。磁盘只存非秘密元数据。后续凭证持久化需独立安全设计。

每个认证上下文串行处理网络请求与 Cookie 更新。revision 用于凭证写入 CAS；generation 仅在导入替换、撤销或后端重启时推进，用于执行结果隔离。合法 Set-Cookie 更新 Jar 并增加 revision，但不改变 generation；同一账号的正常轮换不会丢弃已获取的有效观察。写回须校验请求持有的 generation。后台与 Chrome 共享服务端会话关系，无法保证彼此完全独立；浏览器注销、会话轮换或服务端失效时必须暂停并恢复认证。

Chrome cookies.onChanged 的 overwrite 删除与随后的写入是一次更新过程：去抖后重读，不能立即视为注销。确认必要 Cookie 缺失或撤销权限时清除本地授权；禁止通过后台请求继续维持用户已经撤销的会话。

### 4.4 来源登记与身份

`source_id` 是新监测命名空间 UUID，与旧 `/api/sources` 的数字 ID 分开。`item_ids` 是 IC-001 已保存事项的数字 ID；后端加载它们的 URL 和 locator，校验同一 owner、同一规范化页面及适配器支持情况。

同一 owner + adapter_id + canonical_url + auth_id（公开源为 null）只建一个来源；一页多事项共用一次抓取。监测目标是独立 item_id/locator 绑定。抓取不能自动新增未选事项，也不能按易变标题哈希推断稳定身份；只有标题回退定位的事项在验证前保持 unsupported。

登记新来源返回 201，合并目标返回 200。修改目标集合增加 source revision；已有检查持有旧 revision 时被标为 superseded，不能写回业务结果。C 应在保存事项后的同一事务中写登记 outbox，避免“保存成功但忘记登记”；HTTP 接口作为同一内部注册操作的封装和人工重试入口。

公开源 auth_id=null，但 V1 同样绑定 bridge_id，受本地运行门控。认证源要求 auth_id 与 bridge_id/site_key 一致。用户输入的 platform 或 monitor.supported 不具备授权效力。

### 4.5 检查结果

check.state：queued / running / processing / succeeded / failed / cancelled / superseded。outcome：changed / unchanged / partial / failed / null。

`202` 表示已经排队；HTTP 200、收到 HTML、拿到 304、提交到队列，都不能单独产生业务 succeeded。Extractor 和 Item Service 应用完成后才更新目标 last_success_at。部分目标失败时 outcome=partial，逐目标返回结果；整页 last_success_at 只有本次全部启用目标成功时才推进。

认证上下文状态：needs_credentials / unverified / valid / auth_required / revoked。source.runtime_status：ready / waiting_browser / waiting_auth / paused / backoff / unsupported。运行状态与最近一次业务检查结果分开。source revision 只随配置和目标集合改变，不随检查时间更新而改变。

## 5. 内部接口：供 A / C / D 并行开发

这些是进程内端口，V1 不增加内部 HTTP 或消息中间件。类型定义如下，所有结构禁止包含密码、Cookie 或完整认证 URL。

```python
from typing import Protocol

class MonitoringRegistry(Protocol):
    async def register_saved_items(self, command: "RegisterSavedItems") -> "MonitorSource": ...
    async def request_check(self, source_id: str, request_id: str) -> "Check": ...

class SiteAdapter(Protocol):
    def plan(self, source: "MonitorSource", targets: list["MonitorTarget"]) -> "FetchPlan": ...
    def inspect(self, response: "SafeResponse") -> "AccessVerdict": ...
    def select(self, response: "SafeResponse", targets: list["MonitorTarget"]) -> "ObservationBatch": ...

class AuthProvider(Protocol):
    async def acquire(self, auth_id: str) -> "AuthLease": ...
    async def revoke(self, auth_id: str, expected_revision: int) -> None: ...

class RemoteTransport(Protocol):
    async def fetch(self, plan: "FetchPlan", auth: "AuthLease | None") -> "SafeResponse": ...

class ObservationSink(Protocol):
    async def apply(self, batch: "ObservationBatch") -> "ApplyReceipt": ...
```

| 结构 | 必需字段与约束 |
|---|---|
| RegisterSavedItems | owner_id（调用上下文注入）, item_ids: list[int], site_key, adapter_id, bridge_id, auth_id: str/null, interval_s |
| MonitorTarget | item_id: int, locator: str, enabled: bool；locator 来自已保存事项，插件与后端适配器必须共用同一定位约定 |
| FetchPlan | source_id, source_revision, auth_generation: int/null, check_id, method='GET', canonical_url, target_ids, validators；不得由适配器自行取 Cookie |
| AuthLease | auth_id, generation, approved_origin, opaque_handle；仅受信传输层可用的内存句柄，不序列化、不含可导出的 Cookie 值 |
| SafeResponse | status: int, final_url（已清除秘密参数）, content_type, body: bytes（仅内存）, etag/last_modified；Set-Cookie 在认证层处理，不提供给业务层 |
| AccessVerdict | state: authenticated/public/auth_required/forbidden/unknown；evidence_code: str；principal_key: str/null（本地摘要，不出接口） |
| ObservationBatch | schema_version='1', observation_id: UUID, check_id, source_id, source_revision, auth_generation, observed_at, adapter_version, representation_hash, entries: list[TargetObservation] |
| TargetObservation | item_id, locator, outcome: content/not_modified/missing/error, canonical_url, title: str/null, text: str/null, metadata: object, error: Error/null |
| ApplyReceipt | observation_id, source_id, source_revision, applied: bool, results: list[{item_id,status: changed/unchanged/failed/superseded,last_success_at,error}] |

`content` 必须有 title 和相关正文/元数据；`not_modified` 必须指向同一账号、来源 revision、适配器版本、Vary 条件下已验证且已应用的基线。`missing` 只报告目标缺失，不删除事项。metadata 限于内容元数据，不允许 cookies、headers 或未经清洗的脚本。

A 负责选择目标内容和传输级去重；D 的 Extractor 负责 type/deadline/requirements 等语义字段，Item Service 负责内容哈希、业务版本和用户覆盖。重复 observation_id 原样返回已存 ApplyReceipt；不同 observation_id 但业务内容相同不新增版本。

观察批次和待处理 outbox 在同一 SQLite 事务持久化；D 的应用、去重记录、回执及既有 item_updated/change 事件同事务提交。消费失败重试本地 outbox，不重复抓学校网页。提交时重新校验 source/auth 代际；过时结果拒绝。传输快照保留已选相关内容，完整认证页及无关个人数据不得持久化。

## 6. 调度、网络和失败策略

默认每 600 秒一轮，同账号轮次不更密；同轮合并到期来源和目标。同一主机所有请求（含 robots、重定向、重试）起始间隔至少 2 秒、并发 1；全局最多 4；同 source 和 auth_context 不重叠。手动触发合并到下个允许窗口。规则为本方案默认值，真实访问继续受登记限制和更严格的 Retry-After 约束。

DNS/TCP/TLS 连接阶段预算 10 秒，完整请求含重定向总预算 30 秒，最多 3 跳。网络响应线上正文上限 4 MiB，解压后上限 8 MiB，HTTP 头上限沿用协议栈限制。未实现限额时不得启用真实监测。

| 情况 | 动作 |
|---|---|
| 认证页、CAS 跳转、明确未登录证据 | auth_required；暂停该上下文；不自动重放密码或 ticket |
| 403，且无认证失效证据 | forbidden；只影响相应来源，不注销整个账号 |
| 404 / locator 缺失 | missing；保留原事项与 last_success_at |
| DNS / TCP / 超时 / 5xx | 最多 2 次后续调度重试；不叠加底层多层重试；不提前突破账号间隔 |
| 429 / 503 + Retry-After | 同时解析整数秒和 HTTP-date；设置 not_before，绝不把等待截短为 30 秒 |
| TLS 证书失败 / 禁止域 / 非法重定向 | 终止并报告；不关闭证书校验，不自动降级 HTTP |
| 结构不匹配 / 解析失败 | parse_failed；不当作空结果或删除 |
| Chrome 租约过期 / 休眠 | waiting_browser；恢复最多补一次，不重放所有错过周期 |
| 本地处理队列拥塞 | 停止新抓取；优先完成已保存观察批次 |

网络类连续三次检查失败后冷却至少 1800 秒，再允许一次试探；成功清零失败计数。认证失效不走此自动重试。AccessVerdict=unknown 不能进入已认证成功分支，返回 parse_failed 并保留上次数据。

V1 MUST Moodle 默认不启用条件 GET；待实测证明认证判定和会话活动更新语义后再启用。公开网页可按适配器使用 ETag/Last-Modified。缓存键包含 owner/auth_context、URL、适配器版本、表示相关请求头；切换账号、认证 generation 或目标集合时失效。304 无有效基线时不能当作成功，下一允许窗口执行完整 GET。

HTTP keep-alive 仅复用 TCP 连接；应用会话由服务器和 Cookie 共同维持。正常内容检查可能刷新服务端活动时间；不增加独立的“永不过期”保活线程，不承诺绝对超时可续期。

## 7. 既有接口迁移

1. IC-001 `/api/captures` 请求格式不变。C 保存成功后调用 MonitoringRegistry。IC-002 的事项查询、用户字段和状态语义不变。
2. 新增 target 的 `monitor_executor=legacy_extension|backend_http` 与执行代际。切换时等待旧 300 秒租约结束或明确撤销，原子转移所有权；旧 `/monitor/due` 排除 backend_http 目标，旧 `/monitor/results` 拒绝这些目标的迟到回报。
3. 新监测模块直接调用 ObservationSink，不伪装为旧插件调用 `/monitor/results`。生产特性开关默认关闭，完成安全门槛和端到端用例后按来源启用。
4. IC-002 `monitor.status` 保留既有枚举；可增补 runtime_status/pause_reason 供新 UI 使用。未执行的检查不写 failed，不把旧 last_success_at 刷新。新错误映射：auth_required→auth_expired，target_missing→not_found，其余按最接近旧错误映射并保留具体诊断字段。
5. 不新增 MQTT/WS 通道；D 已有 item_updated/change 负责用户通知。deadline 提醒与内容 Inbox 策略继续由业务层负责。

## 8. 错误协议

统一形状：`{error, message, retryable, retry_after_s, request_id}`。扩展字段不破坏已有 error/message 消费者。

- 401 unauthorized：本地后端令牌无效；与学校网站登录状态无关。
- 403 origin_denied / binding_denied：扩展来源、绑定或调用权限不允许。
- 404 not_found：不存在或不属于当前 owner，避免泄露其他用户资源。
- 409 revision_conflict / idempotency_conflict / stale_backend / account_mismatch / active_session / unsupported：状态冲突或尚不可监测。
- 413 too_large；422 invalid / cookie_scope_denied / partitioned_cookie_unsupported；429 rate_limited；503 unavailable。

上游认证失败、网络错误和解析失败放在 Check/TargetResult 的 error 中，GET 查询仍返回 200。JSON Schema 之外的 Cookie、资源绑定和状态转换约束也必须服务端校验。

## 9. 最小联调顺序

1. B 用现有本地登录获得令牌 → capabilities → presence，用户授权指定学校站点。
2. B 创建 auth_context → 按精确作用域读取 Cookie → PUT cookies，得到 unverified；不宣称有效。
3. 用户按 IC-001 保存事项；C 由保存事务 outbox 登记 source/targets。首轮普通内容 GET 同时验证认证，避免另发保活探测。
4. A 交付 ObservationBatch，C/D 完成抽取和 ApplyReceipt；E 通过 IC-002 查看数据与状态。
5. fake_moodle 模拟变更、失效、重试、浏览器离线；所有 CI 只连接本地替身。

## 10. 验收与当前代码差距

| 验收 | 必须观察到的结果 |
|---|---|
| Cookie 作用域、hostOnly、Secure、Path、过期与删除 | 无跨域/跨账号泄露；Domain 必须属于响应来源且满足站点白名单；拒绝控制字符和分区 Cookie |
| 200 登录页 / CAS 重定向 / 403 | 分别识别未登录与禁止访问；无错误版本入库 |
| 304 + 缺失基线 / 身份变化 | 不误报无变化、不跨身份复用缓存 |
| Set-Cookie 轮换、浏览器覆盖事件、显式撤销 | 不复活旧凭证；注销后停止；旧执行结果被栅栏拒绝 |
| 抓取完成后进程崩溃 / 重复投递 / 乱序 | 本地重试，无重复业务版本；旧代际不覆盖新结果 |
| 同页 10 个目标、连续手动点击 | 同轮仅一次 GET；请求仍满足限流 |
| 429 + HTTP-date / 600 秒 Retry-After | 下一次请求不早于服务端要求 |
| 浏览器关闭、休眠、后台重启 | 有明确暂停/需凭证状态；恢复合并检查；最后成功时间不虚增 |
| 私网 URL、DNS rebinding、重定向到内网、恶意 Set-Cookie Domain | 请求被阻断；测试替身仅显式开发配置放行 |
| Chrome 平台兼容 | 验证目标 Chrome 的扩展权限、本地网络访问策略、Origin 行为、alarm 重建；拒绝时给出可操作错误 |
| MUST 手动验收 | 仅已授权账号、允许页面及限速；超过 2 小时，记录版本、运行条件、逐次成功与失败，不提交实际内容或凭证 |

代码审阅发现的复用门槛（本次不修改实现）：
- `net/http/cookies.py:set_from_header` 直接接收 Domain 属性；使用新契约前需补来源 domain-match 与站点白名单验证。
- `collector/fetcher.py` 将 Retry-After 截为 30 秒，且只识别纯数字；需要改为持久 not_before，支持 HTTP-date。
- 当前 robots 获取及 HTTP 客户端内部重定向不由同一个 Fetcher 外层限速循环逐跳管理；新执行器必须统一约束每次请求。
- 既有 CookieJar 为 RFC 子集，未实现浏览器分区语义；V1 明确拒绝分区 Cookie，不声称通用浏览器会话兼容。

## 11. 依据

仓库：`CLAUDE.md`、`docs/product-definition.md`、IC-001、IC-002、`docs/browser-extension.md`、`docs/protocols/http.md`、`docs/integrations/must-moodle.md`、`server/gleaner/collector/{fetcher,session}.py`、`server/gleaner/net/http/cookies.py`（审阅 main 于 2026-11-07）。接入文档仍有历史 Web Service token 方案，本契约不依赖其可用性，也不删除该历史记录。

外部规范（查阅 2026-11-07）：
- [Chrome cookies](https://developer.chrome.com/docs/extensions/reference/api/cookies)：权限、属性、分区与更新事件。
- [Chrome alarms](https://developer.chrome.com/docs/extensions/reference/api/alarms) 与 [worker 生命周期](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle)：调度唤醒和休眠恢复。
- [跨源请求](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests) 与 [本地网络访问](https://developer.chrome.com/docs/modern-web-guidance/guides/security/local-network-access)：扩展与浏览器环境约束，具体版本须实测。
- [RFC 6265](https://www.rfc-editor.org/rfc/rfc6265.html) §5：Cookie Jar；[RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html) §10.2.3、§13、§15：Retry-After、条件请求与状态语义；[RFC 9112](https://www.rfc-editor.org/rfc/rfc9112.html)：HTTP/1.1 报文与连接。
- [OWASP SSRF](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)：域名/IP 白名单、DNS 与重定向验证。
- [OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html)：随附 HTTP 契约格式。
