# Interface Contract — 本地后端 → Flutter 工作台

**接口 ID：** IC-002
**版本：** v1.0（草案，后端已实现）
**负责人：** 后端：GuanChenhao323 / 工作台负责人（待填）
**最后更新：** 2026-11-06

依据：产品定义 F04–F09、US04–US09、第 2.3、2.4、4.2 节；决策 D19–D23。

## 1. 接口概述

| 项目 | 说明 |
|---|---|
| 发送模块 | 本地后端 core（经网关） |
| 接收模块 | Flutter 工作台 |
| 接口用途 | 按类型、状态列出事项；查看详情、来源与版本差异；修改字段与处理状态；查看和开关监测 |
| 通信方式 | HTTP/1.1 + JSON；实时更新沿用 WebSocket `/ws`（见 `docs/protocols/rest-api-and-sync.md`） |

| 方法与路径 | 用途 |
|---|---|
| `GET /api/feed` | 列表，新增 `type`、`status` 筛选 |
| `GET /api/items/{id}` | 详情，新增 `type`、`status`、`fields`、`conflicts`、`monitor` |
| `GET /api/items/{id}/versions` | 来源版本列表，新增每个版本的 `snapshot`，用于显示差异 |
| `PUT /api/items/{id}/state` | 处理状态，新增 `archived` |
| `PATCH /api/items/{id}/fields` | 修改字段或恢复来源值 |
| `POST /api/items/{id}/fields/resolve` | 处理冲突 |
| `PUT /api/items/{id}/monitor` | 开关监测 |

## 2. 通信协议

鉴权、错误格式、幂等键（`Idempotency-Key`）、后写胜出规则与现有 API 相同。401 时工作台回到登录页。

## 3. 输入

### 3.1 `GET /api/feed` 查询参数（新增部分）

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| `type` | string | optional | `todo`／`event`／`notice`。按用户修改后的类型筛选 |
| `status` | string | optional | 待办 `open`／`done`；通知 `unread`／`read`；日程 `active`／`archived`。可以不带 `type` 单独使用 |
| `origin` | string | optional | `capture`：只看插件采集的事项 |

原有 `kind`、`filter`、`course`、`q`、`cursor`、`limit` 照常可用。

### 3.2 `PUT /api/items/{id}/state`（新增部分）

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| `archived` | boolean | optional | 日程归档／取消归档 |
| `done` | boolean | optional | 待办完成／未完成；等价于 `todo: "done"`／`todo: "todo"` |

原有 `read`、`todo`、`starred`、`hidden`、`note`、`deadline_override`、`ts`、`op_id` 不变。

### 3.3 `PATCH /api/items/{id}/fields`

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| `set` | object | optional | 要修改的字段与新值。可修改：`title`（≤ 300，不能为空）、`summary`（≤ 2000）、`type`（三选一）、`deadline_at`、`start_at`、`end_at`（Unix 秒或 null）、`location`（≤ 200）、`requirements`（≤ 4000） |
| `reset` | string[] | optional | 要撤销修改、恢复为来源值的字段 |

`set` 与 `reset` 至少一个非空，同一字段不能同时出现。值为 null 表示用户确认“没有这个时间”，与“未修改”不同。

### 3.4 `POST /api/items/{id}/fields/resolve`

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| `field` | string | 必填 | 有冲突的字段 |
| `keep` | string | 必填 | `mine`：保留用户的值，以当前来源值为新的基准；`source`：采用来源的新值，删除用户修改 |

### 3.5 `PUT /api/items/{id}/monitor`

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| `enabled` | boolean | 必填 | 开关监测；不支持监测的事项打开时返回 `409 unsupported` |

## 4. 输出

### 4.1 事项对象（列表与详情共用，新增字段）

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | 生效类型（用户修改优先） |
| `status` | string | 按生效类型给出的处理状态，取值见 3.1 |
| `title`、`summary`、`deadline_at`、`requirements` | — | 已是生效值（用户修改优先） |
| `start_at`、`end_at`、`location` | number \| string \| null | 生效值 |
| `fields` | object | 每个可修改字段一项：`{value, source, edited, conflict}`。`value` 为生效值，`source` 为来源当前值，`edited` 表示用户改过，`conflict` 表示用户改过之后来源又变了 |
| `conflicts` | string[] | 有冲突的字段名，没有为空数组 |
| `origin` | string | `capture`（插件采集）或 `source`（订阅来源） |
| `page_url` | string | 采集时的页面网址（原始来源链接）；订阅来源的事项为事项链接 |
| `locator` | string | 页内定位符；订阅来源的事项为空 |
| `state.archived` | boolean | 日程是否已归档 |
| `monitor` | object | 见 4.2 |

原有字段（`id`、`kind`、`url`、`version`、`source`、`state` 其余部分、`change_note`、`important_change` 等）保持不变。

### 4.2 `monitor` 对象

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | `unsupported`：暂不支持；`disabled`：支持但用户关闭了；`pending`：已启用，还没检查过；`unchanged`：最近一次成功检查无变化；`changed`：最近一次检查发现变化；`failed`：最近一次检查失败 |
| `supported`、`enabled` | boolean | |
| `last_checked_at` | number \| null | 最近一次尝试时间（成功或失败） |
| `last_success_at` | number \| null | 最后成功检查时间，工作台必须显示这个值，失败不会更新它 |
| `error` | object \| null | 最近一次失败的 `{code, message}`，取值见 IC-001 3.3 |
| `next_check_at` | number \| null | 计划下次检查时间 |

工作台显示规则：`failed` 必须与 `unchanged` 区分显示；`auth_expired` 提示重新登录对应网站。

### 4.3 `GET /api/items/{id}/versions`

每个版本新增 `snapshot`：该版本的来源内容（`title`、`summary`、`body`、`deadline_at`、`requirements`、`start_at`、`end_at`、`location`、`url`）。工作台用相邻两个版本的 `snapshot` 显示差异，`changed_fields` 给出变化字段的新旧值。

### 4.4 `PATCH /fields` 与 `POST /fields/resolve` → `200`

返回更新后的完整事项对象（同 4.1）。错误：`404 not_found`、`422 invalid`（字段名或取值不合法）、`409 no_conflict`（resolve 的字段没有冲突）。

### 4.5 WebSocket 推送

字段修改、冲突处理、监测开关和监测结果都会向该用户的在线设备推送 `{"type": "item_updated", "item_id": …}`，工作台收到后重新拉取该事项详情。来源变化仍按原有 `change` 投递推送。
