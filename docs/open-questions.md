# 待确认问题

按约定，不确定的需求记在这里，不自行发挥。每条写明：现状（我暂时怎么做的）、需要谁决定。

## A. 需要组长 / 老师决定

第 1–8 条已于 2026-10-22 由组长决定，见 [decisions.md](decisions.md)。尚待提供：

1. **平台发信账号**：注册验证码、每日摘要邮件、运维告警都经它发出（`GLEANER_PLATFORM_SMTP_*`）。谁提供、用哪个邮箱服务？
2. **大模型服务商**：OpenAI 兼容接口的地址、模型名、密钥与额度由谁提供？
3. **个人来源的事项按用户隔离（已实现，请确认）**：compose 实测发现第二个同学登录同一个 Moodle 后看不到作业（身份键全局唯一）。
   现在个人来源（Moodle、个人邮箱）的事项按所有者各存一份，只与本人或公共来源（学院通知、教师页）的事项合并，
   不会并进别人的事项；公共来源仍全员共享一份。代价是同一门课的作业有几个人登录就存几份。是否认可这个隔离方式？

## B. 需要实地确认（第 1–2 周任务）

9. 本校 Moodle 是否开放 Web Service（`moodle_mobile_app`）、是否走统一认证（CAS/SSO）、是否提供 iCal 导出；云端能否访问。
10. 学院通知网站的真实 HTML 结构：模板里的 CSS 选择器（`ul.news-list li`、`.arti-content` 等）是按 fake_moodle 写的，需要按真实页面调整。
11. 学校邮箱是否支持 IMAP / POP3、是否要求 OAuth2、是否允许应用专用密码；SMTP 端口与 STARTTLS 支持情况。
12. 真实站点的 robots.txt：引擎遵守 robots，若禁止相关路径会把来源标为“检查失败”。需登录的个人来源是否也遵守？
13. 截止时间与变更说明按 `GLEANER_TZ=Asia/Shanghai` 计算；本机开发环境时区不同时，变更说明里的时刻会和界面本地时间不一致（演示机请确认时区）。

## C. 环境与未验证项（需要有环境的同学协助）

14. **compose 已实测**（WSL 2 里的 Docker Engine，2026-10-22）：12 个容器启动，演示路径全部通过，PostgreSQL 与 GreenMail 都已实测；
    实测发现并修复 6 个问题（见 [evaluation/README.md](evaluation/README.md) 第三轮）。
    WSL 注意：最后一个 `wsl.exe` 会话退出后发行版会自动关闭（容器随之停止，没有重启策略的 fake_moodle、GreenMail 不会自动回来）。
    演示时保持一个 WSL 会话不退出（本次用后台运行 `wsl -d Ubuntu -- sleep infinity` 解决）。
15. **评估数据**：Windows 初步数据与 WSL 2 上的 Linux 数据都已完成（见 [evaluation/README.md](evaluation/README.md)）：
    实验 1 select 与 epoll（250 → 5000）、手写反应器 5000 连接、实验 4 tc netem 丢包、实验 5 单机三节点、网关多 worker 吞吐等。
    官方 Autobahn 也已在 Docker 里跑完（asyncio 版 0 失败；反应器版只有二进制回显用例失败）。仍需：跨机器扩容（需要云服务器）、Wireshark 抓包（手工）。
    注意 WSL 2 镜像网络只有 4096 个临时端口，且 127.0.0.1 流量绕经 Windows，正式数据最好在云服务器上再测一次。
16. **Flutter 其他平台**：只构建并验证了 Web。Windows 本机需开启“开发者模式”（插件需要符号链接）才能构建 Android / Windows；
    Android 后台常驻 MQTT（前台服务）未实现；iOS、macOS 未配置。
17. **中文字体**：Flutter Web 的中文回退字体从 fonts.gstatic.com 下载。若同学网络访问不到会显示方块。是否内置 Noto Sans SC（约 8–10 MB，首次加载变慢）？
18. `flutter test` 第一次运行偶发 “Building native assets failed”（sqlite3 原生资源构建钩子），重跑即通过。
19. 限流默认值：每 IP 20 次/秒（突发 60）、每用户 10 次/秒（突发 40）。校园网 NAT 下大量同学共用出口 IP，可能误伤；是否以用户维度为主？
20. CI 的自动部署步骤需要服务器地址与 SSH 密钥，目前是占位。
21. **浏览器本地缓存**：在 Claude 应用的内置浏览器里，drift 的 Worker 取 `sqlite3.wasm` 报 `Failed to fetch`（文件本身能正常下载），
    离线缓存不可用。客户端已改为缓存失败不影响在线使用；请有 Chrome / Edge 的同学确认正常浏览器里离线缓存是否工作。
