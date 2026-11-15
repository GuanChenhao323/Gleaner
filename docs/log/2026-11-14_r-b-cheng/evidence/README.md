# 对照证据索引

| 文件 | 实际结果 |
| --- | --- |
| `http-01.jsonl` | 系统地址检查阻断；0 次内容请求；不计入长测 |
| `network-preflight.json` | 无凭证 DNS/robots 预检；DoH 公网结果；目标允许，youtubei 禁止 |
| `http-02.jsonl` | 单一运行、单次导入、13/13；实际请求跨度 7234.717894 秒；已认证且模拟交付 |
| `playwright-01.jsonl` | 锁屏阻断，0 导入/0 请求；未验证 |
| `playwright-02.jsonl` | 解锁后单次导入、13/13；保守跨度 7473.39 秒，已认证且程序确认模拟交付 |
| `verification-playwright.json` | 主代理按全部发送时间区间独立重算，源码与 Git 对象匹配 |
| `integrated-browser-smoke.jsonl` | 通用参数化入口真实单轮成功，含接收边界独立记录；不计作两小时证明 |
| `verification-integrated-smoke.json` | 单轮请求、接收边界回执、交付摘要及源码独立核验 |
| `verification-http.json` | HTTP 结束时主代理独立核验 |
| `verification.json` | 第一次收尾的三组核验；当时仅 HTTP-02 通过两小时条件 |
| `control-events.json` | 浏览器导入阻断与进程清理记录 |
| `sanitization-check.json` | 本轮 JSON/JSONL 敏感字段检查 |
| `sanitization-resume-check.json` | 解锁续验与集成烟测后的完整脱敏数据检查 |
| `cleanup-playwright-resume.json` | 续验、烟测、监督与本轮后台资源清理核对 |

两小时通过只表示该构建、该目标、该会话在观测窗口内成功。HTTP-02 构建为 `98963f8`，Playwright 准备构建为 `6db9163`；浏览器组的准备配置不是实际成功证据。所有 HTML 接收均为内存替身，没有业务内容提取或真实下游交付。

后续 Playwright-02 验证构建为 `8a5595b`；通用入口单轮烟测构建为 `e1dbcb9`。两组源码与时长分别核验，不能把单轮集成烟测写成新构建两小时通过。最新报告见 [playwright-resume.md](../playwright-resume.md)。

复现入口（Cookie 只能经本机隐藏输入导入）：

```sh
.venv/bin/python -m devtools.monitoring.youtube_compare --backend http --duration 7200 --interval 600 --report docs/log/2026-11-14_r-b-cheng/evidence/http-next.jsonl
env -u DEBUG -u PWDEBUG .venv/bin/python -m devtools.monitoring.youtube_compare --backend playwright --duration 7200 --interval 600 --report docs/log/2026-11-14_r-b-cheng/evidence/playwright-next.jsonl
```

每次必须使用不存在的新报告路径。Playwright 需安装 `server[browser-validation]` 可选依赖和对应 Chromium；两组顺序执行，首轮成功后再交给只读监管代理。
