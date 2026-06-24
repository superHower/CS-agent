"""店铺配置 CRUD 操作与统计查询。"""

import logging
import uuid
from datetime import UTC, datetime

import aiosqlite

from admin.schemas import (
    AlertConfigOut,
    AlertConfigUpdate,
    ConversationArchiveCreate,
    ConversationArchiveOut,
    DashboardStats,
    DecoyPhraseCreate,
    DecoyPhraseOut,
    EscalationKeywordCreate,
    EscalationKeywordOut,
    FaqAliasOut,
    FaqCreate,
    FaqImportRow,
    FaqOut,
    FaqUpdate,
    KnowledgeEntryCreate,
    KnowledgeEntryOut,
    KnowledgeEntryUpdate,
    LLMConfigOut,
    LLMConfigUpdate,
    MessageLogCreate,
    MessageLogOut,
    ProductCreate,
    ProductImportRow,
    ProductOut,
    ProductUpdate,
    ShopCreate,
    ShopOut,
    ShopUpdate,
)

logger = logging.getLogger(__name__)


async def create_shop(conn: aiosqlite.Connection, data: ShopCreate) -> ShopOut:
    """创建店铺配置。"""
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    await conn.execute(
        """
        INSERT INTO shops
            (shop_id, platform, name, api_key, api_secret, obsidian_vault,
             confidence_threshold, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.shop_id,
            data.platform,
            data.name,
            data.api_key,
            data.api_secret,
            data.obsidian_vault,
            data.confidence_threshold,
            int(data.enabled),
            now,
            now,
        ),
    )
    await conn.commit()
    return await get_shop(conn, data.shop_id)


async def get_or_create_shop_by_name(
    conn: aiosqlite.Connection, name: str, platform: str
) -> ShopOut:
    """按名称查找店铺，不存在时自动创建（shop_id 自动生成）。"""
    async with conn.execute("SELECT * FROM shops WHERE name = ?", (name,)) as cur:
        row = await cur.fetchone()
    if row is not None:
        return _row_to_shop(row)

    shop_id = uuid.uuid4().hex[:12]
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    await conn.execute(
        """
        INSERT INTO shops
            (shop_id, platform, name, api_key, api_secret, obsidian_vault,
             confidence_threshold, enabled, created_at, updated_at)
        VALUES (?, ?, ?, '', '', '', 85, 1, ?, ?)
        """,
        (shop_id, platform, name, now, now),
    )
    await conn.commit()
    return await get_shop(conn, shop_id)


async def list_shop_names(conn: aiosqlite.Connection) -> list[str]:
    """返回所有店铺名称列表（供前端下拉）。"""
    async with conn.execute("SELECT name FROM shops ORDER BY created_at") as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows]



async def get_shop(conn: aiosqlite.Connection, shop_id: str) -> ShopOut | None:
    """按 shop_id 查询店铺。"""
    async with conn.execute("SELECT * FROM shops WHERE shop_id = ?", (shop_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return _row_to_shop(row)


async def list_shops(conn: aiosqlite.Connection) -> list[ShopOut]:
    """列出所有店铺。"""
    async with conn.execute("SELECT * FROM shops ORDER BY created_at") as cur:
        rows = await cur.fetchall()
    return [_row_to_shop(r) for r in rows]


async def update_shop(
    conn: aiosqlite.Connection,
    shop_id: str,
    data: ShopUpdate,
) -> ShopOut | None:
    """更新店铺配置（仅更新非 None 字段）。"""
    updates: dict[str, object] = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return await get_shop(conn, shop_id)

    updates["updated_at"] = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    if "enabled" in updates:
        updates["enabled"] = int(updates["enabled"])

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [shop_id]

    await conn.execute(f"UPDATE shops SET {set_clause} WHERE shop_id = ?", values)
    await conn.commit()
    return await get_shop(conn, shop_id)


async def delete_shop(conn: aiosqlite.Connection, shop_id: str) -> bool:
    """删除店铺配置，返回是否成功（存在才删除）。"""
    cursor = await conn.execute("DELETE FROM shops WHERE shop_id = ?", (shop_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def get_dashboard_stats(
    conn: aiosqlite.Connection,
    shop_id: str | None = None,
    stat_date: str | None = None,
) -> list[DashboardStats]:
    """查询仪表盘统计数据。

    Args:
        shop_id: 按店铺过滤（None 表示全部）。
        stat_date: 按日期过滤（格式 YYYY-MM-DD，None 表示今日）。
    """
    if stat_date is None:
        stat_date = datetime.now(tz=UTC).strftime("%Y-%m-%d")

    conditions = ["stat_date = ?"]
    params: list = [stat_date]
    if shop_id:
        conditions.append("shop_id = ?")
        params.append(shop_id)

    where = " AND ".join(conditions)
    async with conn.execute(
        f"SELECT * FROM daily_stats WHERE {where} ORDER BY shop_id",
        params,
    ) as cur:
        rows = await cur.fetchall()

    return [_row_to_stats(r) for r in rows]


async def upsert_stat(
    conn: aiosqlite.Connection,
    shop_id: str,
    stat_date: str,
    field: str,
    increment: int = 1,
) -> None:
    """原子性增量更新统计字段（主服务调用）。

    Args:
        field: 字段名，如 "faq_hits"、"llm_calls"、"escalations"、"total_sessions"。
    """
    allowed_fields = {"total_sessions", "faq_hits", "llm_calls", "escalations"}
    if field not in allowed_fields:
        raise ValueError(f"非法统计字段: {field}")

    await conn.execute(
        f"""
        INSERT INTO daily_stats (shop_id, stat_date, {field})
        VALUES (?, ?, ?)
        ON CONFLICT(shop_id, stat_date) DO UPDATE SET
            {field} = {field} + excluded.{field}
        """,
        (shop_id, stat_date, increment),
    )
    await conn.commit()


async def get_alert_config(conn: aiosqlite.Connection) -> AlertConfigOut:
    """获取告警配置（始终返回一行，不存在时返回默认值）。"""
    async with conn.execute("SELECT * FROM alert_config WHERE id = 1") as cur:
        row = await cur.fetchone()
    if row is None:
        return AlertConfigOut(webhook_url="", updated_at="")
    d = dict(row)
    d.pop("id", None)
    return AlertConfigOut(**d)


async def update_alert_config(conn: aiosqlite.Connection, data: AlertConfigUpdate) -> AlertConfigOut:
    """更新告警配置（upsert，id 固定为 1）。"""
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    await conn.execute(
        "INSERT OR IGNORE INTO alert_config (id, updated_at) VALUES (1, ?)",
        (now,),
    )
    if data.webhook_url is not None:
        await conn.execute(
            "UPDATE alert_config SET webhook_url = ?, updated_at = ? WHERE id = 1",
            (data.webhook_url, now),
        )
    await conn.commit()
    return await get_alert_config(conn)


async def get_llm_config(conn: aiosqlite.Connection) -> LLMConfigOut:
    """获取 LLM 配置（始终返回一行，不存在时返回默认值）。"""
    async with conn.execute("SELECT * FROM llm_config WHERE id = 1") as cur:
        row = await cur.fetchone()
    if row is None:
        return LLMConfigOut(
            model="gpt-4o-mini",
            api_key="",
            base_url="https://api.openai.com/v1",
            max_tokens=512,
            temperature=0.3,
            timeout=5.0,
            embedding_model="bge-small-zh",
            updated_at="",
        )
    return _row_to_llm_config(row)


async def update_llm_config(conn: aiosqlite.Connection, data: LLMConfigUpdate) -> LLMConfigOut:
    """更新 LLM 配置（upsert，只有一行，id 固定为 1）。"""
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    # 先确保行存在
    await conn.execute(
        """
        INSERT OR IGNORE INTO llm_config (id, updated_at)
        VALUES (1, ?)
        """,
        (now,),
    )
    updates: dict[str, object] = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        updates["updated_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        await conn.execute(
            f"UPDATE llm_config SET {set_clause} WHERE id = 1",
            list(updates.values()),
        )
    await conn.commit()
    return await get_llm_config(conn)


def _row_to_llm_config(row: aiosqlite.Row) -> LLMConfigOut:
    d = dict(row)
    d.pop("id", None)
    d.pop("backend", None)
    # embedding_model 列可能在旧版数据库中不存在
    if "embedding_model" not in d:
        d["embedding_model"] = ""
    return LLMConfigOut(**d)


def _row_to_shop(row: aiosqlite.Row) -> ShopOut:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    return ShopOut(**d)


def _row_to_stats(row: aiosqlite.Row) -> DashboardStats:
    d = dict(row)
    total = d["total_sessions"] or 1
    d["faq_hit_rate"] = round(d["faq_hits"] / total, 4)
    d.pop("id", None)
    return DashboardStats(**d)


# ── FAQ CRUD ──────────────────────────────────────────────────────────────────


async def _faq_aliases(conn: aiosqlite.Connection, faq_id: int) -> list[FaqAliasOut]:
    async with conn.execute(
        "SELECT id, faq_id, question, is_primary FROM faq_aliases WHERE faq_id = ? ORDER BY is_primary DESC, id",
        (faq_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [FaqAliasOut(id=r["id"], faq_id=r["faq_id"], question=r["question"], is_primary=bool(r["is_primary"])) for r in rows]


async def _row_to_faq(conn: aiosqlite.Connection, row: aiosqlite.Row) -> FaqOut:
    d = dict(row)
    aliases = await _faq_aliases(conn, d["id"])
    return FaqOut(
        id=d["id"],
        shop_id=d["shop_id"],
        answer=d["answer"],
        category=d["category"],
        priority=d["priority"],
        enabled=bool(d["enabled"]),
        aliases=aliases,
        created_at=d["created_at"],
        updated_at=d["updated_at"],
    )


async def _check_alias_conflict(
    conn: aiosqlite.Connection, shop_id: str, questions: list[str], exclude_faq_id: int | None = None
) -> str | None:
    """检查别名是否与同店铺其他 FAQ 冲突，返回冲突的问法或 None。"""
    for q in questions:
        async with conn.execute(
            """
            SELECT fa.question FROM faq_aliases fa
            JOIN faq_items fi ON fi.id = fa.faq_id
            WHERE fi.shop_id = ? AND fa.question = ? AND fi.id != ?
            """,
            (shop_id, q, exclude_faq_id or -1),
        ) as cur:
            row = await cur.fetchone()
        if row:
            return q
    return None


async def create_faq(conn: aiosqlite.Connection, data: FaqCreate) -> FaqOut:
    """创建 FAQ 及其别名列表。"""
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    questions = [a.question for a in data.aliases]

    conflict = await _check_alias_conflict(conn, data.shop_id, questions)
    if conflict:
        raise ValueError(f"问法已存在于该店铺其他 FAQ：{conflict}")

    cur = await conn.execute(
        "INSERT INTO faq_items (shop_id, answer, category, priority, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (data.shop_id, data.answer, data.category, data.priority, int(data.enabled), now, now),
    )
    faq_id = cur.lastrowid
    for alias in data.aliases:
        await conn.execute(
            "INSERT INTO faq_aliases (faq_id, question, is_primary) VALUES (?,?,?)",
            (faq_id, alias.question, int(alias.is_primary)),
        )
    await conn.commit()
    return await get_faq(conn, faq_id)


async def get_faq(conn: aiosqlite.Connection, faq_id: int) -> FaqOut | None:
    """按 ID 查询 FAQ。"""
    async with conn.execute("SELECT * FROM faq_items WHERE id = ?", (faq_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return await _row_to_faq(conn, row)


async def list_faqs(
    conn: aiosqlite.Connection,
    shop_id: str | None = None,
    category: str | None = None,
    enabled_only: bool = False,
) -> list[FaqOut]:
    """列出 FAQ，支持按店铺、分类、启用状态过滤。"""
    conditions = []
    params: list = []
    if shop_id:
        conditions.append("shop_id = ?")
        params.append(shop_id)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if enabled_only:
        conditions.append("enabled = 1")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    async with conn.execute(
        f"SELECT * FROM faq_items {where} ORDER BY shop_id, priority DESC, id",
        params,
    ) as cur:
        rows = await cur.fetchall()
    result = []
    for row in rows:
        result.append(await _row_to_faq(conn, row))
    return result


async def update_faq(conn: aiosqlite.Connection, faq_id: int, data: FaqUpdate) -> FaqOut | None:
    """更新 FAQ（别名全量替换）。"""
    async with conn.execute("SELECT shop_id FROM faq_items WHERE id = ?", (faq_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    shop_id = row["shop_id"]
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

    updates: dict[str, object] = {k: v for k, v in data.model_dump(exclude={"aliases"}).items() if v is not None}
    if "enabled" in updates:
        updates["enabled"] = int(updates["enabled"])
    if updates:
        updates["updated_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        await conn.execute(f"UPDATE faq_items SET {set_clause} WHERE id = ?", list(updates.values()) + [faq_id])

    if data.aliases is not None:
        questions = [a.question for a in data.aliases]
        conflict = await _check_alias_conflict(conn, shop_id, questions, exclude_faq_id=faq_id)
        if conflict:
            raise ValueError(f"问法已存在于该店铺其他 FAQ：{conflict}")
        await conn.execute("DELETE FROM faq_aliases WHERE faq_id = ?", (faq_id,))
        for alias in data.aliases:
            await conn.execute(
                "INSERT INTO faq_aliases (faq_id, question, is_primary) VALUES (?,?,?)",
                (faq_id, alias.question, int(alias.is_primary)),
            )
        if not updates:
            await conn.execute("UPDATE faq_items SET updated_at = ? WHERE id = ?", (now, faq_id))

    await conn.commit()
    return await get_faq(conn, faq_id)


async def delete_faq(conn: aiosqlite.Connection, faq_id: int) -> bool:
    """删除 FAQ（级联删除别名）。"""
    cursor = await conn.execute("DELETE FROM faq_items WHERE id = ?", (faq_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def set_faq_enabled(conn: aiosqlite.Connection, faq_id: int, enabled: bool) -> FaqOut | None:
    """启用/禁用 FAQ。"""
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    cursor = await conn.execute(
        "UPDATE faq_items SET enabled = ?, updated_at = ? WHERE id = ?",
        (int(enabled), now, faq_id),
    )
    await conn.commit()
    if cursor.rowcount == 0:
        return None
    return await get_faq(conn, faq_id)


async def import_faqs(
    conn: aiosqlite.Connection, shop_id: str, rows: list[FaqImportRow]
) -> tuple[int, list[str]]:
    """批量导入 FAQ，返回 (成功数, 错误消息列表)。"""
    success = 0
    errors: list[str] = []
    for i, row in enumerate(rows, 1):
        aliases_list = [row.question] + [a.strip() for a in row.aliases.split("|") if a.strip()]
        # 去重
        seen: set[str] = set()
        unique_aliases = []
        for q in aliases_list:
            if q not in seen:
                seen.add(q)
                unique_aliases.append(q)
        try:
            data = FaqCreate(
                shop_id=shop_id,
                answer=row.answer,
                category=row.category,
                priority=row.priority,
                enabled=True,
                aliases=[
                    {"question": q, "is_primary": (j == 0)}
                    for j, q in enumerate(unique_aliases)
                ],
            )
            await create_faq(conn, data)
            success += 1
        except ValueError as exc:
            errors.append(f"第{i}行：{exc}")
        except Exception as exc:
            errors.append(f"第{i}行：导入异常 {exc}")
    return success, errors


async def load_all_faq_pairs(
    conn: aiosqlite.Connection, shop_id: str
) -> list[tuple[str, str]]:
    """加载指定店铺所有启用的 FAQ (question, answer) 对，用于预热 Redis。"""
    async with conn.execute(
        """
        SELECT fa.question, fi.answer
        FROM faq_aliases fa
        JOIN faq_items fi ON fi.id = fa.faq_id
        WHERE fi.shop_id = ? AND fi.enabled = 1
        ORDER BY fi.priority DESC
        """,
        (shop_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [(r["question"], r["answer"]) for r in rows]


# ── 产品管理 CRUD ─────────────────────────────────────────────────────────────


def _row_to_product(row: aiosqlite.Row) -> ProductOut:
    return ProductOut(**dict(row))


async def create_product(conn: aiosqlite.Connection, data: ProductCreate) -> ProductOut:
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    cur = await conn.execute(
        "INSERT INTO products (shop_id, model, attributes, tags, qdrant_sync, created_at, updated_at) VALUES (?,?,?,?,0,?,?)",
        (data.shop_id, data.model, data.attributes, data.tags, now, now),
    )
    await conn.commit()
    return await get_product(conn, cur.lastrowid)


async def get_product(conn: aiosqlite.Connection, product_id: int) -> ProductOut | None:
    async with conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)) as cur:
        row = await cur.fetchone()
    return _row_to_product(row) if row else None


async def list_products(
    conn: aiosqlite.Connection,
    shop_id: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ProductOut], int]:
    """返回 (产品列表, 总数)。"""
    conditions = []
    params: list = []
    if shop_id:
        conditions.append("shop_id = ?")
        params.append(shop_id)
    if search:
        conditions.append("(model LIKE ? OR tags LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    async with conn.execute(f"SELECT COUNT(*) FROM products {where}", params) as cur:
        total = (await cur.fetchone())[0]
    offset = (page - 1) * page_size
    async with conn.execute(
        f"SELECT * FROM products {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_product(r) for r in rows], total


async def update_product(conn: aiosqlite.Connection, product_id: int, data: ProductUpdate) -> ProductOut | None:
    updates: dict[str, object] = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return await get_product(conn, product_id)
    updates["updated_at"] = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    updates["qdrant_sync"] = 0  # 内容变化，标记为待同步
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    await conn.execute(f"UPDATE products SET {set_clause} WHERE id = ?", list(updates.values()) + [product_id])
    await conn.commit()
    return await get_product(conn, product_id)


async def delete_product(conn: aiosqlite.Connection, product_id: int) -> bool:
    cursor = await conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def import_products(
    conn: aiosqlite.Connection, shop_id: str, rows: list[ProductImportRow], overwrite: bool = False
) -> tuple[int, list[str]]:
    success = 0
    errors: list[str] = []
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    for i, row in enumerate(rows, 1):
        try:
            if overwrite:
                await conn.execute(
                    """
                    INSERT INTO products (shop_id, model, attributes, tags, qdrant_sync, created_at, updated_at)
                    VALUES (?,?,?,?,0,?,?)
                    ON CONFLICT(model, shop_id) DO UPDATE SET
                        attributes=excluded.attributes, tags=excluded.tags, qdrant_sync=0, updated_at=excluded.updated_at
                    """,
                    (shop_id, row.model, row.attributes, row.tags, now, now),
                )
            else:
                await conn.execute(
                    "INSERT OR IGNORE INTO products (shop_id, model, attributes, tags, qdrant_sync, created_at, updated_at) VALUES (?,?,?,?,0,?,?)",
                    (shop_id, row.model, row.attributes, row.tags, now, now),
                )
            await conn.commit()
            success += 1
        except Exception as exc:
            errors.append(f"第{i}行（{row.model}）：{exc}")
    return success, errors


async def mark_product_sync(conn: aiosqlite.Connection, product_id: int, status: int) -> None:
    """更新产品 Qdrant 同步状态：1=已同步, 0=待同步, -1=失败。"""
    await conn.execute("UPDATE products SET qdrant_sync = ? WHERE id = ?", (status, product_id))
    await conn.commit()


# ── 知识库 CRUD ───────────────────────────────────────────────────────────────


def _row_to_knowledge(row: aiosqlite.Row) -> KnowledgeEntryOut:
    return KnowledgeEntryOut(**dict(row))


async def create_knowledge_entry(conn: aiosqlite.Connection, data: KnowledgeEntryCreate) -> KnowledgeEntryOut:
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    cur = await conn.execute(
        "INSERT INTO knowledge_entries (shop_id, category, code, title, content, status, qdrant_sync, created_at, updated_at) VALUES (?,?,?,?,?,1,0,?,?)",
        (data.shop_id, data.category, data.code, data.title, data.content, now, now),
    )
    await conn.commit()
    return await get_knowledge_entry(conn, cur.lastrowid)


async def get_knowledge_entry(conn: aiosqlite.Connection, entry_id: int) -> KnowledgeEntryOut | None:
    async with conn.execute("SELECT * FROM knowledge_entries WHERE id = ?", (entry_id,)) as cur:
        row = await cur.fetchone()
    return _row_to_knowledge(row) if row else None


async def list_knowledge_entries(
    conn: aiosqlite.Connection,
    shop_id: str | None = None,
    category: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[KnowledgeEntryOut], int]:
    conditions = ["status != -1"]
    params: list = []
    if shop_id:
        conditions.append("shop_id = ?")
        params.append(shop_id)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if search:
        conditions.append("(title LIKE ? OR content LIKE ? OR code LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    where = "WHERE " + " AND ".join(conditions)
    async with conn.execute(f"SELECT COUNT(*) FROM knowledge_entries {where}", params) as cur:
        total = (await cur.fetchone())[0]
    offset = (page - 1) * page_size
    async with conn.execute(
        f"SELECT * FROM knowledge_entries {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_knowledge(r) for r in rows], total


async def update_knowledge_entry(conn: aiosqlite.Connection, entry_id: int, data: KnowledgeEntryUpdate) -> KnowledgeEntryOut | None:
    updates: dict[str, object] = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return await get_knowledge_entry(conn, entry_id)
    updates["updated_at"] = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    if "content" in updates or "title" in updates:
        updates["qdrant_sync"] = 0
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    await conn.execute(f"UPDATE knowledge_entries SET {set_clause} WHERE id = ?", list(updates.values()) + [entry_id])
    await conn.commit()
    return await get_knowledge_entry(conn, entry_id)


async def delete_knowledge_entry(conn: aiosqlite.Connection, entry_id: int) -> bool:
    cursor = await conn.execute("UPDATE knowledge_entries SET status = -1 WHERE id = ?", (entry_id,))
    await conn.commit()
    return cursor.rowcount > 0


# ── 告警关键词 CRUD ───────────────────────────────────────────────────────────


def _row_to_escalation_keyword(row: aiosqlite.Row) -> EscalationKeywordOut:
    return EscalationKeywordOut(**dict(row))


async def list_escalation_keywords(conn: aiosqlite.Connection, shop_id: str | None = None) -> list[EscalationKeywordOut]:
    if shop_id:
        async with conn.execute("SELECT * FROM escalation_keywords WHERE shop_id = ? OR shop_id = 'global' ORDER BY id", (shop_id,)) as cur:
            rows = await cur.fetchall()
    else:
        async with conn.execute("SELECT * FROM escalation_keywords ORDER BY shop_id, id") as cur:
            rows = await cur.fetchall()
    return [_row_to_escalation_keyword(r) for r in rows]


async def create_escalation_keyword(conn: aiosqlite.Connection, data: EscalationKeywordCreate) -> EscalationKeywordOut:
    try:
        cur = await conn.execute(
            "INSERT INTO escalation_keywords (shop_id, keyword) VALUES (?,?)",
            (data.shop_id, data.keyword),
        )
        await conn.commit()
    except Exception as exc:
        raise ValueError(f"关键词已存在: {data.keyword}") from exc
    async with conn.execute("SELECT * FROM escalation_keywords WHERE id = ?", (cur.lastrowid,)) as c:
        row = await c.fetchone()
    return _row_to_escalation_keyword(row)


async def delete_escalation_keyword(conn: aiosqlite.Connection, kw_id: int) -> bool:
    cursor = await conn.execute("DELETE FROM escalation_keywords WHERE id = ?", (kw_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def load_escalation_keywords(conn: aiosqlite.Connection, shop_id: str) -> list[str]:
    """加载指定店铺（含全局）的转人工关键词列表，用于主服务启动时初始化。"""
    async with conn.execute(
        "SELECT DISTINCT keyword FROM escalation_keywords WHERE shop_id = ? OR shop_id = 'global'",
        (shop_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows]


# ── 搪塞话术 CRUD ─────────────────────────────────────────────────────────────


def _row_to_decoy_phrase(row: aiosqlite.Row) -> DecoyPhraseOut:
    return DecoyPhraseOut(**dict(row))


async def list_decoy_phrases(conn: aiosqlite.Connection, shop_id: str | None = None) -> list[DecoyPhraseOut]:
    if shop_id:
        async with conn.execute(
            "SELECT * FROM decoy_phrases_pool WHERE shop_id = ? OR shop_id = 'global' ORDER BY id",
            (shop_id,),
        ) as cur:
            rows = await cur.fetchall()
    else:
        async with conn.execute("SELECT * FROM decoy_phrases_pool ORDER BY shop_id, id") as cur:
            rows = await cur.fetchall()
    return [_row_to_decoy_phrase(r) for r in rows]


async def create_decoy_phrase(conn: aiosqlite.Connection, data: DecoyPhraseCreate) -> DecoyPhraseOut:
    cur = await conn.execute(
        "INSERT INTO decoy_phrases_pool (shop_id, phrase) VALUES (?,?)",
        (data.shop_id, data.phrase),
    )
    await conn.commit()
    async with conn.execute("SELECT * FROM decoy_phrases_pool WHERE id = ?", (cur.lastrowid,)) as c:
        row = await c.fetchone()
    return _row_to_decoy_phrase(row)


async def delete_decoy_phrase(conn: aiosqlite.Connection, phrase_id: int) -> bool:
    cursor = await conn.execute("DELETE FROM decoy_phrases_pool WHERE id = ?", (phrase_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def load_decoy_phrases(conn: aiosqlite.Connection, shop_id: str) -> list[str]:
    """加载指定店铺（含全局）的搪塞话术列表。"""
    async with conn.execute(
        "SELECT phrase FROM decoy_phrases_pool WHERE shop_id = ? OR shop_id = 'global' ORDER BY id",
        (shop_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows]


# ── 消息日志 CRUD ─────────────────────────────────────────────────────────────


async def create_message_log(conn: aiosqlite.Connection, data: MessageLogCreate) -> None:
    """异步写入消息处理日志（不阻塞主流程）。"""
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    await conn.execute(
        """
        INSERT INTO message_logs
            (shop_id, buyer_id, message_id, user_msg, match_source, reply, confidence,
             elapsed_ms, llm_tokens_in, llm_tokens_out, is_escalated, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            data.shop_id, data.buyer_id, data.message_id, data.user_msg, data.match_source,
            data.reply, data.confidence, data.elapsed_ms, data.llm_tokens_in, data.llm_tokens_out,
            int(data.is_escalated), now,
        ),
    )
    await conn.commit()


async def list_message_logs(
    conn: aiosqlite.Connection,
    shop_id: str | None = None,
    is_escalated: bool | None = None,
    date: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[MessageLogOut], int]:
    conditions = []
    params: list = []
    if shop_id:
        conditions.append("shop_id = ?")
        params.append(shop_id)
    if is_escalated is not None:
        conditions.append("is_escalated = ?")
        params.append(int(is_escalated))
    if date:
        conditions.append("created_at LIKE ?")
        params.append(f"{date}%")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    async with conn.execute(f"SELECT COUNT(*) FROM message_logs {where}", params) as cur:
        total = (await cur.fetchone())[0]
    offset = (page - 1) * page_size
    async with conn.execute(
        f"SELECT * FROM message_logs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_message_log(r) for r in rows], total


def _row_to_message_log(row: aiosqlite.Row) -> MessageLogOut:
    d = dict(row)
    d["is_escalated"] = bool(d.get("is_escalated", 0))
    return MessageLogOut(**d)


# ── 对话归档 CRUD ─────────────────────────────────────────────────────────────


async def create_conversation_archive(conn: aiosqlite.Connection, data: ConversationArchiveCreate) -> None:
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    await conn.execute(
        """
        INSERT INTO conversation_archive
            (shop_id, buyer_id, session_id, summary, full_history, resolution, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (data.shop_id, data.buyer_id, data.session_id, data.summary, data.full_history, data.resolution, now),
    )
    await conn.commit()


async def list_conversation_archives(
    conn: aiosqlite.Connection,
    shop_id: str | None = None,
    buyer_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ConversationArchiveOut], int]:
    conditions = []
    params: list = []
    if shop_id:
        conditions.append("shop_id = ?")
        params.append(shop_id)
    if buyer_id:
        conditions.append("buyer_id = ?")
        params.append(buyer_id)
    if date_from:
        conditions.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("created_at <= ?")
        params.append(date_to + " 23:59:59")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    async with conn.execute(f"SELECT COUNT(*) FROM conversation_archive {where}", params) as cur:
        total = (await cur.fetchone())[0]
    offset = (page - 1) * page_size
    async with conn.execute(
        f"SELECT * FROM conversation_archive {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ) as cur:
        rows = await cur.fetchall()
    return [ConversationArchiveOut(**dict(r)) for r in rows], total
