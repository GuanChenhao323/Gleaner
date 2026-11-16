# Monitoring Module｜设计文档

本目录存放 Campus Radar **信息源定期监测模块**的架构说明；接口契约目前仍保留在 `docs/architecture/`，没有移动。

- [架构设计（architecture.md）](architecture.md)：8 章，含简化总体架构、模块边界、网络方案、Chrome 协作时序、Session 状态机、故障恢复、参数设置。
- [IC-003 监测模块接口契约（上级目录）](../IC-003-monitoring-module.md)：详细 HTTP 接口、跨模块内部契约、状态与迁移规则。
- [OpenAPI 3.1.1（protocols 目录）](../../protocols/monitoring-v1.openapi.yaml)：机器可读接口描述。

**状态：监测验证版已通过本地测试与 130 分钟真实验收。** 正式插件、业务流水线和生产端点仍待联调。当前只检查显式保存的目标。

## 运行验证版

四阶段及必验项见[执行计划](../../exec-plans/2026-11-09-monitoring-v1-validation.md)，证据见[验收记录](../../evaluation/results/monitoring-v1/verification.json)。本轮 HTTPX 例外按用户授权记录在执行计划中，其他生产模块的网络库限制保持不变。

先使用 Python 3.12 或更新版本创建仓库根目录的 `.venv`，安装 `server[dev]`；本次本机使用 Python 3.14.7、HTTPX 0.28.1。以下命令在仓库根目录执行：

```bash
.venv/bin/python -m pip install -e 'server[dev]'
mkdir -p data/monitoring
.venv/bin/python -m devtools.monitoring.run \
  --database data/monitoring/local.sqlite \
  --report data/monitoring/local.jsonl
```

打开终端输出的回环地址。默认启动合成 Moodle，按钮可复现正文变化、认证失效、心跳暂停及恢复；界面明确显示 `sink_kind=stub`。Cookie 输入框会清空，并只发送批准主机的 `MoodleSession`。本地持久数据库用于重启恢复测试，关闭进程后重新执行同一命令可保留非秘密配置；凭证重新在内存中建立。

真实验证需显式选择已授权的作业详情 URL：

```bash
.venv/bin/python -m devtools.monitoring.run --real \
  --target 'https://moodle.must.edu.mo/mod/assign/view.php?id=<已授权目标ID>' \
  --dns cloudflare \
  --robots-fallback registered-target \
  --chrome-version '<实际Chrome版本>' \
  --report data/monitoring/real.jsonl
```

由 Computer Use 操作已授权的 Cookie-Editor，将当前站点 JSON 导入本地隐藏输入框；不要把 Cookie 放进命令行、文件或聊天。初次导入为 `unverified`，实际内容 GET 验证后才能变为 `valid`。长测开始前关闭 Moodle 标签页，保持 Chrome 与后端运行。真实模式只用内存数据库，不保存真实页面正文；默认至少运行 130 分钟，按 600 秒账号轮次、同主机至少 2 秒执行，日志分别记录获取、解析和模拟回执。

默认监测传输和调试命令使用 `auto` DNS：系统解析返回 `198.18.0.0/15` 或 `2001:2::/48` 的 Fake-IP 时，通过固定 Cloudflare DoH 入口重新获取公网地址。连接超时后在原有时间预算内最多尝试三个同服务商入口请求，并记录 `dns_fallback` 或 `dns_failure` 事件；证书错误、限流和无效结果不会触发此尝试。DoH 不发送站点凭证，保留解析入口和目标站的 TLS/SNI 校验；DoH 返回内网地址仍会被拒绝。普通 DNS 错误、其他内网地址及混合内网结果不会触发 Fake-IP 回退。`--dns system` 可关闭回退；`--dns cloudflare` 显式直接使用 DoH。本机代理和系统设置无需修改。此变更仅作用于监测模块，其他采集器继续遵循各自出站配置。

DNS 解析与目标站 TCP/TLS 建连分别有界，避免解析回退耗尽建连预算；目标站建连上限仍为 10 秒，整次请求包含解析和跳转的上限仍为 30 秒。

手动匿名连通性检查：`.venv/bin/python -m devtools.monitoring.connectivity_probe`。使用实际监测传输 GET `/robots.txt`，不携带 Cookie、不跟随跳转、不保存正文；结果只证明 DNS/TLS/HTTP 连通性。

实测 MUST 的 robots 入口在匿名时跳转登录，携带会话时首跳 303 到个人首页 `/my/`，没有直接提供可解析规则。默认 `strict` 会停止检查。上例显式启用本轮已授权目标策略：仅针对这个已验证的同源、无参数跳转，允许访问唯一登记的完整作业 URL；不请求个人首页，且单独记录 `policy` 事件。明确的 Disallow、登录证据、401、未知 HTML、5xx/网络错误及其他跳转继续阻断。该配置依据本轮精确目标授权，不能解释为站点允许全部访问；缓存仍按认证上下文和代际隔离。

出现认证失效、缺轮、暂停或超过预算的间隔会使长测不通过。恢复必要条件后应重新开一轮并使用新的报告文件名，不能拼接结果。点击“停止并清理凭证”结束检查；状态页保留用于核对，终端 Ctrl+C 关闭调试服务。停止不会退出 Chrome 中的 Moodle 账号。

| 验证对象 | 当前证据边界 |
|---|---|
| MUST 作业详情页 | 已在本校选定页面完成 130 分钟、14 轮真实检查；监测活动标题与 `#intro` 作业说明，身份采用 `cmid-*`。独立日期、附件内容等字段未纳入本轮适配 |
| 本地合成站点 | 获取、变化、错误、恢复、事务交接、重启及 TCP/TLS 已测试 |
| 正式业务应用 | 只有模拟回执；未验证正式 Extractor、事项版本或工作台成功时间 |

测试与 CI 只访问本地替身。Chrome Network 面板不提供 Python 出站请求的证据，后台流量以脱敏日志为准。

本次真实运行：2026-11-10 02:58:44–05:08:45 UTC，14 次内容 GET 均为 200，失败、缺轮、中断均为 0；所有内容摘要与浏览器基线一致。实测只证明本次条件下持续可用，不承诺会话永久有效。结束时已清空后台凭证并停止调试进程，详见[成功日志](../../evaluation/results/monitoring-v1/live-success.jsonl)。

## 参数化原始 HTML 验证入口

本轮独立页面入口的边界为「接收参数 → 维护会话 → 受控 GET → 内存 HTML 接收替身」。它不调用视频/事项提取器，不创建 Inbox 事项，也不更改上述 Moodle 观察回执路径。实施及验证证据见[参数化 HTML 计划](../../exec-plans/2026-11-11-parameterized-html-monitor.md)。

上游参数固定为四项：`target_url`（精确目标）、`interval_s`（检查间隔，真实站点至少 600 秒）、`auth_context_id`（当前已导入会话的引用）、`site_profile`（`youtube`、`bilibili`、`moodle`）。配置名选择服务端登记的 URL/Cookie 范围和会话检查规则，调用方不能传任意解析代码或修改凭证请求头。

```bash
.venv/bin/python -m devtools.monitoring.page_run \
  --site youtube \
  --target 'https://www.youtube.com/@3blue1brown/videos' \
  --interval 600 --duration 7200 \
  --report data/monitoring/youtube-html-run-01.jsonl
```

程序在回环地址显示模拟上游的四项参数和隐藏 Cookie 输入。由获授权的 Cookie-Editor 导出当前站点 JSON，经隐藏输入导入；只保留配置批准的 Cookie 名称和作用域，原 Cookie 属性保留，输入随提交立即清空。点击「导入并开始」后，模拟浏览器心跳仅在本地续期，不请求目标网站。Cookie 和完整 HTML 都只驻内存；进程重启需要重新导入会话。HTML 待交付状态也仅限当前进程，不承诺跨进程恢复。

Bilibili 例：`--site bilibili --target 'https://www.bilibili.com/video/BV1Vd4y1e7pj/'`；UP 主空间可登记，但若 robots 明确禁止会得到 `robots_denied`，不得当成可用。Moodle 例：`--site moodle --target '<已授权作业完整 URL>' --robots-fallback registered-target`；该回退仅沿用上文已记录的 MUST 303 `/my/` 例外，其他站点不提供同类开关。

`--duration 0` 只执行一次冒烟；`--duration 7200` 从首个认证成功且已交付的结果开始，需要末个成功结果跨过至少两小时。每轮都检查认证证据，HTTP 200 或 Cookie 存在不能单独产生成功结果。失败、缺轮、访问拒绝会结束该次运行并清理会话。新运行必须使用新的报告路径，不能拼接历史报告。报告区分真实 HTTP、认证与模拟 HTML 接收，绝不代表业务已应用。

首轮获取立即执行，以后从每轮结束起等待至少配置间隔。接收失败时页面模块保留同一 snapshot_id 和 HTML，优先重试交付；调试长测把任何交付失败记为该轮验收失败。取消或会话代际变化后旧快照被丢弃。可通过状态页查看字节数、摘要、Cookie 修订及两小时跨度；不显示会话值或正文。

