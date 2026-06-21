"""管理后台 FastAPI 应用。

提供：
- 店铺配置 CRUD（/shops）
- 配置变更推送 Redis Pub/Sub（/shops/{id} PUT/DELETE 后自动推送）
- 仪表盘统计 API（/dashboard）

通过 `make dev-server` 或 `python -m admin.app` 启动（默认端口 8080）。
"""

import logging
from contextlib import asynccontextmanager
from typing import Annotated

import aiosqlite
from fastapi import Depends, FastAPI, HTTPException, Query

from admin import crud
from admin.database import get_db, init_db
from admin.schemas import (
    AlertConfigOut,
    AlertConfigUpdate,
    DashboardStats,
    LLMConfigOut,
    LLMConfigUpdate,
    ShopCreate,
    ShopOut,
    ShopUpdate,
)

logger = logging.getLogger(__name__)

# ── 应用生命周期 ───────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("管理后台数据库已初始化")
    yield


app = FastAPI(
    title="CS-Agent 管理后台",
    version="1.0.0",
    description="多平台智能客服系统管理 API",
    lifespan=lifespan,
)


# ── 依赖注入 ──────────────────────────────────────────────────────────────────


async def db_conn():
    """FastAPI 依赖：获取 aiosqlite 连接，请求结束后自动关闭。"""
    conn = await get_db()
    try:
        yield conn
    finally:
        await conn.close()


DbDep = Annotated[aiosqlite.Connection, Depends(db_conn)]


async def _notify_config_updated(shop_id: str) -> None:
    """向 Redis 推送配置变更消息（非阻塞，失败只记录日志）。"""
    try:
        import redis.asyncio as aioredis

        from src.config.settings import get_config

        cfg = get_config()
        r = aioredis.from_url(
            f"redis://{cfg.redis.host}:{cfg.redis.port}/{cfg.redis.db}",
            password=cfg.redis.password or None,
        )
        await r.publish("config_updated", shop_id)
        await r.aclose()
        logger.info("已推送配置变更通知 shop=%s", shop_id)
    except Exception as exc:
        logger.warning("配置变更推送失败（主服务将在下次请求时读取新配置）: %s", exc)


# ── 店铺 CRUD 路由 ─────────────────────────────────────────────────────────────


@app.post("/shops", response_model=ShopOut, status_code=201)
async def create_shop(data: ShopCreate, conn: DbDep):
    """创建新店铺配置。"""
    existing = await crud.get_shop(conn, data.shop_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"店铺 {data.shop_id} 已存在")
    shop = await crud.create_shop(conn, data)
    await _notify_config_updated(data.shop_id)
    return shop


@app.get("/shops", response_model=list[ShopOut])
async def list_shops(conn: DbDep):
    """列出所有店铺配置。"""
    return await crud.list_shops(conn)


@app.get("/shops/{shop_id}", response_model=ShopOut)
async def get_shop(shop_id: str, conn: DbDep):
    """按 ID 查询店铺配置。"""
    shop = await crud.get_shop(conn, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail=f"店铺 {shop_id} 不存在")
    return shop


@app.put("/shops/{shop_id}", response_model=ShopOut)
async def update_shop(shop_id: str, data: ShopUpdate, conn: DbDep):
    """更新店铺配置（部分更新）。"""
    existing = await crud.get_shop(conn, shop_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"店铺 {shop_id} 不存在")
    shop = await crud.update_shop(conn, shop_id, data)
    await _notify_config_updated(shop_id)
    return shop


@app.delete("/shops/{shop_id}", status_code=204)
async def delete_shop(shop_id: str, conn: DbDep):
    """删除店铺配置。"""
    deleted = await crud.delete_shop(conn, shop_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"店铺 {shop_id} 不存在")
    await _notify_config_updated(shop_id)


# ── 告警配置路由 ───────────────────────────────────────────────────────────────


@app.get("/alert-config", response_model=AlertConfigOut)
async def get_alert_config(conn: DbDep):
    """获取当前企业微信告警配置。"""
    return await crud.get_alert_config(conn)


@app.put("/alert-config", response_model=AlertConfigOut)
async def update_alert_config(data: AlertConfigUpdate, conn: DbDep):
    """更新企业微信 Webhook 地址。"""
    result = await crud.update_alert_config(conn, data)
    await _notify_config_updated("__alert_config__")
    return result


# ── LLM 配置路由 ───────────────────────────────────────────────────────────────


@app.get("/llm-config", response_model=LLMConfigOut)
async def get_llm_config(conn: DbDep):
    """获取当前 LLM 配置。"""
    return await crud.get_llm_config(conn)


@app.put("/llm-config", response_model=LLMConfigOut)
async def update_llm_config(data: LLMConfigUpdate, conn: DbDep):
    """更新 LLM 配置（部分更新，变更后主服务热重载时生效）。"""
    result = await crud.update_llm_config(conn, data)
    await _notify_config_updated("__llm_config__")
    return result


# ── 仪表盘统计 ─────────────────────────────────────────────────────────────────


@app.get("/dashboard", response_model=list[DashboardStats])
async def get_dashboard(
    conn: DbDep,
    shop_id: str | None = Query(default=None, description="按店铺过滤"),
    date: str | None = Query(default=None, description="日期 YYYY-MM-DD，默认今日"),
):
    """查询各店铺今日统计数据。"""
    return await crud.get_dashboard_stats(conn, shop_id=shop_id, stat_date=date)


# ── 健康检查 ──────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── 启动入口 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("admin.app:app", host="0.0.0.0", port=8080, reload=True)
