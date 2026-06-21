"""SQLite 数据库连接与表初始化。

使用 aiosqlite 实现异步访问，数据文件默认位于 data/admin.db。
"""

from pathlib import Path

import aiosqlite

DB_PATH = Path("data/admin.db")

_CREATE_SHOPS_TABLE = """
CREATE TABLE IF NOT EXISTS shops (
    shop_id     TEXT PRIMARY KEY,
    platform    TEXT NOT NULL,
    name        TEXT NOT NULL,
    api_key     TEXT NOT NULL DEFAULT '',
    api_secret  TEXT NOT NULL DEFAULT '',
    obsidian_vault TEXT NOT NULL DEFAULT '',
    confidence_threshold INTEGER NOT NULL DEFAULT 85,
    enabled     INTEGER NOT NULL DEFAULT 1,
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
        await conn.commit()
