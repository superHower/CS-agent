"""管理后台路由。

提供：
- 店铺配置 CRUD（/shops）
- 配置变更推送 Redis Pub/Sub（/shops/{id} PUT/DELETE 后自动推送）
- 仪表盘统计 API（/dashboard）

通过 build_router() 返回 APIRouter，挂载到主服务 FastAPI app。
顶层 `app` 供 `uvicorn admin.app:app` 独立启动。
"""

import io
import logging
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from admin import crud
from admin.database import get_db
from admin.schemas import (
    AlertConfigOut,
    AlertConfigUpdate,
    ConversationArchiveOut,
    DashboardStats,
    DecoyPhraseCreate,
    DecoyPhraseOut,
    EscalationKeywordCreate,
    EscalationKeywordOut,
    FaqCreate,
    FaqOut,
    FaqUpdate,
    KnowledgeEntryCreate,
    KnowledgeEntryOut,
    KnowledgeEntryUpdate,
    LLMConfigOut,
    LLMConfigUpdate,
    MessageLogOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    ShopCreate,
    ShopOut,
    ShopUpdate,
)

logger = logging.getLogger(__name__)


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


async def _reload_faq_cache(conn: aiosqlite.Connection, shop_id: str) -> None:
    """重新加载指定店铺的 FAQ 到 Redis 缓存（增删改后调用）。"""
    try:
        import redis.asyncio as aioredis

        from src.config.settings import get_config
        from src.retrieval.faq_cache import FaqCache

        cfg = get_config()
        r = aioredis.from_url(
            f"redis://{cfg.redis.host}:{cfg.redis.port}/{cfg.redis.db}",
            password=cfg.redis.password or None,
            encoding="utf-8",
            decode_responses=True,
        )
        faq_cache = FaqCache(redis_client=r)
        # 先清除该店铺旧的 FAQ 缓存
        old_keys = await r.keys(f"faq:{shop_id}:*")
        if old_keys:
            await r.delete(*old_keys)
        # 重新写入所有启用的 FAQ（含所有别名）
        pairs = await crud.load_all_faq_pairs(conn, shop_id)
        if pairs:
            await faq_cache.batch_set(shop_id, pairs)
        await r.aclose()
        logger.info("FAQ 缓存已重新加载 shop=%s 共 %d 条", shop_id, len(pairs))
    except Exception as exc:
        logger.warning("FAQ 缓存重新加载失败 shop=%s: %s", shop_id, exc)


# ── Router 构建 ───────────────────────────────────────────────────────────────


def build_router() -> APIRouter:
    """返回包含所有管理后台路由的 APIRouter。"""
    router = APIRouter()

    # ── 店铺 CRUD 路由 ─────────────────────────────────────────────────────────

    @router.post("/shops", response_model=ShopOut, status_code=201)
    async def create_shop(data: ShopCreate, conn: DbDep):
        existing = await crud.get_shop(conn, data.shop_id)
        if existing:
            raise HTTPException(status_code=409, detail=f"店铺 {data.shop_id} 已存在")
        shop = await crud.create_shop(conn, data)
        await _notify_config_updated(data.shop_id)
        return shop

    @router.get("/shops", response_model=list[ShopOut])
    async def list_shops(conn: DbDep):
        return await crud.list_shops(conn)

    @router.get("/shop-names", response_model=list[str])
    async def list_shop_names(conn: DbDep):
        """返回所有店铺名称列表，供前端下拉选择。"""
        return await crud.list_shop_names(conn)

    @router.get("/shops/resolve-name", response_model=ShopOut)
    async def resolve_shop_name(
        conn: DbDep,
        name: str = Query(..., description="店铺名称"),
        platform: str = Query(default="taobao", description="平台（新建时使用）"),
    ):
        """按名称查找店铺，不存在时自动创建并返回 shop_id。"""
        shop = await crud.get_or_create_shop_by_name(conn, name, platform)
        await _notify_config_updated(shop.shop_id)
        return shop

    @router.get("/shops/{shop_id}", response_model=ShopOut)
    async def get_shop(shop_id: str, conn: DbDep):
        shop = await crud.get_shop(conn, shop_id)
        if not shop:
            raise HTTPException(status_code=404, detail=f"店铺 {shop_id} 不存在")
        return shop

    @router.put("/shops/{shop_id}", response_model=ShopOut)
    async def update_shop(shop_id: str, data: ShopUpdate, conn: DbDep):
        existing = await crud.get_shop(conn, shop_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"店铺 {shop_id} 不存在")
        shop = await crud.update_shop(conn, shop_id, data)
        await _notify_config_updated(shop_id)
        return shop

    @router.delete("/shops/{shop_id}", status_code=204)
    async def delete_shop(shop_id: str, conn: DbDep):
        deleted = await crud.delete_shop(conn, shop_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"店铺 {shop_id} 不存在")
        await _notify_config_updated(shop_id)

    # ── 告警配置路由 ───────────────────────────────────────────────────────────

    @router.get("/alert-config", response_model=AlertConfigOut)
    async def get_alert_config(conn: DbDep):
        return await crud.get_alert_config(conn)

    @router.put("/alert-config", response_model=AlertConfigOut)
    async def update_alert_config(data: AlertConfigUpdate, conn: DbDep):
        result = await crud.update_alert_config(conn, data)
        await _notify_config_updated("__alert_config__")
        return result

    # ── LLM 配置路由 ───────────────────────────────────────────────────────────

    @router.get("/llm-config", response_model=LLMConfigOut)
    async def get_llm_config(conn: DbDep):
        return await crud.get_llm_config(conn)

    @router.put("/llm-config", response_model=LLMConfigOut)
    async def update_llm_config(data: LLMConfigUpdate, conn: DbDep):
        result = await crud.update_llm_config(conn, data)
        await _notify_config_updated("__llm_config__")
        return result

    # ── 仪表盘统计 ─────────────────────────────────────────────────────────────

    @router.get("/dashboard", response_model=list[DashboardStats])
    async def get_dashboard(
        conn: DbDep,
        shop_id: str | None = Query(default=None, description="按店铺过滤"),
        date: str | None = Query(default=None, description="日期 YYYY-MM-DD，默认今日"),
    ):
        return await crud.get_dashboard_stats(conn, shop_id=shop_id, stat_date=date)

    # ── FAQ 管理路由 ────────────────────────────────────────────────────────────

    @router.post("/faqs", response_model=FaqOut, status_code=201)
    async def create_faq(data: FaqCreate, conn: DbDep):
        try:
            faq = await crud.create_faq(conn, data)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        await _reload_faq_cache(conn, data.shop_id)
        return faq

    @router.get("/faqs", response_model=list[FaqOut])
    async def list_faqs(
        conn: DbDep,
        shop_id: str | None = Query(default=None, description="按店铺过滤"),
        category: str | None = Query(default=None, description="按分类过滤"),
        enabled_only: bool = Query(default=False, description="只返回已启用"),
    ):
        return await crud.list_faqs(conn, shop_id=shop_id, category=category, enabled_only=enabled_only)

    @router.get("/faqs/{faq_id}", response_model=FaqOut)
    async def get_faq(faq_id: int, conn: DbDep):
        faq = await crud.get_faq(conn, faq_id)
        if not faq:
            raise HTTPException(status_code=404, detail="FAQ 不存在")
        return faq

    @router.put("/faqs/{faq_id}", response_model=FaqOut)
    async def update_faq(faq_id: int, data: FaqUpdate, conn: DbDep):
        try:
            faq = await crud.update_faq(conn, faq_id, data)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        if not faq:
            raise HTTPException(status_code=404, detail="FAQ 不存在")
        await _reload_faq_cache(conn, faq.shop_id)
        return faq

    @router.delete("/faqs/{faq_id}", status_code=204)
    async def delete_faq(faq_id: int, conn: DbDep):
        faq = await crud.get_faq(conn, faq_id)
        if not faq:
            raise HTTPException(status_code=404, detail="FAQ 不存在")
        shop_id = faq.shop_id
        deleted = await crud.delete_faq(conn, faq_id)
        if deleted:
            await _reload_faq_cache(conn, shop_id)

    @router.patch("/faqs/{faq_id}/enabled", response_model=FaqOut)
    async def set_faq_enabled(
        faq_id: int,
        conn: DbDep,
        enabled: bool = Query(..., description="true=启用，false=禁用"),
    ):
        faq = await crud.set_faq_enabled(conn, faq_id, enabled)
        if not faq:
            raise HTTPException(status_code=404, detail="FAQ 不存在")
        await _reload_faq_cache(conn, faq.shop_id)
        return faq

    @router.post("/faqs/import", status_code=200)
    async def import_faqs(
        conn: DbDep,
        shop_id: str = Query(..., description="导入目标店铺 ID"),
        file: UploadFile = File(..., description="CSV 文件，列：question,answer,category,priority,aliases"),
    ):
        """CSV 批量导入 FAQ。
        列格式：question,answer,category,priority,aliases
        - aliases 列用 | 分隔多个额外问法，可为空
        """
        import csv

        content = await file.read()
        try:
            text = content.decode("utf-8-sig")  # 兼容 Excel 导出的 BOM
        except UnicodeDecodeError:
            text = content.decode("gbk", errors="replace")

        reader = csv.DictReader(io.StringIO(text))
        rows = []
        parse_errors = []
        for i, row in enumerate(reader, 1):
            try:
                from admin.schemas import FaqImportRow
                rows.append(FaqImportRow(**{k.strip(): v.strip() for k, v in row.items()}))
            except Exception as exc:
                parse_errors.append(f"第{i}行解析失败：{exc}")

        success, import_errors = await crud.import_faqs(conn, shop_id, rows)
        if success > 0:
            await _reload_faq_cache(conn, shop_id)

        return {
            "success": success,
            "total": len(rows),
            "errors": parse_errors + import_errors,
        }

    @router.get("/faqs/template/csv")
    async def download_faq_template():
        """下载 FAQ CSV 导入模板。"""
        csv_content = "question,answer,category,priority,aliases\n"
        csv_content += "发货时间是多久,一般3-5个工作日内发货,发货,10,几天发货|多久发|什么时候发货\n"
        csv_content += "支持退货吗,支持7天无理由退货,退款,10,能退吗|退货政策\n"
        return StreamingResponse(
            io.BytesIO(csv_content.encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=faq_template.csv"},
        )

    # ── 产品管理路由 ────────────────────────────────────────────────────────────

    @router.post("/products", response_model=ProductOut, status_code=201)
    async def create_product(data: ProductCreate, conn: DbDep):
        try:
            return await crud.create_product(conn, data)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @router.get("/products", response_model=dict)
    async def list_products(
        conn: DbDep,
        shop_id: str | None = Query(default=None),
        search: str | None = Query(default=None, description="按型号或标签搜索"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ):
        items, total = await crud.list_products(conn, shop_id=shop_id, search=search, page=page, page_size=page_size)
        return {"total": total, "page": page, "page_size": page_size, "items": [i.model_dump() for i in items]}

    @router.get("/products/{product_id}", response_model=ProductOut)
    async def get_product(product_id: int, conn: DbDep):
        p = await crud.get_product(conn, product_id)
        if not p:
            raise HTTPException(status_code=404, detail="产品不存在")
        return p

    @router.put("/products/{product_id}", response_model=ProductOut)
    async def update_product(product_id: int, data: ProductUpdate, conn: DbDep):
        p = await crud.update_product(conn, product_id, data)
        if not p:
            raise HTTPException(status_code=404, detail="产品不存在")
        return p

    @router.delete("/products/{product_id}", status_code=204)
    async def delete_product(product_id: int, conn: DbDep):
        deleted = await crud.delete_product(conn, product_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="产品不存在")

    @router.post("/products/import", status_code=200)
    async def import_products(
        conn: DbDep,
        shop_id: str = Query(default="global", description="目标店铺 ID"),
        overwrite: bool = Query(default=False, description="相同型号是否覆盖"),
        file: UploadFile = File(..., description="CSV 文件，列：model,attributes,tags"),
    ):
        """CSV 批量导入产品。列格式：model,attributes,tags"""
        import csv
        from admin.schemas import ProductImportRow

        content = await file.read()
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("gbk", errors="replace")

        reader = csv.DictReader(io.StringIO(text))
        rows = []
        parse_errors = []
        for i, row in enumerate(reader, 1):
            try:
                rows.append(ProductImportRow(**{k.strip(): v.strip() for k, v in row.items()}))
            except Exception as exc:
                parse_errors.append(f"第{i}行解析失败：{exc}")

        success, import_errors = await crud.import_products(conn, shop_id, rows, overwrite=overwrite)
        return {"success": success, "total": len(rows), "errors": parse_errors + import_errors}

    @router.get("/products/template/csv")
    async def download_product_template():
        """下载产品 CSV 导入模板。"""
        csv_content = "model,attributes,tags\n"
        csv_content += "XD-2401A,吸顶灯A款，适用客厅，功率36W，色温3000-6500K可调，尺寸50cm,客厅,调光\n"
        return StreamingResponse(
            io.BytesIO(csv_content.encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=product_template.csv"},
        )

    # ── 知识库路由 ──────────────────────────────────────────────────────────────

    @router.post("/knowledge", response_model=KnowledgeEntryOut, status_code=201)
    async def create_knowledge_entry(data: KnowledgeEntryCreate, conn: DbDep):
        return await crud.create_knowledge_entry(conn, data)

    @router.get("/knowledge", response_model=dict)
    async def list_knowledge_entries(
        conn: DbDep,
        shop_id: str | None = Query(default=None),
        category: str | None = Query(default=None, description="shortcut/policy/tutorial/faq_supplement"),
        search: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ):
        items, total = await crud.list_knowledge_entries(
            conn, shop_id=shop_id, category=category, search=search, page=page, page_size=page_size
        )
        return {"total": total, "page": page, "page_size": page_size, "items": [i.model_dump() for i in items]}

    @router.get("/knowledge/{entry_id}", response_model=KnowledgeEntryOut)
    async def get_knowledge_entry(entry_id: int, conn: DbDep):
        e = await crud.get_knowledge_entry(conn, entry_id)
        if not e:
            raise HTTPException(status_code=404, detail="知识条目不存在")
        return e

    @router.put("/knowledge/{entry_id}", response_model=KnowledgeEntryOut)
    async def update_knowledge_entry(entry_id: int, data: KnowledgeEntryUpdate, conn: DbDep):
        e = await crud.update_knowledge_entry(conn, entry_id, data)
        if not e:
            raise HTTPException(status_code=404, detail="知识条目不存在")
        return e

    @router.delete("/knowledge/{entry_id}", status_code=204)
    async def delete_knowledge_entry(entry_id: int, conn: DbDep):
        deleted = await crud.delete_knowledge_entry(conn, entry_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="知识条目不存在")

    # ── 告警关键词路由 ──────────────────────────────────────────────────────────

    @router.get("/escalation-keywords", response_model=list[EscalationKeywordOut])
    async def list_escalation_keywords(
        conn: DbDep,
        shop_id: str | None = Query(default=None),
    ):
        return await crud.list_escalation_keywords(conn, shop_id=shop_id)

    @router.post("/escalation-keywords", response_model=EscalationKeywordOut, status_code=201)
    async def create_escalation_keyword(data: EscalationKeywordCreate, conn: DbDep):
        try:
            return await crud.create_escalation_keyword(conn, data)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @router.delete("/escalation-keywords/{kw_id}", status_code=204)
    async def delete_escalation_keyword(kw_id: int, conn: DbDep):
        deleted = await crud.delete_escalation_keyword(conn, kw_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="关键词不存在")

    # ── 搪塞话术路由 ────────────────────────────────────────────────────────────

    @router.get("/decoy-phrases", response_model=list[DecoyPhraseOut])
    async def list_decoy_phrases(
        conn: DbDep,
        shop_id: str | None = Query(default=None),
    ):
        return await crud.list_decoy_phrases(conn, shop_id=shop_id)

    @router.post("/decoy-phrases", response_model=DecoyPhraseOut, status_code=201)
    async def create_decoy_phrase(data: DecoyPhraseCreate, conn: DbDep):
        return await crud.create_decoy_phrase(conn, data)

    @router.delete("/decoy-phrases/{phrase_id}", status_code=204)
    async def delete_decoy_phrase(phrase_id: int, conn: DbDep):
        deleted = await crud.delete_decoy_phrase(conn, phrase_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="话术不存在")

    # ── 消息日志路由 ────────────────────────────────────────────────────────────

    @router.get("/message-logs", response_model=dict)
    async def list_message_logs(
        conn: DbDep,
        shop_id: str | None = Query(default=None),
        is_escalated: bool | None = Query(default=None),
        date: str | None = Query(default=None, description="日期 YYYY-MM-DD"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ):
        items, total = await crud.list_message_logs(
            conn, shop_id=shop_id, is_escalated=is_escalated, date=date, page=page, page_size=page_size
        )
        return {"total": total, "page": page, "page_size": page_size, "items": [i.model_dump() for i in items]}

    # ── 对话归档路由 ────────────────────────────────────────────────────────────

    @router.get("/conversation-archives", response_model=dict)
    async def list_conversation_archives(
        conn: DbDep,
        shop_id: str | None = Query(default=None),
        buyer_id: str | None = Query(default=None),
        date_from: str | None = Query(default=None, description="开始日期 YYYY-MM-DD"),
        date_to: str | None = Query(default=None, description="结束日期 YYYY-MM-DD"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ):
        items, total = await crud.list_conversation_archives(
            conn, shop_id=shop_id, buyer_id=buyer_id, date_from=date_from, date_to=date_to,
            page=page, page_size=page_size,
        )
        return {"total": total, "page": page, "page_size": page_size, "items": [i.model_dump() for i in items]}

    @router.get("/health")
    async def health():
        return {"status": "ok"}

    # ── 消息调试路由 ─────────────────────────────────────────────────────────────

    @router.post("/debug/message")
    async def debug_message(body: dict, conn: DbDep):
        """执行完整消息处理 pipeline 并返回每步骤的调试信息。

        请求体（直接传 RPA history 条目）：
          {
            "platform": "抖音",
            "shop": "艾睿斯旗舰店",
            "buyer": "买家昵称",
            "product": "商品名或无",
            "chatList": ["气泡1", "气泡2"],
            "detail": "无"
          }
        """
        import time as _time

        from src.config.settings import get_config
        from src.gateway.rpa_parser import (
            extract_history_turns,
            extract_latest_buyer_message,
            parse_rpa_json,
        )
        from src.matching.engine import MatchEngine, MatchRequest

        # 直接从 body 读取 shop 和 platform（扁平格式）
        history_item = body
        shop_name = str(body.get("shop", ""))
        platform_raw = str(body.get("platform", "taobao"))

        if not shop_name:
            raise HTTPException(status_code=400, detail="shop 字段必填")
        if not body.get("chatList"):
            raise HTTPException(status_code=400, detail="chatList 字段必填")

        # 中文平台名 → 英文（供数据库存储用）
        _CN_TO_EN = {"淘宝": "taobao", "拼多多": "pinduoduo", "京东": "jd", "抖音": "douyin"}
        platform = _CN_TO_EN.get(platform_raw, platform_raw.lower())

        # 解析/创建店铺
        shop_out = await crud.get_or_create_shop_by_name(conn, shop_name, platform)
        shop_id = shop_out.shop_id
        await _notify_config_updated(shop_id)

        # 解析 history_item -> 最新买家消息
        session = parse_rpa_json({"history": [history_item]})
        if session is None:
            raise HTTPException(status_code=400, detail="history_item 格式无效")

        latest_msg = session.latest_buyer_message
        history_turns = session.history_turns

        if not latest_msg:
            raise HTTPException(status_code=400, detail="无法从 chatList 提取买家消息")

        cfg = get_config()
        shop_config = cfg.get_shop(shop_id)
        if shop_config is None:
            # 构建一个临时 ShopConfig
            from src.config.settings import ShopConfig
            shop_config = ShopConfig(
                shop_id=shop_id,
                platform=platform,
                name=shop_name,
                confidence_threshold=shop_out.confidence_threshold,
            )

        debug_info: dict = {
            "shop_id": shop_id,
            "shop_name": shop_name,
            "extracted_buyer": session.buyer,
            "extracted_message": latest_msg,
            "history_turns_count": len(history_turns),
            "product_name": session.product,
            "steps": [],
        }

        t_total = _time.time()

        # Step 1: FAQ 缓存检查
        try:
            import redis.asyncio as aioredis
            from src.retrieval.faq_cache import FaqCache

            r = aioredis.from_url(
                f"redis://{cfg.redis.host}:{cfg.redis.port}/{cfg.redis.db}",
                password=cfg.redis.password or None,
                encoding="utf-8",
                decode_responses=True,
            )
            faq_cache = FaqCache(redis_client=r)
            t0 = _time.time()
            faq_reply = await faq_cache.get(shop_id, latest_msg)
            await r.aclose()
            faq_elapsed = int((_time.time() - t0) * 1000)

            if faq_reply:
                debug_info["steps"].append({
                    "step": "faq_cache",
                    "label": "FAQ 缓存",
                    "hit": True,
                    "reply": faq_reply,
                    "elapsed_ms": faq_elapsed,
                })
                debug_info["final_source"] = "faq_cache"
                debug_info["final_reply"] = faq_reply
                debug_info["escalated"] = False
                debug_info["confidence"] = 100
                debug_info["total_elapsed_ms"] = int((_time.time() - t_total) * 1000)
                return debug_info
            else:
                debug_info["steps"].append({
                    "step": "faq_cache",
                    "label": "FAQ 缓存",
                    "hit": False,
                    "elapsed_ms": faq_elapsed,
                })
        except Exception as exc:
            debug_info["steps"].append({
                "step": "faq_cache",
                "label": "FAQ 缓存",
                "hit": False,
                "error": str(exc),
                "elapsed_ms": 0,
            })

        # Step 2: 意图识别
        history_dicts = [{"role": t.role, "content": t.content} for t in history_turns]
        match_req = MatchRequest(
            user_msg=latest_msg,
            product_name=session.product,
            order_detail=session.detail,
            history=history_dicts,
            shop_id=shop_id,
        )

        # 初始化检索器和LLM客户端
        try:
            import redis.asyncio as aioredis
            from pathlib import Path
            from qdrant_client import AsyncQdrantClient
            from src.retrieval.faq_cache import FaqCache
            from src.retrieval.query_enhancer import QueryEnhancer
            from src.retrieval.retriever import Retriever, ShortcutPhraseIndex
            from src.llm.client import LLMClient

            r2 = aioredis.from_url(
                f"redis://{cfg.redis.host}:{cfg.redis.port}/{cfg.redis.db}",
                password=cfg.redis.password or None,
                encoding="utf-8",
                decode_responses=True,
            )
            faq_cache2 = FaqCache(redis_client=r2)
            qdrant_client = AsyncQdrantClient(host=cfg.qdrant.host, port=cfg.qdrant.port)
            query_enhancer = QueryEnhancer.from_yaml(Path("config/product_dict.yaml"))
            shortcut_idx = ShortcutPhraseIndex()
            retriever = Retriever(
                faq_cache=faq_cache2,
                qdrant_client=qdrant_client,
                query_enhancer=query_enhancer,
                model_path=cfg.embedding.model_path,
                shortcut_index=shortcut_idx,
            )
            llm_client = LLMClient.from_config(cfg.llm)
            engine = MatchEngine(retriever=retriever, llm_client=llm_client)
        except Exception as exc2:
            debug_info["error"] = f"引擎初始化失败: {exc2}"
            debug_info["total_elapsed_ms"] = int((_time.time() - t_total) * 1000)
            return debug_info

        intent_result = None
        rewrite_query = latest_msg
        try:
            t0 = _time.time()
            intent_result = await engine._recognize_intent(match_req)
            intent_elapsed = int((_time.time() - t0) * 1000)
            rewrite_query = intent_result.rewrite_query or latest_msg

            debug_info["steps"].append({
                "step": "intent",
                "label": "意图识别",
                "intent": intent_result.intent,
                "entities": intent_result.entities,
                "rewrite_query": rewrite_query,
                "elapsed_ms": intent_elapsed,
            })
        except Exception as exc:
            debug_info["steps"].append({
                "step": "intent",
                "label": "意图识别",
                "error": str(exc),
                "elapsed_ms": 0,
            })

        # Step 3: RAG 向量检索
        try:
            t0 = _time.time()
            retrieval = await retriever.retrieve(shop_config, rewrite_query)
            retrieval_elapsed = int((_time.time() - t0) * 1000)

            chunks_info = [
                {"content": c.content[:200], "score": getattr(c, "score", None)}
                for c in retrieval.chunks
            ]
            debug_info["steps"].append({
                "step": "rag",
                "label": "RAG 向量检索",
                "faq_hit": retrieval.faq_hit,
                "faq_reply": retrieval.faq_reply if retrieval.faq_hit else None,
                "chunks_count": len(retrieval.chunks),
                "chunks": chunks_info,
                "elapsed_ms": retrieval_elapsed,
            })
        except Exception as exc:
            debug_info["steps"].append({
                "step": "rag",
                "label": "RAG 向量检索",
                "error": str(exc),
                "elapsed_ms": 0,
            })
            debug_info["total_elapsed_ms"] = int((_time.time() - t_total) * 1000)
            try:
                await r2.aclose()
            except Exception:
                pass
            return debug_info

        # Step 4: LLM 生成回复
        try:
            from src.contracts.models import LLMRequest, TurnRecord
            import datetime

            knowledge_text = "\n".join(c.content for c in retrieval.chunks)
            history_turn_records = []
            for h in history_dicts[-6:]:
                try:
                    history_turn_records.append(TurnRecord(
                        role=h["role"],
                        content=h["content"],
                        timestamp=datetime.datetime.now(datetime.timezone.utc),
                    ))
                except Exception:
                    pass

            llm_req = LLMRequest(
                shop_id=shop_id,
                shop_name=shop_name,
                buyer_message=latest_msg,
                history=history_turn_records,
                knowledge=knowledge_text,
            )

            t0 = _time.time()
            response = await llm_client.generate(llm_req)
            llm_elapsed = int((_time.time() - t0) * 1000)

            debug_info["steps"].append({
                "step": "llm",
                "label": "LLM 生成",
                "reply": response.reply,
                "confidence": response.confidence,
                "knowledge_chars": len(knowledge_text),
                "elapsed_ms": llm_elapsed,
            })

            needs_escalation = response.confidence < shop_config.confidence_threshold
            debug_info["final_source"] = "intent_rag"
            debug_info["final_reply"] = response.reply
            debug_info["escalated"] = needs_escalation
            debug_info["confidence"] = response.confidence
            debug_info["confidence_threshold"] = shop_config.confidence_threshold
        except Exception as exc:
            debug_info["steps"].append({
                "step": "llm",
                "label": "LLM 生成",
                "error": str(exc),
                "elapsed_ms": 0,
            })
            debug_info["escalated"] = True
            debug_info["final_reply"] = ""

        debug_info["total_elapsed_ms"] = int((_time.time() - t_total) * 1000)
        try:
            await r2.aclose()
        except Exception:
            pass
        return debug_info

    return router


# ── 独立启动入口（uvicorn admin.app:app）────────────────────────────────────────

app = FastAPI(title="CS-Agent 管理后台", version="1.0.0")
# 路由直接挂根路径（测试和 uvicorn 直接启动时均无需 /api 前缀）
app.include_router(build_router())
