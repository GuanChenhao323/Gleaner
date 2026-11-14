# Interface Contract — 输入条件 → DOM 读取 → 预览保存

**接口 ID：** IC-EXTRACTION-001

**版本：** v2.2（2026-11-14）

**负责人：** 插件／网页采集

**最后更新：** 2026-11-14

## 1. 接口概述

| 项目 | 说明 |
|---|---|
| 发送模块 | 单弹窗的 CaptureController |
| 接收模块 | PageExtractionService、DomPageReader、页面范围适配器、DraftRepository |
| 接口用途 | 先确定用户条件和页面范围，只提取匹配内容；明确保存全部预览结果 |
| 通信方式 | 扩展 runtime message；内容脚本处于 isolated world；不使用 AX、debugger、OCR 或学校私有 API |

扩展内部消息版本与后端信封版本独立。校园原生事项保存复用 [IC-BROWSER-001](browser-capture-v1.md) 的 schema_version=1 和 snapshot recipe v2，不增加新的网络端点。原 v1 无条件 channel/section 读取请求被拒绝；历史草稿只读，不自动迁入新保存流程。既有监测 recipe v1 仍兼容。

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


## 5. v2.1 当前页指定信息读取（2026-11-14）

用户确认：普通课程名／关键词预览当前页相关信息；显式 assignments 意图只返回作业。当前页边界与手动打开详情的规则不变。用户已明确确认课程卡片只预览入口，进入详情后保存。本轮不新增课程资料事项类型；完整事项才允许整批保存。

DOM 访问分离两个对象：ContentBoundaryPolicy 决定可读容器及非内容区域；DomAccess 读取可见文本、链接和证据。MoodlePageModel 在选定主区域内仅授权已观察的 aside#block-region-content[data-blockregion=content] 内容区域。隐藏、nav、form、footer 等规则不可被区域授权绕过，其他站点默认策略保持兼容。

MoodleCourseCatalog／CourseScopeResolver 负责必要课程标题与原生 ID 索引和歧义确认；MoodleAssignmentExtractor 只读取课程归属明确的作业；MoodleCoursePreviewExtractor、MoodleSectionExtractor 只预览匹配卡片／明确标题的有限区块。原生 ID 是定位依据，不把位置或临时 DOM ID 用作可保存事项身份。

新增可选字段：records[].preview_reason（navigation_only/section_preview_only/attachments_only）、records[].record_type；候选保留 record_type 与明确预览原因。预览专用记录不能生成可提交 target。新增 result.outcome={status,page_type}，status 为 matched/no_match/navigation_required/needs_choice，旧草稿缺失时由候选／navigation 推导，runtime 消息版本仍为 2。未识别页面结构抛 unsupported_dom，而不是构造 succeeded 的空列表；加载状态仍有界等待后 render_timeout。

普通关键词以课程／活动标题或区块标题定位，不扫描整页正文再筛选；显式选定区块允许读取其当前已加载内容。未匹配正文不出现在快照、预览或上传中。不自动展开控件、翻页或发起请求；跨 frame 不隐式采集。新流程保存仍复用 snapshot recipe v2，不启用监测。

附件型作业仅读取当前主区域内已加载的 mod_assign/introattachment 链接名称及安全 URL，不下载或解析文件，始终 attachments_only。作业详情支持以当前活动标题匹配；以课程名匹配时优先使用原生课程面包屑的 title 属性全文，而不是仅使用短课程代码。源路径限定为已登记的 /my/、/course/view.php、/mod/assign/view.php（loopback 合成夹具例外）。

新增结构回归：extension/tests/moodle-reading.test.js。输出声明的是有界的标题／课程归属／区块读取，不是任意网页全文语义搜索。

## 6. v2.2 区域与分组契约

实施目标：课程范围与字段请求分开解析；Moodle Dashboard 在 #region-main 与已标记 side-pre 的有限具名区块中定位。只授权 Timeline 和标题匹配 Moodle Support 的 HTML 联系区块，不授权整个侧栏。目标区块未找到/无法识别返回 unsupported_region，加载中沿用 page_not_ready 有界重试；已识别且确无活动才返回 no_match。不同区域分别报告 coverage.regions（id、title、status）；不输出未匹配区块正文。

records/candidates 新增可选 presentation={group,region,matched_by,course_relation}，仅供 UI 解释和分组，不作为业务身份、后端分类或上传字段。group 为 courses/assignments/timeline/contacts/sections；course_relation 为 native/unconfirmed/none。raw.fields.course 与活动主标题分开；title 不含图标类型说明或拼接的课程上下文。原站真的名为 assignment 时保留，不凭字符串删词。原文 evidence 仍保留必要范围的对照。

Timeline 按当前已加载的活动单元返回 timeline_event（原生事件身份未确认，entity_id 为空；详情 URL 作为来源），preview_reason=timeline_preview_only，不能把截止摘要当作完整作业。日期/时间只保留原文，不计算时区或推断缺失日期；每个活动单元只选主链接，操作链接不重复生成记录。同 URL 的不同活动行保留，不把活动详情 ID 冒充日历事件 ID。Support 返回 contact_info，preview_reason=contact_preview_only，仅按用户 fields 投影；不访问聊天链接或创建待办。所需字段缺失列 missing_fields，不冒充完整成功。

字段请求不再直接决定 kind=people；明确人员词仍为 people，普通联系方式由站点/区域适配器解释。旧人员查询兼容。普通课程词先在课程索引中确认范围，再只读取有原生归属证明的活动；不能将合并标题中的课程子串当作身份依据。分组由 presentation 提供，旧草稿无该字段时按 record_type 渲染。

完整双语名称的原文别名优先于较长相似名称；相同别名的多个原生课程仍须确认范围，不推测同义词。coverage.course_index 可包含 native_links/indexed_courses/excluded_boundary/excluded_visibility/empty_titles 非负计数，供“识别范围”诊断；不包含未匹配课程正文或身份列表。coverage.regions.status 为 matched/no_match/not_ready/unsupported/fields_missing；未读取区域不能写作无变化或已保存。邮箱投影优先读取原生 mailto，不序列化其他联系字段。

实机补充边界（2026-11-14）：Moodle 把课程概览正文包装在 .block_myoverview 内的 .block-myoverview[data-region=myoverview][role=navigation]。仅将此已识别容器的 role 作为内容授权；真实 nav/header/footer/form、其下的其他 role=navigation 和隐藏内容仍排除。ContentBoundaryPolicy 的显式内容角色集合与 aside 授权独立，不允许站点适配器全局关闭导航过滤。

如果课程概览中有可见原生 coursename 链接却被未知内容边界阻断，主范围读取返回 unsupported_dom，不能仅用最近访问课程建立部分索引后报告成功或零匹配。明确指定右侧区块的读取不受无关左栏结构失败影响。

保存、幂等、身份和网络契约不变。混合入口/摘要预览仍禁止整批保存；用户缩小为“课程名的作业”或进入原文详情后重新抓取。此修订先于代码，现已按此实现；分层验证与限制在本轮本地报告中记录。

## 7. 通用 DOM 扩展（2026-11-14）

见 [IC-WEB-CAPTURE-001](universal-web-capture-v1.md)。runtime version=2 兼容增加 match_scope=content/title，默认 content；通用域名使用 LiteralIntentParser，校园专用语法不变。任务记录 match_scope；泛站候选类型 web_fragment，entity_id=null、target=null，account.state=unknown，独立 FragmentPipeline 校验，不通过校园 CandidateFactory 冒造身份。

extract.save 在 generic 结果时额外接收 source_binding={kind,label}，首次提交前持久冻结；不同标签重试报 idempotency_conflict。只接受任务冻结正文，不接受 UI 新正文或子集。原生结果拒绝此字段，仍走 v1 captures。通用走新的 web-captures 持久 outbox；原请求即使保存回执丢失也复用任务 UUID。

匹配定位是当前 DOM 本地遍历，不声称从未读取非匹配文本；边界保证非匹配正文不序列化、不上传。主 frame＋开放 Shadow DOM，嵌入页面覆盖明确提示。已知校园域名不回退 generic；不扩大其身份／账号或只预览策略。


2026-11-15：界面收敛为单弹窗，独立双栏页移除；UI 状态、连接检查和指定请求重试见 [IC-PANEL-001](capture-panel-v1.md)。本次不改变提取 version=2、原生身份、完整度和保存网络契约。
