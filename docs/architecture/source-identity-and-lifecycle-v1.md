# Interface Contract — 来源身份与个人资料生命周期

**接口 ID：** IC-SOURCE-LIFECYCLE-001
**版本：** v1.0（已实现；真实站点范围另行验收）
**负责人：** 插件／Core／Flutter
**最后更新：** 2026-11-16

## 1. 接口概述
插件读取显式账号控件，Core 保存身份绑定和来源墓碑，Flutter 管理个人回收站。所有操作按工作台 owner 鉴权。公开／私人仅表示原站登录要求，资料不因此分享给别人。

## 2. 通信协议
复用自研 REST、已有持久 Outbox 与个人状态同步；不传 Cookie／密码。扩展新增 extract.verifyAccount，在原标签当前 URL 上读取账号控件，不读取正文作为证明。

## 3. 输入
- source_binding 保留 {kind:public|labeled,label}，labeled 可选 identity:{version:1,probe:account-control-email-v1,account_key:64位小写 SHA256,display:脱敏邮箱}。标签不是证明。旧客户端仍可保存未核对私人资料。
- reading 可选 account_probe:{version:1,kind:account-control-email-v1,display}，binding.account_key 必须与 source_binding.identity 一致。旧 public/unverified 兼容；其他 generic key 必须带探针。
- 探针仅扫描可见、明确标注账号的控件／页面账号属性，唯一邮箱才成功。多个账号、只有正文邮箱、登录页或控件消失返回 account_unknown／need_login；不同指纹返回 account_mismatch。指纹使用本机已有随机盐，只有脱敏显示和指纹上传。已知登录型网页 mail.google.com、wx.mail.qq.com 不允许声明为无需登录；其他站点如检测到账号控件，也拒绝公开声明。未识别到账号不等于无需登录。
- DELETE /api/v1/reading-sources/{id}，JSON {revision:int,trash_items:bool}。首次需当前 revision；同模式重复删除返回相同结果，不升级删除范围。墓碑不允许重新保存恢复，返回 source_deleted；只有显式恢复接口可恢复。
- PUT /api/items/{id}/state 既有 hidden:true/false 作为个人移入回收站／恢复，保留星标、备注、历史、其他用户状态；沿用 op_id 幂等；现有个人状态协议可离线回放，本轮删除／恢复按钮采用在线严格确认，网络失败不显示删除成功。GET /api/feed?filter=trash 查询 hidden=1，支持分页。

## 4. 输出
- 账号核对：返回绑定和脱敏显示，只有实际 DOM 核对通过才显示已绑定；后台能力另需重读测试。
- 来源删除：{schema_version:1,ok:true,source_id,deleted:true,trashed_item_ids:[...]}；事务撤销任务、增加 revision、停调度，保留底层资料和访问权。
- 移入最后一份关联资料后暂停该 owner 的来源并撤销租约；恢复保留暂停，由用户恢复检查。个人回收站仍不提供逐资料物理删除；已删除来源可按[永久删除契约](source-permanent-delete-v1.md)一并清理本人独有资料，先确认范围并拒绝共享资料级联删除。
- GET /api/v1/reading-sources/deleted 返回当前 owner 的墓碑摘要；POST .../{id}/restore 输入 {revision:int}，恢复后 revision+1、paused=true、verified=false、mode=manual，需重新测试。恢复来源不恢复回收站资料，且旧租约仍无效。相同 revision 的立即重试返回同一恢复确认；配置再次改变后返回 revision_conflict。
- 已删除来源不在活动列表列出、不接收 check/config/result；历史资料仍可打开。旧请求 receipt 可能可查询，但重试不能重新创建来源。
- 失败使用现有严格 envelope；过期租约 409、账号不符 409、跨用户 404。HTTP200 空对象不算成功。

## 5. 验证范围与实现位置

扩展 `identity/` 与 DOM `AccountControlProbe`、后台 `SourceSessionVerifier` 实现账号探针与前后复核；Core 的 `source_identity` 字段验证器、ReadingSourceService 管理墓碑／租约，API 复用个人状态事务；Flutter 的 DocumentLifecycleRepository／ReadingSourceRepository 注入 UI，页面不直接操作数据库。Chrome storage 的字段次序不影响证明比较。

本轮只使用合成 DOM、loopback HTTP 与本地真实 Chrome。私人来源的实机重读、资料回收／恢复和来源恢复分别有证据；不声明 QQ／Gmail 真实账号控件已适配。详见本地报告（个人目录不随共享契约提交）。
