# 数据库与持久化

实现：`server/gleaner/storage/db.py`（访问层）、`schema.py`（基础表）、`migrations.py`（带版本的迁移）、
`core/maintenance.py`（数据保留与清理）、`deploy/backup/backup.sh`（每日备份）。

## 1. 两种数据库，一套 SQL

| 环境 | 数据库 | 连接 |
| --- | --- | --- |
| 开发、测试 | SQLite（WAL 模式） | `GLEANER_DB=sqlite:///data/dev.db` |
| docker compose 部署 | PostgreSQL 16 | `GLEANER_DB=postgresql://gleaner:…@postgres:5432/gleaner` |

- SQL 一律用 `?` 占位；PostgreSQL 下 `to_pg` 换成 `%s`，跳过字符串字面量，字面量里的 `%` 转义成 `%%`。
- 建表语句按 SQLite 写，PostgreSQL 下替换类型：`INTEGER PRIMARY KEY AUTOINCREMENT → BIGSERIAL`、`REAL → DOUBLE PRECISION`、`BLOB → BYTEA`。
- 方言差异的写法约定：
  - 取较大 / 较小值用 `CASE WHEN`，不用 SQLite 的两参数 `MAX()` 或 PostgreSQL 的 `GREATEST()`。
  - 布尔参数一律转成 0/1，条件写成 `? = 1`，不要写 `CASE WHEN ?`。
  - 模糊搜索用 `LOWER(col) LIKE ? ESCAPE '!'`，并转义用户输入。SQLite 的 LIKE 不区分大小写，PostgreSQL 区分。
  - 冲突写入用 `ON CONFLICT … DO NOTHING / DO UPDATE`。部分唯一索引要写出条件，例如 `ON CONFLICT (share_key) WHERE share_key IS NOT NULL`。
- 用到数据库的测试可以改跑 PostgreSQL（CI 的 `server-postgres` 任务每次都跑）：
  `GLEANER_TEST_PG=postgresql://… pytest tests/test_core.py tests/test_e2e.py tests/test_mail.py tests/test_api.py tests/test_storage_pg.py`

## 2. 连接池与事务

- **连接池**：
  - PostgreSQL 默认 4 条连接（`GLEANER_DB_POOL`），每条语句借一条连接执行，互不排队。测试 `test_pool_runs_statements_concurrently` 验证：8 条各 0.3 秒的查询约 0.6 秒完成。
  - SQLite 只有一个写者，固定 1 条连接。
  - 驱动是同步的，语句在线程池里执行，不阻塞事件循环。
- **事务**：`async with db.transaction():` 把一条连接固定在当前协程上下文里（contextvar），块内语句都走这条连接；嵌套调用复用外层事务。事务里不要再创建任务（任务会继承上下文）。
- **超时**：PostgreSQL 连接超时 5 秒，语句超时 15 秒（`GLEANER_DB_STATEMENT_TIMEOUT_MS`），并开启 TCP keepalive。建表与迁移用单独的连接，不设语句超时。
- **断线**：
  - 连接断开后，下次借出时重连。
  - 只读语句（`SELECT`）发现连接已断，会重连后重试一次。
  - 写语句不自动重试，因为可能已经执行过：这一条报错，下一条恢复。
  - 事务中途断开不换连接，整个事务失败。
- **需要原子性的操作**都放在事务里：
  - 分配投递序号 seq，加上写投递记录；
  - 新事项连同第 1 个版本和别名一起写入；
  - 事项变更，加上写新版本；
  - 个人状态修改，加上幂等记录；
  - 添加来源，加上订阅；
  - 删除账号；
  - 替换个性化规则。
- **唯一性由数据库保证**，不靠“先查后插”：
  - 公共来源按（类型，地址，模式）唯一，用 `sources.share_key` 加部分唯一索引；
  - 每人一个“网页收藏”来源；
  - 投递序号、幂等键、配对码。
  - 同一事项身份键的写入在进程内还有一把锁（`Pipeline._key_lock`），避免并发时撞唯一约束。

## 3. 迁移

- `schema_migrations(version, name, applied_at)` 记录已执行的迁移。
- 启动时按版本号执行尚未执行的迁移，每个迁移一个事务；失败就回滚并中止启动，不吞错误。
- 多个服务同时启动时，PostgreSQL 用会话级咨询锁串行化建表与迁移。
- 新库先由 `SCHEMA` 建出基础表，再从第 1 个迁移跑起，所以每个迁移都要能在新库上安全执行，例如加列前先检查列是否存在。
- 新增迁移：在 `MIGRATIONS` 末尾追加下一个版本号；不要修改已发布的迁移。

| 版本 | 内容 |
| --- | --- |
| 1 | `users.digest_email` |
| 2、3 | 个人来源的身份键与别名键加所有者前缀（决策第 9 条） |
| 4 | 热点查询与级联删除用的索引：订阅按来源、事项按来源、别名、个人状态、凭据、投递、事件等 |
| 5 | 公共来源唯一键 `share_key`（先合并已有的重复公共来源）、每人唯一的网页收藏来源 |
| 6 | 调度器按到期时间、每日摘要按摘要时间的索引 |
| 7 | 新基线（决策 D19–D23）：`items.item_type`（待办／日程／通知，按默认规则回填）、`user_item_state.archived_at`（日程归档）、`user_item_edits`（用户修改，旧 `deadline_override` 一并迁入）、`item_monitors`（事项级监测）及索引 |

## 3.1 事项、用户修改与监测（迁移 7）

| 表 | 主键 | 内容 |
| --- | --- | --- |
| `items` | `id` | 来源值。`identity_key` 对插件采集的事项为 `@<uid>/capture:<规范化页面网址>#<locator>`；`item_type` 是来源侧判定的类型；活动时间、地点、页面网址、定位符存在 `attrs` |
| `user_item_edits` | `(user_id, item_id, field)` | 用户修改，`value` 与 `base`（修改时的来源值）都存 JSON。来源更新从不写这张表；`base` 与当前来源值不同即为冲突 |
| `item_monitors` | `(user_id, item_id)` | 是否支持、是否启用、间隔、下次检查与租期、最后检查与最后成功时间、最近结果、错误（JSON）、连续失败次数 |

- 生效值 = 用户修改优先，否则来源值；旧接口的 `deadline_override` 与 `user_item_edits` 的截止时间同步。
- 截止提醒（`core/reminders.py`）按生效的截止时间；用户确认“没有截止时间”时不提醒。
- 删除账号时两张新表随用户数据一起删除。

## 4. 凭据加密

- 来源的 Cookie / Token、邮箱的应用专用密码用 AES-256-GCM 加密保存。附加数据（AAD）是“用户 id:来源 id”，防止把一条密文挪到别的用户或来源上。
- 密文格式：`"GK" + 密钥编号 + nonce(12) + 密文 + tag`。早期没有前缀的格式仍能解密。
- **密钥**：
  - `GLEANER_DATA_KEY` 是 32 字节十六进制。
  - 没有设置时，由 `GLEANER_SECRET` 派生，此时更换令牌密钥会导致凭据无法解密，所以生产环境必须单独设置。
- **轮换**：把旧密钥放进 `GLEANER_DATA_KEY_OLD`（逗号分隔），新密钥放进 `GLEANER_DATA_KEY`。旧密文仍能解密，新写入的用新密钥。
- **启动检查**：未设置密钥时记警告；`GLEANER_STRICT_SECRETS=1` 时拒绝启动（生产环境建议打开）。

## 5. 数据保留与清理

core 每小时执行一次 `run_maintenance`，默认保留期如下（可用环境变量调整，单位：天）：

| 内容 | 保留 | 变量 |
| --- | --- | --- |
| 邮件正文（只留标题、发件人、摘要、链接） | 30 天后清空 | `GLEANER_KEEP_MAIL_BODY_DAYS` |
| 投递记录（离线补发） | 60 天；更早的同步返回 `reset`，客户端全量刷新 | `GLEANER_KEEP_DELIVERIES_DAYS` |
| 幂等记录 op_log | 30 天 | `GLEANER_KEEP_OPLOG_DAYS` |
| 行为事件 events | 180 天 | `GLEANER_KEEP_EVENTS_DAYS` |
| 发信记录 | 180 天 | `GLEANER_KEEP_SENT_DAYS` |

另外每轮都会清理：
- 过期验证码、已吊销或 30 天未用的登录会话、截止已过 30 天的提醒记录；
- 卡在 sending 超过 10 分钟的发信记录，标记为失败；
- 来源已“需要重新登录”超过 7 天时，删除保存的会话凭据（过期即删）；
- 过期一天以上的扫码传输，连同磁盘文件；
- 没有任何订阅者的公共来源；
- 指向已删除事项的投递记录。

删除账号在一个事务里删除该用户的全部数据，还会：
- 从公共事项的 `merged_from` 里抹掉该用户私有来源的痕迹；
- 删除磁盘上的传输文件；
- 让 Broker 清掉该用户的会话与保留消息。

## 6. 备份

- docker compose 的 `backup` 服务每天执行 `pg_dump -Fc`，并把数据卷（传输文件、Broker 状态）打包，保留 14 天，放在 `deploy/backups/`。
- 恢复步骤见 README“备份与恢复”。2026-11-05 实测：把备份恢复到临时库，用户与事项数量与原库一致。
- 本地开发环境：`python devtools/backup.py` 使用 SQLite 在线备份接口。
