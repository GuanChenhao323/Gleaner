# 里程碑计划与状态

按约定原本“一次只做一个里程碑”；本轮按组长要求一次性实现了 P0、P1、P2 与全部核心技术模块，
因此下面每个里程碑都标为 **已实现 · 待组内验收**，验收时请按“验收方式”逐项确认后改为“已完成”。

状态说明：✅ 已完成 · 🟡 已实现待验收 · ⏳ 未开始 · ⚠️ 部分完成（见备注）

| # | 里程碑 | 内容 | 状态 | 验收方式 |
| --- | --- | --- | --- | --- |
| M1 | 协议基础 | HTTP/1.1 服务端与客户端（chunked、keep-alive、条件请求、Range）、WebSocket、内部二进制总线、Prometheus 指标 | 🟡 | `pytest tests/test_http.py tests/test_websocket.py tests/test_bus.py`；与 requests / websockets 库互通 |
| M2 | MVP（P0） | 账号、校园模板、网页 / RSS 采集与变化监测、统一收件箱、WebSocket 实时推送与未读同步、来源状态 | 🟡 | `pytest tests/test_e2e.py -k notices`；`python devtools/dev_all.py --seed` 后浏览器走一遍 |
| M3 | Moodle 与变更跟随（P1） | 来源登录与会话（只存会话）、Moodle Web Service + 网页解析、作业列表与日历、事项版本与重要变更、截止抽取与提醒 | 🟡 | `test_full_demo_path`；fake_moodle 管理台“提前 2 天” |
| M4 | 推送可靠性（P1） | 推送节点手写反应器（epoll/select）、MQTT 3.1.1 Broker（QoS 0/1、持久会话、保留、ACL、WebSocket 传输）、断线补发、故障转移、离线缓存与操作回放 | 🟡 | `pytest tests/test_mqtt.py`；e2e 中结束推送节点后重连补发 |
| M5 | 邮件（P1） | IMAP IDLE、POP3、SMTP STARTTLS 发信（附件、防重复）、跨渠道合并 | 🟡 | `pytest tests/test_mail.py`；`test_mail_merge_and_send` |
| M6 | 个性化与看板（P1） | 规则打分与分级推送、免打扰、每日摘要、不重要反馈、自定义看板 | 🟡 | `pytest tests/test_core.py`；客户端看板编辑 |
| M7 | P2 加分项 | 课程与教师信息、大模型摘要（可选）、扫码传输（分块、断点续传、校验）、本地采集代理、自研 DNS | 🟡 | `test_transfer_chunked_resume_and_range`、`test_local_agent_long_connection`、`test_dns.py` |
| M8 | 部署与运维 | Docker Compose、Prometheus + Grafana 面板与告警、CI、HTTPS / MQTT TLS | 🟡 | `docker compose --profile dev up -d --build` 后 `python devtools/compose_demo.py` 全部通过（PostgreSQL、GreenMail 实测）；HTTPS 证书与 CI 部署待云服务器 |
| M9 | 评估 | Autobahn、5000 连接压测、对比实验 1–5、故障注入、Wireshark 抓包 | ⚠️ | Windows 与 Linux（WSL 2）数据齐全：select/epoll 曲线、反应器 5000 连接、tc netem、网关多 worker，见 docs/evaluation；官方 Autobahn 已通过（asyncio 版 0 失败）；跨机器扩容、抓包待补 |
| M10 | 上线与用户 | 云服务器、域名证书、内测、≥ 50 名真实用户、SUS 问卷 | ⏳ | — |
| M11 | 真实平台接入 | 先接 MUST Moodle（授权登记 → 探测 → 本人登录 → 适配解析 → 24 小时验收）；之后视情况接飞书、X、Facebook | ⏳ | 等待授权；流程与验收见 `docs/integrations/must-moodle.md` |

## 当前测试基线（2026-10-22）

- 服务端：`pytest` 151 项通过、2 项跳过（跳过的是需要 PostgreSQL 的 `test_storage_pg.py`）；Windows 与 Linux / WSL 2 各跑一遍；`ruff check`、`ruff format --check` 通过。
- PostgreSQL：`GLEANER_TEST_PG=postgresql://… pytest tests/test_core.py tests/test_e2e.py tests/test_mail.py tests/test_storage_pg.py` 40 项通过。
- compose：`docker compose -f deploy/docker-compose.yml --profile dev up -d --build` 后 `python devtools/compose_demo.py` 全部步骤通过。
- 客户端：`flutter analyze` 无问题；`flutter test` 6 项通过；`flutter build web --release` 成功。
- 端到端：同进程组合 fake_moodle + 业务 + 2 个推送节点 + 网关 + Broker + 采集 + 邮件服务，覆盖三个演示时刻。
