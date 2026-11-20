# 个人贡献记录｜陈鸿天（GitHub：HongtianChan）

更新：2026-11-20。依据：本人署名提交（`HongtianChan`）、组长合入的前端改版提交 `20a6e32` 及其中归档的改版建议、`docs/log/2026-11-18_HongtianChan/`、本地协作过程。数字可用文末命令复核。

## 0. 概览

| 项目 | 数据 |
| --- | --- |
| 分工 | **信息管理前端／工作台主界面**：信息展示、筛选、编辑与交互逻辑；品牌与视觉；不负责插件采集与自研协议栈 |
| 署名提交 | 3 个（`HongtianChan`）：约 105 文件次，+14,518 / −2,070 |
| 早期合入 | `20a6e32`（作者 GuanChenhao323，说明为「合并前端同学 2026-10-26 的修改」）：17 文件，+885 / −601；含本人改版建议归档 |
| 工作方式 | 本人定交互与视觉方向，在 Cursor / Claude 辅助下改代码与文档，本地验证后提交或交组长合入 |

## 1. 时间线

| 日期 | 依据 | 内容 |
| --- | --- | --- |
| 10-25～10-26 | `功能建议.md` → 归档 `docs/archive/frontend-suggestions-2026-10-26.md`；实现合入 `20a6e32` | 第一轮工作台改版建议与落地：紧急行着色、收件箱筛选、侧栏悬停、写邮件／扫码外置、「来源」改称「信息源」等 |
| 11-10 | 团队职责与范围确认 | 明确不做 Chrome Side Panel／插件采集，主责 **Flutter 主界面交互** |
| 11-11～11-12 | 品牌与图标设计过程 | Campus Radar 方向的图标草图、Figma 导出与资源替换（后续产品名回到 **拾课 Gleaner**，图标迭代为黄色 G） |
| 11-18 | `0826534` | 信息架构：去掉独立作业导航；课程主页／详情；看板截止日历 |
| 11-19 | `fb5c179` | 白黄主题；收件箱自定义标签（含后端迁移与 API）；紧急态改为左侧色条 |
| 11-20 | `991485f` | 默认英文 + 中英繁；演示种子英文；favicon；Courses／Sources 加载卡死修复 |

过程记录：`docs/log/2026-11-18_HongtianChan/`（`yellow-theme-inbox-labels.md`、`i18n-en-zh.md`）。

## 2. 第一轮前端改版（2026-10-26，合入 `20a6e32`）

本人先写改版建议，再改 Flutter 客户端；由组长审查合并。建议原文现归档为 [frontend-suggestions-2026-10-26.md](../docs/archive/frontend-suggestions-2026-10-26.md)。

| 建议点 | 落地 |
| --- | --- |
| 紧急事项整行提醒 | 24h 内／`urgent` 淡红底；72h 内「即将到期」淡黄；抽出 `dueRowAccent` 统一工作台／收件箱／作业列表 |
| 收件箱筛选过载 | 去掉「全部」；「重要」并入「收藏」；修未读强调与筛选条横滑；弱化右侧空态长文案 |
| 作业列表 | 去掉「全部课程」；紧急行同套着色；日历并入作业页（列表／日历切换） |
| 工作台看板 | 去掉可调宽高编辑，改为固定「今天要看的」板块 |
| 「来源」命名与设置过载 | 「来源」→「信息源」；写邮件、扫码移出设置，放入侧栏工具区 |
| 侧栏 | 默认收起仅图标，悬停展开、可固定；启动画面与图标资源更新 |

合入说明见提交信息：`合并前端同学 2026-10-26 的修改`（作者为 GuanChenhao323）。

## 3. 职责边界与品牌设计（2026-11 上旬）

- **职责**：团队表中对应「信息管理前端」（展示、搜索筛选、编辑、交互）。与插件负责人确认后：**不做插件 Side Panel**，主界面在 Flutter 工作台；插件只负责把网页内容送进工作台。
- **品牌／图标**：产品曾用 Campus Radar 方向；完成图标方向讨论、草图与资源替换试验。后续产品名固定为 **拾课 Gleaner**，应用图标迭代为黄色 G（见第 6 节）。

## 4. Flutter 信息架构（`0826534`）

目标：减少并行入口，让「课程」成为作业与截止日期的主入口，看板专注今日要事与日历。

- 删除独立 `assignments` 路由与页面；作业列表下沉到课程维度（`assignment_list.dart`）。
- 新增课程详情页（`course_detail_page.dart`）：待办、通知、教师联系方式。
- 看板：收紧类型筛选；接入截止日历（`deadline_calendar.dart`）。
- 侧栏与 `router.dart`：主功能收为 Desk／Inbox／Courses／Sources。

## 5. 视觉主题与收件箱标签（`fb5c179`）

### 5.1 主题（`client/lib/theme.dart`）
- **白底近中性画布 + 墨黑主控**，黄色仅作点缀（星标、未读点、标签、登录侧栏图标）。
- 紧急提示：由整行铺色改为卡片**左侧紧迫度色条**，去掉标题删除线，避免「已完成」误读（相对 10 月整行着色的迭代）。

### 5.2 自定义标签（前后端）
- 服务端：迁移 9 `labels`／`item_labels`；REST `GET/POST /api/labels`、`PUT/DELETE /api/labels/{id}`、`PUT /api/items/{id}/labels`；feed `filter=labeled&label_id=`；事项带 `label_ids`。
- 客户端：收件箱新建／筛选／删除标签；详情打标；「收藏」与自定义标签并存。

## 6. 多语言与英文首发（`991485f`）

| 项 | 说明 |
| --- | --- |
| 基础设施 | `l10n.yaml`、`app_en.arb`／`app_zh.arb`／`app_zh_TW.arb`、`localeProvider`（默认 `en`） |
| 表面 | Shell、登录、设置、收件箱、详情／看板／Courses／Sources 等 UI chrome |
| 服务端中文说明的本地化 | `change_note`、打分 `reasons`、监测失败原因、来源 toast 在英文 locale 下映射 |
| 品牌 | 标题 **拾课 Gleaner**；favicon／PWA icons 换黄色 G |
| 演示数据 | `fake_moodle` 与校园模板英文，避免英文 UI 下演示内容全是中文 |
| 缺陷修复 | Courses／Sources 不再监视 WebSocket `cursor` 导致一直转圈；改看 `lastSync` + `skipLoadingOnReload` |

## 7. 协作与边界

- 过程记在 `docs/log/2026-11-18_HongtianChan/`；产品定义类文档不擅自改。
- 10 月改版由组长合入；11 月署名提交在 `merge_branches`。
- 合入他人监测改动时保留对方侧栏 logo 锚定等交互，不覆盖监测模块。
- 自研协议、采集、总线、插件 DOM 采集由其他组员负责。

## 8. 尚未做完／可继续

| 事项 | 说明 |
| --- | --- |
| Sources 深层页全面 l10n | 深层页已英文化以保证默认英文；切回中文时部分可能仍显示英文 |
| 中文 locale 冒烟 | 设置／规则／删除账号等建议再走一遍 |
| 与监测 UI 文案统一 | 合入监测 handoff 后，Sources 状态 pill 可再统一走 ARB |

## 附：复核命令

```bash
# 本人署名提交
git log --author=HongtianChan --oneline
git log --author=HongtianChan --no-merges --shortstat --format= \
  | awk '{f+=$1; i+=$4; d+=$6} END {print f, i, d}'

# 10 月改版合入
git show 20a6e32 --stat
ls docs/archive/frontend-suggestions-2026-10-26.md
ls docs/log/2026-11-18_HongtianChan/
```
