# DNS 与 YouTube 会话排查

## 修改前假设与证据

本轮从 `c2bd2e3` 继续，保留既有实验文件。遵守根目录 `AGENTS.md`，只在本日志目录记录结果，不修改架构 README 或既有实施文档。时间以 America/New_York 表示；原始机器证据使用 UTC 与单调时钟。

1. **DNS 网络路径间歇不可用**：旧运行记录两台 Cloudflare 引导地址超时。2026-11-12 本轮对 `1.1.1.1`、`1.0.0.1` 和官方客户端文档示例的 `104.16.111.25`、`104.16.112.25` 各两次无凭证 DoH 探测全部成功（0.678–2.547 秒），不能据此归因于固定地址永久不可用，也不据此新增地址。系统解析仍为 Fake-IP。
2. **超时预算与观测有缺口**：当前 DoH 外层 9 秒，三次尝试每次连接 3 秒、读取 5 秒；TCP 和 TLS 也可能各自占用连接超时。最后一次可能被外层取消，已有报告缺少终止阶段。先用真实事件循环的合成慢连接复现，再调整整个尝试的预算、记录脱敏失败阶段；保留总预算、同供应商、TLS 和 Retry-After。
3. **YouTube 浏览器与独立会话发生轮换竞争**：旧运行首两轮 `LOGGED_IN=true`，第三轮 false 且 Cookie 数量发生变化。目前 Chrome 留有旧 YouTube 标签页。[yt-dlp 维护文档](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)记载打开标签页会轮换账号 Cookie。它支持这一假设，尚不足以证明本次根因。先增加内存中 Cookie 变更的脱敏诊断，不记录 Cookie 值、密码或 HTML。
4. **Cookie 作用域/覆盖缺陷或登录证据误判**：已有域名规范化和轮换测试，未发现前导点导致重复 Cookie 的缺陷。继续验证真实响应的变更种类和登录标记；不把 HTTP 200 或 Cookie 存在改成认证通过。

DNS 参考：[Cloudflare 加密解析端点](https://developers.cloudflare.com/1.1.1.1/infrastructure/network-operators/)、[官方客户端示例](https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/dns-over-https-client/)。未关闭 TLS、robots，也未访问 Bilibili 被禁止的会话接口或 UP 投稿列表。

## 进展

- 已确认 Chrome 的 YouTube 访问权限正常，页面显示账号菜单。
- 先诊断再修改；外部网络故障和站点撤销授权不能作永久不再发生的保证。
- 修复完成后，以固定源码和独立 run_id 启动新长测，由 Terra（max、无历史上下文）监管脱敏证据；验收仍为真实请求首末至少 7200 秒、相邻轮次至少 600 秒。失败不拼接。
