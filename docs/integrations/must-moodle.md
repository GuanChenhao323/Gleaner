# 澳门科技大学（MUST）Moodle 接入

第一个真实平台接入（M11，2026-10-26 组长决定）。访问规则见 `CLAUDE.md`“工作方式”：下面的授权状态不是“已获授权”时，
任何人（包括 Claude）都不得访问真实站点；自动化测试与 CI 永远只连 `devtools/fake_moodle`。

## 1. 授权与登记（组长填写）

授权状态：待提供

| 项目 | 内容 |
| --- | --- |
| Moodle 地址 | （待提供，例如 `https://xxx.must.edu.mo`） |
| 授权人 / 部门 | （待提供：老师或学校 IT 部门） |
| 授权形式与存放位置 | （书面邮件或文件；原件不入库，这里只写存放位置） |
| 授权范围 | （允许的账号、页面 / 接口、访问频率） |
| 有效期 | （待提供） |
| 测试账号 | 登记人与用途（**只写账号名，不写密码**；登录由本人在客户端界面完成） |
| 登记日期 | （待提供） |

授权到手后，把第一行改为 `授权状态：已获授权`，并补全表格。

## 2. 允许访问范围（默认清单，以授权范围为准）

只读，不提交作业、不发帖、不修改任何数据。

| 类别 | 地址 / 函数 | 用途 |
| --- | --- | --- |
| 公开信息 | `/robots.txt`、`/lib/ajax/service-nologin.php` 的 `tool_mobile_get_public_config` | 探测登录方式（账号密码 / SSO）、站点版本、是否开放移动端服务 |
| 登录 | `/login/token.php`（`service=moodle_mobile_app`）、`/login/index.php` | 换取 Web Service token，或保存网页会话 Cookie；只存会话不存密码 |
| Web Service | `core_webservice_get_site_info`、`core_enrol_get_users_courses`、`mod_assign_get_assignments` | 课程列表、作业、截止时间、附件信息 |
| 网页（Web Service 不可用时回退） | `/my/`、`/course/view.php`、`/mod/assign/index.php`、`/mod/assign/view.php` | 同上，用 HTML 解析 |

请求间隔：同一主机不少于 2 秒（采集服务 `GLEANER_HOST_INTERVAL=2`）；单个账号检查间隔不短于 10 分钟（`GLEANER_MIN_INTERVAL=600`）。

## 3. 接入步骤

| 阶段 | 内容 | 谁来做 |
| --- | --- | --- |
| 0. 授权 | 拿到书面授权，填写第 1 节 | 组长 |
| 1. 探测 | `python devtools/must_moodle_probe.py`：只读公开信息，判断登录方式、版本、Web Service 是否可用，结果写入第 4 节 | Claude（授权后） |
| 2. 登录 | 组员本人在客户端“添加信息源 → Moodle”里登录测试账号；系统换取 token 或 Cookie 后加密保存，不保存密码 | 组员本人 |
| 3. 适配 | 根据探测结果调整连接器：Web Service 路径一般无需改动；回退到网页解析时，按真实页面结构调整选择器。测试用脱敏后的结构样本（只保留标签结构，不含真实课程、姓名、邮箱） | Claude |
| 4. 验收 | 手动对比 Moodle 页面与拾课里的作业、截止时间、附件是否一致；连续运行 24 小时观察失败率与请求量 | 组员 + Claude |
| 5. 上线 | 云服务器 `deploy/.env` 设置 `GLEANER_MOODLE_URL`，演示前确认授权仍在有效期内 | 组长 |

## 4. 探测结果

（授权后由 `devtools/must_moodle_probe.py` 生成，只记录站点级信息，不记录任何个人数据。）

## 5. 可能遇到的情况与对策

| 情况 | 影响 | 对策 |
| --- | --- | --- |
| 学校统一认证（CAS / Microsoft 等 SSO），`typeoflogin` 为 2 或 3 | `/login/token.php` 无法用账号密码换 token | 方案 A：用户在 Moodle“偏好设置 → 安全密钥”里复制自己的 Web Service 密钥，粘贴到拾课（需要新增“粘贴密钥”登录方式）；方案 B：走移动端 SSO 启动流程（`admin/tool/mobile/launch.php`），需要学校允许 |
| 未开放移动端服务（`enablemobilewebservice` 关闭） | 只能用网页解析 | 用网页会话 Cookie + HTML 解析，选择器按真实页面调整 |
| 登录有验证码或二次验证 | 无法自动登录 | 由用户在浏览器登录后提供会话，或请学校为本项目开放 token；不绕过验证码 |
| 网页是自定义主题 | 现有选择器失效 | 以 Moodle 标准的 `data-region` 属性与 Web Service 为主，减少对主题 class 的依赖 |
| 会话过期 | 来源状态变为“需要重新登录” | 客户端提示用户重新登录（已实现） |

## 6. 数据与隐私

- 真实站点的页面、课程、作业、姓名、邮箱一律不入库、不进测试夹具、不贴进 issue 或聊天记录。
- 会话与 token 用 AES-GCM 加密保存（AAD 为“用户 id:来源 id”），用户删除来源或注销账号时一并删除。
- 个人来源的事项按用户隔离（见 `docs/decisions.md` 第 9 条）。
