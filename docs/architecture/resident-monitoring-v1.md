# Interface Contract — 专用标签页 → 来源周期监测

**接口 ID：** IC-RESIDENT-001
**版本：** v1.0（已实现；验收范围见本地报告）
**负责人：** 插件／Core／Flutter
**最后更新：** 2026-11-16

## 1. 接口概述
Chrome原标签提供会话及DOM，Core唯一调度、存储和版本比较；Flutter呈现实际状态。标签管理、刷新策略、内容读取与调度分开，通过端口组合。

## 2. 通信协议
复用现有REST与租约，schema_version=1。Chrome最低110，使用原chrome.*API与storage.session，不增加cookies/debugger权限。一个origin在同一owner/device内绑定一套浏览器会话，页面下可有多规则。

## 3. 输入
- extract.save 可选 monitoring:{mode:resident,interval_s:1800|3600|7200}；新UI默认带上，缺省兼容仅快照。
- reading新增可选 resident:{version:1,session_id:UUID,page_id:UUID,refresh:reload,interval_s:int}。引用不含tabId、Cookie或原始临时URL；身份键仍沿用原规则，不因启用而新建资料。
- 浏览器本地注册表保存owner、origin、专用tabId、当前浏览器epoch、稳定URL、原视图及可识别账号指纹；原始SID等临时URL仅在浏览器本地，工作台URL去敏。同页规则共用page_id及周期；字段projection只影响输出，不分裂页面刷新分组，实际学期／周次等视图仍隔离。
- 新来源自动mode=periodic,pending=activate,verified=false。POST /api/v1/reading-sources/{id}/activate 输入{revision,interval_s}；显式将已打开唯一匹配原页绑定为监测页，首次实际刷新后启动。不自动打开未知账号页面。
- claim主job保持兼容，可选companions=[同页job]，最多10条，一批共享刷新。purpose新增activate；每个租约独立确认，返回不得缺少任何job。
- activate成功结果除account_key、snapshot外包含resident描述符；旧来源配方在严格校验后补充resident。未知generic账号允许resident单会话，account_key保持unverified，绝不宣称网站账号认证。
- 登录失效、已知账号不同、路由或视图改变、检查时发现标签关闭、浏览器重启需重绑、权限问题时暂停；user_busy延后重试，render_timeout等有界失败后暂停。失败不覆盖成功快照／时间。
- 前端同page_id聚合规则，检查／配置同页作用于整组；逐规则删除保留其他规则。定期执行仍是至少一次＋幂等，错过周期不逐次补跑。

## 4. 输出
保存回执另返回monitoring:{state:starting,mode:resident,interval_s}；“已保存，监测启动中”不当作监测已运行。activate实际成功后记录last_success_at／next_at及verified=true；内容变化更新原版本，首次无变化不造版本。

状态包括starting、changed、unchanged、user_busy、tab_missing、tab_rebind_required、need_login、account_mismatch、view_mismatch、render_timeout等。浏览器／本地服务离线由心跳和连接状态呈现，不显示监测中。配置、墓碑和恢复均保持原修订保护。原JSON字段键序不作为身份依据。

## 5. 能力边界与验收
专用标签按约定刷新GET页面，检测到编辑或表单活动不刷新；不上传密码、编辑内容或表单值；为核对刷新后的视图，仅在浏览器内读取可见select／search控件并保存哈希，不将它们加入资料正文或传给后端。浏览器会话不保证永久有效，无法观察的账号切换只能受单账号使用约定约束。测试使用合成DOM与本地夹具；真实站点、浏览器长时间运行和模拟证据分别记录。没有稳定刷新／视图恢复能力的页面明确暂停，不承诺所有页面都可监测。


## 6. 调度、持久化与兼容细节

`reading_sessions`按(owner,device,origin)唯一，`reading_pages`按页面引用及稳定URL／配方view唯一。数据库新增仅为增量建表及`failure_count`，不重置旧数据。原事项身份键不含resident，显式激活不重建资料。配置更改撤销旧租约，来源删除／回收站继续遵守墓碑保护。

一次设备claim最多10个独立租约，180秒过期、同租约最多3次领取。任务及结果outbox持久，worker中断报告未确认结果，不推定读取成功。临时失败累计3次暂停；编辑延后60秒且不消耗失败次数。后台每分钟alarms轮询，Core按持久next_at唯一决策；可能延迟，不是精确定时器。成功批次按同一计划安排下一周期，错过周期不逐次补跑。

首个保存回执不是监测成功；首次activate会真实调用tabs.reload，并用注入守卫的文档代次确认确实发生导航，再执行同一提取器。刷新前后检查账号／URL／视图；零匹配及失败均保留成功快照与成功时间。只处理当前已加载范围，不恢复任意UI交互，不读取其他详情页。

旧接口缺少monitoring或resident时保留旧快照／手动行为；旧来源启用必须有唯一已授权原页。历史含临时凭据URL不猜测迁移，可能需重新采集。关闭原监测页后不偷偷开新页，完整浏览器重启或扩展重载要求用户显式重绑；普通worker回收保留storage.session代次和local绑定。

## 7. 浏览器与测试边界

最低Chrome110：`storage.session`自102支持，110起扩展API调用重置worker计时；本实现每分钟alarm，不使用120才支持的30秒alarm。启动时补建丢失alarm，不能依赖alarm永远跨会话保存。[Chrome storage](https://developer.chrome.com/docs/extensions/reference/api/storage)、[worker生命周期](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle)、[alarms](https://developer.chrome.com/docs/extensions/reference/api/alarms)、[tabs与host权限](https://developer.chrome.com/docs/extensions/reference/api/tabs)。最低110本轮未实机测试。

`ReadingSchedule`允许依赖注入QA周期；`dev_all.py --fixture-reading-interval 60`只对localhost／127.0.0.1／::1生效，响应`effective_interval_s`并在工作台明确标记。无此参数时始终执行30／60／120分钟，真实域名不受QA参数影响。测试加速证据不得写成真实30分钟或真实学校／邮箱验收。专用标签不延长Cookie寿命，不支持同origin多个账号并行监测；已识别绑定账号需切回原账号，当前不提供会话重置／更换账号UI。
