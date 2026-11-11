# Interface Contract — 输入条件 → DOM 读取 → 预览保存

**接口 ID：** IC-EXTRACTION-001

**版本：** v2.0（2026-11-11）

**负责人：** 插件／网页采集

**最后更新：** 2026-11-11

## 1. 接口概述

| 项目 | 说明 |
|---|---|
| 发送模块 | popup／独立预览页的 CaptureController |
| 接收模块 | PageExtractionService、DomPageReader、页面范围适配器、DraftRepository |
| 接口用途 | 先确定用户条件和页面范围，只提取匹配内容；明确保存全部预览结果 |
| 通信方式 | 扩展 runtime message；内容脚本处于 isolated world；不使用 AX、debugger、OCR 或学校私有 API |

扩展内部消息版本与后端信封版本独立。保存复用 [IC-BROWSER-001](browser-capture-v1.md) 的 schema_version=1 和 snapshot recipe v2，不增加新的网络端点。原 v1 无条件 channel/section 读取请求被拒绝；历史草稿只读，不自动迁入新保存流程。既有监测 recipe v1 仍兼容。

## 2. 通信协议

成功 `{ok:true,value}`，失败 `{ok:false,error}`。后台只接受本扩展可信页面发来的消息；不将 token 或草稿暴露给内容脚本。

| 消息 | 输入 | 输出 |
|---|---|---|
| extract.start | version=2、UUID request_id、整数 tabId、完整 url、query、可选 choice | `{id}`；先持久 queued，再异步执行 |
| extract.get | id | 当前 owner 的任务／结果／可选 submission |
| extract.list | 无 | `{tasks}`；摘要不含正文、owner、内部签名 |
| extract.delete | id | `{}`；只删除预览，不撤销已保存事项或提交 |
| extract.save | id、query | `{request_id,device_id}`；表示持久入队，不代表保存成功 |

owner 为后端 origin+uid；表单也按 owner+原标签隔离。query 修改立即失效旧预览。任务保留 24 小时，每账号最多 10 条、全扩展 20 条、总序列化 2.5M 字符；提供查看／删除预览入口。worker 重建时 queued/running → interrupted，保留成功草稿，不伪装继续持有旧 DOM。已完成预览可在原页关闭后保存。

同 owner 同 request_id 同输入返回同任务；不同输入报 idempotency_conflict。任务 ID 同时用作确定性保存 request_id，后台意图签名及后端持久幂等覆盖提交后、回执登记前回收的窗口。outbox 最多三次自动提交，HTTP 200、空 JSON 或缺失逐项 ID 都不能算成功。

## 3. 输入

| 字段／对象 | 类型 | 约束 |
|---|---|---|
| query | string | trim 后 1–200 字符；不接受空输入并回退全页 |
| url | string | 精确绑定当前完整 URL（query/hash）；凭据与敏感查询参数拒绝 |
| choice | string optional | 用户从歧义课程中确认的原生数字 ID；重新核对属于当前条件，不能绕过范围 |
| IntentParser.parse(query) | 进程内对象 | `{version:2,query,kind,target,keyword,fields,current,all}` |
| DomPageReader.read(tabId,intent,choice) | 进程内调用 | 只注入主 frame；有界稳定等待 12 秒；前后校验 URL／学校账号 |

支持课程名／标题关键词、基础繁简规范化、人员邮箱／办公室等字段，以及 `课程：网络编程；关键词：实验`。不是自由自然语言问答；复杂时间／排除／语义运算明确报 unsupported_query，不推断截止日期，不模糊替换课程名。

DOM 范围适配器先读必要课程名、标题和原生链接关系，再读取匹配的正文／字段。只返回匹配记录，不返回整页 HTML、非匹配正文、Cookie 或输入框值。课程所有权不明确时不读取其他课程作业；同名课程先返回 needs_choice，不提取作业正文。

## 4. 输出

| 字段 | 类型 | 说明 |
|---|---|---|
| state | enum | queued/running/needs_choice/succeeded/failed/interrupted；succeeded 可为零匹配，不表示已保存 |
| result.intent / coverage | object | 原条件、current_rendered_view、匹配依据及数量；不承诺未加载历史／全学期 |
| result.choices | array | 原生课程 ID、名称、原文上下文；仅用于确认课程范围 |
| candidates | array | candidate_id、原生 entity_id（可空）、raw、url、evidence、save_allowed/save_reason、missing_fields、target |
| raw | object | `{title,text,fields}`；标题≤300，正文≤20000；字段白名单由后端再校验 |
| evidence | array | 匹配原文片段及 DOM locator；locator 是依据，不充当业务身份 |
| account / binding | object | public/known/unknown；可靠账号原生标识在浏览器内转为设备加盐绑定，返回 UI 前移除原生账号 |
| warnings / navigation | array | 当前覆盖、缺失字段、需进入的已匹配课程入口；不自动导航 |
| submission | object optional | 持久提交 ID；须另查严格后端逐项回执 new/changed/unchanged/failed |

人员字段投影的稳定字段集合纳入 locator.view.projection，避免邮箱快照静默覆盖同一人员的完整资料。身份不依赖标题、内容 hash、页面位置或 DOM 临时 ID。课表保留学期／日期原文等上下文；原生课次身份未确认时只预览，不猜测可保存身份。

保存冻结全部匹配预览，不接收 UI 新正文或 candidate ID 子集；须同 query、1–30 条、全部可保存、具备可靠账号／原生身份及完整内容。任一不满足即禁止整批保存，让用户缩小条件或进入详情；列表摘要不能冒充已读取正文。结果只经明确保存进入 Core；snapshot recipe v2 强制 supported=false、enabled=false，不进入后台重读调度。重新抓取并明确保存同一身份可更新原事项／版本。

错误包括 query_required/query_too_long/unsupported_query、invalid_request/invalid_choice/idempotency_conflict、wrong_section/unsupported/unsupported_dom、need_login/account_unknown/account_mismatch/backend_account_changed、route_mismatch/selection_missing/render_timeout/page_read_failed、draft_limit/draft_not_found/worker_interrupted、preview_required/query_changed/preview_only/invalid_selection，以及严格网络回执错误。失败不沿用旧成功结果。

对应验证：`extension/tests/extraction.test.js`、`capture-ui.test.js`、`worker.test.js`、`extraction-live.mjs` 和后端 `test_browser_capture.py`。模拟 DOM／API、真实本地 HTTP、真实 Chrome／生产页面证据分别记录。
