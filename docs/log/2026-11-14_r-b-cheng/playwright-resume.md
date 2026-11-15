# Playwright 解锁后续验

## 最终结果

**Playwright 已完成真实两小时验证，并已接入可选通用 HTML 传输后端。原有 HTTP 实现和原站点配置保留。**

长测构建 `8a5595b` 完成 13/13 轮，实际发送跨度的保守下界为 **7,473.39 秒**。之后完成接入，集成构建 `e1dbcb9` 又通过一轮真实烟测：HTTP 200、显式已登录、1,352,657 字节 HTML、接收边界回执与交付记录的 snapshot / 字节数 / SHA-256 完全匹配。单轮烟测不计作新的两小时证明。

最终本地检查 **399 passed、3 skipped，113.96 秒**；Ruff、相关文件格式与 diff 检查通过。长测由 Terra-max 独立监管，主代理从 Git 对象及原始脱敏记录独立复算；见 [独立报告](terra-playwright-supervision.md)、[长测核验](evidence/verification-playwright.json)、[集成烟测核验](evidence/verification-integrated-smoke.json)。

实际支持结论仍限定为 YouTube 指定频道的认证主文档 HTML。账号菜单在受限渲染中不可见，完整应用渲染未获证明；没有新增 Moodle/Bilibili 真实验证，也没有业务内容提取、分页或字幕功能。

基线 `8a5595b`，分支 `codex/youtube-http-playwright-validation`。用户确认 Mac 已解锁，要求先完成真实 Playwright 登录态与两小时验证，通过后再接入通用后端，并保留现有 HTTP 实现。

## 开始前核对

- 已检查 Git 状态和既有报告；只有先前未跟踪的历史候选说明，不改动或提交该文件。
- 正常 Chrome 可访问 YouTube 目标，已观察到账号菜单；没有绕过访问门禁。浏览器工具一次超时重置后重新绑定同一个标签，未重复刷新目标获取保活。
- Cookie 通过 Cookie-Editor 及本机隐藏输入导入，导入后清空字段并覆盖临时剪贴板；没有读取或输出 Cookie 值。
- 保持上轮通过本地检查的代码；实验仍使用严格 robots、TLS、固定公网 DNS 和内存上下文，不增加目标或业务功能。

## Playwright-02

- 运行入口：`env -u DEBUG -u PWDEBUG .venv/bin/python -m devtools.monitoring.youtube_compare --backend playwright --duration 7200 --interval 600 --report docs/log/2026-11-14_r-b-cheng/evidence/playwright-02.jsonl`。
- run_id：`54adc4f8-fdf1-4386-a49d-a4fb32e090c7`；源码摘要 `090bc2c9be1a6b05e39c28f4534fceb3b1e1b3d7899c2eecef3a38cd97b9e5be`。
- 首轮内容请求 UTC 区间 `[1794698362.6554382, 1794698363.417848]`；单调时钟区间 `[860355.562196291, 860356.324607708]`。
- 首轮 HTTP 200，原始 HTML 显式已登录，1,351,527 字节，模拟接收成功。浏览器原生会话最终维护 5 项允许的 Cookie。
- `dom_logged_in=true`，`account_menu_visible=false`：认证 HTML 已获得，完整应用渲染尚未证明，不混淆两个结论。
- 首轮后委派 `gpt-6.1-terra` / `max` / `fork_turns=none` 子代理，只读脱敏状态与报告。实际发送区间的保守跨度须满足 7200 秒，相邻间隔保守下界至少 600 秒、上界不超过 640 秒。源码冻结，不追加会话或浏览器刷新。

后续结果、通用后端是否接入、验证与清理将在本文件续记。此前 HTTP 或未开始的 Playwright 记录不计入本次运行。

## 真实验收结果

Playwright-02 单一运行 **13/13 通过**。原始记录封存于 `evidence/playwright-02.jsonl`，主代理独立重算为 `evidence/verification-playwright.json`。首轮纽约时间区间为 18:19:22.655438–18:19:23.417848，末轮为 20:23:56.818320–20:23:57.522319；均在 2026-11-14。

- 保守跨度：mono **7,473.392933 秒**、UTC **7,473.400472 秒**。
- 所有间隔保守范围 **620.993642–626.207165 秒**；无失败、缺轮或中断。
- 13 个内容响应均 HTTP 200、显式认证、程序确认的模拟回执；每轮完整解码 HTML **1,351,527–1,354,244 字节**。本构建没有独立 sink 日志，不将程序确认的回执夸大为独立下游审计。
- 13 次 DNS 成功、0 回退/失败；3 次 robots HTTP 200；13 次确认请求后已离开目标页。
- DOM 登录标志 13/13 为真，账号菜单可见 0/13。只证明认证主文档 HTML 获取，完整应用渲染未证明。
- 主代理从 Git 提交对象重建源码摘要，与运行记录匹配；执行进程退出码 **0**，凭证及私有浏览器已随进程清理。

以上验收结束后才开始通用后端接入，后续集成构建的本地检查及真实烟测与此固定构建的长测分别记录。

## 接入实现

- 复用现有 `PageMonitor` / `RemoteTransport` / `HTMLSink` 契约，四个上游参数保持不变。HTTPX 路径继续存在，浏览器由显式站点配置选择。
- 已验证的浏览器核心进入可选模块；域名、Cookie 范围、必要静态资源和会话检查由受信任 profile 提供。只声明已实际验证的 YouTube 主文档范围，完整应用渲染仍单独标注。
- 浏览器会话绑定一个 auth_context，撤销和重新授权必须使旧执行失效并清理原生浏览器凭证；不能让旧浏览器状态覆盖新 generation。
- 接入后检查 profile 绑定、默认 HTTP 保留、原始 HTML 交付、会话失效清理以及 robots/TLS/重定向边界。运行中的实验源码在验收结束前不改动。

新增入口 `gleaner.monitoring.backends.create_page_transport`，可选实现位于 `gleaner.monitoring.browser.PlaywrightTransport`。旧实验入口仅保留兼容包装，不复制浏览器核心。原 `HTTPXTransport` 文件相对 `8a5595b` 没有改动；`ResponseGuard` 和 `PinnedTunnel` 与长测构建的 AST（排除类型注解）一致。

| site_profile | 后端与会话配置 |
| --- | --- |
| `moodle` / `youtube` / `bilibili` | 原 HTTP 路径与原配置，保持兼容 |
| `youtube_http_v2` | HTTPX；四项 3P 初始凭证，维护自身响应的 LOGIN_INFO，显式公网 DoH |
| `youtube_browser_v1` | 隔离 Playwright 内存上下文；同样的 Cookie / DNS 范围与严格网络约束 |

上游参数仍只有 `target_url`、`interval_s`、`auth_context_id`、`site_profile`。Cookie 名称、初始导入范围、请求头、静态资源与就绪检查来自注册配置；没有自动把 HTTP 拒绝转换成浏览器访问。

会话运行时绑定一个 auth_context；撤销会同步阻止继续使用并等待浏览器清理，重新授权使旧 generation 失效，取消撤销请求不会取消底层凭证清理。接入测试覆盖了运行时打开途中撤销、旧状态不得覆盖新 Cookie、正常 Cookie 轮换保留会话、多账号绑定拒绝、调试日志拒绝以及原 HTTP 行为。

手动验证入口示例（首次运行使用下列尚不存在的报告路径）：

```sh
env -u DEBUG -u PWDEBUG .venv/bin/python -m devtools.monitoring.page_run --site youtube_browser_v1 --target https://www.youtube.com/@3blue1brown/videos --duration 0 --interval 600 --exit-on-finish --report docs/log/2026-11-14_r-b-cheng/evidence/next-browser-smoke.jsonl
```

浏览器依赖为可选 `server[browser]`，当前固定 Playwright 1.65.2。环境必须关闭 `DEBUG` / `PWDEBUG`；开启可能输出凭证的调试模式时，后端拒绝启动。Cookie 只能通过本机隐藏输入，不能放入上述命令。

## 收尾

- `08cdae5` 封存两小时证据；`df76542` 增加会话资源失效接口；`e1dbcb9` 接入可选浏览器后端与显式站点配置。
- 长测及集成烟测均退出码 0，私有浏览器与内存凭证随运行清理；Terra 已结束监管。本轮 caffeinate 已停止。
- 最后一次导入后，字段和临时剪贴板已清理；本轮验证标签已关闭，未执行用户 Chrome 登出或删除其 Cookie。
- 仅本任务代码、测试和 `docs/log` 记录进入提交；原历史未跟踪说明及主工作目录的旧试验保留。没有推送、合并或创建定时自动化。
