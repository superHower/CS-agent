"""SQLite 数据库连接与表初始化。

使用 aiosqlite 实现异步访问，数据文件默认位于 data/admin.db。
"""

from pathlib import Path

import aiosqlite

DB_PATH = Path("data/admin.db")

_CREATE_SHOPS_TABLE = """
CREATE TABLE IF NOT EXISTS shops (
    shop_id      TEXT PRIMARY KEY,
    category_id  TEXT NOT NULL DEFAULT 'default',
    platform     TEXT NOT NULL,
    name         TEXT NOT NULL,
    confidence_threshold INTEGER NOT NULL DEFAULT 85,
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_CATEGORIES_TABLE = """
CREATE TABLE IF NOT EXISTS categories (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    model_path  TEXT NOT NULL DEFAULT 'models/bge-small-zh',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_ALERT_CONFIG_TABLE = """
CREATE TABLE IF NOT EXISTS alert_config (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    webhook_url TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_LLM_CONFIG_TABLE = """
CREATE TABLE IF NOT EXISTS llm_config (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    backend     TEXT NOT NULL DEFAULT 'cloud',
    model       TEXT NOT NULL DEFAULT 'gpt-4o-mini',
    api_key     TEXT NOT NULL DEFAULT '',
    base_url    TEXT NOT NULL DEFAULT 'https://api.openai.com/v1',
    max_tokens  INTEGER NOT NULL DEFAULT 512,
    temperature REAL NOT NULL DEFAULT 0.3,
    timeout     REAL NOT NULL DEFAULT 5.0,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_STATS_TABLE = """
CREATE TABLE IF NOT EXISTS daily_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id     TEXT NOT NULL,
    stat_date   TEXT NOT NULL,
    total_sessions   INTEGER NOT NULL DEFAULT 0,
    faq_hits         INTEGER NOT NULL DEFAULT 0,
    llm_calls        INTEGER NOT NULL DEFAULT 0,
    escalations      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(shop_id, stat_date)
)
"""

_CREATE_FAQ_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS faq_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id TEXT NOT NULL DEFAULT 'default',
    shop_id     TEXT NOT NULL DEFAULT 'global',
    answer      TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    priority    INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_FAQ_ALIASES_TABLE = """
CREATE TABLE IF NOT EXISTS faq_aliases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    faq_id      INTEGER NOT NULL REFERENCES faq_items(id) ON DELETE CASCADE,
    question    TEXT NOT NULL,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(faq_id, question)
)
"""

_CREATE_FAQ_ALIAS_UNIQUE_IDX = """
CREATE INDEX IF NOT EXISTS idx_faq_aliases_faq_id ON faq_aliases(faq_id)
"""

_CREATE_PRODUCTS_TABLE = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id TEXT NOT NULL DEFAULT 'default',
    shop_id     TEXT NOT NULL DEFAULT 'global',
    model       TEXT NOT NULL,
    attributes  TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    qdrant_sync INTEGER NOT NULL DEFAULT 0 CHECK (qdrant_sync IN (-1, 0, 1)),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(model, category_id, shop_id)
)
"""

_CREATE_PRODUCTS_IDX = """
CREATE INDEX IF NOT EXISTS idx_products_shop_id ON products(shop_id)
"""

_CREATE_KNOWLEDGE_ENTRIES_TABLE = """
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id TEXT NOT NULL DEFAULT 'default',
    shop_id     TEXT NOT NULL DEFAULT 'global',
    category    TEXT NOT NULL DEFAULT 'shortcut',
    code        TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    status      INTEGER NOT NULL DEFAULT 1 CHECK (status IN (-1, 0, 1)),
    qdrant_sync INTEGER NOT NULL DEFAULT 0 CHECK (qdrant_sync IN (-1, 0, 1)),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_KNOWLEDGE_IDX = """
CREATE INDEX IF NOT EXISTS idx_knowledge_shop_category ON knowledge_entries(category_id, shop_id, category)
"""

# ── MD 文件管理 ─────────────────────────────────────────────────────────────────

_CREATE_KNOWLEDGE_FILES_TABLE = """
CREATE TABLE IF NOT EXISTS knowledge_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id     TEXT NOT NULL DEFAULT 'default',
    shop_id         TEXT NOT NULL DEFAULT 'global',
    filename        TEXT NOT NULL,
    raw_content     TEXT NOT NULL,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    total_chars     INTEGER NOT NULL DEFAULT 0,
    status          INTEGER NOT NULL DEFAULT 1 CHECK (status IN (-1, 0, 1)),
    qdrant_sync     INTEGER NOT NULL DEFAULT 0 CHECK (qdrant_sync IN (-1, 0, 1)),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_KNOWLEDGE_FILES_IDX = """
CREATE INDEX IF NOT EXISTS idx_knowledge_files_shop ON knowledge_files(shop_id)
"""

_CREATE_ESCALATION_KEYWORDS_TABLE = """
CREATE TABLE IF NOT EXISTS escalation_keywords (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id  TEXT,
    shop_id      TEXT NOT NULL DEFAULT 'global',
    keyword      TEXT NOT NULL,
    UNIQUE(keyword, shop_id)
)
"""

_CREATE_DECOY_PHRASES_TABLE = """
CREATE TABLE IF NOT EXISTS decoy_phrases_pool (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id TEXT,
    shop_id      TEXT NOT NULL DEFAULT 'global',
    phrase       TEXT NOT NULL
)
"""

_CREATE_MESSAGE_LOGS_TABLE = """
CREATE TABLE IF NOT EXISTS message_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id         TEXT,
    buyer_id        TEXT,
    message_id      TEXT,
    user_msg        TEXT,
    match_source    TEXT,
    reply           TEXT,
    confidence      REAL,
    elapsed_ms      INTEGER,
    llm_tokens_in   INTEGER,
    llm_tokens_out  INTEGER,
    is_escalated    INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_MESSAGE_LOGS_IDX = """
CREATE INDEX IF NOT EXISTS idx_message_logs_shop_time ON message_logs(shop_id, created_at)
"""

_CREATE_CONVERSATION_ARCHIVE_TABLE = """
CREATE TABLE IF NOT EXISTS conversation_archive (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id       TEXT NOT NULL,
    buyer_id      TEXT NOT NULL,
    session_id    TEXT,
    summary       TEXT,
    full_history  TEXT,
    resolution    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_CONVERSATION_ARCHIVE_IDX = """
CREATE INDEX IF NOT EXISTS idx_conv_archive_shop_buyer ON conversation_archive(shop_id, buyer_id)
"""


async def get_db() -> aiosqlite.Connection:
    """获取 aiosqlite 数据库连接（调用方负责关闭）。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db() -> None:
    """创建所有表（幂等）。"""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute(_CREATE_SHOPS_TABLE)
        await conn.execute(_CREATE_ALERT_CONFIG_TABLE)
        await conn.execute(_CREATE_LLM_CONFIG_TABLE)
        await conn.execute(_CREATE_STATS_TABLE)
        await conn.execute(_CREATE_FAQ_ITEMS_TABLE)
        await conn.execute(_CREATE_FAQ_ALIASES_TABLE)
        await conn.execute(_CREATE_FAQ_ALIAS_UNIQUE_IDX)
        await conn.execute(_CREATE_PRODUCTS_TABLE)
        await conn.execute(_CREATE_PRODUCTS_IDX)
        await conn.execute(_CREATE_CATEGORIES_TABLE)
        await conn.execute(_CREATE_KNOWLEDGE_ENTRIES_TABLE)
        await conn.execute(_CREATE_KNOWLEDGE_IDX)
        await conn.execute(_CREATE_KNOWLEDGE_FILES_TABLE)
        await conn.execute(_CREATE_KNOWLEDGE_FILES_IDX)
        await conn.execute(_CREATE_ESCALATION_KEYWORDS_TABLE)
        await conn.execute(_CREATE_DECOY_PHRASES_TABLE)
        await conn.execute(_CREATE_MESSAGE_LOGS_TABLE)
        await conn.execute(_CREATE_MESSAGE_LOGS_IDX)
        await conn.execute(_CREATE_CONVERSATION_ARCHIVE_TABLE)
        await conn.execute(_CREATE_CONVERSATION_ARCHIVE_IDX)
        await conn.commit()

        await _migrate_add_columns(conn)
        await conn.commit()


async def _migrate_add_columns(conn: aiosqlite.Connection) -> None:
    """为已有表添加新增字段（幂等迁移）。"""
    await _migrate_add_column(conn, "shops", "category_id", "TEXT NOT NULL DEFAULT 'default'")

    cur = await conn.execute("SELECT COUNT(*) FROM categories")
    row = await cur.fetchone()
    if row[0] == 0:
        await conn.execute(
            "INSERT OR IGNORE INTO categories (id, name, description) VALUES ('default', '默认分类', '系统默认分类')"
        )

    await _migrate_add_column(conn, "faq_items", "category_id", "TEXT NOT NULL DEFAULT 'default'")
    await _migrate_add_column(conn, "products", "category_id", "TEXT NOT NULL DEFAULT 'default'")
    await _migrate_add_column(conn, "knowledge_entries", "category_id", "TEXT NOT NULL DEFAULT 'default'")
    await _migrate_add_column(conn, "knowledge_files", "category_id", "TEXT NOT NULL DEFAULT 'default'")
    await _migrate_add_column(conn, "escalation_keywords", "category_id", "TEXT")
    await _migrate_add_column(conn, "decoy_phrases_pool", "category_id", "TEXT")


async def _migrate_add_column(conn: aiosqlite.Connection, table: str, column: str, definition: str) -> None:
    """若表中不存在指定列则添加（SQLite 兼容）。"""
    cur = await conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in await cur.fetchall()}
    if column not in existing:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
