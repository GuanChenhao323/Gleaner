# YouTube HTTP / Playwright 对照验证

后续状态：Mac 解锁后的 Playwright-02 已通过真实两小时，且可选通用后端已接入并通过真实单轮烟测。最新结果与使用方式见 [playwright-resume.md](playwright-resume.md)。以下保留第一次收尾时的历史状态与未开始记录。

## 第一次收尾结果

**修正后的 HTTP 实验路径通过真实两小时；Playwright 在会话导入前因 Mac 锁屏阻断，对照未完成，未接入通用浏览器后端。**

HTTP-02 的 13 轮均为 HTTP 200、明确已登录、完整 HTML 模拟接收成功；实际请求跨度 7,234.72 秒。原开发分支 `codex/monitoring-v1-validation` 仍为 `7e961b1`；本分支没有修改 `server/gleaner` 中的默认实现。实验工具与本地测试不能代表 Playwright 登录态已验证，也不能代表其他站点已获支持。

原始脱敏证据、主代理从 Git 对象与请求记录独立重算结果见 [evidence/verification.json](evidence/verification.json)；独立 Terra 监管报告见 [terra-supervision.md](terra-supervision.md)。最后完整本地检查为 **386 passed、3 skipped**，包含真实 Chromium 的本机假站点检查；Ruff 与本轮文件格式检查通过。

浏览器工具原始阻断原因：`The Mac is locked and automatic unlock could not unlock it.` 用户要求不询问，因此没有请求解锁或改走其他凭证读取通道。Playwright-01 只有准备与结束记录，0 次导入、0 次监测请求、0 次认证、0 次交付；不能计为一次认证失败，更不能计为通过。

HTTP-02 自行完成并退出；Playwright 等待进程已优雅停止，退出码 0；本轮 caffeinate 已停止；Terra 已结束读取与等待。最后进程检查没有残留验证进程、测试用无头浏览器或本轮睡眠抑制进程。最后一次成功 Cookie 导入后已覆盖临时剪贴板；锁屏尝试没有产生新的 Cookie 导出。未执行用户浏览器登出或删除其 Cookie。

Moodle 与 Bilibili 本轮没有新的真实验证。没有视频识别、分页发现、内容比较、字幕下载，也没有接真实 Extractor / Item Service / Inbox。

基线：`7e961b1`。实验分支：`codex/youtube-http-playwright-validation`。
工作树：`/Users/george/.codex/worktrees/youtube-session-state/Gleaner`。
用户要求先完成真实对照，再决定是否接入通用后端；原开发分支和现有生产配置保留。

## 修改前假设

1. HTTP 的导入凭证与服务端下发的会话状态需要分开处理。上轮 3P-only 配置拒收 `LOGIN_INFO`，单次探针接受该字段时曾成功，但持续性未验证。本轮只在实验入口采用四项 3P 初始凭证、五项响应 Cookie（含 `LOGIN_INFO`）。不改变既有默认 profile。
2. 完整浏览器的 Cookie 维护与 JavaScript 状态可能改善持续认证。浏览器也可能失败，不能预先称为修复。两组共用相同初始 Cookie 名称、目标 URL、User-Agent、语言、严格 robots/TLS 规则。
3. Chrome 与独立 HTTP 客户端可能使用不同出口。实验浏览器经本机只允许 `www.youtube.com:443` 的 CONNECT 网关，使用现有受限 DNS 解析，TLS 端到端交由 Chromium 验证；与 HTTPX 均使用直接连接，不读取系统代理。浏览器与 HTTP 结果中的网络标识仅在内存比较，脱敏输出布尔值。

## 实验设计与边界

- 两组顺序运行、每组重新由 Cookie-Editor 隐藏输入导入一次。避免同时使用同一份凭证相互干扰；这不是完全独立随机实验，不从两次顺序运行推断唯一根因。
- 每轮内容请求间隔至少 600 秒；单一运行首末成功请求跨度至少 7200 秒，失败立即记为失败，不拼接运行。原始请求计时、认证证据、完整 HTML 字节数和模拟接收回执分别记录。
- 首轮实际认证与接收成功后，委派 `gpt-6.1-terra` / `max` / `fork_turns=none` 只读监管脱敏状态。
- Playwright 使用非持久化上下文；不写 storageState、HAR、trace、截图或认证 HTML；Cookie 不进入命令行/日志。禁用 Service Worker，禁止 WebSocket、下载、跨域及未登记请求。必要同源静态脚本仍逐请求检查 robots 与主机间隔。
- 目标页原始响应 HTML 作为交付物；DOM 登录信号只记录布尔值。页面每轮结束离开目标，间隔内不额外刷新保活。
- 本轮 YouTube 目标：`https://www.youtube.com/@3blue1brown/videos`。不测试视频、分页或字幕。不新增 Bilibili robots 例外，不修改 Moodle 路径。

## 进展

- 正常 Chrome 已可访问目标，页面显示账号菜单；无权限绕过。
- 新分支已从最终基线建立；前次候选仅作代码参考，不直接改变默认配置。
- 本地新增 16 项测试通过，覆盖 Cookie 导入/响应区分、原 profile 保留、参数与账号绑定、网络标识脱敏、robots/跨域/请求方法限制、CONNECT 目的地与私有 DNS 拒绝、实际发送计时。Playwright 1.65.2 / Chromium 159.0.8154.6 无真实凭证启动检查通过。
- 首次完整测试为 377 passed、3 skipped、1 failed；失败为既有 `test_e2e.py::test_full_demo_path` 的 WebSocket 重连回放断言。单独复验通过（1 passed，10.09 秒）；不修改无关推送代码，收尾再次执行完整检查。
- `e6a8c4b`：仅对手动验证入口开放实验工厂并将全部监测 devtools Python 源码纳入摘要。生产监测模块未修改。
- `5b63c03`：实验代码与边界测试提交；52 项相关检查通过。HTTP 首次运行 `http-01.jsonl` 导入四项 Cookie 后在地址检查阶段 `blocked`，0 次内容请求，0 次成功；已退出并清理内存凭证。
- 无凭证诊断确认系统 DNS 返回一项公网 IPv4 和一项私有 IPv6，原有全量地址检查正常拒绝。显式调用现有 CloudflareDNS 后全部结果为公网，robots HTTP 200 / 792 字节，目标允许，`/youtubei/v1/browse` 禁止。实验后续两组统一显式选择此 DoH 解析器，不向私有地址连接，不拓宽 Fake-IP 范围，不修改系统代理/DNS 或默认传输。配置改变后从新 run_id 开始。
- `98963f8` 的 HTTP-02 于纽约时间 09:47:22.455999 发出首个内容请求：HTTP 200 / 显式已登录 / 1,351,017 字节 / 接收回执成功。`LOGIN_INFO` 在本客户端响应中新增并保留。run_id `2cac3f5e-e6dc-4033-8ba3-f9529a0501b7`；首轮后已交给 Terra-max 无上下文子代理，只读监管脱敏状态和记录。
- 再次完整复验为 **378 passed、3 skipped，111.20 秒**；Ruff 和本轮 Python 文件格式检查通过。运行期间生产与实验源码冻结，未刷新 YouTube 或追加凭证。
- 浏览器组开始前还需收紧实际渲染验收：仅存在内联 `ytcfg` 不足以说明应用完成加载，应另检查可见账号菜单；此检查只返回布尔值。等待 HTTP 组终态后再修改，避免使运行中的源码证据失效。
- 浏览器前置审查还需处理：取消导航后 route 回调的受控清理、阻止非代理 WebRTC 流量、原生 Cookie 状态与脱敏会话计数的一致性。浏览器文档响应与渲染就绪证据分开记录；不能用内联配置变量冒充完整应用渲染。当前 HTTP 运行不受这些浏览器专属检查影响。
- **HTTP-02 最终通过**：13/13，0 失败；纽约时间 09:47:22.455999 → 11:47:57.193156。单调时钟跨度 7,234.717894 秒，UTC 跨度 7,234.737157 秒；间隔 602.284218–605.023174 秒。13 次 DNS 成功，0 回退/失败，3 次 robots 200。Terra 与主代理分别重算，主代理还从 Git 提交对象重建源码摘要，见 `evidence/verification-http.json`。进程退出码 0，凭证已清理。
- 浏览器本地真实 Chromium 测试复现了普通 Playwright route 不重新检查重定向第二跳；现于 CDP Fetch 响应阶段阻止跳转。为避免 Worker、子框架、后台连接逃出请求检查，增加收紧的 CSP；原站 CSP 保留。当前运行时仅改响应头未生效，现将 CDP 读到的原始解码 HTML 字节驻内存回传，接收前逐字节核对，且只接受 UTF-8/ASCII 字符集。纯文本与 gzip HTML 原字节保持测试均通过；没有关闭 TLS 或调用被 robots 禁止的 API。
- 响应阶段施加 CSP 会丢失 Chromium 响应对象的发送时间字段，浏览器验收改用更保守的网络时间区间：放行已暂停请求前记录下界，收到同一 network_id 的真实响应头时记录上界。首末跨度按“末轮下界 − 首轮上界”，最小间隔按“后轮下界 − 前轮上界”，最大间隔按“后轮上界 − 前轮下界”检查；单调时钟与 UTC 均须满足要求。交付时间不参与补足跨度。HTTP 原有精确发送计时不变。
- 浏览器前置修改后相关检查 **42 passed**；完整检查 **386 passed、3 skipped，113.52 秒**，Ruff 与格式检查通过。真实账号尚未进入 Playwright；即将以新的源码摘要和 run_id 开始独立浏览器组。
- 待完成：正常浏览器可用时重新进行 Playwright 会话导入及两小时验证；达到真实验收后再决定通用后端接入。现有实验组之间不得拼接。
