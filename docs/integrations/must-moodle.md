# 澳门科技大学（MUST）Moodle 接入

当前产品的首个真实来源验证对象；旧里程碑 M11 已归档，当前对应 R0/R3/R4。访问规则见 `CLAUDE.md`“真实平台访问”：下面的授权状态不是“已获授权”时，
任何人（包括 Claude）都不得访问真实站点；自动化测试与 CI 永远只连 `devtools/fake_moodle`。

## 1. 授权与登记（组长填写）

授权状态：已获授权

| 项目 | 内容 |
| --- | --- |
| Moodle 地址 | `https://moodle.must.edu.mo` |
| 授权人 / 部门 | 澳门科技大学与 CMU 合作项目同意连接（组长 GuanChenhao323 于 2026-10-26 确认） |
| 授权形式与存放位置 | 组长口头转达；书面材料（合作协议或邮件）待补，原件不入库，补齐后在此写明存放位置 |
| 授权范围 | 只读访问第 2 节所列页面与 Web Service；仅限下面登记的测试账号；限速见第 2 节 |
| 有效期 | 待补（以合作协议为准） |
| 测试账号 | `1230003454`（组长提供；密码不入库，登录由账号持有人本人在客户端完成） |
| 登记日期 | 2026-10-26 |

书面授权材料与有效期补齐后更新本表；授权失效时把第一行改回 `授权状态：待提供`，探测脚本与真实访问随即停止。

## 2. 允许访问范围（默认清单，以授权范围为准）

只读，不提交作业、不发帖、不修改任何数据。

| 类别 | 地址 / 函数 | 用途 |
| --- | --- | --- |
| 公开信息 | `/robots.txt`、`/lib/ajax/service-nologin.php` 的 `tool_mobile_get_public_config` | 探测登录方式（账号密码 / SSO）、站点版本、是否开放移动端服务 |
| 登录 | `/login/token.php`（`service=moodle_mobile_app`）、`/login/index.php`、统一认证登录页 `https://login.must.edu.mo/login`（只读表单结构） | 换取 Web Service token，或保存网页会话 Cookie；只存会话不存密码 |
| Web Service | `core_webservice_get_site_info`、`core_enrol_get_users_courses`、`mod_assign_get_assignments` | 课程列表、作业、截止时间、附件信息 |
| 网页（Web Service 不可用时回退） | `/my/`、`/course/view.php`、`/mod/assign/index.php`、`/mod/assign/view.php` | 同上，用 HTML 解析 |

请求间隔：同一主机不少于 2 秒（采集服务 `GLEANER_HOST_INTERVAL=2`）；单个账号检查间隔不短于 10 分钟（`GLEANER_MIN_INTERVAL=600`）。

## 3. 当前接入验证

1. 按开发约定核对授权、有效期、只读范围与限速；真实验证不进入 pytest／CI。
2. 列明支持页面、候选事项定位与脱敏结构样例，分别验证采集和监测能力。
3. 用户在浏览器自行登录，验证多事项选择与本地保存。登录态不自动等于后台可访问权限。
4. 关闭目标标签页，保持 Chrome 与后端运行，验证支持来源的重新获取、版本比较、失败提示与恢复；执行产品场景 A/B/C。
5. 记录支持矩阵、环境、测试时间及结果。当前产品不以云部署或连续 24 小时监测为验收承诺。

第 4–6 节保留旧连接器的探测和实现经验；安全密钥仅为待验证的复用候选，不代替新监测方案决策。网页结构与权限必须重新核对。

## 4. 探测结果

2026-10-26 `devtools/must_moodle_probe.py`（只读站点级公开信息，不登录）：

| 项目 | 结果 | 含义 |
| --- | --- | --- |
| robots.txt | 返回 303 重定向，无 robots 文件 | 没有禁止路径；仍按第 2 节限速 |
| 站点名 | Macau University of Science and Technology | — |
| 登录方式（`typeoflogin`） | 内嵌浏览器 SSO；身份提供方 “Login MUST” | 学生账号走统一认证，不是 Moodle 本地账号 |
| 统一认证 | `/login/index.php` 302 到 `https://login.must.edu.mo/login?service=…`（CAS 协议） | — |
| CAS 登录页结构 | 账号 + 密码 + 隐私政策勾选；页面引入 jsencrypt（密码疑似在浏览器端 RSA 加密后提交）；后台提交表单带验证码字段；另有扫码登录 | 服务端代登录需要复刻加密，且可能遇到验证码 |
| Web Service | `enablewebservices = 1`，`enablemobilewebservice = 1` | 移动端服务已开放，拿到 token 后可直接用 Web Service |
| `/login/token.php` | 空账号返回 `invalidlogin` | 端点可用；但统一认证账号一般不能用账号密码直接换 token |
| 移动端 SSO 入口 | `https://moodle.must.edu.mo/admin/tool/mobile/launch.php` | 可走移动端 SSO 启动流程取得 token |
| Moodle 版本 | 未公开 | — |

结论：现有“账号密码换 token”的方式大概率不适用，需要在第 5 节的方案里选一个。

## 5. 历史登录方案（旧连接器方案 A，见决策第 14 条）

| 方案 | 做法 | 优点 | 缺点 |
| --- | --- | --- | --- |
| **A. 粘贴安全密钥（已选定并实现）** | 用户在浏览器里正常登录 Moodle → 偏好设置 → 安全密钥，复制 “Moodle mobile web service” 的密钥，粘贴到拾课“添加信息源 → Moodle” | 拾课完全不接触统一认证密码；Web 版、手机版都能用；实现量小 | 用户多一步操作；密钥失效后要重新粘贴；需确认 MUST 是否对学生显示安全密钥页面 |
| B. App 内嵌浏览器 SSO | 手机版用内嵌浏览器打开 `launch.php`，用户自己在 CAS 页登录（含验证码、扫码），App 截获 `moodlemobile://token=…` 回跳取得 token | 体验与官方 Moodle App 一致；不接触密码 | 只适用手机 / 桌面 App，Web 版截获不了回跳；实现量中等 |
| C. 服务端代登录 CAS | 拾课服务端用自研 HTTP 客户端走 CAS 表单（复刻 RSA 加密）拿到会话，再换 token | 用户只输一次账号密码 | 要经手统一认证密码（同一密码可登录学校全部系统）；遇到验证码就失败，不能也不应绕过；学校改页面就会坏 |

方案 A 的实现：

- 客户端：信息源 → Moodle → 登录框默认“粘贴安全密钥”，带“打开 Moodle 安全密钥页面”按钮（`/user/managetoken.php`）；仍可切换到“账号密码”。
- 服务端：`POST /api/sources/{id}/login {"token": "…"}`。去掉空白后必须是 32 位十六进制（否则 422）；
  用 `core_webservice_get_site_info` 校验（无效 401），并确认该服务包含 `mod_assign_get_assignments`；通过后 AES-GCM 加密保存，立即触发一次采集。
- 采集：只有 token、没有网页会话，全部走 Web Service（`mod_assign_get_assignments`）。
- 验证：fake_moodle 新增“安全密钥”页面；端到端测试 `test_moodle_login_with_pasted_security_key`；compose 环境里从“需要重新登录”粘贴密钥后恢复正常并采到 7 个作业。
- 接入时还发现并修复：容器里的 Python 3.12 拼 Web Service 地址会丢掉“?”，导致 Web Service 从未生效（见评估第三轮第 8 条）。

## 6. 可能遇到的情况与对策

| 情况 | 影响 | 对策 |
| --- | --- | --- |
| 学校统一认证（CAS / Microsoft 等 SSO），`typeoflogin` 为 2 或 3 | `/login/token.php` 无法用账号密码换 token | 方案 A：用户在 Moodle“偏好设置 → 安全密钥”里复制自己的 Web Service 密钥，粘贴到拾课（需要新增“粘贴密钥”登录方式）；方案 B：走移动端 SSO 启动流程（`admin/tool/mobile/launch.php`），需要学校允许 |
| 未开放移动端服务（`enablemobilewebservice` 关闭） | 只能用网页解析 | 用网页会话 Cookie + HTML 解析，选择器按真实页面调整 |
| 登录有验证码或二次验证 | 无法自动登录 | 由用户在浏览器登录后提供会话，或请学校为本项目开放 token；不绕过验证码 |
| 网页是自定义主题 | 现有选择器失效 | 以 Moodle 标准的 `data-region` 属性与 Web Service 为主，减少对主题 class 的依赖 |
| 会话过期 | 来源状态变为“需要重新登录” | 客户端提示用户重新登录（已实现） |

## 7. 数据与隐私

- 真实站点的页面、课程、作业、姓名、邮箱一律不入库、不进测试夹具、不贴进 issue 或聊天记录。
- 会话与 token 用 AES-GCM 加密保存（AAD 为“用户 id:来源 id”），用户删除来源或注销账号时一并删除。
- 个人来源的事项按用户隔离（见 `docs/decisions.md` 第 9 条）。
