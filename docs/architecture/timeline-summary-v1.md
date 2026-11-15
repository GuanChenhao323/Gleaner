# Interface Contract — Timeline 摘要集合 → Core → 工作台

**接口 ID：** IC-TIMELINE-SUMMARY-001

**版本：** v1.0（已实现；分层验收见本轮本地报告）

**负责人：** 插件／Core／Flutter

**最后更新：** 2026-11-16

## 1. 接口概述

| 项目 | 说明 |
|---|---|
| 发送模块 | 已认证 Moodle Timeline DOM 候选、条件来源重读执行器 |
| 接收模块 | TimelineCaptureContract、集合保存事务、ReadingSourceService、Flutter |
| 用途 | 将当前匹配的活动摘要整组保存为资料，更新原版本；不是完整作业／日历事件 |
| 通信 | 既有 HTTP JSON＋Bearer；schema_version=1、ok=true |

## 2. 通信协议

- POST `/api/v1/timeline-captures`：明确保存，必须带 reading；复用持久 outbox，返回单个 collection 结果。
- GET `/api/v1/timeline-captures/{request_id}`、GET `/api/v1/timeline-captures`：owner 隔离的回执与集合。
- reading 沿 IC-READING-SOURCE-001，新增 `representation:timeline_summary`，source=moodle；旧配方缺省保持原生／通用表示，不迁移旧冻结预览。
- 明确 Timeline／时间线查询、content 范围、choice 为空、view 为空；只保存当前加载的 1–30 个活动。超过限制明确失败，不截断、不自动翻页。

## 3. 输入

| 字段 | 类型 | 约束 |
|---|---|---|
| schema_version／request_id／device_id | int／UUID／string | 1、稳定请求 UUID、执行设备 |
| collection_type | string | timeline_summary |
| source | object | url为Moodle HTTPS /my/（或localhost合成Dashboard）；title为页面标题 |
| query／match_scope／observed_at | string／string／number | 原条件、content、观测毫秒时间 |
| source_binding | object | adapter=moodle、同origin、设备加盐account_key；禁止public／unverified，不接受Cookie |
| fragments | array | 每条candidate_id、title、text、url、fields、evidence、context；不伪造entity_id |
| fields | object | course、date_text、datetime_text，均为原文字符串，缺失为空，不推断日期时区 |
| url | string | 同源活动详情URL；禁止凭据参数和action提交链接 |
| evidence | object | channel=dom、locator、text；text是可对照的原文，可包含日期上下文 |
| context | object | frame_url等于source.url、region=Timeline、completeness=summary |
| reading | object | 原URL／query／范围／account绑定一致；representation=timeline_summary |

一份集合的身份为 owner＋representation＋网站账号绑定＋完整URL＋规范化条件＋范围。活动没有可靠事件ID，不按行号／标题hash认独立事项。同详情链接的多行仍分别保留；集合比较忽略顺序／DOM定位位置，但保留条数及标题、正文、课程、日期／时间和链接变化。

## 4. 输出与兼容

回执结构兼容集合保存：request_id、candidate_ids、capture_type=timeline_summary、results=[{candidate_id:collection,capture_id,item_id,source_id,status:new|changed|unchanged,fragment_count,version}]、reading_source_id。严格核对后才显示保存成功。相同请求幂等；同request_id不同payload返回409，其他无效输入422；401未认证。逐活动不返回伪造原生事项ID。

资料仍为clip类型的集合，web_capture元信息带collection_type=timeline_summary、account_state=bound、completeness=summary及每条活动链接／原文字段。抑制自动截止日期推断，不写成assignment。Flutter标注“活动摘要资料”，活动链接进入原网页详情。来源检查复用现有验证、手动／周期、账号核对、租约、失败保护和版本流程；验证不改基线、空结果不清空原资料、变化不覆盖个人备注与状态。

旧 captures／web-captures 的请求和身份保持；通用网页端点继续禁止校园来源。课程入口、Support和混合摘要／完整作业的提交仍受原规则限制。旧预览需重新提取后取得新集合表示，不能静默升级已冻结内容。
