# 浏览器插件｜输入条件、匹配预览与明确保存

更新：2026-11-14，扩展 **0.5.0**。需求以 [产品定义](product-definition.md) 为准；内部契约见 [IC-EXTRACTION-001 v2.1](architecture/page-extraction-v1.md)，网络保存见 [IC-BROWSER-001](architecture/browser-capture-v1.md)。

## 当前交互

1. Flutter 信息源提供学院公告／学生系统、教师信息、Moodle 三个真实入口。学生系统、Moodle 分别在原站自行登录；教师网页公开。不在 Campus Radar 输入学校密码。旧 localhost 演示订阅另列，不等于学校网站已连接。
2. 在原网页点插件，输入想抓取的内容，例如 `人工智能`、`Timeline`、`网络编程的作业`、`奖学金公告`、`这位老师的邮箱和办公室`。先输入条件，再点“抓取匹配内容”。无需打开大预览页才能输入。
3. 插件先定位目标课程／标题／个人字段，再读取匹配内容。当前页有同名课程时只确认课程范围，不要求逐条选作业。零匹配不会变成整页采集；复杂条件明确拒绝。需要同时限制课程和标题可写 `课程：网络编程；关键词：实验`。
4. 核对整组匹配预览、原始字段、原文依据和限制，再点一次“保存匹配结果”。没有逐项复选框；不满足预期时修改条件重新抓取。修改输入立即禁用旧结果。
5. 入队与后端确认分开显示；只有严格逐项回执才能显示新增／更新／已有／失败及工作台链接。保存快照**不启用监测**；重新抓取后明确保存相同身份，可更新原事项与版本。

Moodle 普通课程词预览当前相关卡片及已加载信息；显式作业条件只读作业，Timeline 等具名区块按标题读取。课程卡片、区块和附件元信息标为仅预览，不能生成提交 target；本组含预览项时保存禁用，需缩小条件或打开详情。作业详情可按活动标题读取，附件只有已加载名称／链接时不下载文件、不冒充完整正文。未识别布局返回明确失败，只有已识别布局且目标不存在才显示零匹配；已定位课程但无正文显示需要进入详情。

只处理当前页已加载内容，不自动打开课程／作业详情、翻页或切换学期周次。列表只有摘要时可以预览，须进入详情再抓取才能保存为完整事项。未知学校账号可预览、禁止保存；显示名不作为可靠账号标识。正式课表原生课次身份尚未核实，保留上下文但仅预览，不推算日期。

## 对象与模块边界

| 对象／文件 | 职责 |
|---|---|
| IntentParser · extraction/intent.js | 确定性条件语法、基础繁简规范化；不做业务摘要和时间推断 |
| DomPageReader · extraction/readers.js | Chrome scripting 注入、稳定等待、路由和账号变化检查 |
| RenderedVisibility / ContentBoundaryPolicy / DomAccess · content/scoped/dom.js | 渲染可见性、内容边界及原文读取分开；只授权已确认的内容 aside，导航／表单／页脚仍拒绝 |
| MoodlePageModel / CourseCatalog / ScopeResolver / 各 Extractor · content/scoped/moodle-*.js | 页面识别、必要课程索引、范围选择与课程／作业／区块提取对象；适配器组合注入依赖 |
| content/scoped/{moodle,student,people}.js | 统一 supports/run 契约；先定位范围，再提取匹配内容；新增站点不改 popup |
| ExtractionPipeline / CandidateFactory | 统一技术结果、原生身份、可保存性、人员字段投影视图 |
| DraftRepository / PageExtractionService | 持久任务、owner 隔离、幂等、恢复与保存编排；通过注入依赖测试 |
| ui/{controller,view,form-store,client}.js | 流程编排、纯显示、表单存储、消息端口分离；popup/workspace 共享 |
| background.js / lib/{api,outbox}.js | 持久意图和提交回执、严格 HTTP 响应；保留既有 v1 监测执行器 |
| Core / Flutter | 鉴权、事项身份、分类去重、快照版本调度；管理、来源、差异展示 |

这是职责与依赖边界，不把 SOLID 解释成每个操作新增一层抽象。适配器依赖 DOM 访问对象，服务依赖 Reader／Repository／Queue 端口，界面依赖消息客户端；测试可替换各端口。后端继续使用项目自研协议，无新增依赖。

## 安装与本地复现

1. 按仓库 README 启动本地栈；另运行 `.venv/bin/python devtools/campus_fixture/app.py --port 8098`。
2. Chrome `chrome://extensions` 加载仓库 `extension/`，已有安装点“重新加载”。本版本只提供 DOM，已删除 AX 读取器、选项和开发构建器；如果仍有旧 AX 测试副本，请停用，避免两个 worker 同时处理监测。
3. popup 连接设置中允许本地后端，再以 Campus Radar 账号登录。工作台使用同一账号。后端地址固定使用 localhost 或 127.0.0.1 之一，它们的网页会话不同。
4. 打开 `http://127.0.0.1:8098/login`，模拟学校登录后进入 `/capture/moodle-dashboard`。该合成场景采用已观察的内容 aside 布局：`人工智能` 预览课程卡片，`Timeline` 预览当前区块，`网络编程的作业` 只读两条完整作业并可一次保存。一次保存后打开工作台回执链接。
5. `/capture/courses?ambiguous=1` 验证同名课程确认；修改关键词验证零匹配；管理台修改后重新抓取并明确保存，查看原事项版本。新快照不支持自动重新获取。

来源权限按 origin 请求 optional host permissions；第一次权限提示可能关闭 popup。条件／请求先持久化，重新打开插件可继续登记同一任务，避免重复抓取。读取完成前需保留原页；成功草稿在本地保留 24 小时，可在“管理本地预览”查看和删除。每账号最多 10 条、全扩展 20 条、2.5M 字符。后台回收时未完成读取标为中断，需重新抓取；已入持久提交队列的结果可重开查询。

## 来源边界与旧监测兼容

| 来源 | 当前 DOM 行为 | 未由本地测试证明的能力 |
|---|---|---|
| Moodle | 已知 course/view.php 原生课程 ID、mod/assign/view.php 活动 ID；课程范围内已加载正文；仅入口则提示进入 | 真实生产主题、课程归属 DOM、账号标识和后台重入尚未验收 |
| 学生首页／资讯 | 已加载公告／新闻标题匹配，原生 detail ID；详情主体与日期原文 | 生产账号绑定、安全保存与真实详情覆盖不视为已完成；不访问未验证 API |
| 当前课表 | 课程名匹配，保留学期、时间／日期原文，未知周次／日期留空 | 全学期和原生课次身份未确认；正式课表仅预览 |
| FIE 人员 | 指定目录本站详情入口；个人主体或指定联系方式字段；不读通用页脚 | 正式各类人员字段覆盖仍需逐页验收；不追外链、不把目录当全校任课名单 |

夹具标记只信任 loopback。原有 `content/runtime.js`、`content/capture.js`、`adapters/` 仅为已保存 **recipe v1** 监测兼容，不是新 popup 的全量采集入口。新 snapshot recipe v2 强制不监测；已有 v1 配置继续由 Core 唯一调度（600 秒周期／120 秒租约），扩展每分钟领一项，浏览器会话只在 Chrome 内使用，同源重入至少间隔 2.1 秒。失败、需登录、未执行与无变化分开；失败不覆盖成功快照／时间。不得将兼容监测测试解释成新条件读取已支持自动重入。

## 验证与官方依据

`node --test extension/tests/*.test.js` 验证模拟 DOM／Chrome API；`node extension/tests/extraction-live.mjs` 需 8080 和 8098，验证模拟 DOM＋真实本地 HTTP；`.venv/bin/python -m pytest server/tests/test_browser_capture.py server/tests/test_extension_build.py -q` 验证后端和 DOM-only 权限边界。首次安装 JS 测试依赖用 `npm --prefix extension ci`；生产扩展无运行时第三方库。普通网页 harness 不算真实扩展验收。

最低 **Chrome 110**，使用 scripting/activeTab/storage/alarms；不申请 debugger，不依赖新版本专属 alarm 选项。2026-11-11 核对官方 [scripting 与 isolated world](https://developer.chrome.com/docs/extensions/reference/api/scripting)、[MV3 生命周期及 Chrome 110 API 调用重置计时器](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle/)。最低版本是工程基线，未在 Chrome 110 实机测试；真实 Chrome 版本、具体证据和未验证项保存在本地开发报告。
