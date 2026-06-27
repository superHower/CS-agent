"""店铺配置 CRUD 操作与统计查询。"""

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from admin.schemas import (
    AlertConfigOut,
    AlertConfigUpdate,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
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
    KnowledgeFileUpdate,
    LLMConfigOut,
    LLMConfigUpdate,
    ProductCreate,
    ProductImportRow,
    ProductOut,
    ProductUpdate,
    ShopCreate,
    ShopOut,
    ShopUpdate,
)

logger = logging.getLogger(__name__)


async def _ensure_category_exists(conn: aiosqlite.Connection, category_id: str) -> None:
    """确保分类存在，不存在则自动创建。"""
    async with conn.execute("SELECT id FROM categories WHERE id = ?", (category_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        # 尝试用 category_id 作为 name，如果包含特殊字符则生成可读名称
        name = category_id if category_id != "default" else "默认分类"
        await conn.execute(
            "INSERT OR IGNORE INTO categories (id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (category_id, name, "自动创建", now, now),
        )


async def create_shop(conn: aiosqlite.Connection, data: ShopCreate) -> ShopOut:
    """创建店铺配置。"""
    # 自动创建不存在的分类
    await _ensure_category_exists(conn, data.category_id)
    
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    await conn.execute(
        """
        INSERT INTO shops
            (shop_id, category_id, platform, name, api_key, api_secret,
             confidence_threshold, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.shop_id,
            data.category_id,
            data.platform,
            data.name,
            data.api_key,
            data.api_secret,
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
            (shop_id, platform, name, api_key, api_secret,
             confidence_threshold, enabled, created_at, updated_at)
        VALUES (?, ?, ?, '', '', 85, 1, ?, ?)
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
    async with conn.execute(
        """SELECT shop_id, category_id, platform, name, confidence_threshold, enabled, created_at, updated_at
           FROM shops WHERE shop_id = ?""",
        (shop_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return _row_to_shop(row)


async def list_shops(conn: aiosqlite.Connection) -> list[ShopOut]:
    """列出所有店铺。"""
    async with conn.execute(
        """SELECT shop_id, category_id, platform, name, confidence_threshold, enabled, created_at, updated_at
           FROM shops ORDER BY created_at"""
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_shop(r) for r in rows]


async def update_shop(
    conn: aiosqlite.Connection,
    shop_id: str,
    data: ShopUpdate,
) -> ShopOut | None:
    """更新店铺配置（仅更新非 None 字段）。"""
    # 如果更新了 category_id，自动创建不存在的分类
    if data.category_id is not None:
        await _ensure_category_exists(conn, data.category_id)
    
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


# ── 分类 CRUD ─────────────────────────────────────────────────────────────────


def _row_to_category(row: aiosqlite.Row) -> CategoryOut:
    return CategoryOut(**dict(row))


async def create_category(conn: aiosqlite.Connection, data: CategoryCreate) -> CategoryOut:
    """创建分类。"""
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    await conn.execute(
        "INSERT OR IGNORE INTO categories (id, name, description, model_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (data.id, data.name, data.description, data.model_path, now, now),
    )
    await conn.commit()
    async with conn.execute("SELECT * FROM categories WHERE id = ?", (data.id,)) as cur:
        row = await cur.fetchone()
    return _row_to_category(row)


async def get_category(conn: aiosqlite.Connection, category_id: str) -> CategoryOut | None:
    async with conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return _row_to_category(row)


async def list_categories(conn: aiosqlite.Connection) -> list[CategoryOut]:
    async with conn.execute("SELECT * FROM categories ORDER BY created_at") as cur:
        rows = await cur.fetchall()
    return [_row_to_category(r) for r in rows]


async def update_category(conn: aiosqlite.Connection, category_id: str, data: CategoryUpdate) -> CategoryOut | None:
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return await get_category(conn, category_id)
    updates["updated_at"] = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    await conn.execute(f"UPDATE categories SET {set_clause} WHERE id = ?", list(updates.values()) + [category_id])
    await conn.commit()
    return await get_category(conn, category_id)


async def delete_category(conn: aiosqlite.Connection, category_id: str) -> bool:
    if category_id == "default":
        return False
    # 将该分类下的店铺迁移到 default
    await conn.execute("UPDATE shops SET category_id = 'default' WHERE category_id = ?", (category_id,))
    cursor = await conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
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
    d = {
        "shop_id": row["shop_id"],
        "category_id": row["category_id"],
        "platform": row["platform"],
        "name": row["name"],
        "confidence_threshold": row["confidence_threshold"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
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
        category_id=d.get("category_id", "default"),
        shop_id=d["shop_id"],
        answer=d["answer"],
        sub_tag=d.get("category", ""),
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
        "INSERT INTO faq_items (category_id, shop_id, answer, category, priority, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (data.category_id, data.shop_id, data.answer, data.category, data.priority, int(data.enabled), now, now),
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
    category_id: str | None = None,
    sub_tag: str | None = None,
    enabled_only: bool = False,
) -> list[FaqOut]:
    """列出 FAQ，支持按分类、店铺、子标签、启用状态过滤。

    检索逻辑说明：
    - category_id + shop_id 同时指定：返回同时满足两者的记录
    - 仅 category_id：返回该分类下所有记录（包括 global 店铺）
    - 仅 shop_id：返回该店铺下所有记录（包括 default 分类）
    """
    conditions = []
    params: list = []
    if shop_id:
        conditions.append("shop_id = ?")
        params.append(shop_id)
    if category_id:
        conditions.append("category_id = ?")
        params.append(category_id)
    if sub_tag:
        conditions.append("category = ?")
        params.append(sub_tag)
    if enabled_only:
        conditions.append("enabled = 1")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    async with conn.execute(
        f"SELECT * FROM faq_items {where} ORDER BY category_id, shop_id, priority DESC, id",
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
    conn: aiosqlite.Connection, category_id: str, shop_id: str, rows: list[FaqImportRow]
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
                category_id=category_id,
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
    conn: aiosqlite.Connection, shop_id: str, category_id: str | None = None
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """加载指定店铺和分类的所有启用的 FAQ (question, answer) 对，用于预热 Redis。

    返回两个列表的元组：
    1. 店铺专属 FAQ：shop_id = 传入的 shop_id
    2. 分类共享 FAQ：shop_id = 'global' AND category_id = 传入的 category_id

    若 category_id 为 None，则只返回店铺专属 FAQ。
    """
    # 店铺专属 FAQ
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
        shop_rows = await cur.fetchall()
    shop_faqs = [(r["question"], r["answer"]) for r in shop_rows]

    if category_id is None or category_id == "default":
        return shop_faqs, []

    # 分类共享 FAQ
    async with conn.execute(
        """
        SELECT fa.question, fi.answer
        FROM faq_aliases fa
        JOIN faq_items fi ON fi.id = fa.faq_id
        WHERE fi.enabled = 1
          AND fi.shop_id = 'global'
          AND fi.category_id = ?
        ORDER BY fi.priority DESC
        """,
        (category_id,),
    ) as cur:
        cat_rows = await cur.fetchall()
    cat_faqs = [(r["question"], r["answer"]) for r in cat_rows]

    return shop_faqs, cat_faqs


# ── 产品管理 CRUD ─────────────────────────────────────────────────────────────


def _row_to_product(row: aiosqlite.Row) -> ProductOut:
    return ProductOut(**dict(row))


async def create_product(conn: aiosqlite.Connection, data: ProductCreate) -> ProductOut:
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    cur = await conn.execute(
        "INSERT INTO products (category_id, shop_id, model, attributes, tags, qdrant_sync, created_at, updated_at) VALUES (?,?,?,?,?,0,?,?)",
        (data.category_id, data.shop_id, data.model, data.attributes, data.tags, now, now),
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
    category_id: str | None = None,
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
    if category_id:
        conditions.append("category_id = ?")
        params.append(category_id)
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
    conn: aiosqlite.Connection, category_id: str, shop_id: str, rows: list[ProductImportRow], overwrite: bool = False
) -> tuple[int, list[str]]:
    success = 0
    errors: list[str] = []
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    for i, row in enumerate(rows, 1):
        try:
            if overwrite:
                await conn.execute(
                    """
                    INSERT INTO products (category_id, shop_id, model, attributes, tags, qdrant_sync, created_at, updated_at)
                    VALUES (?,?,?,?,?,0,?,?)
                    ON CONFLICT(category_id, model, shop_id) DO UPDATE SET
                        attributes=excluded.attributes, tags=excluded.tags, qdrant_sync=0, updated_at=excluded.updated_at
                    """,
                    (category_id, shop_id, row.model, row.attributes, row.tags, now, now),
                )
            else:
                await conn.execute(
                    "INSERT OR IGNORE INTO products (category_id, shop_id, model, attributes, tags, qdrant_sync, created_at, updated_at) VALUES (?,?,?,?,?,0,?,?)",
                    (category_id, shop_id, row.model, row.attributes, row.tags, now, now),
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
        "INSERT INTO knowledge_entries (category_id, shop_id, category, code, title, content, status, qdrant_sync, created_at, updated_at) VALUES (?,?,?,?,?,?,1,0,?,?)",
        (data.category_id, data.shop_id, data.category, data.code, data.title, data.content, now, now),
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
    category_id: str | None = None,
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
    if category_id:
        conditions.append("category_id = ?")
        params.append(category_id)
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


# ── MD 文件管理 ───────────────────────────────────────────────────────────────


def _row_to_knowledge_file(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "category_id": row["category_id"],
        "shop_id": row["shop_id"],
        "filename": row["filename"],
        "chunk_count": row["chunk_count"],
        "total_chars": row["total_chars"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def list_knowledge_files(
    conn: aiosqlite.Connection,
    shop_id: str | None = None,
    category_id: str | None = None,
) -> list[dict]:
    """获取文件列表，支持按分类/店铺过滤。"""
    conditions = ["status != -1"]
    params: list = []
    if shop_id:
        conditions.append("shop_id = ?")
        params.append(shop_id)
    if category_id:
        conditions.append("category_id = ?")
        params.append(category_id)
    where = "WHERE " + " AND ".join(conditions)
    async with conn.execute(
        f"SELECT * FROM knowledge_files {where} ORDER BY created_at DESC",
        params,
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_knowledge_file(r) for r in rows]


async def get_knowledge_file(conn: aiosqlite.Connection, file_id: int) -> dict | None:
    """获取单个文件（含 raw_content）。"""
    async with conn.execute("SELECT * FROM knowledge_files WHERE id = ?", (file_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return dict(row)


# ── Qdrant 同步 ────────────────────────────────────────────────────────────────


def _infer_category_from_path_parts(parts: tuple[str, ...]) -> str:
    """从文件相对路径 parts 元组推断分类标签。取第一层目录作为分类。"""
    if len(parts) >= 2:
        # 直接使用第一层目录名作为分类标签
        return parts[0]
    return ""


async def _sync_file_chunks_to_qdrant(
    category_id: str,
    shop_id: str,
    filename: str,
    chunks: list[str],
    category: str = "",
) -> int:
    """将分块文本嵌入并写入 Qdrant category 和 shop 双层 Collection。返回写入的 chunk 数量。"""
    from qdrant_client.models import Distance, PointStruct, VectorParams

    from src.config.settings import get_config

    cfg = get_config()
    vector_size = 512

    qdrant_client = __import__("qdrant_client", fromlist=["QdrantClient"]).QdrantClient(
        host=cfg.qdrant.host, port=cfg.qdrant.port, timeout=cfg.qdrant.timeout
    )

    for collection in [f"collection_{category_id}", f"collection_{shop_id}"]:
        try:
            qdrant_client.get_collection(collection)
        except Exception:
            qdrant_client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

    model_path = cfg.embedding.model_path
    is_api = not (model_path.startswith("models/") or model_path.startswith("./") or model_path.startswith("/"))

    if is_api:
        import openai
        client = openai.OpenAI(api_key=cfg.llm.api_key, base_url=cfg.llm.base_url)
        vectors = []
        for chunk in chunks:
            resp = client.embeddings.create(model=model_path, input=chunk)
            vectors.append(resp.data[0].embedding)
    else:
        model = get_embedding_model(model_path)
        arr = model.encode(chunks, batch_size=32, show_progress_bar=False)
        vectors = arr.tolist()

    for collection in [f"collection_{category_id}", f"collection_{shop_id}"]:
        points = []
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            chunk_id = f"{filename}#p{i+1}"
            point_id = int(hashlib.md5(chunk_id.encode()).hexdigest()[:8], 16)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vec,
                    payload={
                        "chunk_id": chunk_id,
                        "content": chunk,
                        "source_file": filename,
                        "category_id": category_id,
                        "shop_id": shop_id,
                        "tags": [],
                        "backlinks": [],
                        **({"category": category} if category else {}),
                    },
                )
            )
        await qdrant_client.upsert(collection_name=collection, points=points)

    return len(chunks)


async def _delete_file_chunks_from_qdrant(category_id: str, shop_id: str, filename: str) -> None:
    """从 Qdrant 删除指定文件在 category 和 shop Collection 中的所有向量点。"""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from src.config.settings import get_config

    cfg = get_config()

    qdrant_client = __import__("qdrant_client", fromlist=["QdrantClient"]).QdrantClient(
        host=cfg.qdrant.host, port=cfg.qdrant.port, timeout=cfg.qdrant.timeout
    )

    for collection in [f"collection_{category_id}", f"collection_{shop_id}"]:
        await qdrant_client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="source_file", match=MatchValue(value=filename))]
            ),
        )


async def create_knowledge_file(
    conn: aiosqlite.Connection,
    category_id: str,
    shop_id: str,
    filename: str,
    raw_content: str,
    chunks: list[str],
    category: str = "",
) -> dict:
    """创建文件记录并解析分块存入 knowledge_entries，同步到 Qdrant category+shop 双层。"""
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    # 若未提供 category，尝试从文件名推断（取第一层目录）
    if not category:
        parts = Path(filename).parts
        category = _infer_category_from_path_parts(parts)
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

    cur = await conn.execute(
        """
        INSERT INTO knowledge_files (category_id, shop_id, filename, raw_content, chunk_count, total_chars, status, qdrant_sync, created_at, updated_at)
        VALUES (?,?,?,?,?,?,1,0,?,?)
        """,
        (category_id, shop_id, filename, raw_content, len(chunks), len(raw_content), now, now),
    )
    file_id = cur.lastrowid

    for i, chunk in enumerate(chunks):
        title = chunk.split("\n")[0][:50] if chunk else f"段落 {i+1}"
        await conn.execute(
            """
            INSERT INTO knowledge_entries (category_id, shop_id, category, code, title, content, status, qdrant_sync, created_at, updated_at)
            VALUES (?,?,?,?,?,?,1,0,?,?)
            """,
            (category_id, shop_id, category, filename, title, chunk, now, now),
        )

    await conn.commit()

    try:
        await _sync_file_chunks_to_qdrant(category_id, shop_id, filename, chunks, category)
        await conn.execute("UPDATE knowledge_files SET qdrant_sync = 1 WHERE id = ?", (file_id,))
        await conn.commit()
    except Exception as exc:
        logging.warning("Qdrant 同步失败 file_id=%d: %s", file_id, exc)

    return await get_knowledge_file(conn, file_id)


async def update_knowledge_file(conn: aiosqlite.Connection, file_id: int, data: KnowledgeFileUpdate) -> dict | None:
    """更新文件状态。"""
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    updates = {}
    if data.status is not None:
        updates["status"] = data.status
    if not updates:
        return await get_knowledge_file(conn, file_id)
    updates["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    await conn.execute(f"UPDATE knowledge_files SET {set_clause} WHERE id = ?", list(updates.values()) + [file_id])
    await conn.commit()
    return await get_knowledge_file(conn, file_id)


async def delete_knowledge_file(conn: aiosqlite.Connection, file_id: int) -> bool:
    """软删除文件（status=-1），并从 Qdrant 删除对应向量。"""
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

    async with conn.execute("SELECT category_id, shop_id, filename FROM knowledge_files WHERE id = ?", (file_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return False
    file_info = dict(row)

    cursor = await conn.execute(
        "UPDATE knowledge_files SET status = -1, updated_at = ? WHERE id = ?",
        (now, file_id),
    )
    await conn.execute(
        "UPDATE knowledge_entries SET status = -1, updated_at = ? WHERE code = ?",
        (now, file_info["filename"]),
    )
    await conn.commit()

    try:
        await _delete_file_chunks_from_qdrant(
            file_info["category_id"], file_info["shop_id"], file_info["filename"]
        )
    except Exception as exc:
        logging.warning("Qdrant 删除失败 file_id=%d: %s", file_id, exc)

    return cursor.rowcount > 0


# ── 告警关键词 CRUD ───────────────────────────────────────────────────────────


def _row_to_escalation_keyword(row: aiosqlite.Row) -> EscalationKeywordOut:
    return EscalationKeywordOut(**dict(row))


async def list_escalation_keywords(
    conn: aiosqlite.Connection,
    category_id: str | None = None,
    shop_id: str | None = None,
) -> list[EscalationKeywordOut]:
    conditions = []
    params: list[str] = []
    if category_id:
        conditions.append("(category_id = ? OR category_id IS NULL)")
        params.append(category_id)
    if shop_id:
        conditions.append("(shop_id = ? OR shop_id = 'global')")
        params.append(shop_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    async with conn.execute(
        f"SELECT * FROM escalation_keywords {where} ORDER BY id",
        params,
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_escalation_keyword(r) for r in rows]


async def create_escalation_keyword(conn: aiosqlite.Connection, data: EscalationKeywordCreate) -> EscalationKeywordOut:
    try:
        cur = await conn.execute(
            "INSERT INTO escalation_keywords (category_id, shop_id, keyword) VALUES (?,?,?)",
            (data.category_id, data.shop_id, data.keyword),
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


async def load_escalation_keywords(
    conn: aiosqlite.Connection,
    category_id: str = "default",
    shop_id: str = "global",
) -> list[str]:
    """加载指定分类+店铺（含全局）的转人工关键词列表，用于主服务启动时初始化。"""
    async with conn.execute(
        "SELECT DISTINCT keyword FROM escalation_keywords WHERE (category_id = ? OR category_id IS NULL) AND (shop_id = ? OR shop_id = 'global')",
        (category_id, shop_id),
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows]


# ── 搪塞话术 CRUD ─────────────────────────────────────────────────────────────

async def load_decoy_phrases(conn: aiosqlite.Connection, category_id: str = "default", shop_id: str = "global") -> list[str]:
    """加载指定分类+店铺（含全局）的搪塞话术列表。"""
    async with conn.execute(
        "SELECT phrase FROM decoy_phrases_pool WHERE (category_id = ? OR category_id IS NULL) AND (shop_id = ? OR shop_id = 'global') ORDER BY id",
        (category_id, shop_id),
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows]
