"""数据表定义（见 proposal“核心数据表”）。时间统一存 Unix 秒（REAL）。

DDL 以 SQLite 方言书写，PostgreSQL 下自动替换自增主键、REAL、BLOB。
"""

SCHEMA: list[str] = [
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        grade TEXT NOT NULL DEFAULT '',
        major TEXT NOT NULL DEFAULT '',
        courses TEXT NOT NULL DEFAULT '[]',
        digest_time TEXT NOT NULL DEFAULT '08:00',
        quiet_start TEXT NOT NULL DEFAULT '23:00',
        quiet_end TEXT NOT NULL DEFAULT '07:00',
        timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
        token_version INTEGER NOT NULL DEFAULT 1,
        digest_email INTEGER NOT NULL DEFAULT 0,
        next_seq INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        last_active_at REAL
    )""",
    """CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        template TEXT NOT NULL DEFAULT '',
        config TEXT NOT NULL DEFAULT '{}',
        course TEXT NOT NULL DEFAULT '',
        etag TEXT,
        last_modified TEXT,
        content_hash TEXT,
        interval_s REAL NOT NULL DEFAULT 600,
        next_fetch_at REAL NOT NULL DEFAULT 0,
        last_checked_at REAL,
        last_success_at REAL,
        last_change_at REAL,
        status TEXT NOT NULL DEFAULT 'pending',
        last_error TEXT,
        fail_count INTEGER NOT NULL DEFAULT 0,
        via_agent INTEGER NOT NULL DEFAULT 0,
        stats TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_sources_next ON sources(next_fetch_at)",
    """CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        weight REAL NOT NULL DEFAULT 0.7,
        muted INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        PRIMARY KEY (user_id, source_id)
    )""",
    """CREATE TABLE IF NOT EXISTS credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        auth_type TEXT NOT NULL,
        secret_encrypted BLOB NOT NULL,
        expires_at REAL,
        updated_at REAL NOT NULL,
        UNIQUE (user_id, source_id)
    )""",
    """CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        identity_key TEXT NOT NULL UNIQUE,
        content_hash TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL,
        course TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        raw_title TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '',
        deadline_at REAL,
        published_at REAL,
        audience TEXT NOT NULL DEFAULT '',
        attrs TEXT NOT NULL DEFAULT '{}',
        version INTEGER NOT NULL DEFAULT 1,
        deleted INTEGER NOT NULL DEFAULT 0,
        first_seen_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_items_deadline ON items(deadline_at)",
    "CREATE INDEX IF NOT EXISTS ix_items_hash ON items(content_hash)",
    # 跨渠道合并：其他渠道的身份键指向同一事项
    """CREATE TABLE IF NOT EXISTS item_aliases (
        alias_key TEXT PRIMARY KEY,
        item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        source_id INTEGER NOT NULL,
        created_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS item_versions (
        item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        version INTEGER NOT NULL,
        snapshot TEXT NOT NULL,
        changed_fields TEXT NOT NULL DEFAULT '{}',
        important INTEGER NOT NULL DEFAULT 0,
        change_note TEXT NOT NULL DEFAULT '',
        detected_at REAL NOT NULL,
        PRIMARY KEY (item_id, version)
    )""",
    """CREATE TABLE IF NOT EXISTS deliveries (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        item_id INTEGER,
        version INTEGER,
        kind TEXT NOT NULL,
        score INTEGER NOT NULL DEFAULT 0,
        priority TEXT NOT NULL DEFAULT 'low',
        channel TEXT NOT NULL DEFAULT 'feed',
        payload TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL,
        delivered_at REAL,
        acked_at REAL,
        PRIMARY KEY (user_id, seq)
    )""",
    """CREATE TABLE IF NOT EXISTS user_item_state (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        read_at REAL,
        starred INTEGER NOT NULL DEFAULT 0,
        todo_status TEXT NOT NULL DEFAULT '',
        hidden INTEGER NOT NULL DEFAULT 0,
        not_important INTEGER NOT NULL DEFAULT 0,
        deadline_override REAL,
        note TEXT NOT NULL DEFAULT '',
        score INTEGER NOT NULL DEFAULT 0,
        priority TEXT NOT NULL DEFAULT 'low',
        reasons TEXT NOT NULL DEFAULT '[]',
        updated_at REAL NOT NULL,
        PRIMARY KEY (user_id, item_id)
    )""",
    # 幂等键：离线操作回放与发信防重复
    """CREATE TABLE IF NOT EXISTS op_log (
        user_id INTEGER NOT NULL,
        op_id TEXT NOT NULL,
        result TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL,
        PRIMARY KEY (user_id, op_id)
    )""",
    """CREATE TABLE IF NOT EXISTS rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        pattern TEXT NOT NULL,
        boost REAL NOT NULL DEFAULT 0.5,
        created_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sent_mails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        idempotency_key TEXT NOT NULL,
        message_id TEXT NOT NULL DEFAULT '',
        recipients TEXT NOT NULL DEFAULT '[]',
        subject TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        error TEXT NOT NULL DEFAULT '',
        sent_at REAL,
        created_at REAL NOT NULL,
        UNIQUE (user_id, idempotency_key)
    )""",
    """CREATE TABLE IF NOT EXISTS dashboards (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        layout TEXT NOT NULL,
        updated_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS reminders_sent (
        user_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        deadline_at REAL NOT NULL,
        sent_at REAL NOT NULL,
        PRIMARY KEY (user_id, item_id, kind, deadline_at)
    )""",
    """CREATE TABLE IF NOT EXISTS transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        pair_code TEXT NOT NULL UNIQUE,
        token TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'waiting',
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS transfer_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transfer_id INTEGER NOT NULL REFERENCES transfers(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        size INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        received INTEGER NOT NULL DEFAULT 0,
        direction TEXT NOT NULL DEFAULT 'up',
        status TEXT NOT NULL DEFAULT 'uploading',
        path TEXT NOT NULL,
        created_at REAL NOT NULL
    )""",
    # 注册邮箱验证码：只存 HMAC，不存明文
    """CREATE TABLE IF NOT EXISTS email_codes (
        email TEXT PRIMARY KEY,
        code_hash TEXT NOT NULL,
        expires_at REAL NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        sent_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kind TEXT NOT NULL,
        data TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL
    )""",
]


# 已有数据库的增量迁移：列已存在时忽略错误
MIGRATIONS: list[str] = [
    "ALTER TABLE users ADD COLUMN capture_generation INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE reading_sources ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE reading_sources ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE reading_sources ADD COLUMN delete_result TEXT",
    "ALTER TABLE users ADD COLUMN digest_email INTEGER NOT NULL DEFAULT 0",
    # 个人来源的身份键与别名键加所有者前缀（pipeline._scope），已有数据补上；可重复执行
    """UPDATE items SET identity_key = '@' || (SELECT s.owner_id FROM sources s WHERE s.id = items.source_id)
           || '/' || identity_key
       WHERE identity_key NOT LIKE '@%'
         AND source_id IN (SELECT id FROM sources WHERE owner_id IS NOT NULL)""",
    """UPDATE item_aliases SET alias_key = '@' || (SELECT s.owner_id FROM sources s WHERE s.id = item_aliases.source_id)
           || '/' || alias_key
       WHERE alias_key NOT LIKE '@%'
         AND source_id IN (SELECT id FROM sources WHERE owner_id IS NOT NULL)""",
]

# Browser capture v1: private entity identity + backend-owned schedule and durable leases.
SCHEMA += [
    """CREATE TABLE IF NOT EXISTS web_collections (
        id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        identity_key TEXT NOT NULL, source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        created_at REAL NOT NULL, UNIQUE(owner_id, identity_key)
    )""",
    """CREATE TABLE IF NOT EXISTS web_capture_requests (
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        request_id TEXT NOT NULL, digest TEXT NOT NULL, response TEXT NOT NULL,
        created_at REAL NOT NULL, PRIMARY KEY(owner_id, request_id)
    )""",
]

SCHEMA += [
    """CREATE TABLE IF NOT EXISTS browser_requests (
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        request_id TEXT NOT NULL, digest TEXT NOT NULL, response TEXT NOT NULL,
        created_at REAL NOT NULL, PRIMARY KEY(owner_id, request_id)
    )""",
    """CREATE TABLE IF NOT EXISTS browser_monitors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        device_id TEXT NOT NULL, identity_key TEXT NOT NULL,
        binding TEXT NOT NULL, recipe TEXT NOT NULL,
        source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        item_id INTEGER REFERENCES items(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL DEFAULT 1, supported INTEGER NOT NULL,
        enabled INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
        interval_s REAL NOT NULL DEFAULT 600, next_at REAL NOT NULL DEFAULT 0,
        last_result TEXT NOT NULL DEFAULT 'not_executed', last_attempt_at REAL,
        last_success_at REAL, error TEXT NOT NULL DEFAULT '',
        last_raw TEXT NOT NULL, created_at REAL NOT NULL,
        UNIQUE(owner_id, identity_key)
    )""",
    """CREATE TABLE IF NOT EXISTS browser_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        monitor_id INTEGER NOT NULL REFERENCES browser_monitors(id) ON DELETE CASCADE,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        device_id TEXT NOT NULL, revision INTEGER NOT NULL, lease TEXT NOT NULL,
        expires_at REAL NOT NULL, claimed_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 1,
        digest TEXT, response TEXT, finished_at REAL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_browser_due ON browser_monitors(owner_id, device_id, next_at)",
    "CREATE INDEX IF NOT EXISTS ix_browser_job_target ON browser_jobs(monitor_id, finished_at)",
    """CREATE TABLE IF NOT EXISTS browser_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        monitor_id INTEGER NOT NULL REFERENCES browser_monitors(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL,
        checked_at REAL NOT NULL, version INTEGER
    )""",
]

SCHEMA += [
    """CREATE TABLE IF NOT EXISTS reading_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        device_id TEXT NOT NULL, identity_key TEXT NOT NULL, recipe TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'manual', paused INTEGER NOT NULL DEFAULT 0,
        verified INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
        interval_s INTEGER NOT NULL DEFAULT 1800, next_at REAL NOT NULL DEFAULT 0,
        pending TEXT NOT NULL DEFAULT '', last_result TEXT NOT NULL DEFAULT 'not_executed',
        last_attempt_at REAL, last_success_at REAL, error TEXT NOT NULL DEFAULT '',
        last_snapshot TEXT NOT NULL, created_at REAL NOT NULL,
        UNIQUE(owner_id, identity_key)
    )""",
    """CREATE TABLE IF NOT EXISTS reading_source_items (
        reading_id INTEGER NOT NULL REFERENCES reading_sources(id) ON DELETE CASCADE,
        item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        PRIMARY KEY(reading_id, item_id)
    )""",
    """CREATE TABLE IF NOT EXISTS reading_devices (
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        device_id TEXT NOT NULL, last_seen_at REAL NOT NULL,
        PRIMARY KEY(owner_id, device_id)
    )""",
    """CREATE TABLE IF NOT EXISTS reading_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reading_id INTEGER NOT NULL REFERENCES reading_sources(id) ON DELETE CASCADE,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        device_id TEXT NOT NULL, revision INTEGER NOT NULL, purpose TEXT NOT NULL,
        lease TEXT NOT NULL, expires_at REAL NOT NULL, claimed_at REAL NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 1, finished_at REAL, digest TEXT, response TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_reading_jobs ON reading_jobs(owner_id, device_id, finished_at)",
    """CREATE TABLE IF NOT EXISTS reading_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reading_id INTEGER NOT NULL REFERENCES reading_sources(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL, purpose TEXT NOT NULL, result TEXT NOT NULL,
        detail TEXT NOT NULL, checked_at REAL NOT NULL
    )""",
]

SCHEMA += [
    """CREATE TABLE IF NOT EXISTS reading_sessions (
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        device_id TEXT NOT NULL, origin TEXT NOT NULL, session_id TEXT NOT NULL,
        PRIMARY KEY(owner_id, device_id, origin)
    )""",
    """CREATE TABLE IF NOT EXISTS reading_pages (
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        device_id TEXT NOT NULL, page_id TEXT NOT NULL, origin TEXT NOT NULL,
        url TEXT NOT NULL, session_id TEXT NOT NULL, view TEXT NOT NULL,
        PRIMARY KEY(owner_id, device_id, page_id), UNIQUE(owner_id, device_id, url, view)
    )""",
]
