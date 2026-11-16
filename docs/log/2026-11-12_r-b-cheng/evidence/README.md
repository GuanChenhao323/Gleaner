# 本轮真实验证证据

记录时间使用 UTC / 单调时钟；下表的人类时间使用 America/New_York。原始 HTML、Cookie 值、密码及网络地址未写入这些报告。HTML 接收方是同一进程的内存替身。

| 站点及实际范围 | HTTP、认证、接收 | 连续验证 |
|---|---|---|
| MUST Moodle：与上一轮相同的单一授权作业详情 | [long-02](moodle-long-02.jsonl) 13 轮均 HTTP 200、`logout_and_main`、171,442 字节、`delivered` | **通过**。2026-11-12 22:56:53.876469 至 2026-11-13 00:57:36.629184；单调跨度 7,242.744530 秒，UTC 跨度 7,242.752715 秒；间隔 602.668932–607.694847 秒。 |
| YouTube：指定频道 `/videos` | [long-01](youtube-long-01.jsonl) 与 [long-02](youtube-long-02.jsonl) 各前两轮认证并交付成功，第三轮 HTTP 200 但明确 `LOGGED_IN=false`，停止交付 | **未通过**。成功请求跨度分别为 603.874006 和 601.900900 秒；前者冻结原用户标签页，后者正常 active。没有拼接。 |
| Bilibili：指定视频详情 | [单次检查](bilibili-check-01.jsonl) HTTP 200、276,464 字节；缺少正面登录证据，`auth_unverified`，未交付 | 未满足首轮认证条件，未开展长测。[无凭证 API robots 检查](bilibili-api-robots.json)仍禁止会话接口，接口未请求。UP 投稿列表未验证，不能从详情页结果推断支持。 |

Moodle long-02 的 13 次 DNS 查询均直接成功，0 次回退、0 次失败。这个窗口证明当时网络条件下成功运行；DNS 慢响应、重试耗尽与 TLS 错误的处理由本地故障注入测试覆盖，不能据此保证外部网络以后永不超时。

[Terra 独立监管](../terra-supervision.md)核对了逐轮时间、请求与快照 ID。主代理另按原始 JSONL 重算并从 Git 对象重新构造源码摘要，结果见 [verification.json](verification.json)。`delivered` 表示内存替身已返回 `accepted=true` 且回执 ID 匹配；不代表真实 Extractor、Item Service 或 Inbox 已接收。

## 未计入通过的记录

- `moodle-check-01` 是单轮回归；`moodle-long-01` 四轮成功后由主代理主动停止，以固定新源码重新验证。它的跨度仅 1,814.860 秒，不计为两小时通过。
- `youtube-diagnostic-01` 至 `03` 为未导入成功、未发内容请求的准备运行；`04` 一轮成功后第二轮明确未登录，使用早期计时记录，不能计为连续通过。
- `youtube-3p-probe` 只验证初始 3P 子集的单轮请求，`duration=0`。它的 wrapper 摘要经主代理核对，随后收到服务器新发的 `LOGIN_INFO`。其 summary 的单轮 `passed=true` 不等于两小时通过。
- `youtube-long-03` 在导入前结束用于更新诊断入口；`youtube-session-network-check` 因 Mac 锁屏未完成导入。两者没有实际内容请求，不能作为候选修复成功的证据。
- [control-events.jsonl](control-events.jsonl)记录主动停止、浏览器恢复和锁屏阻断；[network-routing-metadata.json](network-routing-metadata.json)仅记录系统代理配置布尔值。Chrome 与 HTTPX 的实际出口是否一致尚未实测。

Moodle long-02 的验证提交是 `eaa8c8d`，源码摘要为 `6c7609ef5489045a8276fd60474505a756f79a04358dfc7fff930500af74845a`。收尾撤回了无效的 YouTube 白名单限制；Moodle 逻辑及传输、会话核心保持该已验证行为，最终本地检查为 377 passed、3 skipped。
