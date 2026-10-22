# 待确认问题

按约定，不确定的需求记在这里，不自行发挥。每条写明：现状（我暂时怎么做的）、需要谁决定。

## A. 需要组长 / 老师决定

第 1–8 条已于 2026-10-22 由组长决定，见 [decisions.md](decisions.md)。尚待提供：

1. **平台发信账号**：注册验证码、每日摘要邮件、运维告警都经它发出（`GLEANER_PLATFORM_SMTP_*`）。谁提供、用哪个邮箱服务？
2. **大模型服务商**：OpenAI 兼容接口的地址、模型名、密钥与额度由谁提供？

## B. 需要实地确认（第 1–2 周任务）

9. 本校 Moodle 是否开放 Web Service（`moodle_mobile_app`）、是否走统一认证（CAS/SSO）、是否提供 iCal 导出；云端能否访问。
10. 学院通知网站的真实 HTML 结构：模板里的 CSS 选择器（`ul.news-list li`、`.arti-content` 等）是按 fake_moodle 写的，需要按真实页面调整。
11. 学校邮箱是否支持 IMAP / POP3、是否要求 OAuth2、是否允许应用专用密码；SMTP 端口与 STARTTLS 支持情况。
12. 真实站点的 robots.txt：引擎遵守 robots，若禁止相关路径会把来源标为“检查失败”。需登录的个人来源是否也遵守？
13. 截止时间与变更说明按 `GLEANER_TZ=Asia/Shanghai` 计算；本机开发环境时区不同时，变更说明里的时刻会和界面本地时间不一致（演示机请确认时区）。

## C. 环境与未验证项（需要有环境的同学协助）

14. **Docker 未安装**：`docker compose up` 未实际启动；PostgreSQL 路径只做了代码适配，测试都跑在 SQLite 上；GreenMail 的启动参数需实测。
15. **评估数据**：实验 2、3、4（无丢包）与网关 REST 吞吐已在 Windows 上跑出第一轮数据（见 [evaluation/README.md](evaluation/README.md)）；Autobahn、5000 连接、实验 1（select/epoll）、实验 5、丢包注入、Wireshark 抓包需要 Linux，等 WSL 2 + Docker 安装后补。
16. **Flutter 其他平台**：只构建并验证了 Web。Windows 本机需开启“开发者模式”（插件需要符号链接）才能构建 Android / Windows；
    Android 后台常驻 MQTT（前台服务）未实现；iOS、macOS 未配置。
17. **中文字体**：Flutter Web 的中文回退字体从 fonts.gstatic.com 下载。若同学网络访问不到会显示方块。是否内置 Noto Sans SC（约 8–10 MB，首次加载变慢）？
18. `flutter test` 第一次运行偶发 “Building native assets failed”（sqlite3 原生资源构建钩子），重跑即通过。
19. 限流默认值：每 IP 20 次/秒（突发 60）、每用户 10 次/秒（突发 40）。校园网 NAT 下大量同学共用出口 IP，可能误伤；是否以用户维度为主？
20. CI 的自动部署步骤需要服务器地址与 SSH 密钥，目前是占位。
