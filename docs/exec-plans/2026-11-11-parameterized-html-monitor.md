# 参数驱动的跨站 HTML 监测验证

负责人：Codex；持续验证监管：Terra（max）
日期：2026-11-11

## 1. 目标与非目标

### 目标

- 模拟上游传入 `target_url`、`interval_s`、`auth_context_id`、`site_profile`，监测器复用现有会话和受控 HTTP 传输，获取完整 HTML。
- 将站点 URL、Cookie 作用域、请求头和认证证据集中到明确注册的站点配置；本轮验证 YouTube、Bilibili，并回归 MUST Moodle。
- 输出完整 HTML 与请求上下文到内存接收替身；不识别视频、不比较新增、不实现 Extractor、Item Service 或 Inbox。
- 用合成测试覆盖参数、会话轮换、失效、范围约束、原始 HTML、交付重试与限速；真实验证只通过手动调试程序运行。
- 在有效会话下持续检查至少 7200 秒，600 秒以上轮次间隔，跨两小时后仍有真实请求证据；由用户指定的 Terra-max 子代理监管脱敏状态，主代理等待并最后核验、提交。

### 边界与执行条件

沿用已有 HTTPXTransport、AuthManager/CookieJar 和 DNS 兼容逻辑。Moodle 既有观察/业务回执路径保留，用回归测试验证。新增页面路径的输入不要求 item_id；输出不包含已提取的标题或业务变化结论。

真实页面与 Cookie 只留在受控进程内存。输出记录时间、状态、字节数、摘要、认证证据和交付结果，不记录 Cookie、Set-Cookie、密码或完整 HTML。测试替身不写生产事项。会话正常轮换更新 Cookie 修订；重新授权、撤销及账号变化废弃旧请求和待交付内容。

本轮用户已授权使用 Chrome 中已有站点会话。Moodle 登录可使用 Chrome 已保存的密码，并按用户说明点击密码框下的圆形选项后登录；不得读取或导出保存的密码。遇到新的验证码或未授权权限提示时按工具规则处理。

Bilibili 的 UP 主空间此前触发 robots_denied。本轮先验证公开、获准路径；明确禁止的路径保留失败证据，不增加关闭 robots/TLS 的参数，不用 Cookie 将拒绝伪装成可用。若只能验证视频详情页，报告必须限定支持面，不能宣称投稿列表已通过。

正式浏览器桥接、完整站点抓取、分页、字幕、视频下载、业务接口和生产切换均不在本包。模拟上游与 HTML 接收替身足以验证模块边界。

## 2. 数据流

### 改动前

```text
已保存 Moodle item_id → Registry → Scheduler
    → Moodle URL / host-only Cookie 规则 → HTTPXTransport
    → MoodleAdapter 提取标题正文 → ObservationBatch → DebugSink
```

### 改动后

```text
模拟上游：目标 URL + 间隔 + 会话引用 + 站点配置名
    → 页面任务校验 → 使用现有 Cookie 会话 → 定时受控 GET
    → 更新 Set-Cookie / 判断访问和认证状态
    → HTMLSnapshot（完整 HTML、任务/请求/代际信息）
    → 内存 HTML 接收替身 → 按 snapshot_id 确认接收

真实 Extractor / Item Service：不接入
既有 Moodle 观察路径：保留并回归
```

### 自然语言说明

当前 URL 和会话规则散落在 Moodle 专用实现中，调度还依赖业务 item_id。本包增加窄范围的页面任务入口，站点配置负责允许的地址、Cookie 范围和认证证据。监测器交付实际收到的完整 HTML，内嵌 JSON 不被内容提取器删除；凭证不进入交付上下文。获取失败与交付失败分别记录，未确认的同一快照优先重试，不重复请求远端页面。网页登录状态判断只服务于会话维护，不提取业务内容。

上游示例：

```json
{
  "target_url": "https://www.youtube.com/@3blue1brown/videos",
  "interval_s": 600,
  "auth_context_id": "<已导入会话的引用>",
  "site_profile": "youtube"
}
```

## 3. 文件清单

```text
仓库根目录/
├── server/gleaner/monitoring/
│   ├── models.py                           [修改] 默认站点策略扩展点；Moodle 默认约束保留
│   ├── profiles.py                         [新增] 站点配置、精确任务 URL 与认证证据
│   ├── pages.py                            [新增] 参数化页面任务、原始 HTML 与接收回执
│   ├── auth.py                             [修改] 按配置保留 Cookie 属性与轮换规则
│   └── transport.py                        [修改] 读取配置请求头，复用现有受控请求
├── server/tests/
│   ├── test_monitoring_profiles.py         [新增] URL/Cookie/认证隔离与 Moodle 默认回归
│   └── test_monitoring_pages.py            [新增] 参数、完整 HTML、重试、节流和失效
├── devtools/monitoring/
│   └── page_run.py                         [新增] 模拟上游、隐藏 Cookie 输入、长时脱敏验证
└── docs/
    ├── exec-plans/2026-11-11-parameterized-html-monitor.md [新增] 本计划及实际证据
    ├── architecture/monitoring_module/README.md          [修改] 参数化入口和验证边界
    └── evaluation/results/parameterized-html-monitor/   [新增] 脱敏实测证据
```

## 4. 检验清单

- [x] 上游参数能建立页面任务，无需业务 item_id；未知配置、无效 URL、过短间隔及错误会话绑定被拒绝。
- [x] YouTube/Bilibili 第一方 Domain Cookie 保留属性；跨域、分区、控制字符、错误名称与恶意删除 Cookie 被拒绝；Moodle 既有严格规则继续通过。
- [x] 原始 HTML 按字节交付，脚本中的 JSON 保留；请求凭证不出现在快照元数据、日志、异常和报告中。
- [x] 认证未知、登录失效、访问限制与网络失败不计为成功；Set-Cookie 轮换后下一次请求使用更新值。
- [x] 接收失败只重试相同 snapshot_id；撤销或配置变化后不能交付旧快照；下一次请求遵守轮次与主机限速。
- [x] 所有新增测试、相关 Moodle 回归、Ruff 与格式检查通过。
- [x] YouTube 使用当前会话真实取 HTML，接收替身确认；记录目标范围和认证证据。连续运行另行验收。
- [x] Bilibili 真实执行并记录可用/阻断路径；禁止路径不得标记通过。登录态仍未验证。
- [x] Moodle 登录及真实内容请求回归通过；旧观察路径仍可解析已授权作业。连续运行另行验收。
- [ ] Terra-max 监管连续两小时：首末成功间隔至少 7200 秒，每轮有脱敏结果；不混用匿名成功代替登录态验证、不拼接失败后的新运行。
- [x] 真实验证结束后清理后台内存凭证和临时剪贴板，停止调试及防休眠进程，保留浏览器登录态。
- [x] 核对任务文件范围并小步提交；历史 `html_parity` 和 `platform_probe` 文件保持独立。

## 5. 完成证据

本地定向验证：149 项测试通过（新增参数/会话/HTML 用例及既有监测、请求合规和历史试验回归）。本轮 DNS、认证诊断及导入修正后，`.venv/bin/pytest -q server/tests`：**353 passed、3 skipped，111.11 秒**。`.venv/bin/ruff check server devtools/monitoring` 及本包格式检查通过。

此前浏览器权限门禁曾拒绝 YouTube、Bilibili 和 Moodle。2026-11-12 本轮 Chrome 权限已恢复；用户明确同意后，Cookie-Editor 获得 Bilibili 所需权限。Moodle 使用 Chrome 已保存的密码登录，未读取或导出密码。

真实单轮证据和各次失败的独立日志见[参数化 HTML 结果](../evaluation/results/parameterized-html-monitor/README.md)：YouTube 频道页和 Moodle 授权作业页各有 HTTP 200、正面认证证据与内存 HTML 接收回执；Moodle 旧观察路径另有一次真实获取、解析和模拟业务回执成功。Bilibili 视频详情页返回 HTTP 200，但 HTML 没有已检查的正面登录证据，未交付。用户同意考虑第一方会话接口后，其 robots 规则禁止该路径，因此没有请求接口，也没有声称 Bilibili 登录态或 UP 主投稿列表已通过。

连续运行未通过：YouTube 有 `auth_required`、DNS 和连接超时失败，单次运行最长成功内容请求跨度 **610.300 秒**；Moodle 的最长运行前 6 轮成功，第 7 轮 DNS 失败，成功内容请求跨度 **3,055.180 秒**。各次运行均保留单独 `run_id` 和失败摘要，不拼接。已针对观察到的 Fake-IP 环境扩展同一 Cloudflare DoH 的有界超时重试，保留 10 秒 DNS 和建连各自上限及 30 秒整次请求上限，DNS 回退事件单独记录；TLS、robots 和限速继续生效。Terra-max 子代理只监管脱敏报告，主代理已按原始请求记录独立核验。全部调试进程与临时防休眠进程已停止，后台会话与临时剪贴板已清理，Chrome 登录态保留。

已有未跟踪的 `html_parity.py`、`platform_probe.py` 及各自历史报告不属于本包提交；仅按需阅读和复用其已验证思路。
