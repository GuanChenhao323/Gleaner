# IC-003｜监测模块输入与输出契约

版本：0.2.0 · 2026-11-15。

适用范围：参数化页面监测单元与调用方、会话桥接方、HTML 接收方之间的进程内协作。

实施状态：页面获取、会话管理、HTML 交付和部分控制方法已实现；统一模块入口及正式系统联调待实现。

本文以“调用方交给模块什么、模块返回什么、失败后各方做什么”为主线。**已实现**指当前可调用的 Python 组件；**待实现**指尚不能依赖的接口或保证。HTTP 客户端、浏览器驱动与 DNS 实现属于模块内部选择。

现有 [monitoring-v1.openapi.yaml](../protocols/monitoring-v1.openapi.yaml) 仍是 0.1.0 事项监测 HTTP 提案，未定义本文的页面任务接口，不能用于生成页面调用客户端。本文不宣称生产 HTTP 端点已经上线。

## 1. 模块职责与交付边界

监测模块接收精确目标、检查间隔和已授权会话，执行受控页面获取与认证检查，向接收方交付完整主文档 HTML，并报告获取、交付和失败状态。

| 参与方 | 提供或负责的内容 |
|---|---|
| 任务调用方 | 选择目标 URL、间隔和站点配置，引用会话，关联自身业务；自行保存任务与业务对象的映射 |
| 会话桥接方 | 经用户授权取得指定范围的 Cookie，提供在线信号，发起重新授权或撤销 |
| 监测模块 | 验证参数和绑定、维护会话、决定检查时机、获取 HTML、识别认证状态、重试与交付 |
| HTML 接收方 | 接收快照、按快照 ID 去重并确认接收；后续提取、变化判断和业务入库由下游负责 |
| 宿主集成层 | 注入可信调用身份、装配组件和接收端、驱动生命周期；当前由本地集成代码承担 |

主契约不依赖 `item_id`、locator、事项类型、Deadline、Inbox 或业务版本。模块不判断页面是否产生了新的事项，也不以业务入库完成作为 HTML 交付成功条件。原有事项观察路径保留，兼容边界见第 6 节。

当前交付范围为**授权会话下的页面主文档 HTML**。它不包含分页结果、附件、视频、字幕或完整资源包，也不保证包含 JavaScript 执行后新增的 DOM。当前页面路径要求认证上下文，匿名页面、RSS、OAuth 尚无对应输入契约。

## 2. 输入契约

### 2.1 页面任务参数

调用已实现的 `PageMonitor.register(params, *, owner_id, bridge_id)`。四项业务参数全部必填，不提供隐式默认值；缺字段、多字段和类型不符均拒绝。

| 字段 | 类型 | 含义与约束 |
|---|---|---|
| `target_url` | `str` | 一个精确的 HTTPS 页面 URL；须符合所选 profile 的域名、路径和查询参数规则。当前拒绝账号密码、片段、控制字符和显式端口 |
| `interval_s` | `int / float` | 获取间隔，单位秒；必须有限，布尔值不接受；不得低于 profile 的最低间隔，当前真实站点均为 600 秒。当前页面实现未设置统一上限 |
| `auth_context_id` | `str` | 已由本模块创建的会话引用；必须存在，且与当前调用身份、bridge 和装配策略一致；不接受 `null` |
| `site_profile` | `str` | 已登记配置的名称，见下表；调用方不能传入任意解析代码、Cookie 规则或请求头 |

示例：

```json
{
  "target_url": "https://www.youtube.com/@3blue1brown/videos",
  "interval_s": 600,
  "auth_context_id": "<本模块创建的会话 ID>",
  "site_profile": "youtube_http_v2"
}
```

登记成功返回 `PageTask`，字段为 `task_id`、`owner_id`、`bridge_id`、上述四项参数，以及 `revision=1`、`enabled=true`。模块生成 UUID 字符串形式的 `task_id`；调用方保存它与自身业务对象的关联。

**登记只建立任务，不启动后台循环，也不表示会话已验证。** 每个 `PageMonitor` 实例当前只保存一个任务；再次成功登记会生成新 ID、替换原任务、清除待交付 HTML 和最近获取/交付时间。当前没有任务登记幂等键，重复调用不能用于查询或恢复原任务。运行期间应通过宿主串行协调登记和控制操作，禁止直接修改返回对象的字段。

### 2.2 调用上下文与装配依赖

以下内容由受信任宿主提供，不混入四项任务参数。

| 输入 | 当前要求 |
|---|---|
| `owner_id: int` | 从宿主已验证的调用身份取得；必须与会话所属 owner 一致 |
| `bridge_id: str` | 与会话绑定的桥接实例一致；用于在线租约，不代表业务事项身份 |
| 站点策略与会话管理器 | 使用同一配置装配；当前策略包含目标 URL，不能推定同站任意目标都能复用一个会话引用 |
| `HTMLSink` 接收端 | 宿主在装配时注入，满足第 3.2 节；任务参数中不接受回调 URL |
| 执行驱动 | 宿主周期调用 `tick()` 并提供真实在线信号；模块内部判断是否到期 |

这些方法是受信任进程内方法，未自带独立的网络鉴权层。`AuthContext` 内部对象持有凭证，不能直接序列化给其他模块或客户端；对外只使用会话 ID 与 `AuthManager.metadata()` 的非秘密元数据。

### 2.3 会话创建、导入与在线信号

**创建会话：已实现。** `AuthManager.create(owner_id, bridge_id, cookie_store_id="0")` 创建空上下文，初始状态为 `needs_credentials`。返回对象的 `auth_id` 用作任务参数中的 `auth_context_id`；这两个名称指向同一个 ID。

**导入凭证：已实现。** `AuthManager.import_cookies()` 接受以下输入：

| 参数 | 类型与默认值 | 约束 |
|---|---|---|
| `auth_id` | `str`，必填 | 已创建的会话 ID；宿主先校验调用者有权操作该会话 |
| `cookies` | `list[dict]`，必填 | 非空、保留属性的 Cookie 快照，格式见下文 |
| `backend_epoch` | `str`，必填 | 当前 `AuthManager.backend_epoch`；管理器重建后旧值失效 |
| `expected_revision` | `int`，必填 | 当前会话修订号；不一致返回冲突 |
| `request_id` | `str`，必填 | 非空去重键，调用方应生成 UUID；当前组件不强制校验 UUID 格式 |
| `reason` | `str`，默认 `initial` | `initial / backend_restart / auth_recovery / manual_reauthorize` |
| `confirmed_same_account` | `bool`，默认 `false` | 同账号确认；只有用户明确确认后才可为 true |

从 `backend_epoch` 起的参数须按关键字传入。宿主通过 `page_policy()` 获得注册策略，用其 `import_cookie_names` 提供允许导入的名称；桥接方按该 profile 的主机/路径范围取得凭证，模块再次校验作用域。

每条 Cookie 提供 `name/value/domain/path` 字符串，`host_only/secure/http_only/session` 布尔属性，`same_site` 与 `expires_at`。`same_site` 接受 `strict/lax/none/unspecified/no_restriction`；`session=true` 时 `expires_at=null`，否则必须是晚于当前时间的有限 UTC Unix 秒。浏览器导出的其他字段命名须由桥接方先规范化。

导入仅接受 profile 批准的名称和作用域，拒绝重复的规范化 `(domain, path, name)`、分区 Cookie 和非法字符。导入序列化大小上限为 256 KiB。Moodle 保留精确主机、`host_only=true`、`secure=true`、路径 `/` 的约束；其他 profile 按各自注册规则检查 Domain Cookie。

导入成功返回与 `metadata()` 相同的字段：`auth_id`、`owner_id`、`bridge_id`、`cookie_store_id`、`state`、`revision`、`generation`、`was_verified`。其中 revision 用于凭证写入并发检查，generation 用于隔离旧执行，was_verified 表示该上下文曾通过认证。Cookie 值不会出现在该响应中。状态进入 `unverified`，首次内容获取通过认证检查后才成为 `valid`。

导入去重记录只驻当前管理器内存，键为 `(auth_id, request_id)`；相同键及相同导入内容返回原响应，不同内容返回 `idempotency_conflict`。原响应不代表最新会话状态，需要时重新读取 `metadata()`。有效会话只有显式 `manual_reauthorize` 才能替换；无法可靠确认原账号的再次授权要求用户确认，检测到账号不一致时不能沿用原任务绑定。

**在线信号：已实现组件，正式插件桥接待接入。** `presence(bridge_id, sequence, enabled=True)` 接受非负整数序号，按当前单调时钟授予 180 秒租约；桥接方正常每 60 秒续期。重复序号返回原期限、不延长租约，倒退返回 `revision_conflict`。切换 `enabled` 也需要新序号；`enabled=false` 阻止新远端获取。返回期限仅能在同一进程的单调时钟下解释。

在线信号只访问本地模块。调试程序生成的模拟信号仅用于验证，生产集成必须由真实桥接状态驱动；租约恢复后按当前到期状态执行，不补发休眠期间的每一轮。

### 2.4 已登记站点配置

| `site_profile` | 可登记的页面范围 | 当前能力边界 |
|---|---|---|
| `moodle` | `https://moodle.must.edu.mo/mod/assign/view.php?id=<活动 ID>`，ID 为规范化十进制数字 | 作业详情主文档；页面路径输出完整 HTML |
| `youtube` | `www.youtube.com` 下 `/@<handle>/` 或 `/channel/UC…/` 的 `videos/shorts/streams` 页面，或 `/watch?v=<11 位视频 ID>` | 保留的 HTTP 配置 |
| `youtube_http_v2` | 同上述 YouTube URL 类型 | 显式会话配置；初始导入范围与后续轮换范围分别限制 |
| `youtube_browser_v1` | 同上述 YouTube URL 类型 | 可选浏览器后端；交付原始主文档响应体，完整应用渲染未获证明 |
| `bilibili` | `www.bilibili.com/video/BV…/`、`space.bilibili.com/<uid>/` 或其 `upload/video` 路径，以及获准的 `/en/` 变体；不接受查询参数 | 配置及本地测试已有；真实登录态尚未验证，受 robots 阻断的路径不交付 |

登记后的请求仍受精确目标、认证、robots、重定向和地址范围检查。注册某种 URL 类型不保证该类型下所有页面均可访问。后端由 profile 显式选择，访问失败不会自动切换后端或扩大允许范围。配置注册查询的统一接口尚未实现。

## 3. 输出与接收契约

### 3.1 HTMLSnapshot：交给下游的数据

获取与认证检查均成功后，模块调用接收端的 `accept(snapshot)`。当前结构如下：

| 字段 | 类型 | 含义 |
|---|---|---|
| `snapshot_id` | `str`，UUID | 一次获取结果的交付身份；重试交付时保持不变 |
| `task_id` | `str`，UUID | 产生结果的任务 ID |
| `task_revision` | `int` | 获取时的任务修订号，用于识别过期配置 |
| `auth_generation` | `int` | 获取时的认证代际，用于隔离撤销、重新授权前的结果 |
| `requested_url` | `str` | 任务要求获取的精确 URL |
| `final_url` | `str` | 通过范围校验后实际取得内容的 URL |
| `fetched_at` | `float` | 获取及认证检查完成时的 UTC Unix 秒；不等同于请求开始时间 |
| `status` | `int` | 主文档 HTTP 状态；当前 profile 的成功交付要求 200 |
| `content_type` | `str` | 主文档响应的 Content-Type，供下游解释内容与编码 |
| `body` | `bytes` | 完整主文档响应体，已处理传输压缩；保留内嵌 JSON 与脚本内容，不做业务抽取 |

`body` 为原始响应 HTML，当前浏览器后端也不输出渲染后的 DOM。它可能包含页面中的个人数据或页面令牌，未经过业务脱敏；仅交给受信任的本地接收端在内存中处理，不能直接写日志或作为调试输出。请求 Cookie、Authorization、Set-Cookie 和 Cookie Jar 不加入快照元数据。下游需要保存业务内容时，应自行提取所需字段，不持久化完整认证页面。

每次新的有效获取都会生成新 `snapshot_id`，即使内容与上次相同。模块不在这条路径输出标题、事项列表、`changed/unchanged`、业务版本或业务成功时间。

### 3.2 HTMLReceipt：下游确认接收

已实现的接收端口：

```python
class HTMLSink(Protocol):
    async def accept(self, snapshot: HTMLSnapshot) -> HTMLReceipt: ...
```

`HTMLReceipt` 仅含两个字段：

| 字段 | 类型 | 约束 |
|---|---|---|
| `snapshot_id` | `str` | 必须与此次调用收到的快照 ID 完全相同 |
| `accepted` | `bool` | 只有值为 `True` 时确认接收；接收方已承担该快照的后续处理责任 |

只有 ID 匹配、`accepted is True` 且任务/会话仍有效，模块才返回 `delivered` 并更新 `last_delivery_at`。`accepted=false`、错误 ID、无效回执或接收端抛出普通异常，均进入交付重试。下游按 `snapshot_id` 幂等接收；已经接收的重复快照可以再次返回相同成功回执。

接收确认不包含内容提取或业务入库结论。接收方确认后发生的业务失败由下游处理，监测模块不会因此重新获取页面。

### 3.3 执行结果：交给宿主的状态

`await PageMonitor.tick()` 返回本次状态事件字典，或 `None`。所有事件具有：

| 字段 | 类型与语义 |
|---|---|
| `state` | 下表所列状态字符串 |
| `utc` | 事件发生的 UTC Unix 秒 |
| `mono` | 当前进程的单调时钟值，仅用于本进程时序诊断 |
| `last_fetch_at` | 最近一次通过获取和认证检查的时间；未知为 `None` |
| `last_delivery_at` | 最近一次接收确认成功的时间；未知为 `None` |

| `state` | 本次含义 | 附加字段 |
|---|---|---|
| `delivered` | 快照已被接收端确认 | `snapshot_id`、`bytes`、`sha256`、`authentication="authenticated"`、`evidence_code`、`http_status` |
| `delivery_pending` | HTML 已取得，接收未确认，保留待重试快照 | `snapshot_id`、`error="delivery_failed"` |
| `waiting_browser` | 在线条件不满足，未发起新获取 | 无 |
| `waiting_auth` | 会话尚缺凭证、要求重新授权或已撤销，未发起新获取 | 无 |
| `failed` | 本次获取、认证或策略检查失败 | `error`、`retryable` |
| `superseded` | 结果已过期，模块丢弃待处理结果 | 无 |

`None` 表示本次没有新事件，可能是未登记、已暂停、未到期、重复等待状态或已有一次 `tick()` 在执行；不能据此推导成功或失败。`waiting_browser / waiting_auth` 连续未变化时不重复发出。

状态事件仅描述本次执行：当前不自带 `task_id`，宿主按所属 `PageMonitor` 实例关联；`sha256` 和 `bytes` 属于成功事件的附加摘要，独立于 `HTMLSnapshot` 结构。`failed` 当前不包含 `retry_after_s`，宿主可读取 `next_due_at` 了解下一允许时刻。统一查询与事件封装见第 6 节。

会话状态单独通过 `metadata()` 读取：`needs_credentials / unverified / valid / auth_required / revoked`。任务暂停由 `PageTask.enabled=false` 表达，不会凭空生成一次抓取失败。

## 4. 调用接口与流程

### 4.1 当前可调用接口

下表均为已实现的进程内组件接口；正式网络 API 和统一模块入口仍待实现。

| 接口 | 输入 → 返回 | 调用效果 |
|---|---|---|
| `AuthManager.create(...)` | owner、bridge、Cookie Store → 内部 `AuthContext` | 建立空会话；对外使用其 ID 和非秘密元数据 |
| `AuthManager.import_cookies(...)` | 第 2.3 节导入参数 → 元数据字典 | 接收候选凭证，状态进入 `unverified` |
| `AuthManager.presence(...)` / `online(bridge_id)` | 在线信号 → 租约期限 / bridge → `bool` | 更新或检查本地运行条件 |
| `AuthManager.metadata(auth_id)` | 会话 ID → 元数据字典 | 读取状态、revision 和 generation；不返回凭证 |
| `PageMonitor.register(...)` | 第 2.1 节参数及调用上下文 → `PageTask` | 登记或替换当前实例的任务 |
| `await PageMonitor.tick()` | 无额外业务参数 → 事件字典或 `None` | 尝试交付待处理快照，或执行一次到期检查 |
| `PageMonitor.pause()` | 无 → `None` | 禁用任务、增加 revision、丢弃待交付快照；保留会话 |
| `await AuthManager.revoke(auth_id, expected_revision)` | 会话 ID、修订号 → `None` | 撤销凭证，使旧执行失效，并等待已绑定运行时清理 |
| `HTMLSink.accept(snapshot)` | 快照 → `HTMLReceipt` | 模块调用的下游端口；接收实现由宿主注入 |
| `AuthManager.close()` 与 `await transport.close()` | 无 → `None` | 清空会话并关闭相关资源；宿主退出时须完成两部分清理 |

`pause()` 不保证已发送的远端请求立即中断；迟到响应在交付前按修订号和代际丢弃。浏览器运行时也持有凭证，撤销会同步阻止旧运行时继续使用凭证，再等待清理；宿主不能只丢弃 Python 引用就宣称清理完成。

### 4.2 首次接入与周期运行

1. **宿主完成装配。** 根据 profile 与目标调用 `page_policy(profile, target_url)`，建立同策略的 `AuthManager`、`SessionInspector(profile)` 和 `create_page_transport(policy, auth)`，将这些组件及下游 sink 注入 `PageMonitor`。这层装配当前需要宿主集成代码承担，统一入口尚未封装。
2. **创建会话并授权。** 创建上下文，向获准桥接方提供 `auth_id`、当前 epoch 与 revision。桥接方提交规范化 Cookie，成功后仅显示“凭证已接收、待验证”。
3. **登记任务。** 提交四项参数，接收并保存 `task_id`。不需要先创建事项或写入业务数据库。
4. **建立在线条件并启动宿主循环。** 桥接方按序号续期；宿主周期调用 `tick()`。首次有效任务的到期时间为立即，但实际获取仍受在线、认证和传输限流约束。
5. **获取并交付。** 模块获取内容、检查认证、维护会话轮换，生成快照并调用 sink。下游返回回执后，宿主取得 `delivered` 或交付失败事件。
6. **继续下一轮。** 正常下一次获取时间从本轮获取及认证处理结束起，等待至少 `interval_s`；等待接收确认期间不抓新页面。交付恢复后若已到期，下一次 `tick()` 可以检查，不重放全部错过周期。

`tick()` 内部串行保护当前实例，并使用认证上下文锁防止同一上下文并发获取。当前单实例行为不能作为跨多个实例、多个任务的统一账号间隔或全局限流保证。

### 4.3 暂停、恢复、撤销与退出

- **暂时失去在线条件：** 停止新获取；新的有效 presence 到达后继续按到期时间检查。已经取得的快照优先尝试本地交付，该步骤不要求在线租约仍有效。
- **认证失效：** 会话进入 `auth_required`，任务等待重新授权。有效重新导入后，在下一允许时刻重新验证；重新授权不自动清除原到期等待。
- **显式暂停：** 调用 `pause()`。当前没有保留原 `task_id` 的恢复方法；需要再次监测时，重新登记会产生新任务。原任务就地恢复属于待实现接口。
- **撤销：** 读取最新会话 revision 后调用 `revoke()`；凭证立即失效，旧代际的执行和结果被拒绝，任务等待有效重新授权。撤销已撤销的上下文可重复调用，清理仍须完成。
- **退出：** 停止宿主派发，暂停任务，清理会话，并等待传输/浏览器资源关闭；失败时仍须执行其余清理步骤。退出不负责登出用户的 Chrome 账号。

## 5. 失败处理与交付保证

### 5.1 同步拒绝：参数、绑定与凭证错误

登记、配置装配和会话操作中的受控拒绝通过 `MonitorError` 抛出；其字段为 `code: str`、`retryable: bool`、`retry_after_s: float`。这是 Python 错误契约，不对应既有 HTTP 状态码。未覆盖异常的宿主处理要求见第 5.2 节。

| 典型错误码 | 调用方处理 |
|---|---|
| `invalid / unsupported / unsupported_profile / blocked` | 修正参数或选用已登记范围；不要反复提交同一非法输入 |
| `not_found / binding_denied` | 检查会话是否存在、owner/bridge/profile/目标是否匹配；禁止自动改绑其他账号 |
| `revision_conflict / stale_backend` | 重新读取当前上下文或重建会话，基于最新版本发起明确操作 |
| `idempotency_conflict / active_session` | 检查请求 ID 是否误用；有效会话替换必须是明确重新授权 |
| `cookie_scope_denied / partitioned_cookie_unsupported / too_large` | 桥接方修正导入范围或格式；不扩大权限来重试 |
| `account_confirmation_required / account_mismatch` | 请求同账号确认；账号已改变时创建新的上下文及任务 |
| `browser_unavailable / unsupported_browser_scope / unsafe_browser_debug` 等装配错误 | 由宿主修正部署或注册配置；任务参数不能绕过限制 |
| `session_cleanup_failed / browser_cleanup_failed` | 宿主停止该实例，继续完成资源关闭；不恢复旧凭证，也不宣称清理成功 |

成功登记不承诺首次获取一定成功。凭证存在、URL 可以登记、HTTP 返回 200 都不能单独证明认证有效。

### 5.2 执行失败：是否自动恢复

获取阶段捕获的 `MonitorError` 通常转换为第 3.3 节事件；`superseded` 单独报告。

| 场景 / 典型错误 | 模块动作 | 调用方与下游处理 |
|---|---|---|
| 登录页、明确失效：`auth_required` | 报告 `failed`，会话进入 `auth_required`，后续等待授权 | 保留历史结果；由桥接方重新授权 |
| 缺少正面登录证据：`auth_unverified` | 不交付 HTML；进入等待授权流程 | 检查会话及 profile 识别规则；不能把匿名页面计作成功 |
| 账号不一致或缺少确认 | 不交付本次结果，使会话要求重新授权 | 按第 5.1 节处理账号绑定 |
| 可重试网络错误，如 `dns / network / timeout`，HTTP 路径的 `upstream_5xx` | 报告 `failed`，按最早允许时刻重试 | 调用方持续驱动 tick，无需重复登记 |
| 限流：`rate_limited` | 同时遵守任务间隔和服务端等待要求 | 等待，不用手动调用提前突破间隔 |
| 不可重试拒绝，如 `forbidden / robots_denied / blocked / target_missing / response_too_large`、证书错误 | 报告 `failed` 并设置任务 `enabled=false` | 检查原因；恢复条件后显式重新登记，不删除下游历史数据 |
| HTTP 路径收到 304：`missing_baseline` | 当前页面路径不支持条件 GET；此错误不产生“无变化”，任务被禁用 | 不套用旧事项路径的 304 成功语义 |
| 配置或会话代际已变 | 报告 `superseded`，丢弃过期结果 | 不将旧结果应用到新任务或新会话 |
| 接收端失败或回执不匹配 | 报告 `delivery_pending`，保留原快照 | 接收端恢复并允许幂等重试 |

自动重试以实际 `retryable` 值为准。不同后端的错误分类可能不同，例如 `robots_unavailable` 不具有跨后端统一的可重试性；调用方不能仅凭错误名自行发起网络重试。

可重试失败后，下一次等待至少取任务间隔与 `retry_after_s` 中较大者；连续获取失败达到三次且本次错误可重试时，还须至少等待 1800 秒。有效获取后失败计数清零。当前页面路径没有总重试次数上限，也不采用旧事项路径“最多两次后续重试”的承诺。认证错误须先恢复会话；其他不可重试错误须先恢复任务。

组件尚未将所有异常统一封装成状态事件：准备阶段的错误或未覆盖异常可能向宿主抛出。宿主应终止本次执行、保留原结果并记录脱敏诊断；不得将异常文本、凭证或 HTML 直接输出到用户接口。统一错误封装待实现。

### 5.3 交付失败、过期结果与重启

- 接收失败后保留同一份 HTML 与 `snapshot_id`，至少 60 秒后由后续 `tick()` 重试。存在待交付快照时停止新获取，避免用新页面覆盖尚未确认的结果。
- 当前没有接收调用超时、最大交付重试次数或死信接口；sink 应有界返回，长期挂起会阻塞该实例。统一超时及终止策略列为待实现。
- 模块在交付前、接收调用返回后检查任务 ID/revision、认证 generation 和有效状态；普通 Cookie 轮换只增加认证 revision，不废弃同身份快照。
- 暂停、重新登记、撤销或重新授权会使旧结果失效。若下游已经进入 `accept()`，监测模块无法撤回接收方已经执行的副作用；下游必须按代际处理延迟业务写入。跨模块提交时的有效性校验接口尚待正式接入。
- 任务、待交付 HTML 和本路径的运行状态只驻进程内存。进程退出后重新装配、按仍有效的授权重新导入凭证并登记；不承诺待交付快照的跨进程恢复、跨进程至少一次交付或 exactly-once。
- 获取或交付失败不会清除已有成功时间；重新登记新任务会重置这些时间。状态与数据消费者须分别处理“本次失败”和“历史仍有成功结果”。

## 6. 待实现接口与兼容接入

### 6.1 尚不能依赖的接口或保证

| 待实现项 | 需要明确或完成的边界 |
|---|---|
| 统一模块入口与生命周期 | 封装 profile、会话、传输、接收端装配及循环启停，向调用方提供稳定入口；当前需宿主集成这些组件 |
| 页面任务管理 | 按 ID 查询/列表、保留 ID 的恢复、参数更新、取消/删除、受限手动检查、任务创建幂等；当前仅有单实例 register/pause/tick |
| 统一状态与错误响应 | 关联 task_id、暂停原因、下一次允许时间、重试等待；当前事件字段按第 3.3 节，不能套用旧 Check Schema |
| 多任务协调 | 跨实例的同账号轮次、同主机请求预算、全局并发和共享会话规则；单实例锁不提供全局保证 |
| 接收端可靠性 | 接收超时、重试终止策略、跨模块代际提交校验及正式下游接收实现；当前只有端口与验证替身 |
| 跨进程恢复 | 任务恢复和交付恢复策略；完整认证 HTML 不因旧 outbox 设计而自动获得持久化授权 |
| 正式桥接与 HTTP 包装 | Chrome 授权/在线信号接入，可信 owner 注入与所有权校验，回环限制、令牌及敏感操作 Origin 校验；调试页面不能替代正式桥接 |
| 能力查询与统一执行预算 | 对外列出已登记 profile、依赖及限制，并对齐各后端超时和大小预算；旧文档中的统一数字不能当作浏览器路径已经通过的验收结论 |

这些条目不表示需要立即新增独立服务或消息中间件。当前已实现端口采用进程内调用；未来新增 HTTP 包装时须另行定义请求/响应 Schema、鉴权与版本，本文没有预设新的 URL。

### 6.2 原事项监测路径

既有 `Registry → Scheduler → MoodleAdapter → ObservationBatch → ObservationSink.apply() → ApplyReceipt` 仍保留在代码中，面向已保存的 `item_id/locator`。其选定内容的 SQLite outbox、逐事项结果及业务应用语义不属于页面 HTML 主契约。

| 内容 | 页面主契约 | 原事项路径 |
|---|---|---|
| 任务身份 | `task_id` 与四项任务参数 | `source_id`、已保存事项和 locator |
| 数据交付 | 完整主文档 `HTMLSnapshot` | 已选目标的 `ObservationBatch` |
| 回执 | `HTMLReceipt.accepted`：已接收 | `ApplyReceipt`：逐目标应用结果 |
| 成功时间 | `last_fetch_at / last_delivery_at` | 观察应用后推进的目标/来源 `last_success_at` |
| 恢复 | 当前进程内重试 | 选定观察内容的持久 outbox 重试 |

新接入方使用页面契约即可，不需要为抓取而先创建业务事项。将 HTML 转为事项观察或业务事件的适配属于下游集成，正式适配待实现；此次文档重写不表示相关代码已经迁移。

IC-001 Capture 与 IC-002 工作台契约继续有效。既有 `/api/monitor/due`、`/api/monitor/results` 属于旧插件监测接口；旧提案中的 `/api/monitor/v1/capabilities`、presence、auth-contexts、sources、checks 等生产端点尚未接入。相关 OpenAPI 文件此次保持原样，只用于识别旧 HTTP 提案范围。

### 6.3 实现与验证依据

- [pages.py](../../server/gleaner/monitoring/pages.py)：任务输入、HTMLSnapshot、HTMLReceipt、状态事件和交付重试。
- [auth.py](../../server/gleaner/monitoring/auth.py)、[profiles.py](../../server/gleaner/monitoring/profiles.py)、[backends.py](../../server/gleaner/monitoring/backends.py)：会话控制、站点登记和受控后端选择。
- [页面测试](../../server/tests/test_monitoring_pages.py)、[配置测试](../../server/tests/test_monitoring_profiles.py)、[后端测试](../../server/tests/test_monitoring_backends.py)、[会话资源测试](../../server/tests/test_monitoring_session_resources.py)：输入拒绝、完整 HTML、重复交付、撤销、并发和旧代际隔离。
- [Moodle 验证与运行说明](monitoring_module/README.md)：包含指定作业页 130 分钟验证及正式业务接入的限制。
- [参数化 HTML 计划](../exec-plans/2026-11-11-parameterized-html-monitor.md)、[浏览器接入记录](../log/2026-11-14_r-b-cheng/playwright-resume.md)：页面路径与指定 YouTube 频道的认证 HTML 验证；不将单站验证推广为任意站点、完整应用渲染或正式业务成功。
