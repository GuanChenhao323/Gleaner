# Interface Contract — Chrome 插件 → 本地后端

**接口 ID：** IC-001
**版本：** v1.0（草案，后端已实现）
**负责人：** 插件负责人（待填） / 后端：GuanChenhao323
**最后更新：** 2026-11-06

依据：产品定义 F01–F03、F07–F09、US01–US02、US07–US09；决策 D19–D24。

## 1. 接口概述

| 项目 | 说明 |
|---|---|
| 发送模块 | Chrome 插件（弹窗与后台 service worker） |
| 接收模块 | 本地后端 core（经网关 `http://localhost:8080`） |
| 接口用途 | ① 批量保存用户勾选的候选事项；② 领取监测任务并回报重新获取的结果 |
| 通信方式 | HTTP/1.1 + JSON（UTF-8），自研 HTTP 服务端（`server/gleaner/net/http/`） |

共三个接口：

| 方法与路径 | 用途 |
|---|---|
| `POST /api/captures` | 批量保存同页多条事项 |
| `GET /api/monitor/due` | 领取到期的监测任务 |
| `POST /api/monitor/results` | 回报重新获取的结果 |

旧接口 `POST /api/clips {url, title, text}` 保留兼容，等价于一条 `locator` 为空的整页事项，新插件不再使用。

## 2. 通信协议

- 鉴权（D24）：`Authorization: Bearer <token>`，令牌由 `POST /api/auth/login` 取得。令牌失效、会话被吊销统一返回 `401`；插件应清掉令牌并提示重新登录，不能把 401 当成保存成功或“无变化”。
- 请求体上限 2 MiB（网关限制），超出返回 `413`。
- 错误统一格式：`{"error": "<code>", "message": "<给人看的说明>"}`。
- 插件只对用户填写的后端地址申请主机权限；页面读取用 `activeTab` + `scripting`，不读取表单、密码、Cookie。
- 网络失败、超时、5xx、非 JSON 响应：插件一律显示“保存失败”，不显示成功。

## 3. 输入

### 3.1 `POST /api/captures`

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| `page.url` | string | 必填 | 当前页面网址，只能是 http/https，≤ 2048 字符。规范化后参与事项身份 |
| `page.title` | string | optional | 页面标题，≤ 300 字符 |
| `page.platform` | string | optional | `moodle` 或 `web`，只用于展示和统计 |
| `items` | array | 必填 | 用户勾选的候选事项，1–50 条。未勾选的不要发送 |
| `items[].locator` | string | 必填 | 页内定位符，≤ 200 字符，同一请求内不能重复。同一事项每次采集必须得到相同的值，例如 `cmid:123`、`#notice-45`。没有稳定标识时，用规范化标题（去首尾空白、合并空白、小写）的 SHA-1 前 12 位，写成 `t:xxxxxxxxxxxx` |
| `items[].title` | string | 必填 | 事项标题，≤ 300 字符，不能为空 |
| `items[].text` | string | optional | 事项正文，≤ 100000 字符 |
| `items[].url` | string | optional | 事项自己的链接（如作业详情页），默认等于 `page.url`；只能是 http/https |
| `items[].type` | string | optional | `todo`／`event`／`notice`，插件的分类建议。缺省时后端按默认规则判定（D21） |
| `items[].fields.deadline_at` | number \| null | optional | 截止时间，Unix 秒。不确定就不给或给 null，不能猜 |
| `items[].fields.start_at` | number \| null | optional | 活动开始时间，Unix 秒 |
| `items[].fields.end_at` | number \| null | optional | 活动结束时间，Unix 秒 |
| `items[].fields.location` | string | optional | 地点，≤ 200 字符 |
| `items[].fields.requirements` | string | optional | 提交或参加要求，≤ 4000 字符 |
| `items[].fields.course` | string | optional | 课程名，≤ 100 字符 |
| `items[].monitor.supported` | boolean | optional | 插件适配器确认该页面可以在关掉标签页后重新获取（Spike 02 已验证的页面类型），默认 false。为 true 时后端默认启用监测 |

后端在 `text` 里只做规则抽取：插件没给截止时间时，正文里写明的日期会被识别；识别不到就保持为空。

### 3.2 `GET /api/monitor/due`

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| `limit`（查询参数） | int | optional | 本次最多领取几条，1–50，默认 20 |

领取后这些任务被租用 5 分钟，期间不会再次发出；插件没在租期内回报，任务会重新到期。

### 3.3 `POST /api/monitor/results`

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| `results` | array | 必填 | 1–50 条 |
| `results[].item_id` | int | 必填 | 来自 `monitor/due` |
| `results[].ok` | boolean | 必填 | 是否成功重新获取并找到该事项 |
| `results[].title`、`text`、`url`、`type`、`fields` | 同 3.1 | ok 为 true 时 `title` 必填 | 重新获取到的内容，格式与保存时相同 |
| `results[].error.code` | string | ok 为 false 时必填 | `auth_expired`（登录过期）、`forbidden`（无权限）、`network`（网络错误或超时）、`not_found`（页面或定位符找不到）、`parse_failed`（页面结构变了）、`unsupported`（该页面不再支持） |
| `results[].error.message` | string | optional | ≤ 300 字符，给用户看的说明 |

插件的调度约束：同一主机两次请求至少间隔 2 秒；同一页面上的多条事项只取一次页面再按定位符逐条提取；真实站点遵守 `CLAUDE.md` 的授权与访问范围。

## 4. 输出

### 4.1 `POST /api/captures` → `200`

请求合法时总是返回 200，逐条看结果。

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | boolean | 全部成功才为 true |
| `saved` | int | 成功条数（new + changed + unchanged） |
| `failed` | int | 失败条数 |
| `results[].index` | int | 对应请求里 `items` 的下标 |
| `results[].locator` | string | 原样返回 |
| `results[].status` | string | `new`：新建；`changed`：已有事项内容变化，记了新版本；`unchanged`：已有且无变化；`error`：这一条没保存 |
| `results[].item_id` | int \| null | 事项 id，失败时为 null |
| `results[].type` | string \| null | 后端最终判定的类型 |
| `results[].monitor` | string \| null | `enabled`／`unsupported` |
| `results[].error` | object \| null | `{code, message}`，例如 `invalid`（这一条字段不合法）、`internal`（写入失败） |

整批拒绝（什么都不保存）：

| 状态码 | `error` | 情况 |
|---|---|---|
| 401 | `unauthorized` | 未登录或令牌失效 |
| 413 | `too_large` | 请求体过大 |
| 422 | `bad_url` | `page.url` 不是 http/https |
| 422 | `invalid` | `items` 为空、超过 50 条、`locator` 重复或缺失 |
| 429 | `rate_limited` | 请求过于频繁 |

### 4.2 `GET /api/monitor/due` → `200`

| 字段 | 类型 | 说明 |
|---|---|---|
| `tasks[].item_id` | int | 事项 id |
| `tasks[].page_url` | string | 要重新打开的页面 |
| `tasks[].locator` | string | 页内定位符 |
| `tasks[].title` | string | 当前标题，便于提示 |
| `lease_s` | number | 租期秒数（300） |
| `next_due_at` | number \| null | 没有到期任务时，下一个任务的到期时间，插件可据此安排下次轮询 |

### 4.3 `POST /api/monitor/results` → `200`

| 字段 | 类型 | 说明 |
|---|---|---|
| `results[].item_id` | int | 原样返回 |
| `results[].status` | string | `unchanged`、`changed`、`failed`、`error`（回报本身无效，例如事项不存在或没启用监测） |
| `results[].last_success_at` | number \| null | 更新后的最后成功检查时间；失败时保持原值 |
