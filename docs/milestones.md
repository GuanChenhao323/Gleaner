# 当前里程碑与验收状态

更新：2026-11-03。产品范围唯一依据为 [产品定义](product-definition.md)，课程交付依据为 [项目提案](proposal.md)。旧 M1–M12、旧 P0/P1/P2 及测试数量见 [历史记录](archive/milestones-before-2026-11-03.md)，不沿用为当前产品完成状态。

## 产品实施计划

状态“待核验”表示已有相关实现，但尚未按新基线逐项审计；不等同于未开始，也不等同于已实现。负责人及日期待团队排期。本次文档统一没有运行产品验收。

| 编号 | 交付关口 | 对应需求 | 现状与下一步 | 验收证据要求 |
| --- | --- | --- | --- | --- |
| R0 | 来源、首发平台和质量基线 | 第 9 节、Spike 01/02 | 待确认：列明页面类型、采集／监测能力、样例、平台和提取质量阈值 | 支持矩阵、程序方案测试结果；效果不足时记录 LLM 评估结论 |
| R1 | 选择采集与结构化保存 | F01–F04、US01–US04 | 待核验：已有剪藏接口与解析逻辑；需核对同页多事项勾选、三类分类、失败反馈与持久化 | 场景 A；未选内容不保存、后端不可用不报成功、缺失字段不编造 |
| R2 | 管理、身份与来源追溯 | F04–F06、US04–US06 | 待核验：已有 Flutter 和事项状态逻辑；需核对新类型、状态、字段编辑与事项级去重 | 场景 C；同 URL 多事项、重复采集、用户修改及重启保留 |
| R3 | 有条件的主动变化监测 | F07–F09、US07–US09 | 待核验：已有采集与版本模块；需验证关掉目标标签页后的重新获取及运行恢复 | 场景 B；新旧版本、差异、最后成功检查时间、认证过期和网络失败 |
| R4 | 当前 MVP 综合验收 | 全部 P0、场景 A/B/C | 待 R0–R3 证据齐全；旧演示通过不能替代 | 本地约定环境稳定复现三场景；真实页面按授权单独验证 |

### 2026-11-06 · 后端部分进展（R1–R3）

- 需求：F01–F09 的后端接口与数据（US02、US04–US09 的服务端行为）；决策 D19–D25；接口 [IC-001](architecture/IC-001-extension-to-backend.md)、[IC-002](architecture/IC-002-backend-to-workbench.md)；计划 [执行计划](exec-plans/2026-11-06-backend-r1-r3.md)。
- 改动：`POST /api/captures` 批量保存与逐条结果；三类类型与状态、筛选；用户修改与冲突；事项级监测领取与回报；LLM 显式开关；迁移 7。
- 验证（Windows 11，Python 3.14，SQLite）：`pytest -q` 192 passed、3 skipped；`ruff check .`、`ruff format --check .` 通过。PostgreSQL 16（WSL Docker，Python 3.12）：数据库相关测试 68 passed。新增测试 `tests/test_captures.py`。
- 未完成：插件改用新接口、各页面 `locator` 取法与后台监测调度（插件负责人，Spike 01／02）；工作台按类型、状态、冲突与监测状态展示（工作台负责人）；分类规则替换（分类负责人）。在这些完成前，R1–R3 仍为“待核验”，场景 A／B／C 没有端到端运行。

### 2026-11-09 · 插件、分类规则与工作台（R1–R3 全链路）

- 需求：F01–F09、US01–US09；接口 IC-001、IC-002。
- 插件 `extension/` v0.2.0：候选识别与勾选、批量保存与逐条结果、后台监测（alarms + offscreen 解析）。测试页实测见 `docs/browser-extension.md`；后台监测未在真实 Chrome 中运行。
- 分类规则 `server/gleaner/core/classify.py`：三类事项、截止时间、活动时间与地点；Moodle 英文日期格式。已有事项正文未变时规则新推断的字段不产生新版本（避免误报）。测试 `tests/test_classify.py`。
- 工作台（Flutter）：按类型（待办／日程／通知）与状态筛选；详情显示类型与状态并可切换（完成／归档／已读）、日程时间与地点、字段修改与恢复来源值、冲突“保留我的／采用来源”、来源监测状态与开关、版本逐字段差异；收到 `item_updated` 自动刷新。
- 联调中发现并修复：HTTP 客户端只连解析出的第一个地址（`localhost` 先解析为 `::1` 时连不上只监听 IPv4 的服务）；网关把 Flutter 的 `assets/` 长缓存一天，重新构建后浏览器沿用旧图标字体。
- 验证（Windows 11，Python 3.14）：`pytest -q` 208 passed、3 skipped；ruff 通过；PostgreSQL 16 数据库相关测试 71 passed；`flutter analyze` 无问题，`flutter test` 6 项通过，`flutter build web` 成功；本地环境（`dev_all.py`）中用插件测试页保存、在工作台查看冲突、版本差异与监测卡片。
- 未完成：插件后台监测与 Spike 02 在真实 Chrome 中验证；R0 来源清单与质量基线；场景 A／B／C 的正式验收记录。部分汉字在 Flutter Web 中显示为方框（字体回退问题，早于本次改动，见待决问题“字体”）。

### 2026-11-09 · 通信层补强（IC-003 后端部分前置条件）

- 依据：IC-003 第 3.1 节（本地控制接口的 Host／CORS 校验）与第 10 节列出的复用门槛；对应课程交付 C01。
- 改动：Cookie Jar 按 RFC 6265 §5.3 校验 Domain、Secure 与数量上限；HTTP 客户端跨源重定向不转发凭证；抓取器逐跳重定向限速、RFC 9309 robots.txt、Retry-After 支持 HTTP-date 且不截短；网关 `GLEANER_ALLOWED_HOSTS` 与按端口通配的 CORS 白名单。
- 验证（Windows 11，Python 3.14）：`pytest -q` 202 passed、3 skipped（另加网关实测用例后 `tests/test_fetch_compliance.py` 11 passed）；ruff 通过；PostgreSQL 16 数据库相关测试 68 passed。本机已有另一套环境占用 1883／8080，`dev_all.py` 没有完整重启验证，Host 校验以测试中的真实网关验证。
- 未完成：IC-003 的监测模块（A）本身、Cookie 导入的站点白名单；`architecture.md` 与 `CLAUDE.md` 的库使用冲突待确认（Q09）。

### 2026-11-16 · R2 信息管理验收核对（邓燊）

- 范围：R2 管理、身份与来源追溯（F04–F06、US04–US06）中「事项状态、字段编辑、事项级去重」的后端行为核对。本次无代码改动，仅按新基线验证现有实现。
- 环境：macOS（darwin 22.6.0），Python 3.12（miniconda base），SQLite；`python devtools/dev_all.py --seed` 本地启动，网关 8080。
- 验证结果：
  - 全量测试 `pytest -q` 208 passed、3 skipped（约 116 秒）；`ruff check .`、`ruff format --check .` 通过。
  - 状态流转（US05，三类全通）：待办 `done=true` → `status="done"`；通知 `read=true` → `status="read"`；日程 `archived=true` → `status="archived"`。
  - 保存字段（US04）：事项详情返回原文 `body`、来源 `url`／`page_url`、采集时间 `first_seen_at`，满足「结构化内容＋原文＋来源 URL＋采集时间」。
  - 字段编辑（US04）：`PATCH /api/items/7/fields {"set":{"title":…}}` → `fields.title.value` 为用户值、`fields.title.source` 为来源原值、`edited=true`、`conflict=false`。
  - 事项级去重（US06）：`POST /api/captures` 同一 `page.url`＋`locator` 连发两次 → 第一次 `status="new"`（item 17），第二次 `status="unchanged"`（仍 item 17，不重复）；换 `locator` → `status="new"`（item 18），同 URL 多条可区分。
  - 冲突场景（US04，item 19）：用户把标题改为「我自己的标题」→ `edited=true, conflict=false`；来源重新采集改标题为 v2 → `conflict=true`（`value` 保留用户值、`source` 为新来源值）→ `POST /api/items/19/fields/resolve {"field":"title","keep":"mine"}` → 保留用户值、基准 rebase、`conflict=false`；来源再改 v3 重新触发冲突 → `keep="source"` → 采用来源值、删除用户修改、`edited=false`。
  - 重启持久化（item 19）：改状态 `done=true`、标题「重启后应保留的标题」→ kill 后重启 `dev_all.py --seed` → 重新登录查询：`state.todo="done"`、`fields.title.value` 仍为用户值、`edited=true`，数据落 SQLite `data/dev.db`。
- 未验证（R2 仍为「待核验」）：场景 C 的 Flutter 工作台端到端未跑（本机未装 Flutter）。

### 2026-11-17 · 分类规则扩充与样例评估（邓燊）

- 依据：分工表 D 邓燊负责「分类」；Q05／Q04 要求分类负责人用样例集评估分类质量、不足则改进规则（本次不做 LLM，按产品定义 LLM 仅在规则效果不足时才评估）。
- 评估：自建 20 条校园样例（待办／日程／通知）跑 `classify()`，基线准确率 94%，1 条分错（「社团纳新」因正文「本周三中午」无具体时刻被判为通知）。
- 改动：`server/gleaner/core/classify.py` 扩充 `EVENT_WORDS`／`TODO_WORDS` 校园高频词（活动：纳新、招新、献血、义卖、募捐、义诊、球赛、马拉松、夜跑、英语角、读书会、分享会、双选会、学位授予、研学、支教、志愿者、补考、缓考、展；待办：缴纳、注册、报到、申报、签到、打卡、补办、备案）。扩充后新增样例（献血、义卖、注册、打卡、答辩等）全部分对。
- 深挖出的三条规则缺口并修复：①「周末活动报名」这类带活动词、但语义是报名的标题，待办动词应优先于活动词 → `TODO_WORDS` 提到 `EVENT_WORDS` 之前；②「考试须知」「选课须知」「停电公告」是说明文／公告，不是日程 → 新增 `NOTICE_WORDS`（须知、公告、公示）并放在待办／活动词之前；③「健康打卡提醒」「提交作业的注意事项」里的「提醒」「注意事项」不能判成通知 → 词表只保留明确的通知词（须知、公告、公示），不收「提醒／注意事项／说明／指南」这类待办也会用的词。
- 验证（macOS，Python 3.12，SQLite）：新增 `tests/test_classify.py::test_campus_keyword_coverage`、`test_type_priority_and_notice_markers`；全量 `pytest -q` 210 passed、3 skipped；`ruff check`／`ruff format --check` 通过。
- 未完成：时段词（「本周三中午」「周五下午」等无具体时刻）仍不按活动时间处理，需与组长确认是否把「上午／下午／晚上／中午」也算作活动时间；Q04 的正式样例集待 R0 来源清单（Q01）建立后再做系统评估。

P1/P2 的范围和含义仅引用产品定义第 3.1 节，当前不承诺排期。邮箱、发信、Lark、扫码传输等旧功能不自动进入后续产品计划。

## 课程技术交付状态

| 对应交付 | 既有证据位置 | 当前处理 |
| --- | --- | --- |
| C01–C04 | `docs/protocols/`、历史 M1/M3–M7/M12、仓库测试 | 保留历史实现声明；按模块复核，不重复标成未实现；复用到产品需单独验收 |
| C03/C05 性能与故障评估 | `docs/evaluation/`、历史 M9 | 保留已记录结果；跨机器扩容、抓包等缺口继续单独跟踪 |
| C05 部署与用户 | 历史 M8/M10 | 云证书、CI 部署、真实用户仍有未完成项；课程要求调整待组长与老师确认 |

## 状态更新规则

每次推进记录：需求编号、改动位置、执行命令或手动步骤、环境、实际结果和未解决问题。只有对应验收标准满足且证据可复现时，才标为已完成；测试通过时间必须写明，不把历史结果当成本轮结果。
