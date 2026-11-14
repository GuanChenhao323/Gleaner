# 对照证据索引

| 文件 | 实际结果 |
| --- | --- |
| `http-01.jsonl` | 系统地址检查阻断；0 次内容请求；不计入长测 |
| `network-preflight.json` | 无凭证 DNS/robots 预检；DoH 公网结果；目标允许，youtubei 禁止 |
| `http-02.jsonl` | 单一运行、单次导入、13/13；实际请求跨度 7234.717894 秒；已认证且模拟交付 |
| `playwright-01.jsonl` | 锁屏阻断，0 导入/0 请求；未验证 |
| `verification-http.json` | HTTP 结束时主代理独立核验 |
| `verification.json` | 所有组独立核验；仅 HTTP-02 通过两小时条件 |
| `control-events.json` | 浏览器导入阻断与进程清理记录 |
| `sanitization-check.json` | 本轮 JSON/JSONL 敏感字段检查 |

两小时通过只表示该构建、该目标、该会话在观测窗口内成功。HTTP-02 构建为 `98963f8`，Playwright 准备构建为 `6db9163`；浏览器组的准备配置不是实际成功证据。所有 HTML 接收均为内存替身，没有业务内容提取或真实下游交付。

复现入口（Cookie 只能经本机隐藏输入导入）：

```sh
.venv/bin/python -m devtools.monitoring.youtube_compare --backend http --duration 7200 --interval 600 --report docs/log/2026-11-14_r-b-cheng/evidence/http-next.jsonl
env -u DEBUG -u PWDEBUG .venv/bin/python -m devtools.monitoring.youtube_compare --backend playwright --duration 7200 --interval 600 --report docs/log/2026-11-14_r-b-cheng/evidence/playwright-next.jsonl
```

每次必须使用不存在的新报告路径。Playwright 需安装 `server[browser-validation]` 可选依赖和对应 Chromium；两组顺序执行，首轮成功后再交给只读监管代理。
