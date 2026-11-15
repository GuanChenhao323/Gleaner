# 浏览器插件｜输入条件、匹配预览与明确保存

更新：2026-11-16，扩展 **0.10.0**。需求以 [产品定义](product-definition.md) 为准；内部契约见 [IC-EXTRACTION-001 v2.3](architecture/page-extraction-v1.md)，网络保存见 [IC-BROWSER-001](architecture/browser-capture-v1.md)。

## Timeline 活动摘要保存（0.10.0）

在已登录且可核对账号的 Moodle Dashboard 输入 Timeline／时间线，预览当前已加载活动后，“保存为一份活动摘要（N条）”将整组资料及原条件关联到工作台。仍显示“活动摘要”，逐条保留日期／时间原文与详情链接，不读取详情正文，不生成原生事件ID。旧冻结预览保持原限制，需重新提取；超过30条或正文20,000字符不截断保存，未知学校账号禁止保存。课程入口、Support及混合结果不在本次开放范围。

`TimelineSummaryPolicy`独立决定集合资格，`TimelineCapturePayload`投影冻结数据，持久outbox提交 `/api/v1/timeline-captures`；回执必须确认摘要类型、全部候选、资料版本和来源关联。后端通过 `TimelineCaptureContract`复用集合事务；原通用端点继续拒绝校园来源。来源配方新增 `representation:timeline_summary`，重读仍用同一DOM端口与账号核对，更新同一集合；重排不报内容变化，时间／链接变化可产生版本。

工作台标注活动摘要资料，显示活动详情链接及原文字段，来源验证／手动／周期与失败保护沿既有流程。[字段与身份契约](architecture/timeline-summary-v1.md)，本地复现脚本 `node devtools/timeline_monitoring_smoke.mjs` 使用模拟DOM／浏览器端口和真实loopback HTTP，不是真实Chrome验收。

## 原条件来源与后台检查（0.9.0）

当前入口不变：输入 → 预览 → 明确保存；新保存另带 `reading` 原条件上下文，事务内关联工作台来源。回执可进入统一信息源页；默认手动。重读测试通过后在工作台选择周期30／60／120分钟；暂停周期仍可立即检查。旧资料／演示来源折叠保留，无上下文草稿继续保存但不虚构监测配方。

关闭原标签／popup 后，由 `PageReentry` 创建非激活自有标签，使用 Chrome 最新原会话、等待 DOM 后调用同一提取器。`SourceSessionVerifier` 核对原学校账号，`ConditionalPageReader` 投影已匹配内容，`ReadingJobExecutor` 持久租约／outbox 和回执；Core 是唯一计划者。扩展每分钟心跳与领任务，手动“立即”表示排队而非同步网页请求。

会话不离开 Chrome，不新增 cookies/debugger 权限，最低 Chrome110不变。仅声明公开的泛站与具备可靠原生账号的校园来源可测试后台读取；私人泛站标签不足以确认身份，会明确保留当前页手动采集。权限撤销后需在原网页打开插件重新授权，未知路由／视图不自动重放交互操作。

契约：[IC-READING-SOURCE-001](architecture/condition-monitoring-v1.md)。原生 snapshot recipe v2 自身仍不调度，旧 v1 兼容执行器不同时拥有新条件来源的计划。失败、零匹配、需登录、未执行、无变化分开；验证不改基线，检查变化更新原资料。自动测试只使用本地／脱敏结构；真实平台授权与兼容性单独验收。

本地 HTTP 烟测：`node devtools/reading_monitoring_smoke.mjs`（实际 HTTP＋模拟 DOM／Chrome port，不是真实 Chrome）；完整分层证据在本地本轮报告。

## 单弹窗与通用网页提取（0.8.1）

面板默认520px宽、600px高，固定浅色；结果使用雾灰卡片、单行摘要与就地原文展开。浏览器弹窗尺寸声明在popup启动层，显示组件仅负责内容；通用来源标签、片段不完整说明、校园仅预览提示与错误回执继续保留。

普通 HTTP(S) 页面使用通用 DOM 提取，不再因域名没有登记而直接拒绝。已知校园域名仍优先使用专用适配器，其错误与仅预览限制不会回退绕过。具体网络契约：[IC-WEB-CAPTURE-001](architecture/universal-web-capture-v1.md)。

1. 当前页点击插件，输入字面关键词／短语；普通网页可选“正文与列表”或“仅标题与链接标题”。不做自由自然语言问答。
2. 点输入框右侧“提取”，在同一弹窗核对紧凑预览；卡片右上角“原文”查看完整片段、字段、原文依据和链接。不打开独立预览页。条件、范围或当前页 URL／hash 修改后旧预览不可保存。
3. 普通页片段允许保存。结果出现后选择“公开网页”，或输入私人来源标签并点“确定”；标签只隔离资料，不证明网站账号已认证。切换网页账号时换标签。一次保存整组，不逐条勾选。
4. 同工作台账号、来源标签、完整 URL、规范化条件、匹配范围组成一份资料。重新提取并明确保存后更新版本；不会按片段位置冒认原生事项，也不自动监测。工作台统一“信息源”可找到新资料；旧快照收在“旧资料与演示订阅”。
5. 提交持久入队和后端确认分别显示；通用回执必须逐一确认 fragment ID，再显示单份资料的新增／更新／已有及版本。worker 回收后的已完成预览可恢复；未完成读取明确中断。

采集面板内部约定见 [IC-PANEL-001](architecture/capture-panel-v1.md)。连接行通过 worker 调用既有 `GET /api/me` 核对 uid／email；本地配置不能作为连接成功证明。网络不可达仍可读取本地页面并保留预览，保存等待确认；401 提示重新登录工作台。设置在弹窗内折叠，不输入学校密码。最近记录仅查看原冻结预览，提取输入只读，并提供“返回当前网页”。重试只针对当前 request_id。预览与回执轮询不收起已展开内容。

遍历当前主 frame 可见文本定位命中，只序列化匹配的有限段落／列表行／表格行，支持开放 Shadow DOM；不读取隐藏内容、输入值、编辑草稿、脚本样式。不自动打开详情、翻页或读取 iframe、关闭 Shadow DOM、图片／画布。列表摘要不等于邮件正文。单片段≤20000字、预览≤100条、保存≤30个片段且整组格式化正文≤20000字；超限拒绝而不静默截断。

通用本地复现：启动结构夹具后打开 `/generic`（无适配标记），查询“项目会议”匹配两行，排除第三行、隐藏文本和输入值；保存整组后在管理台制造变化，回原页刷新、重新提取并明确保存。`node extension/tests/generic-live.mjs` 是模拟 DOM＋真实本地 HTTP；不是 Chrome 权限或 Gmail 验收。

对象边界：FragmentVisibility、FragmentText、FragmentBoundary、GenericFragmentExtractor 分别处理资格／投影／块边界／匹配；LiteralIntentParser 保持普通查询原词；FragmentPipeline、WebCapturePayload 校验预览／提交；WebCaptureContract、WebCaptureService 管理网络校验与集合身份；既有 Pipeline 管理事项和版本。没有新增第三方运行依赖、浏览器权限或 AX 支持。最低 Chrome 110 不变。

## 校园页面交互（保留原生身份规则）

1. Flutter 信息源提供学院公告／学生系统、教师信息、Moodle 三个真实入口。学生系统、Moodle 分别在原站自行登录；教师网页公开。不在 Campus Radar 输入学校密码。旧 localhost 演示订阅另列，不等于学校网站已连接。
2. 在原网页点插件，输入想抓取的内容，例如 `人工智能`、`Timeline`、`网络编程的作业`、`奖学金公告`、`这位老师的邮箱和办公室`。先输入条件，再点“提取”。所有操作均在工具栏弹窗内完成。
3. 插件先定位目标课程／标题／个人字段，再读取匹配内容。优先匹配原文中的完整双语课程别名；同名不同班仍只确认课程范围，不要求逐条选作业。零匹配不会变成整页采集；复杂条件明确拒绝。需要同时限制课程和标题可写 `课程：网络编程；关键词：实验`。
4. 课程概览与原生归属明确的作业分组显示；活动主标题、类型、课程原文分开，不删除原站实际名为 assignment 的标题。展开“读取范围与限制”和“原文依据”可核对覆盖与来源。核对整组匹配预览、原始字段、原文依据和限制，再点一次“保存匹配结果”。没有逐项复选框；不满足预期时修改条件重新抓取。修改输入立即禁用旧结果。
5. 入队与后端确认分开显示；只有严格逐项回执才能显示新增／更新／已有／失败及工作台链接。保存快照**不启用监测**；重新抓取后明确保存相同身份，可更新原事项与版本。

Moodle 普通课程词预览当前相关卡片及已加载信息；显式作业条件只读作业，Timeline 按已加载活动逐条预览，保留日期／时间原文；Moodle Support 独立读取联系信息，可输入“Moodle Support 的邮箱”投影字段。课程卡片、时间线摘要、联系区块和附件元信息标为仅预览，不能生成提交 target；本组含预览项时保存禁用，需缩小条件或打开详情。作业详情可按活动标题读取，附件只有已加载名称／链接时不下载文件、不冒充完整正文。未识别布局返回明确失败，只有已识别布局且目标不存在才显示零匹配；已定位课程但无正文显示需要进入详情。

只处理当前页已加载内容，不自动打开课程／作业详情、翻页或切换学期周次。列表只有摘要时可以预览，须进入详情再抓取才能保存为完整事项。未知学校账号可预览、禁止保存；显示名不作为可靠账号标识。正式课表原生课次身份尚未核实，保留上下文但仅预览，不推算日期。

## 对象与模块边界

| 对象／文件 | 职责 |
|---|---|
| IntentParser · extraction/intent.js | 确定性条件语法、基础繁简规范化；不做业务摘要和时间推断 |
| DomPageReader · extraction/readers.js | Chrome scripting 注入、稳定等待、路由和账号变化检查 |
| RenderedVisibility / ContentBoundaryPolicy / DomAccess · content/scoped/dom.js | 渲染可见性、内容边界及原文读取分开；显式授权内容 aside 与 Moodle 原生课程概览 role 容器，其他导航／表单／页脚仍拒绝 |
| MoodlePageModel / CourseCatalog / ScopeResolver / 各 Extractor · content/scoped/moodle-*.js | 页面识别、必要课程索引、范围选择与课程／作业／区块提取对象；适配器组合注入依赖 |
| MoodleRegionIndex / TimelineExtractor / SupportExtractor · content/scoped/moodle-{model,regions}.js | 有限语义区域索引及专用读取；侧栏只授权 Timeline / Moodle Support；区域级错误和覆盖 |
| content/scoped/{moodle,student,people}.js | 统一 supports/run 契约；先定位范围，再提取匹配内容；新增站点不改 popup |
| ExtractionPipeline / CandidateFactory | 统一技术结果、原生身份、可保存性、人员字段投影视图 |
| DraftRepository / PageExtractionService | 持久任务、owner 隔离、幂等、恢复与保存编排；通过注入依赖测试 |
| ResultGroups · ui/result-groups.js | 课程、作业、Timeline、联系信息分组；不决定保存或扩大读取范围 |
| CaptureController · ui/controller.js | 依赖 browser/client/forms/view 端口，编排当前页／历史、账号代次、持久任务恢复与原请求重试 |
| CaptureView / PanelPolicy / PreviewView / SourceBindingView / ReceiptView | 组合式界面、保存资格、紧凑原文预览、标签明确确认、严格回执显示；不实现站点或后端业务规则 |
| ui/{form-store,client,dom,errors}.js | owner/tab 表单与独立历史表单、消息端口、安全 DOM 构造及中文错误映射 |
| background.js / lib/{api,outbox}.js | 持久意图和提交回执、严格 HTTP 响应；保留既有 v1 监测执行器 |
| Core / Flutter | 鉴权、事项身份、分类去重、快照版本调度；管理、来源、差异展示 |

这是职责与依赖边界，不把 SOLID 解释成每个操作新增一层抽象。适配器依赖 DOM 访问对象，服务依赖 Reader／Repository／Queue 端口，界面依赖消息客户端；测试可替换各端口。后端继续使用项目自研协议，无新增依赖。

## 安装与本地复现

1. 按仓库 README 启动本地栈；另运行 `.venv/bin/python devtools/campus_fixture/app.py --port 8098`。
2. Chrome `chrome://extensions` 加载仓库 `extension/`，已有安装点“重新加载”。本版本只提供 DOM，已删除 AX 读取器、选项和开发构建器；如果仍有旧 AX 测试副本，请停用，避免两个 worker 同时处理监测。
3. popup 连接设置中允许本地后端，再以 Campus Radar 账号登录。工作台使用同一账号。后端地址固定使用 localhost 或 127.0.0.1 之一，它们的网页会话不同。
4. 打开 `http://127.0.0.1:8098/login`，模拟学校登录后进入 `/capture/moodle-dashboard`。该合成场景采用脱敏双栏结构，内容 aside 与 side-pre 侧栏分开：`人工智能` 预览课程卡片，`Timeline` 逐条预览右侧活动，`Moodle Support 的邮箱` 预览右侧联系字段，`网络编程的作业` 只读两条完整作业并可一次保存。一次保存后打开工作台回执链接。
5. `/capture/courses?ambiguous=1` 验证同名课程确认；修改关键词验证零匹配；管理台修改后重新抓取并明确保存，查看原事项版本。新快照不支持自动重新获取。

来源权限按 origin 请求 optional host permissions；第一次权限提示可能关闭 popup。条件／请求先持久化，重新打开插件可继续登记同一任务，避免重复抓取。读取完成前需保留原页；成功草稿在本地保留 24 小时，可在“最近记录”查看和确认删除。每账号最多 10 条、全扩展 20 条、2.5M 字符。后台回收时未完成读取标为中断，需重新抓取；已入持久提交队列的结果可重开查询。

## 来源边界与旧监测兼容

| 来源 | 当前 DOM 行为 | 未由本地测试证明的能力 |
|---|---|---|
| Moodle | 已知 course/view.php 原生课程 ID、mod/assign/view.php 活动 ID；课程范围内已加载正文；仅入口则提示进入 | 当前已只读验证指定 Dashboard 的课程概览、Timeline 和 Support；其他主题、真实活动原生课程归属、安全保存及后台重入仍待验收 |
| 学生首页／资讯 | 已加载公告／新闻标题匹配，原生 detail ID；详情主体与日期原文 | 生产账号绑定、安全保存与真实详情覆盖不视为已完成；不访问未验证 API |
| 当前课表 | 课程名匹配，保留学期、时间／日期原文，未知周次／日期留空 | 全学期和原生课次身份未确认；正式课表仅预览 |
| FIE 人员 | 指定目录本站详情入口；个人主体或指定联系方式字段；不读通用页脚 | 正式各类人员字段覆盖仍需逐页验收；不追外链、不把目录当全校任课名单 |

夹具标记只信任 loopback。原有 `content/runtime.js`、`content/capture.js`、`adapters/` 仅为已保存 **recipe v1** 监测兼容，不是新 popup 的全量采集入口。新 snapshot recipe v2 强制不监测；已有 v1 配置继续由 Core 唯一调度（600 秒周期／120 秒租约），扩展每分钟领一项，浏览器会话只在 Chrome 内使用，同源重入至少间隔 2.1 秒。失败、需登录、未执行与无变化分开；失败不覆盖成功快照／时间。不得将兼容监测测试解释成新条件读取已支持自动重入。

## 验证与官方依据

`node --test extension/tests/*.test.js` 验证模拟 DOM／Chrome API；`node extension/tests/extraction-live.mjs` 需 8080 和 8098，验证模拟 DOM＋真实本地 HTTP；`.venv/bin/python -m pytest server/tests/test_browser_capture.py server/tests/test_extension_build.py -q` 验证后端和 DOM-only 权限边界。首次安装 JS 测试依赖用 `npm --prefix extension ci`；生产扩展无运行时第三方库。普通网页 harness 不算真实扩展验收。单弹窗、回执丢失恢复、重登和历史隔离新增回归见 `extension/tests/panel.test.js`。

最低 **Chrome 110**，使用 scripting/activeTab/storage/alarms；不申请 debugger，不依赖新版本专属 alarm 选项。2026-11-11 核对官方 [scripting 与 isolated world](https://developer.chrome.com/docs/extensions/reference/api/scripting)、[MV3 生命周期及 Chrome 110 API 调用重置计时器](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle/)。最低版本是工程基线，未在 Chrome 110 实机测试；真实 Chrome 版本、具体证据和未验证项保存在本地开发报告。
