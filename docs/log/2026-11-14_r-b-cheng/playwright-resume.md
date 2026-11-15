# Playwright 解锁后续验

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

## 通过后的接入边界（待验收，尚未实施）

- 复用现有 `PageMonitor` / `RemoteTransport` / `HTMLSink` 契约，四个上游参数保持不变。HTTPX 路径继续存在，浏览器由显式站点配置选择。
- 已验证的浏览器核心进入可选模块；域名、Cookie 范围、必要静态资源和会话检查由受信任 profile 提供。只声明已实际验证的 YouTube 主文档范围，完整应用渲染仍单独标注。
- 浏览器会话绑定一个 auth_context，撤销和重新授权必须使旧执行失效并清理原生浏览器凭证；不能让旧浏览器状态覆盖新 generation。
- 接入后检查 profile 绑定、默认 HTTP 保留、原始 HTML 交付、会话失效清理以及 robots/TLS/重定向边界。运行中的实验源码在验收结束前不改动。
