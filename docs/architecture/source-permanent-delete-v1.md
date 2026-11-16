# Interface Contract — 来源回收区 → 永久清理与采集代次

**接口ID：** IC-SOURCE-PURGE-001
**版本：** v1.0（已实现；本地隔离数据库与界面复核）
**负责人：** Flutter／Core／插件
**最后更新：** 2026-11-16

## 1. 接口概述
本人已软删除来源的物理清理；移除关联资料与版本、任务、回执、无用来源绑定，释放原身份。账号级采集代次隔离此前预览与离线提交，不继续保存目标来源墓碑。学校Cookie不在清理范围。

## 2. 通信协议
既有自研HTTP JSON、Bearer、schema_version=1／ok=true。最低Chrome110与现有权限不变。只清理应用记录，不承诺磁盘安全擦除或外部备份。

## 3. 输入
- GET `/api/v1/reading-sources/{id}/purge-preview`：仅本人已删除来源；返回影响plan与HMAC token，5分钟有效，含owner／source／revision／generation、关联资料ID与版本、受影响规则修订及计数。
- POST `/api/v1/reading-sources/{id}/purge`：`{plan,token,confirm:true}`。事务中重新计算计划；影响／修订变化409，非法签名422，跨用户404，未先软删除409。
- GET `/api/v1/capture-context`：返回账号`generation`、保留的`resident_pages` UUID、`reading_sources:[{id,revision}]`、`monitors:[{id,revision}]`与当前可访问的`item_ids`（不含Cookie／URL／原文）。来源列表包含软删除但尚未物理清理的行；客户端据修订过滤失效在途结果，保留无关规则。
- captures／web-captures／timeline-captures外层可选`capture_generation:int>=0`；缺省0兼容旧客户端。用户永久删除后gen递增，旧值409 `capture_context_changed`。后台检查结果走既有租约与修订，不因无关来源清理被当成旧预览。
- 用户确认：永久删除让该账号之前未完成预览统一失效；其他账号隔离。插件连接后清理旧代次草稿、提交缓存及无用绑定，再允许新提取。不离线假称新代次有效，服务端最终校验。

## 4. 输出
- 预览：`{plan,token}`，计数显示资料、版本、检查记录、受影响规则；不接受客户端自行指定删除资料清单。
- 清理：`{source_id,purged:true,item_ids,purged_source_ids,paused_source_ids,generation,already_absent}`。同有效签名计划的响应丢失重试可确认已不存在，不另存来源墓碑或删除回执。新采集正常建立新来源与资料，不恢复旧版本。
- 本人其他规则引用相同资料时：空规则清理、含其他资料的规则暂停并清空旧快照／任务，要求重新提取以确认范围；其他资料版本保留。涉及他人／公共／外部订阅资料时409 `shared_document`，不得物理删除。
- Flutter删除内存、离线缓存和待回放个人操作，刷新列表与详情；联网其他工作台收到清理通知，离线端重连按代次刷新缓存。插件离线时需待重新连接完成本地清理，后端仍拒绝旧提交。


## 5. 实现与验证边界

- `SourcePurgeService`独立计算影响、签名与原子清理；`CaptureFence`通过账号行写锁协调清理与采集写入，生产依赖和自研协议不变。
- `CaptureContextSync`串行同步插件草稿、Outbox、任务与专用页绑定。断网只沿用已知代次，不冒充取得新代次；服务端最终拒绝旧值。首次永久清理之后，旧插件需更新，不能继续缺省代次0。
- Flutter repository校验回执，确认框呈现数量；FeedStore在刷新、重连、实时清理通知和在线每分钟核对时清理离线正文及待回放备注。缓存失败显示“服务器已删除、本机清理待重试”，不把后端提交回滚为未删除。
- 91项相关后端、150项插件模拟和24项Flutter测试通过；其中10项后端清理测试使用临时数据库，含真实loopback HTTP＋实际插件生命周期模块／模拟storage互通。覆盖计划篡改／过期／变化、原子回滚、他人保护、同条件新建和无关监测继续更新。
- Chrome157实机复核0.13扩展加载、Flutter影响确认／勾选门槛／取消，以及旧拒绝预览的来源管理入口。未在用户账号上执行不可恢复删除；不将此界面检查描述为真实Chrome全链路永久清理验收。
