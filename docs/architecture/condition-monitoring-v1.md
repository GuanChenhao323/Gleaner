# Interface Contract — 条件来源 → Chrome → Core → 工作台

**接口 ID：** IC-READING-SOURCE-001

**版本：** v1.0（已实现；实际验收范围见本地报告）

**负责人：** 插件／Core／Flutter

**最后更新：** 2026-11-15

## 1. 接口概述

| 项目 | 说明 |
|---|---|
| 发送模块 | DOM 提取保存、Chrome 条件重读执行器、Flutter 来源管理 |
| 接收模块 | ReadingSourceService、已有原生／整组资料保存服务 |
| 接口用途 | 保留原条件与原资料关联，验证重读、手动／周期检查、来源变化 |
| 通信方式 | 既有自研 HTTP JSON＋Bearer；schema_version=1，ok=true |

Chrome 保持运行；原标签可关闭。会话留在 Chrome，接口不接受密码／Cookie。公开通用网页依据用户声明；私人通用网页无可靠账号验证时不支持后台重读，保留当前页手动采集。学校账号来自已验证 DOM 标识的设备加盐散列；标签不是认证。

## 2. 通信协议

- 既有 captures/web-captures 可选 `reading` 对象，缺省保持旧语义；保存事务同时关联条件来源并回执 `reading_source_id`。原生 recipe v1／v2 不迁移、不把 snapshot 改为 enabled。
- GET `/api/v1/reading-sources`：统一条件来源、关联事项摘要、执行设备在线状态。旧来源另外兼容呈现，不重复显示已关联原生／网页资料。
- PUT `/api/v1/reading-sources/{id}`：`{revision,mode:manual|periodic,paused,interval_s:1800|3600|7200}`；仅已验证支持 periodic，修订后撤销旧租约。
- POST `/api/v1/reading-sources/{id}/check`：`{revision,purpose:verify|check}`，排队／复用同修订在途任务；manual／paused 仍可单次。verify 不入库内容、不更新成功检查时间。
- GET `/api/v1/reading-sources/{id}/checks`：有界检查历史及关联版本。
- POST `/api/v1/reading-devices/heartbeat`：`{device_id}`，仅当前 owner；150 秒内视为近期连接，不等于网站会话有效。
- POST `/api/v1/reading-jobs/claim`：`{device_id}`，Core 唯一调度，180 秒租约、至多 3 次尝试；同设备至多一个未完成有效租约；过期任务最终失败，不补跑离线周期。
- POST `/api/v1/reading-jobs/{id}/result`：设备／租约／修订／payload 校验；确认含 job_id、status、result，重复同结果只返回原确认。409 陈旧租约／幂等冲突。

Chrome 每分钟唤醒、提交心跳、优先清空 outbox 后领取任务；手动请求不是同步网页请求。唤醒和任务持久化不依赖 popup。来源至少间隔 2.1 秒，Chrome API 110 基线，不新增 cookies/debugger 权限。动态站点须稳定 DOM、同路由／账号／视图；不自动登录／展开控件／翻页。

同设备手动请求优先，其后按最早到期顺序领取。保存前先校验可选 reading，再进入已有保存事务，避免无效来源关联产生内容副作用；新保存回执缺少正整数 reading_source_id 时，插件不得宣称来源已关联。关联资料全部删除后不再领取任务，旧在途结果拒绝写入，不自动复活已删除来源。

生命周期依据：[Chrome service worker 生命周期](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle/)（110 起扩展 API 调用重置空闲计时）；[alarms](https://developer.chrome.com/docs/extensions/reference/api/alarms) 可能延迟，本实现使用一分钟唤醒且在启动时重建，不依赖 120 的半分钟下限或 150 的跨会话标志。最低版本 110 是实现声明，仍需最低版本实机验收；不承诺电脑休眠、Chrome 退出期间准点执行。

## 3. 输入

| 字段 | 类型 | 语义及约束 |
|---|---|---|
| reading | object | version=1、url、query、match_scope、intent（提取 v2）、choice、source、binding、view；不含 raw DOM／凭据 |
| source_label | string | 通用来源的原声明标签，参与来源身份；原生来源为空，不是认证凭据 |
| source | enum | generic/moodle/student/fie；须与实际提交类型、origin 相符 |
| binding | object | adapter、origin、account_key；generic public/labeled 与 source_binding 一致，labeled 的未知账号为 unverified |
| view | object | 必要 semester/week/projection/route 等字符串上下文；原生重复读取必须一致 |
| source identity | derived | owner＋binding＋完整 URL＋规范化 query＋范围＋choice＋view；设备变更需重新验证，不自动继承旧周期配置 |
| result | object | schema_version、device_id、lease、revision、status；成功还含 account_key、snapshot |
| snapshot | object | 原生 targets 或通用 fragments，沿既有保存契约严格校验；仅匹配结果，1–30 个；完整度不足不入库 |
| failures | enum | need_login/account_unknown/account_mismatch/route_mismatch/view_mismatch/permission_denied/render_timeout/selection_missing/no_match/unsupported/failed/worker_interrupted |

来源标签不能成为账号认证。泛站隐私来源不得因字段相同绕过限制。未知／零匹配结果独立记录，不能以空集覆盖原资料。稳定业务身份不能依赖标题／hash／位置；通用资料按整组比较，片段无原生身份。比较忽略候选序号与 DOM locator 重排，不忽略匹配正文或明确字段。

## 4. 输出

来源包含 id、revision、device_id、recipe、mode、paused、verified、capability、last_result、last_attempt_at、last_success_at、next_at、active_job、items。资料保存时间不等于来源成功检查。UI 区分排队／设备离线／执行中／待首次、变化、无变化、未匹配、需登录、失败。

verify 成功只证明当次按同身份／视图重入，不能证明永久登录。check 成功且内容变化，调用已有保存服务更新原集合／原生事项、版本及投递；不改个人状态、备注和 deadline_override。不变化不生成新版本；失败不覆盖成功基线和时间。账号不符撤销验证并暂停，须回到原账号重新验证；普通恢复不能解除。修改／停止配置的在途结果不得提交。

旧数据没有原条件时展示“旧采集来源／资料”，可打开原文重新采集；不从旧正文猜关键词。测试分后端、Chrome API 模拟、真实 Chrome 本地、授权真实来源，不能相互替代。
