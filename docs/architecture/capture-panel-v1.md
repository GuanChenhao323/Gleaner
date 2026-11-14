# Interface Contract — 单弹窗采集面板

**接口 ID：** IC-PANEL-001

**版本：** v1.0（扩展 0.8.0 已实现）

**负责人：** 插件 UI／worker

**最后更新：** 2026-11-15

## 1. 接口概述

| 项目 | 说明 |
|---|---|
| 发送模块 | popup.html、CaptureController、显示组件 |
| 接收模块 | ExtensionClient、MV3 worker、既有提取与保存服务 |
| 用途 | 在同一弹窗完成条件、提取、预览、来源声明与明确保存 |
| 通信方式 | 既有可信runtime消息；复用HTTP接口，无新权限／依赖 |

## 2. 通信协议

沿用IC-EXTRACTION-001 runtime version=2以及IC-WEB-CAPTURE-001／IC-BROWSER-001保存请求。只有明确保存才提交正文。关闭弹窗不撤销已持久提交；重开查询原任务。独立workspace入口移除，旧草稿通过最近记录恢复。

新增`connection.check`只读消息：worker调用既有GET `/api/me`并严格核对返回的正整数id、非空email与当前配置uid一致。返回`{state:'connected',uid,email}`；未登录、401、网络不可达、超时及畸形响应使用既有`{ok:false,error}`，不能用本地cfg代替网络连接证明。连接检查独立于监测串行任务，不阻塞弹窗初始化／本地预览。

GET `/api/me` 沿用既有无 v1 envelope 的用户对象，本次只验证 id／email，其他字段不返回 popup。消息成功包为 `{ok:true,value:{state:'connected',uid,email}}`。错误包括 `backend_login_required`、`unauthorized`、`backend_account_changed`、`invalid_session_response`、`invalid_response`、`backend_timeout`、`backend_unavailable`。HTTP 超时 12 秒，runtime 等待上限沿用 20 秒；当前弹窗每 30 秒检查连接，关闭后不再由 UI 轮询。返回时再次核对工作台 owner，旧账号响应不能改变新账号状态。

`retry`兼容新增可选request_id；面板只重试本次提交，复用原请求ID。自动重试仍有界；用户明确重试可重置该请求的等待及失败状态，不重新采集正文或创建任务。

request_id 为非空字符串、最多 100 字符；不传时保留旧调用方式。指定重试只重置当前 owner 下匹配请求的 failed／auth_required／带错误 pending；rejected／confirmed 不重置，其他请求保持原重试计划。之后仍由原队列发送到期任务。弹窗保存 RPC 超时后保留 pending_save 标记；重开先查询原 request_id，尚未接收的请求也只能重发原冻结预览。

## 3. 输入与状态

| 输入／状态 | 语义 |
|---|---|
| query、match_scope | 默认content；修改立即失效旧预览；校园专用规则不提供无效title选项 |
| source_binding | 首次普通片段保存前出现；公开明确选择，私人标签显式确认；只在本owner／原页表单内保留 |
| 任务状态 | queued/running/needs_choice/succeeded/failed/interrupted保持既有含义 |
| 提交状态 | pending/auth_required/failed/rejected/confirmed；未确认不算成功；逐项失败不伪装整批成功 |
| 当前页／历史 | 当前页标题、域名、完整URL分层显示；历史显示原来源及返回当前页入口，不能直接对历史地址发起新的提取 |

输入、权限请求、任务查询与连接检查使用不同代次保护。页面URL、工作台owner变化时清除显示及可保存性；旧任务仍保留其原owner。已完成的冻结预览在原页关闭后可保存。来源标签不证明网站账号登录，切换网站账号需更换标签。

## 4. 输出与对象职责

PanelPolicy只推导UI保存资格／限制，不放宽worker规则；PreviewView负责紧凑摘要、弹窗内展开全文／字段／证据及分组；SourceBindingView负责标签编辑和明确确认；ReceiptView负责严格回执的用户文案与对应操作；CaptureView组合组件。CaptureController负责浏览器、账号、任务及表单端口编排，不实现站点DOM或业务分类。

结果展示可以折叠／截取摘要，上传始终使用服务端任务冻结的完整候选，不能从界面摘要构造正文。普通网页整组一份资料与校园独立事项的计数分别显示。网络未确认保留请求，重试后查询同一回执；保存／重试期间锁定条件和标签，确认后才能显示新增／更新／内容无变化及工作台入口。

创建前的明确拒绝清除未创建的taskId并保留read_error和输入，不轮询为“预览过期”；worker失联保留prepared原UUID供重开登记。

表单兼容旧 captureForm.v2，历史另用 captureHistoryForm.v1，均按 server／uid 隔离，不含密码和正文。历史原任务、未确认提交、来源标签不会写回当前页未提交条件。已连接时“切换连接或账号”先展开登录表单，只有再次明确登录才提交凭据；登录失败显示在连接设置内并清空密码。

验证位置：`extension/tests/panel.test.js`、`worker.test.js`、`capture.test.js`；相关后端边界在 `server/tests/test_extension_build.py`、`test_browser_capture.py`、`test_web_captures.py`。本次未修改网络保存接口、生产后端或 Flutter；最低 Chrome 110 和权限保持不变。
