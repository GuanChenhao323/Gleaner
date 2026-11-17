# Interface Contract — Chrome 网页采集插件 → Core 后端

**接口 ID：** IC-BROWSER-INGEST-001

**版本：** v1.0

**负责人：** 插件／网页采集负责人 / Core 后端负责人（具体人员由团队指派）

**最后更新：** 2026-11-17

## 1. 接口概述

| 项目 | 说明 |
|---|---|
| 发送模块 | Chrome 插件：`PageExtractionService`、三类 Payload 构造器、持久 Outbox、`ReadingJobExecutor` |
| 接收模块 | Core：`BrowserMonitorService`、`WebCaptureService`、`TimelineCaptureContract`、`ReadingSourceService`；处理结果进入 `Pipeline` |
| 接口用途 | 接收用户明确预览并保存的网页匹配内容，关联原条件来源，接收后续检查结果并更新原资料版本 |
| 通信方式 | 插件到 Core：HTTP JSON，经网关转发，使用 Campus Radar Bearer 令牌；Core 到 Pipeline：进程内异步调用 |

**适用基线：** Git `06065c6`、扩展 `0.13.1`。此编号是交接报告的汇总编号，不新增网络接口；沿用原生事项、通用网页、Timeline、条件来源的既有契约。

**数据边界：** 当前从渲染后的主 frame DOM 读取匹配文本、原文字段及有限定位上下文，上传结构化 JSON。没有整页 HTML、完整 DOM 树、AX 树或原站 Cookie 上传字段。原站 Cookie 和登录会话由 Chrome 管理；`account_key`、`session_id`、`page_id` 都不是 Cookie，也不能用于后端独立登录原站。

**用户流程：** 打开原网页并自行登录 → 插件输入条件 → 提取当前已加载匹配内容 → 预览 → 明确保存 → 后端处理 → Flutter 查看。当前 UI 默认请求专用监测页定期检查，也可仅保存一次；监测依赖 Chrome、扩展、专用标签页及本地后端可用。

**文档关系：** 本文件严格按四节模板提供接口报告。端到端图、源码索引、留存／隐私限制、历史 HTML 采集分支及核对记录，见[完整交接说明](browser-data-handoff-v1.md)。本轮仅整理文档，不修改业务代码、不重新进行真实网站验收。

## 2. 通信协议

### 2.1 网络通信

| 协议项 | 约定 |
|---|---|
| 传输 | 既有 HTTP/1.1；本地典型 base URL 为 `http://localhost:8080`，以实际配置为准 |
| 路由 | 网关 `/api/*` 转发 Core；插件不直接写数据库 |
| 请求／响应编码 | JSON，`Content-Type: application/json`，HTTP JSON 正文使用 UTF-8 |
| 鉴权 | `Authorization: Bearer <Campus Radar token>`；owner 由服务器登录态确定，客户端不能指定其他 user_id |
| 令牌获取 | `POST /api/auth/login` 输入 email/password，返回 token/user；不是学校登录接口 |
| 浏览器请求 | 插件 fetch 使用 `credentials:'omit'`；原站 Cookie 不随采集 POST 发送到 Core |
| 成功信封 | v1 接口包含 `schema_version:1,ok:true`，并携带对应业务结果 |
| 失败信封 | 契约错误通常为 `schema_version:1,ok:false,error`，部分带 message；401／网关等通用错误可为 `{error,message}` |
| 确认要求 | HTTP 200 或空对象不足以确认保存；必须核对 request_id、候选覆盖、结果状态及关联 ID |
| 超时及重试 | 插件 API client 超时12秒；Outbox 自动提交最多3次。同请求原样重试或查询原回执，不能因超时断言后端未写入 |
| 幂等 | 首次保存按 owner＋request_id＋请求体摘要；相同返回原回执，不同内容同 ID 返回409 |
| 时间单位 | observed_at：UTC epoch 毫秒；后端 *_at、任务 expires_at：UTC epoch 秒；interval_s：秒 |
| 长度单位 | 字符约束不是UTF-8字节数；JS字符串长度与Python Unicode长度对非BMP字符可能不同 |

### 2.2 接口清单及数据方向

| 方法与路径 | 发送 → 接收 | 用途 |
|---|---|---|
| POST `/api/v1/captures` | 插件 → Core | 校园原生事项，targets 批次保存 |
| POST `/api/v1/web-captures` | 插件 → Core | 普通网页 fragments 整组保存 |
| POST `/api/v1/timeline-captures` | 插件 → Core | Moodle Timeline 活动摘要整组保存 |
| GET 上述三个路径的 `/{request_id}` | 插件 → Core → 插件 | 查询同 owner 的持久保存回执 |
| GET `/api/v1/capture-context` | 插件 → Core → 插件 | 获取采集代次和有效资源引用 |
| POST `/api/v1/reading-devices/heartbeat` | 插件 → Core | 执行设备心跳 |
| POST `/api/v1/reading-jobs/claim` | 插件 → Core → 插件 | 领取 Core 计划中的租约任务及原条件 |
| POST `/api/v1/reading-jobs/{id}/result` | 插件 → Core | 上报新匹配快照或失败状态 |
| GET `/api/v1/reading-sources` | 工作台 → Core → 工作台 | 查询条件来源、资料关联及实际执行状态 |
| PUT `/api/v1/reading-sources/{id}` | 工作台 → Core | 修改检查方式、周期或暂停状态 |
| POST `/api/v1/reading-sources/{id}/activate` | 工作台 → Core | 请求首次刷新／明确重绑并启动周期 |
| POST `/api/v1/reading-sources/{id}/check` | 工作台 → Core | 请求一次验证或检查 |
| GET `/api/v1/reading-sources/{id}/checks` | 工作台 → Core → 工作台 | 查询最近50条检查日志 |

扩展内部 `extract.start` 的版本为2；网络 schema_version 为1；原生 target.recipe.version 当前为2；reading.version 与 resident.version 均为1。版本号属于不同对象，不能互换。

预览只在插件本地保存，不将非匹配正文上传。明确保存经过持久队列后，才调用三类 POST 之一。单片段／原生正文上限20000字符，预览最多100条，保存1–30条；集合格式化正文总长也须≤20000，超限拒绝，不静默丢弃候选。

周期检查由 Core 单一调度，插件每分钟尝试 heartbeat/claim。租约180秒，同一任务最多领取3次；同页最多10条独立租约共用刷新，各自上报。当前30／60／120分钟周期不是精确定时保证；离线期间不逐次补跑。Cookie不由后端保活，原站登录过期需用户重新登录。

### 2.3 Core 内部调用

以下为进程内调用，不使用 HTTP 字段描述：

| 函数签名（省略self） | 调用方式 |
|---|---|
| `BrowserMonitorService.capture(uid: int, body: Any, *, from_reading_job: bool = False) -> dict[str, Any]` | async；路由await native.capture(uid, body) |
| `WebCaptureService.capture(uid: int, body: Any, *, from_reading_job: bool = False) -> dict[str, Any]` | async；路由await web.capture(uid, body) |
| `ReadingSourceService.attach(uid: int, body: dict[str, Any], receipt: dict[str, Any], kind: str) -> int \| None` | async；保存事务通过on_capture回调关联来源；原生批次有failed时不建立关联 |
| `Pipeline.ingest(msg: dict[str, Any]) -> dict[str, int]` | async；保存服务await pipeline.ingest(msg) |

前两项完成契约、身份、幂等及保存事务；Timeline 使用配置了 `TimelineCaptureContract` 的 WebCaptureService 实例。可选 reading 在同事务内关联资料与条件来源。`from_reading_job` 是内部受控参数，**不是插件可上传的字段**。

## 3. 输入

本节“输入”均从接收方 Core 视角定义；3.7另列 Pipeline 的进程内输入。

### 3.1 首次保存的公共字段

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| schema_version | integer | 必填 | 固定1 |
| request_id | string | 必填 | 当前插件用预览任务UUID；集合端点要求规范UUID，原生端点允许1–100字符；重试保持不变 |
| device_id | string | 必填 | 1–100字符，当前插件生成安装UUID；不是网站账号 |
| capture_generation | integer | optional，当前插件携带 | 账号当前采集代次，0..2^53-1；省略按0处理，仅兼容从未永久清理的账号；代次变化后旧预览重新提取 |
| reading | object | optional；Timeline外部保存必填 | 原条件与来源配方，见3.5；当前主流程携带，resident决定周期申请 |

三类内容结构独立，不能把下列对象合并为任意字段包。集合服务投影掉 reading/capture_generation 后严格校验内容，未声明的 html/dom/metadata 等字段会拒绝。

### 3.2 普通网页保存：`POST /api/v1/web-captures`

公共字段之外，内容对象严格包含 source/query/match_scope/observed_at/source_binding/fragments。

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| source | object | 必填 | 仅含 url、title |
| source.url | string | 必填 | ≤2048，HTTP(S)，无URL用户名密码；保留业务query/hash；拒绝已知校园专用域名及敏感凭据参数 |
| source.title | string | 必填 | 页面标题，1–300字符 |
| query | string | 必填 | 原提取条件，trim后1–200字符 |
| match_scope | string | 必填 | content或title；分别为正文／列表匹配、标题／链接标题匹配 |
| observed_at | number | 必填 | 浏览器观测毫秒，有限、>0，最多超前服务器5分钟；不是服务端检查成功时间 |
| source_binding.kind | string | 必填 | public或labeled；是原站来源声明，不决定资料共享权限 |
| source_binding.label | string | 必填 | NFKC规范化，1–80字符；public固定“公开网页” |
| source_binding.identity | object | optional，仅labeled | 账号控件观测证明；不是原站登录凭据，见下表 |
| fragments | array | 必填 | 1–30，整组对应一份资料；零匹配不能保存为空集合 |
| fragments[].candidate_id | string | 必填 | 1–100，批次唯一；如candidate-1，不是持久业务身份 |
| fragments[].title | string | 必填 | 1–300，片段标题 |
| fragments[].text | string | 必填 | 1–20000，清理空白后的匹配块文本，不是HTML |
| fragments[].evidence | object | 必填 | 仅含channel/locator/text |
| evidence.channel | string | 必填 | 固定dom |
| evidence.locator | string | 必填 | 1–4000，DOM原文定位描述；不充当业务身份或可靠重入selector |
| evidence.text | string | 必填 | 必须等于片段text |
| fragments[].context | object | 必填 | 仅含下列四个context字段 |
| context.frame_url | string | 必填 | 必须等于source.url，当前只读主frame |
| context.boundary | string | 必填 | paragraph、list_row、table_row、section、text之一 |
| context.completeness | string | 必填 | 固定fragment；不宣称完整文章／邮件 |
| context.matched_by | string | 必填 | 固定literal；字面条件匹配 |

source_binding.identity严格为：

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| version | integer | 提供identity时必填 | 1 |
| probe | string | 提供identity时必填 | account-control-email-v1 |
| account_key | string | 提供identity时必填 | 64位小写十六进制，设备加盐的账号指纹 |
| display | string | 提供identity时必填 | ≤100，脱敏显示如s***@example.test |

public不能带identity；Gmail／QQ邮箱不能声明public。labeled标签和正文里的邮箱不能证明当前登录账号。资料始终按Campus Radar owner隔离。

集合保存为一份网页资料，后端格式化 `【片段 n】标题\n正文`，总长≤20000。每个fragment没有独立URL、fields或原生entity_id；普通网页的source.url才是该资料来源。

### 3.3 校园原生事项保存：`POST /api/v1/captures`

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| binding | object | 必填 | adapter/origin/account_key；来源及原站账号绑定 |
| binding.adapter | string | 必填 | 当前moodle、student、fie；兼容manual |
| binding.origin | string | 必填 | 与target URL同源的HTTP(S)来源 |
| binding.account_key | string | 必填 | 非空≤200，当前设备加盐账号指纹；公开FIE为public，学校登录来源不能public |
| targets | array | 必填 | 1–30个原生身份明确、满足保存策略的匹配事项 |
| targets[].candidate_id | string | 必填 | 非空≤200，批次唯一，逐项回执关联 |
| targets[].entity_id | string | 必填 | 非空≤200，assignment:/notice:/person:/timetable:/manual:后接无空白原生身份；不按标题、内容hash或位置生成 |
| targets[].locator | object | 必填 | url/frame_url/view |
| locator.url | string | 必填 | HTTP(S)、≤2048、与binding同源，保留必要路由／query/hash |
| locator.frame_url | string | 必填 | 当前必须等于locator.url；跨frame不支持 |
| locator.view | object | 必填 | 字符串键值，compact JSON≤2000字符；route/query/projection及必要课表上下文 |
| targets[].raw | object | 必填 | title/text/fields；字段原文，不是HTML |
| raw.title | string | 必填 | 1–300字符 |
| raw.text | string | 必填 | 1–20000字符，空、纯登录或loading壳不能当有效内容 |
| raw.fields | object | optional，默认{} | 白名单原文字段，值均为字符串、允许空、每值≤2000 |
| targets[].recipe | object | 必填 | 当前snapshot recipe，见下文 |
| targets[].supported | boolean | 必填 | 当前recipe v2固定false，不能用旧monitor独立调度 |
| targets[].enabled | boolean | 必填 | 当前主流程固定false；周期监测由reading来源负责 |

当前recipe的键为 `{adapter,version:2,strategy:"snapshot",entity_id,url,view}`，须与binding、entity_id及locator一致。历史version1/selector仍兼容，但不作为本报告的新提交方式。

raw.fields允许的全部键：

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| subtype | string | optional | 原文资料子类型，如teacher_profile、timetable |
| course / course_code / class_group | string | optional | 课程原名、课程代码、班组 |
| semester / week / weekday / period | string | optional | 学期、周次、星期、节次上下文；不足以直接推算日期 |
| location | string | optional | 原文上课地点等 |
| datetime_text / date_text | string | optional | 原文时间／日期，不是归一化时间戳 |
| published_text / valid_until_text | string | optional | 发布时间／有效期原文，与作业截止不同 |
| department / office / email / phone / role | string | optional | 主体资料中的部门、办公室、电邮、电话、职务 |
| requirements | string | optional | 原文提交要求 |

白名单不代表各适配器已填满所有字段。当前原生上传**不含**预览evidence、presentation、coverage、missing_fields、完整度、document.title或observed_at；不能在后端假定这些数据存在。

### 3.4 Timeline保存：`POST /api/v1/timeline-captures`

沿3.2集合结构，以下字段替换或新增；其余约束相同。

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| collection_type | string | 必填 | 固定timeline_summary |
| source.url | string | 必填 | HTTPS Moodle /my/；本地合成来源另允许localhost/127.0.0.1的/my/或/capture/moodle-dashboard |
| source_binding | object | 必填 | 严格为adapter=moodle、origin、account_key；与generic的kind/label结构不同；禁止public/unverified |
| query | string | 必填 | 显式Timeline／时间线条件 |
| match_scope | string | 必填 | 固定content |
| fragments[].url | string | 必填，新增 | 同源活动详情URL；不得含凭据或action参数，不代表已打开详情 |
| fragments[].fields | object | 必填，新增 | 严格course/date_text/datetime_text三个字符串，每值≤1000，缺失为空 |
| fragments[].evidence | object | 必填 | channel=dom，locator≤4000，text≤22000且包含片段text；可含日期分组上下文 |
| fragments[].context | object | 必填 | 严格为frame_url=source.url、region=Timeline、completeness=summary |
| reading | object | 外部首次保存必填 | source=moodle、representation=timeline_summary；choice为空，view={}；intent.kind=auto、fields=[]、target为Timeline／时间线 |

整组保存为一份活动摘要资料，保留标题、课程、日期／时间原文和链接，不伪造独立事件ID、不作为完整assignment，不推断摘要缺失日期。后端排序后格式化总文本≤20000。

### 3.5 原条件来源配方 `reading`

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| version | integer | 必填 | 1 |
| url / query / match_scope | string | 必填 | 与提交来源和原条件一致；url≤2048，query≤200，scope为content/title |
| source | string | 必填 | generic、moodle、student、fie |
| intent | object | 必填 | 原条件解释，version=2、query一致、fields为字符串数组，compact JSON≤2000 |
| intent其他键 | string/boolean/array | 按提取结果携带 | mode、match_scope、kind、target、keyword、fields、current、all；不能作为自由扩展字典 |
| choice | string | 必填 | 可空、≤100；用户确认的课程范围ID |
| view | object | 必填 | 字符串字典、compact JSON≤2000；必要projection/semester/week/weekday/period |
| binding | object | 必填 | 严格adapter/origin/account_key；adapter等于source、URL同源；不是原站凭据 |
| source_label | string | optional | ≤80，可空；generic须与source_binding.label一致 |
| account_probe | object | optional | generic账号已核对时为version=1、kind=account-control-email-v1、display，与identity一致 |
| representation | string | optional | 当前仅timeline_summary，用于显式Moodle摘要集合 |
| resident | object | optional | 专用标签页周期申请；不参与原规则身份，不应因开启监测重建资料 |
| resident.version | integer | 提供resident时必填 | 1 |
| resident.session_id / page_id | string | 提供resident时必填 | 规范UUIDv4，不透明会话／页面引用，不含tabId或Cookie |
| resident.refresh | string | 提供resident时必填 | 固定reload |
| resident.interval_s | integer | 提供resident时必填 | 1800、3600或7200 |

generic的reading.binding.account_key为public、已核对指纹或unverified。unverified仅在已确认resident单会话模式下允许后台重读，不能宣称原站账号已认证。当前同owner/device/origin绑定一套原站会话，可设多个关键词；未观察到的账号切换不能保证识别。

### 3.6 监测控制及结果上传

| 接口／字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| heartbeat、claim的device_id | string | 必填 | 请求仅含device_id，≤100；owner由Bearer确定 |
| 配置请求revision | integer | 必填 | 当前来源修订，旧修订409 |
| 配置请求mode / paused / interval_s | string/boolean/integer | 必填 | 请求仅含revision及这三个键；mode为manual/periodic，周期1800/3600/7200；启用未验证来源拒绝 |
| activate请求revision / interval_s | integer | 必填 | 请求仅这两个键；排队首次实际刷新，不是立即成功 |
| check请求revision / purpose | integer/string | 必填 | 请求仅这两个键；purpose为verify/check |

`POST /api/v1/reading-jobs/{id}/result`：

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| schema_version | integer | 必填 | 1 |
| device_id | string | 必填 | 必须匹配任务设备 |
| lease | string | 必填 | claim返回的当前租约 |
| revision | integer | 必填 | 同时匹配任务和当前规则修订 |
| status | string | 必填 | success或下列失败枚举；不是客户端自行计算changed/unchanged |
| account_key | string | status=success时必填 | 与原reading.binding一致 |
| snapshot | object | status=success时必填 | 新匹配结果，三种形态见下表 |
| resident | object | activate成功时必填，其他时禁止 | 与激活任务匹配的专用页描述符 |

失败请求只能含schema_version/device_id/lease/revision/status五个键，不接受snapshot/account_key或任意error详情。成功请求的键集合也严格校验。

| snapshot类型 | 实际内容 |
|---|---|
| 原生 | binding＋targets；沿3.3，recipe v2、enabled=false，视图与原条件一致 |
| generic | schema_version/request_id/source/query/match_scope/observed_at/source_binding/fragments；浏览器构造时不含device_id，由后端沿初始基线重建 |
| Timeline | generic列出的结构加collection_type，使用3.4的source_binding/fragments；同样由后端重建集合身份 |

结果snapshot不带初次传输控制reading/capture_generation。集合的URL/query/scope/binding必须与基线一致，后端只采用新observed_at/fragments并保留初始标题／身份。

允许的失败status为：need_login、account_unknown、account_mismatch、route_mismatch、view_mismatch、permission_denied、render_timeout、selection_missing、no_match、unsupported、failed、worker_interrupted、preview_only、private_source_required、tab_missing、tab_rebind_required、tab_ambiguous、user_busy、single_account_conflict。未分类浏览器异常当前仅上报failed，没有细分stage或堆栈字段。

### 3.7 Core传给Pipeline的输入（进程内）

`await Pipeline.ingest(msg)` 接收已校验、已投影的事项字典，不重新读取Chrome或HTML：

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| msg.source_id | integer | 必填 | 已建立的底层sources ID，不是reading规则ID |
| msg.status | string | 必填 | 正常采集保存为ok |
| msg.prev_status | string | 按调用携带 | 前一来源状态，当前保存服务传ok |
| msg.items | array | 成功保存必填 | 已投影的事项集合 |
| items[].key | string | 必填 | 原生browser:monitor_id，集合web:capture_id；Pipeline再加owner前缀 |
| items[].kind | string | 必填 | 原生assignment／event／notice；generic和Timeline为clip |
| items[].title / body / url | string | 必填 | 原生标题／正文／来源；集合标题及格式化片段正文／来源URL |
| items[].course / requirements | string | optional | 从原生原文字段投影；不由插件编造缺失信息 |
| items[].attrs | object | 必填，当前保存路径携带 | 原生raw_fields、subtype、browser_monitor_id等；集合web_capture、subtype；课表／集合设置suppress_deadline |

Pipeline负责已有摘要／事实提取、适用日期提取、版本比较和投递。新处理逻辑应保留原文，不把处理后summary当原文，不将来源更新覆盖个人note／deadline_override。读取结果及存储映射详见[完整说明第4节](browser-data-handoff-v1.md#4-输出后端接收处理存储和客户端)。

## 4. 输出

### 4.1 保存回执

| 字段 | 类型 | 说明 |
|---|---|---|
| schema_version / ok | integer/boolean | 成功为1／true；不代表每个原生target都成功 |
| request_id | string | 与提交一致，支持持久查询 |
| results | array | 原生逐项；generic／Timeline恰好一个collection结果 |
| results[].candidate_id | string | 原生对应请求candidate_id；集合固定collection |
| results[].status | string | new、changed、unchanged；原生还可为failed |
| results[].item_id | integer | 成功关联资料ID，正整数 |
| results[].monitor_id | integer | 原生成功项；即使snapshot-only也承载原生身份，不等同当前reading监测状态 |
| results[].capture_id | string | 集合成功项UUIDv4，不是原站事项ID |
| results[].source_id | integer | 集合成功项，底层sources ID |
| results[].version | integer | 集合成功项，当前内容版本，正整数 |
| results[].fragment_count | integer | 集合成功项，等于提交片段数 |
| results[].error / message | string | 原生失败项的错误码／说明，不应当作整批保存成功 |
| candidate_ids | array | 集合回执，按请求顺序覆盖全部fragments的ID |
| capture_type | string | Timeline固定timeline_summary；generic没有该必填字段 |
| reading_source_id | integer/null | 有reading且全部结果正常时为正整数条件规则ID，与底层source_id不同；原生批次含failed时可为null，不能据此显示来源已关联 |
| monitoring | object | resident保存时为state=starting、mode=resident、interval_s；只表示启动申请，非监测成功 |

原生要核对结果数量、顺序和candidate_id，并分别处理failed；集合要核对恰好一项结果及全部candidate_ids，禁止只凭HTTP200显示成功。

### 4.2 任务、监测确认及来源状态

| 字段 | 类型 | 说明 |
|---|---|---|
| heartbeat.device_id | string | 回显设备；150秒内心跳表示近期在线，不证明原站登录有效 |
| claim.job | object/null | 无可领取任务为null；否则包含下列job字段 |
| job.id / source_id | integer | 任务ID／**reading_sources规则ID** |
| job.device_id / revision / lease | string/integer/string | 后续结果必须原样匹配，不能跨设备或复用旧修订 |
| job.expires_at | number | 租约截止，UTC epoch秒 |
| job.purpose / interval_s / recipe | string/integer/object | verify/check/activate，周期及原reading配方 |
| job.companions | array，optional | 同页最多额外9条独立租约，各自提交结果 |
| result.job_id | integer | 确认的任务ID |
| result.status | string | changed、unchanged或failed，由后端判定 |
| result.result | string | verified、changed、unchanged或具体失败状态；verified的status映射unchanged但不是一次内容检查成功 |
| sources | array | 来源列表，各项含id/device_id/revision/recipe/mode/paused/verified及下列状态 |
| sources[].last_result / error | string | 最近执行结果／错误；可有starting、result_rejected等服务器状态 |
| sources[].last_attempt_at / last_success_at / next_at | number/null | 最近尝试、最后成功和下次计划；秒 |
| sources[].pending / execution_state | string | pending为待执行目的；execution_state为queued/running/expired/idle |
| sources[].active_job | object/null | 仅有效未过期任务的id/purpose/expires_at/claimed_at |
| sources[].items / match_count | array/integer | 关联资料摘要／当前基线匹配条数 |
| sources[].device_online / capability | boolean/string | 设备近期在线；capability为account_unknown/unverified/ready |
| sources[].interval_s / effective_interval_s | integer/number | 配置周期／实际执行周期；loopback测试可加速，真实站点仍用生产周期 |
| checks | array | 最近50条job_id/purpose/result/detail/checked_at；detail可含关联结果或拒绝错误 |

verify成功只确认读取能力，不更新内容基线／last_success_at；activate/check实际成功才更新成功时间，变化更新原资料版本，无变化不造新版本。need_login、no_match、超时等失败不覆盖成功快照或时间；user_busy延后60秒，resident临时失败累计3次暂停，身份／权限／绑定失效立即暂停。

有效租约结果被422拒绝时，内容事务回滚，后端记录result_rejected及detail.error并结束任务／暂停规则；HTTP仍返回原422。result_rejected不是客户端允许上传的status，不能用200成功结果上报代替。

### 4.3 后端处理结果与工作台读取

| 字段／接口 | 类型 | 说明 |
|---|---|---|
| Pipeline.ingest返回值 | dict[str,int] | new/changed/merged/removed/duplicate计数；不直接作为插件HTTP响应 |
| GET `/api/items/{id}` | object | 当前owner资料详情，含body/raw_title/summary/source_fields/web_capture以及关联来源；该既有接口不是v1信封 |
| source_fields | object | 原生raw.fields的输出，保留原文字段 |
| web_capture | object/null | 集合source/query/scope/binding/observed_at/completeness/fragments等元数据；Timeline另含collection_type |
| GET `/api/items/{id}/versions` | object | versions数组，含version/changed_fields/important/change_note/detected_at，不是完整HTML或原始上传包 |
| GET `/api/feed`、`/api/sync`、WebSocket `/ws` | object/消息 | 资料列表及每用户seq投递／补发；与保存回执查询不同 |

原生原文依据未上传，历史版本也不是完整DOM档案。web_capture.monitoring=false是快照元数据兼容值，当前监测应读取reading来源状态，不能用该值判定周期关闭。

### 4.4 错误输出

| 字段 | 类型 | 说明 |
|---|---|---|
| schema_version / ok | integer/boolean，可能存在 | v1契约错误通常为1／false；公共鉴权或网关错误不保证包含 |
| error | string | 错误码，处理依据 |
| message | string，optional | 展示说明；未提供时不能假设存在中文文案 |

| HTTP／错误 | 说明 |
|---|---|
| 401 unauthorized | Campus Radar登录失效，与原站need_login区分 |
| 404 not_found | 不存在／非当前owner的资源或回执 |
| 409 idempotency_conflict | 同request_id或已完成任务提交不同内容 |
| 409 capture_context_changed | 永久清理使旧预览失效，需要重新提取 |
| 409 stale_lease / revision_conflict | 租约过期／设备或修订不符，旧结果不能写回 |
| 409 source_deleted / binding_or_recipe_changed | 已删除来源／绑定变动，不能靠旧重试复活 |
| 422 invalid_request / invalid_snapshot / invalid_evidence等 | 严格字段或内容契约不符，按具体error定位 |
| 422 specialized_source_required / private_source_required | 专用站点或私人来源声明约束，不能绕过 |
| 5xx／网络超时 | 结果未确认，沿原request_id查回执／有界重试 |

**交接示例：** [合成JSON请求及回执](browser-data-handoff-v1.examples.json)包含三种首次保存、claim、成功／失败结果的完整对象；每个顶层键为独立报文示例，不可将整个文件作为一次POST。示例无真实Cookie／账号／原站正文，目标环境的token、generation、lease、revision必须动态获取。

**规范及实现依据：** [原生事项](browser-capture-v1.md)、[通用网页](universal-web-capture-v1.md)、[Timeline](timeline-summary-v1.md)、[条件来源](condition-monitoring-v1.md)、[专用监测页](resident-monitoring-v1.md)及[完整源码／流转索引](browser-data-handoff-v1.md#10-源码索引与兼容文档)。本文仅重组当前契约，没有把后续建议字段写成已实现接口。
