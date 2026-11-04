# 已结束或被替代的决策

原编号保留供追溯；当前决定见 [决策记录](../decisions.md)。

| 编号 | 问题 | 当时决定 | 当时落地位置 |
| --- | --- | --- | --- |
| 1 | 提交方式 | 按里程碑拆分 commit（不区分成员） | git 历史重写为 M1–M7 若干提交 |
| 7 | 大模型（产品策略已由 D17 替代） | 旧实现：默认 OpenAI 兼容接口，接国内服务商；地址、模型、密钥三项齐全才启用，否则规则提取 | `core/summarize.py`、`deploy/.env.example`；测试 `tests/test_summarize.py` |
| 10 | 真实平台接入范围与顺序（已由 D16 替代） | 旧计划：在 P0–P2 之外新增真实平台接入（M11）。先接澳门科技大学（MUST）Moodle，之后接飞书国际版 Lark（X、Facebook 见第 13 条） | `docs/integrations/`；`docs/archive/milestones-before-2026-11-03.md` M11 |
| 12 | 飞书版本（已退出当前范围） | 旧计划：用国际版 Lark（`open.larksuite.com`），不用中国大陆版飞书（`open.feishu.cn`）；两者账号与数据互不相通 | 接入时在 `docs/integrations/` 登记；接口域名按 Lark |
| 13 | X（Twitter）、Facebook | 不接入 | 从 M11 范围中移除 |
| 15 | 浏览器插件（已由当前插件需求替代） | 旧实现：新增 Chrome / Edge 插件：点一下把当前页面“保存到收件箱”（当场读取正文）或“订阅更新”（整页监测 / RSS）。超出 proposal 原范围，作为 M12 | `docs/browser-extension.md`；`extension/`；`POST /api/clips`；web 连接器整页模式 |
