# Interface Contract — 通用网页片段 → Core → 工作台

**接口 ID：** IC-WEB-CAPTURE-001
**版本：** v1.0（已实现；实机范围见验证报告）
**负责人：** 插件／Core／Flutter
**最后更新：** 2026-11-14

## 1. 接口概述

| 项目 | 说明 |
|---|---|
| 发送模块 | 通用 DOM 提取器、PageExtractionService、持久 outbox |
| 接收模块 | WebCaptureService、既有 Pipeline、Flutter 资料详情 |
| 接口用途 | 明确保存当前页匹配片段；不推断完整正文、公开状态或原生身份 |
| 通信方式 | runtime message v2 向后兼容；HTTP JSON＋Bearer 鉴权 |

## 2. 通信协议

新增 POST `/api/v1/web-captures`、GET `/api/v1/web-captures/{request_id}`、GET `/api/v1/web-captures`（当前 owner 最近100份集合摘要，不返回正文）。校园原生 captures 和监测接口不变。通用请求不接受校园 binding、recipe、enabled、原生 entity_id。source_binding 是用户明确声明的来源隔离标签，不是网站鉴权凭证。仅快照，不产生监测任务。

默认站点策略为 generic；已知校园域名保留专用策略，专用读取报错或只预览时不回退。默认条件是字面关键词／短语，NFKC、大小写与基础繁简规范化；不做语义扩写。可选 match_scope=`content`（正文与列表）或 `title`（标题／链接标题），默认 content。校园专用语法继续兼容，不宣称支持通用自然语言。

DOM 只处理主 frame 和开放 Shadow DOM（已由合成结构验证）；iframe、关闭 shadow、画布及未加载内容不被声明为已读。只返回命中后的有界块，单片段≤20000 字、最多100条预览／30条保存；过大直接报错，不静默截断。输入值、可编辑区域、隐藏内容、脚本和样式不参与。

## 3. 输入

| 字段 | 类型 | 语义及约束 |
|---|---|---|
| schema_version | int | 1 |
| request_id | UUID string | 预览任务 ID；同 owner＋ID＋相同请求重试返回原回执，不同内容409 |
| device_id | string | 设备标识，非网站账号身份 |
| source | object | url、title；完整 query/hash；不含凭据／敏感令牌参数 |
| query | string | 用户字面条件，1–200字 |
| match_scope | enum | content/title |
| observed_at | number | 浏览器采集 UTC epoch 毫秒；不等同后端检查时间 |
| source_binding | object | kind=public/labeled；public 的 label 固定“公开网页”，labeled 为用户填写的1–80字标签，不自动确认账号 |
| fragments | array | 1–30；candidate_id、title、text、evidence、context；整组格式化原文总长≤20000字，超限拒绝，不截断 |
| evidence | object | channel=dom、locator、text（与片段正文一致）；只作溯源，不作业务身份 |
| context | object | frame_url、boundary（paragraph/list_row/table_row/section/text）、completeness=fragment、matched_by=literal；非完整邮件／文章 |

页面 URL 是来源，匹配链接可作为预览辅助，不能以未打开链接当已读取详情来源。敏感输入从来不进入请求。无法识别网站账号时 account_state=unknown，仅保存当前资料，不进行账号合并或重新获取。校园资料不能由伪造 generic source 绕过既有策略。

用户已确认：允许片段快照；整组匹配作为一份资料，按同 owner＋source_binding＋完整 URL＋NFKC/大小写/空白规范化条件＋match_scope 合并。不同标签、URL query/hash、条件或范围互相隔离。网站账号无法自动核实时必须由用户选择／填写标签；切换账号须切换标签。后端不能据此声称网站账号已认证。

## 4. 输出

信封 `{schema_version:1,ok:true,request_id,candidate_ids,results:[{candidate_id:"collection",capture_id,item_id,source_id,status,fragment_count,version}]}`。整组是一项资料，results 必须恰有一项；candidate_ids 必须与提交 fragments 的 ID 顺序完全一致。status=new/changed/unchanged，ID／version 为正整数，capture_id 为服务端 UUID。HTTP 200、空对象、缺字段、缺少片段确认或数量错乱不算成功。校验失败整组拒绝，不保存部分资料。GET 返回原请求回执，其他 owner 不可查询。

后端建立 web_collections 和 web_capture_requests，内部 capture_id 是资料集合 ID，绝不是原站事项 ID。URL 和条件作为用户明确选择的资料身份，不按每个片段的位置／标题自动认定原站事项。一组片段保留各自原文与依据；明确保存后经既有 Pipeline 更新资料版本并投递，用户备注／待办状态不覆盖。零匹配不能保存为空集删除原资料。元数据含 account_state=unverified、scope=current_rendered_view、completeness=fragment、monitoring=false。没有 browser_monitor，也不启动后台采集。

错误：schema_version/invalid_request/invalid_url/invalid_snapshot/invalid_targets/duplicate_candidates/page_not_ready/idempotency_conflict/not_found；浏览器另区分 unsupported（非HTTP）、need_login、permission_denied、render_timeout、content_too_large/candidate_limit、route_mismatch、worker_interrupted。outbox 沿用最多三次自动重试、鉴权恢复、显式重试和持久回执。


## 5. 实现与验证边界

执行链：content/scoped/generic.js → extraction/fragments.js → extraction/web-payload.js → background.enqueueWebCapture → lib/outbox.js → core/web_captures.py → Pipeline → Flutter。新建 web_collections/web_capture_requests 表，不修改校园 native 监测表结构。服务启动自动建表；已有数据保留。

2026-11-14：Node 92项、后端相关65项、Flutter 11项通过；真实 Chrome 本地无适配标记页面两条匹配和整组保存确认，Flutter 来源、片段与版本差异经独立浏览器核验。真实 Gmail、未登记学校 DOM、Chrome 110 最低版本实机、嵌入／关闭 Shadow DOM 不在本轮通过声明中。真实 Chrome 已验证原页关闭、扩展重载后恢复预览并更新资料37至v2；在途回执丢失／异常响应仍主要由模拟 Chrome API 验证。

## 2026-11-15 兼容扩展：条件来源

扩展 0.9.0 的明确保存可选携带 `reading`，按 [IC-READING-SOURCE-001](condition-monitoring-v1.md) 原子关联原集合，回执增加 `reading_source_id`。不带该对象的旧客户端仍仅保存快照。公开声明的来源可经重读测试后配置手动／周期检查；私人来源标签不能证明账号身份，无法可靠核对账号时仍保留原页手动采集。原 URL／条件／范围／标签的整组版本与原有幂等语义保持。

## 2026-11-16 集合事务复用

WebCaptureContract的来源／绑定／片段／正文／元信息策略可替换，由TimelineCaptureContract复用集合事务及幂等存储。通用端点字段、身份和校园域名拒绝规则保持；Timeline使用独立端点与账号绑定，不能用公共标签绕过校园限制。回执按类型隔离，generic集合列表不混入Timeline。见 [IC-TIMELINE-SUMMARY-001](timeline-summary-v1.md)。
