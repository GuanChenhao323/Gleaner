# 共用 HTML Extractor 可行性验证

日期：2026-11-10（America/New_York）。范围：作业详情页的事项标识、标题、正文、截止时间。状态：本地两组浏览器实验及一份真实 MUST Moodle 作业页的四字段一致性验证通过。

## 验证方法

新增独立实验工具 `devtools/monitoring/html_parity.py`，不修改正式 Capture API、插件或监测模块。通过 Computer Use 从实际 Chrome 页面读取 `document.documentElement.outerHTML`，模拟拟议插件的 HTML 输入；另一份输入由既有 `HTTPXTransport` 发起 GET 获得。两份输入调用完全相同的 Python `extract()`，逐字段比较。

标题、正文及事项定位复用现有 `MoodleAdapter`；截止时间使用本次实验性的日期区域解析器，读取 `.activity-dates` / `[data-region=activity-dates]` 内明确的 Due 标签，兼容旧主题提交状态表中明确的 Due date 行。只读取目标日期，不收集其余个人提交状态。日期未知、无法解析或存在冲突分别标记，不把“两边都缺失”计作四字段验证通过。

本实验明确使用 `Asia/Macau` 解释页面日期；尚未独立验证学校账号的显示时区。正式接入需要明确时区来源。本实验也未验证正式扩展的权限、HTML 上传流程、业务保存和版本管理。

## 已完成的本地浏览器实验

原始证据：[local-browser-results.json](local-browser-results.json)。两组均由真实 Chrome 执行页面脚本，同时由 Python HTTP GET 获取未经脚本执行的响应；并非手工构造两份相同的提取结果。

| 场景 | HTML 是否相同 | 标识／标题／正文 | 截止时间 | 判定 |
|---|---|---|---|---|
| 服务端 HTML 已包含日期，Chrome 添加 DOM 状态 | 不同（762 / 675 bytes） | 全部一致 | 两端均提取成功且相等 | 四字段通过 |
| 日期仅通过 JavaScript 插入 DOM | 不同（862 / 683 bytes） | 全部一致 | DOM 有值、HTTP 缺失 | 正确检测到不一致 |

纯程序测试覆盖独立期望值、DOM 无关变化、日期单独改变、日期缺失、脚本不会被 Python 执行、旧表格日期、开放/修改日期干扰、冲突日期、登录页与错误事项身份。与既有 Moodle 适配器测试一起运行：13 passed。

## 已完成的真实页面验证

用户手动登录后，已只读检查一份 MUST Moodle 作业详情页：浏览器 DOM 含独立的 `[data-region=activity-dates]` 区域，其中 Opened 与 Due 分开。这说明现有仅选择 `#intro` 作业说明的监测观察会遗漏独立日期。

用户明确批准将当前 MoodleSession 临时导入本机回环验证进程后，完成了对同一作业页面的真实 HTTP 请求。结果见 [real-browser-results.json](real-browser-results.json)。执行时间：2026-11-10 20:36:25 EST（2026-11-11 01:36:25 UTC）。

| 对照项 | Chrome DOM 输入 | Python HTTP 输入 | 结果 |
|---|---|---|---|
| 完整 HTML 大小 | 166166 bytes | 170046 bytes（传输压缩后 25910 bytes） | 原始 HTML 不相同 |
| 事项定位符 | 21 字符 | 21 字符 | 内容相等 |
| 标题 | 57 字符 | 57 字符 | 内容相等 |
| 正文 | 360 字符 | 360 字符 | 内容相等 |
| 截止时间 | present | present | 按显式时区归一化后的值相等 |

四字段组合的 SHA-256 相同，四字段非空校验通过。HTTP 请求包含一次 robots GET（303，同源 `/my/` 跳转未跟随）和一次目标作业 GET（200），沿用已授权的单个精确目标回退策略，两次请求起始相隔约 3.72 秒。没有扩大到其他作业页，也没有执行提交操作。

凭证通过现有 Cookie-Editor 和本机隐藏输入框传入，只接受精确主机的 MoodleSession；请求结束后 AuthContext 已撤销。输入框已清空，系统剪贴板中的临时导出已用无敏感信息文本替换。完整 HTML、Cookie 和真实字段内容均未写入报告或测试夹具。验证后已停止临时服务，并确认回环端口不再监听。

结论：这个实际作业页支持“浏览器 DOM HTML／HTTP 原始 HTML → 同一 Extractor → 一致事项字段”。其截止时间已经包含在服务端 HTML 中，当前仅选择作业说明的范围会漏掉它。这个单页结果不能推广到所有 Moodle 页面；本地 JavaScript 日期反例仍说明动态字段需要另外的获取路径。

## 复现

```bash
.venv/bin/python -m devtools.monitoring.html_parity --report /tmp/html-parity.jsonl
.venv/bin/python -m pytest -q server/tests/test_html_parity.py server/tests/test_monitoring_moodle.py
```

打开终端给出的回环地址。模式默认是静态日期；在同一端口打开 `/mod/assign/view.php?id=7`，将该页的 DOM HTML 填入实验表单，点击对比。测试动态日期时，先选择动态模式并空 HTML 提交以配置合成页面，再重新加载合成页面、读取 DOM、提交对比。

真实模式仅用于手动运行、已授权的单个 MUST 作业详情 URL；沿用既有精确目标访问策略与显式 DoH 调试路径。Cookie 只驻内存并在请求后撤销，报告仅保留字段是否相等、提取状态、长度、摘要和脱敏请求事件。真实 HTML 不落盘、不进入测试夹具。原始页面不得粘贴到聊天或提交进仓库。
