# Interface Contract — Chrome 原始采集 → Core → Flutter

**接口 ID：** IC-BROWSER-001

**版本：** v1.1（成功信封 schema_version 仍为 1）

**负责人：** 插件／网页采集 / 后端及 Flutter 接线

**最后更新：** 2026-11-11

## 1. 接口概述

| 项目 | 说明 |
|---|---|
| 发送模块 | Chrome 内容适配器、持久后台；Flutter 监测控制 |
| 接收模块 | Core BrowserMonitorService；既有 Pipeline／推送／Flutter |
| 接口用途 | 所选候选独立保存、关联原始快照、单一调度和检查结果确认 |
| 通信方式 | 本地网关 HTTP JSON + Bearer；既有 WebSocket 推送事项 |

## 2. 通信协议

所有已鉴权 v1 成功响应必须为 JSON 对象并含 `schema_version:1, ok:true`，业务错误为非 2xx 且 `{schema_version:1,ok:false,error,message}`。HTTP 200、HTML 或空 JSON 不是成功。401 沿用既有鉴权错误格式，不含成功信封。旧 `/api/clips` 和模板接口兼容保留，新扩展不使用 clip/page 双记录。

| 方法 | 路径 | 语义 |
|---|---|---|
| POST | /api/v1/captures | 按 request_id 幂等的候选批次；逐项成功或失败 |
| GET | /api/v1/captures/{request_id} | 当前用户持久结果查询 |
| GET | /api/v1/monitors | 当前用户目标、运行状态与原事项 ID |
| PUT | /api/v1/monitors/{id} | `{revision,enabled}`；递增配置版本，撤销在途租约 |
| DELETE | /api/v1/monitors/{id} | 停止并软删除监测；保留已保存事项／历史 |
| POST | /api/v1/monitors/{id}/check | 请求立即检查；仍由同一租约机制执行 |
| GET | /api/v1/monitors/{id}/checks | 检查记录，不含其他用户内容 |
| POST | /api/v1/monitor-jobs/claim | `{device_id}`；至多一项，120 秒租约；后端是唯一调度者 |
| POST | /api/v1/monitor-jobs/{id}/result | 绑定设备、租约及配置版本的结果；重复确认不重复版本 |

任务默认 600 秒周期；Chrome alarm 60 秒唤醒，不是第二套计划。单个任务最多 3 次租约尝试；到期后记录失败并进入下一周期。执行按主机串行、至少 2 秒间隔；不会补跑所有离线周期。暂停／删除／配置版本变化后旧结果返回 409，不能写回。

## 3. 输入

| 字段 | 类型 | 必填/optional | 语义及约束 |
|---|---|---|---|
| schema_version | integer | 必填 | 1；仅 captures/result 需要 |
| request_id | string | 必填 | 客户端 UUID，1–100 字符；同用户相同 ID 不同请求体返回 409 |
| device_id | string | 必填 | Chrome 安装设备 UUID，不能跨设备执行旧任务 |
| binding | object | 必填 | `{adapter,origin,account_key}`；account_key 为设备加盐的学校账号散列，公开来源为 public，不是 Campus Radar uid |
| targets | array | 必填 | 1–30 个用户条件匹配且已确认预览的目标；未匹配内容不上传（旧客户端选择协议仍兼容） |
| targets[].candidate_id | string | 必填 | 批次内唯一，结果回显 |
| targets[].entity_id | string | 必填 | 原站活动 ID／人员 ID／资讯 ID；手动补充用稳定元素 ID；不接受标题／内容 hash／序号身份 |
| targets[].locator | object | 必填 | `{url,frame_url,view}`；保留 query/hash，view 是学期／周次／节次等上下文；首版主 frame，跨 frame 明确不支持 |
| targets[].raw | object | 必填 | `{title,text,fields}`；title 1–300，text 1–20000 字符；超限拒绝，不静默截断。fields 只含原文可见元数据，无 Cookie／密码／整页 HTML |
| targets[].recipe | object | 必填 | v1：`{adapter,version:1,entity_id,url,view,selector}`，初次与重新获取共用适配器；v2：`{adapter,version:2,strategy:'snapshot',entity_id,url,view}`，仅显式快照保存，必须 supported=false、enabled=false；URL 与 locator 一致 |
| targets[].supported | boolean | 必填 | 已有确定重入方式和账号识别；未知真实 DOM 不得冒充已验证 |
| targets[].enabled | boolean | 必填 | 用户启用意愿；supported=false 时不得启用 |
| result.lease | string | 必填 | 后端随机租约；校验当前用户、设备、配置版本和时限 |
| result.revision | integer | 必填 | 认领时版本 |
| result.status | enum | 必填 | success / need_login / selection_missing / view_mismatch / route_mismatch / render_timeout / permission_denied / unsupported / account_mismatch / failed |
| result.raw | object | 成功必填 | 与首次采集相同 raw 规则；空／加载壳／登录页不是成功 |
| result.account_key | string | 成功必填 | 与原绑定相同；切换账号时暂停旧任务，需人工确认，不能自动重绑 |

后端身份 = 当前 uid + binding（平台／origin／学校账号）+ entity_id + frame/view 上下文，不使用标题、内容 hash 或页面序号。详情 URL 留作定位；FIE locale 不决定人员身份，Moodle 入口与同活动详情使用同一 entity_id。课表没有完整日期时，时间原文和学期／周次／节次只作为上下文，不推算截止或日期。

2026-11-11 兼容扩展：recipe v2 拒绝支持／启用监测（snapshot_monitor_unsupported / monitor_unsupported），不把临时页面定位依据当作重入配方。新 UI 按条件匹配后一次保存整组预览，见 IC-EXTRACTION-001 v2；不提供监测启用选项。raw.fields 允许新增 `published_text`、`valid_until_text`、`course_code`、`class_group`、`location`、`date_text` 原文键；分别保留时间语义，不在插件推断截止。v1 不迁移；已有同一身份但 recipe 不同仍返回 binding_or_recipe_changed，不能静默覆盖旧配置。事项详情 browser_monitor 的 enabled/supported 统一返回 JSON boolean。

## 4. 输出

| 字段 | 类型 | 说明 |
|---|---|---|
| results | array | captures 按 candidate_id 回显；每项 `{candidate_id,status,monitor_id,item_id}` 或 `{candidate_id,status:'failed',error,message}`；status new/changed/unchanged/failed |
| request_id | string | 查询与重试必须保留；请求／逐项结果持久化 |
| monitors | array | 私有目标及 item_id、recipe、revision、enabled、supported、last_result、last_attempt_at、last_success_at、error；不返回其他用户数据 |
| job | object/null | `{id,monitor_id,lease,revision,device_id,binding,recipe,expires_at}`；无到期任务为 null |
| status / result | enum | result 确认的 status 返回 changed / unchanged / failed；result 保留具体检查状态；同时回显 job_id，只有收到匹配确认才可删除本地 outbox |
| checks | array | 每次检查的时间、结果、错误与事项版本，不以未执行当作无变化 |

配置状态 enabled/paused 与 last_result 区分。初次保存建立初始来源快照但检查结果仍 not_executed；后台成功后才更新最后成功检查时间。失败只记录检查及状态，不改成功快照／成功时间。Pipeline 保留用户个人备注及 deadline_override；来源版本不替代这些修正。批次中的验证失败逐项返回，服务异常回滚；事务提交后响应丢失可用同请求 ID 重试。过期／被撤销租约 409；相同完成结果重传返回原确认，不增加版本。

兼容映射：Moodle assignment → 既有 assignment（产品任务）；教师资料 → notice + teacher_profile；课表 → event + timetable，未知日期为 null；普通资讯 → notice。旧接口与旧数据不自动迁移或删除。浏览器来源为私有 type=browser，Python collector 不调度；调度／绑定／数据库只由后端模块维护。

本契约先于实现建立，现已由 `server/gleaner/core/monitors.py` 注册实现，并由后端契约／HTTP 集成测试、插件 Node 测试和本地 Chrome 联调核对。可复现步骤见 [插件说明](../browser-extension.md) 和 [合成夹具](../../devtools/campus_fixture/README.md)。真实站点支持范围必须另列，不由结构夹具或通用 Moodle 经验推定。


## 5. 预览、恢复和显式确认细则

- 首次 captures 只传用户看到的所选快照，详情候选必须先由 worker 读取并预览；不把保存前另一次隐式重读当成用户已看过。后续来源读取走 monitor job。
- browser identity 的 frame URL 规范化 query 键顺序；FIE locale 不增加人员身份，但 recipe 改变仍返回 binding_or_recipe_changed，当前无自动跨设备／recipe 迁移。
- 普通 enabled 控制不能解除 account_mismatch。v1 兼容客户端回到原账号重新识别、预览、保存并明确启用后，相同 binding 的既有记录可明确重新启用，配置 revision 增加，检查状态回到 not_executed，原成功历史保留。其他账号形成独立 binding；删除的监测不在保存时静默复活。已有启用目标的新采集未勾监测不会隐式暂停，暂停在来源面板明确执行。
- account_key 为浏览器侧设备盐散列，仅用于绑定一致性，不是学校授权凭据或服务端学校身份认证。不同 Chrome 安装不自动共用旧学校绑定；设备丢失／重新绑定流程后续另做。
- outbox 自动重试 3 次；401 待同用户重新登录，409 标为拒绝，手动重试不复活旧租约。队列最多 60 条／约 2MB；持久保存意图最多 20 条待处理／约 2MB，已确认回执只保留紧凑元数据。后端回执仍可按 request_id 查询，不依赖 popup。
- 视图对象按键比较，不能将 JSON 键顺序变化当成来源变化；真正学期／周次／路由变化分别报 view_mismatch / route_mismatch。失败不会写入新成功版本。
- 运行中 self-owned 标签先登记再导航；恢复清理非激活、仍在预期 URL／runner／同源登录重定向的标签。用户激活或导航到其他位置的标签保留。未知跨域 SSO 页面可能留给用户处理，不自动扩大权限。

## 2026-11-15 兼容扩展：条件来源

扩展 0.9.0 在已有原生保存请求中可选携带 `reading`（[IC-READING-SOURCE-001](condition-monitoring-v1.md)）。保存成功时同事务关联原事项并返回 `reading_source_id`；缺省保持本契约原语义。snapshot recipe v2 本身仍不启用旧 monitor，新条件来源单独保存查询及单一调度配置；旧已删除 monitor 的防复活保护保留。没有原条件的旧记录不自动迁移或推断关键词。
