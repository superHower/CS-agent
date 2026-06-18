"""店铺配置 CRUD 操作与统计查询。"""

import logging
from datetime import UTC, datetime

import aiosqlite

from admin.schemas import DashboardStats, ShopCreate, ShopOut, ShopUpdate

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
