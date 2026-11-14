# YouTube HTTP / Playwright 对照验证

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
- 待补：本地检查、实际每组运行证据、Terra 监管结论、清理与有效提交。
