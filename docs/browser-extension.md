# 浏览器插件｜候选采集与有条件的来源监测

更新：2026-11-05，扩展 0.2.0。产品范围见 [产品定义](product-definition.md)；执行契约为 [IC-BROWSER-001 v1](architecture/browser-capture-v1.md)。以下区分已实现机制、结构夹具验证和真实站点待验收范围。

## 当前实现

流程为“识别候选 → 用户勾选 → 读取所选详情并预览 → 保存 → Flutter 管理 → 来源变化”。同页候选默认全部不选，手动选区仅作为公开页面的补充。不将整页自动保存，也不自动保存后来出现的新候选。

| 模块 | 职责与文件 |
|---|---|
| popup | `extension/popup.*`：连接、原站权限、候选勾选、正文／原始字段预览、提交结果 |
| 内容运行时 | `content/runtime.js`、`content/capture.js`：登录／就绪校验、稳定元素、路由和视图校验，限主 frame |
| 站点适配器 | `adapters/`：统一候选与重读 recipe，不承担分类、业务去重或截止日期推断 |
| 持久后台 | `background.js`：持久意图、设备／学校账号绑定、自有后台标签、alarm 唤醒、租约结果上报 |
| HTTP／队列 | `lib/api.js`、`lib/outbox.js`：严格响应、12 秒网络超时、最多 3 次自动提交、重试与确认 |
| Core | `core/monitors.py`：私有身份、关联事项／快照／监测、唯一调度、租约、逐项幂等及版本；沿用自研 HTTP 和 Pipeline |
| Flutter | 信息源中的采集来源控制，事项详情的原始字段、来源链接、检查状态和版本前后内容 |

保存使用用户实际预览的快照。初次保存只建立一个关联的私有 `browser` 来源、事项和监测配置，检查状态为“待首次检查”。“启用来源检查”默认不选；保存不会自动开启监测。后台重读更新同一个 item，不生成独立的 clip/page 双记录。重复批次返回持久回执；同一事项的新批次无变化不增加版本。同 URL 的不同 native ID、账号／视图上下文独立。

## 来源支持边界

| 来源 | 当前程序路径 | 已验证 | 真实站点仍需验证 |
|---|---|---|---|
| MUST Moodle | `/my/`、课程入口中的具体 `/mod/assign/view.php?id=…`，详情内容与日期原文；native 活动身份 | 合成结构、原站模拟登录、真实 Chrome 读取所选详情／保存／关页重读 | 生产主题 DOM、账号标识、实际课程／活动路由、登录重定向和后台重入；不调用未验证私有 API |
| 学生系统 | 资讯／课表统一 DOM profile；保留 hash/query、学期、周次、星期、节次 | 合成结构同 URL 两条保存；未知结构／frame／加载壳拒绝；课表无完整日期不推测 | 生产 DOM／frame、native ID、账号标识、详情路由及视图重入未取得证据；不是已完成真实 WeMust 适配 |
| FIE 人员 | 目录 `/person/id-828.html` 与 `/person/view/id-…` 分开；个人主体内字段，排除导航和页脚 | 合成目录选择、详情预览、Chrome 后台重读更新原事项及 Flutter 差异 | 生产目录／详情结构、人员身份和字段质量未验收；未知主体结构拒绝 |
| FIE 公开手动补充 | 预览稳定 ID 元素的完整内容；无稳定 ID 拒绝 | 内容模块静态／模拟测试 | 此模式不监测；认证页面手动选区尚不支持 |

夹具 meta 标记只允许 loopback 主机，不能让任意网页冒充受支持站点。结构匹配和监测启用只代表具备程序尝试条件；首次后台成功检查才表示这次来源实际可重读。学校账号未知时认证来源不保存，账号变化时旧监测暂停且不可直接恢复；需回原站确认后重新识别、预览并明确保存启用；原账号可恢复原绑定，其他账号独立建档。学校密码和 Cookie 不发给后端，不处理真实学校登录。

## 安装和本地复现

1. 按 README 启动本地后端／Flutter；可另运行 `.venv/bin/python devtools/campus_fixture/app.py --port 8098`。
2. Chrome 打开 `chrome://extensions`，启用开发者模式，加载仓库 `extension/`。升级代码后点“重新加载”；旧 0.1 登录配置需重新登录，新意图／回执不会迁移旧 clip。
3. popup 先“允许连接此后端”，再用 Campus Radar 账号登录。首次授权可能关闭 popup，重新打开即可；不在插件输入学校密码。
4. 打开 `http://localhost:8098/`，按 [夹具说明](../devtools/campus_fixture/README.md) 选择页面。在原站登录模拟账号后识别；目录条目须先读取所选详情预览，核对正文及字段，再保存。
5. 勾选启用检查时，Chrome 和本地后端需保持运行。保存只显示入队，收到严格逐项回执后才显示 new/changed/unchanged/failed；失败不虚报成功。可关闭 popup／原页，再打开查询。
6. 管理台制造变化，Flutter“信息源 → 立即检查”请求入队；alarm 下一次唤醒执行。进入原事项查看修改历史前后内容、打开原文。默认每 10 分钟，可能因 Chrome 调度延迟。

开发测试：`npm --prefix extension ci && npm --prefix extension test`（模拟 DOM／Chrome API）；`.venv/bin/python -m pytest -q server/tests/test_browser_capture.py`（后端契约及实际本地 HTTP 集成）。普通网页旧 harness 已停用，不能作为真实扩展验收。

## 生命周期、权限和恢复

Manifest V3，最低 **Chrome 110**；本轮真实 Chrome 版本记录于本地报告。使用 `chrome.*` API；不依赖文档中新引入的 `browser.*` 或 Chrome 150 的 alarm 跨会话选项。`scripting`/`activeTab`/`storage`/`alarms` 是固定权限，来源与后端按 origin 请求 optional host 权限。activeTab 仅单次读取不足以保证关闭原页后重读；后台打开自有非激活标签，使用浏览器现有会话执行主 frame 内容脚本，不导出 Cookie。

Chrome service worker 可在空闲时回收，全局内存不是任务状态。意图、预览快照、outbox、在途租约和自有标签写入 storage；重启检查 alarm 是否存在，避免每次 popup 重设时间。后端是唯一的 600 秒计划／120 秒租约所有者；alarm 仅每分钟领取一项。浏览器离线不补跑全部历史周期，同 origin 至少间隔 2.1 秒，正文稳定等待有界。回收中断不能冒充成功，恢复报告失败或在同请求 ID 下重传未确认结果；旧配置／过期租约拒绝。自动提交最多 3 次，登录失效待同账号重登，显式重试仍受账号隔离。

失败、需登录、选区丢失、渲染超时与无变化分开记录；失败不覆盖成功快照／最后成功时间。来源变化沿用版本与推送，个人备注和截止修正留在用户状态，不被来源覆盖。删除监测仅停止检查并保留事项；当前停止后的同一旧绑定不自动复活，跨设备／recipe 改变也需后续明确重绑流程。

官方依据（2026-11-05 查阅）：[MV3 生命周期与 Chrome 110 定时器改进](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle)、[alarm 延迟／睡眠与存在检查](https://developer.chrome.com/docs/extensions/reference/api/alarms)、[scripting 主 frame 与权限](https://developer.chrome.com/docs/extensions/reference/api/scripting)、[optional host 权限](https://developer.chrome.com/docs/extensions/develop/concepts/declare-permissions)。最低版本由所用 API 与生命周期选择推导；未在 Chrome 110 实机回归，不宣称跨版本验收。
