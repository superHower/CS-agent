"""客服系统主入口。

初始化所有依赖，启动统一 FastAPI 服务（0.0.0.0:8080），包含：
- POST /api/message   影刀 RPA 消息接入
- /shops /alert-config /llm-config /dashboard  管理后台
- GET /health         健康检查

运行方式:
    conda activate knowledge_qa
    python -m src.main
"""

import asyncio
import signal
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from src.actions.alert_human import AlertService
from src.actions.send_message import send_reply
from src.config.hot_reload import start_config_watcher
from src.config.settings import init_config
from src.contracts import LLMRequest, Platform
from src.gateway.registry import gateway_registry
from src.gateway.rpa import RpaGateway
from src.llm.client import LLMClient
from src.retrieval.faq_cache import FaqCache
from src.retrieval.query_enhancer import QueryEnhancer
from src.retrieval.retriever import Retriever
from src.scheduler.dispatcher import SessionScheduler
from src.scheduler.session_store import SessionStore
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

_shutdown = asyncio.Event()


def _handle_signal(sig):
    logger.info("收到信号 %s，开始优雅关闭…", sig)
    _shutdown.set()


async def _run_gateway_listener(gateway, shop_config, scheduler):
    """持续监听单个店铺的 RPA 消息，投入调度队列。"""
    try:
        async for msg in gateway.listen(shop_config):
            await scheduler.enqueue(msg)
            if _shutdown.is_set():
                break
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("网关监听异常 shop=%s: %s", shop_config.shop_id, exc)


# ── 应用工厂 ──────────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """创建并返回配置好的 FastAPI 应用。"""

    _bg_tasks: list[asyncio.Task] = []
    _state: dict = {}  # 存储跨 lifespan 共享对象

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ── 配置初始化 ────────────────────────────────────────────────────────
        config = await init_config()
        setup_logging(level=config.logging.level, log_dir=Path(config.logging.dir))
        logger.info("客服系统启动，共 %d 个店铺", len(config.shops))

        # ── 数据库初始化 ──────────────────────────────────────────────────────
        from admin.database import init_db

        await init_db()
        logger.info("管理后台数据库已初始化")

        # ── Redis 客户端 ──────────────────────────────────────────────────────
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(
            f"redis://{config.redis.host}:{config.redis.port}/{config.redis.db}",
            password=config.redis.password or None,
            encoding="utf-8",
            decode_responses=True,
        )

        # ── Qdrant 客户端 ─────────────────────────────────────────────────────
        from qdrant_client import AsyncQdrantClient

        qdrant_client = AsyncQdrantClient(host=config.qdrant.host, port=config.qdrant.port)

        # ── 配置热更新 ────────────────────────────────────────────────────────
        _bg_tasks.append(asyncio.create_task(start_config_watcher()))

        # ── FAQ 缓存、检索器、LLM 客户端 ──────────────────────────────────────
        faq_cache = FaqCache(redis_client=redis_client)
        query_enhancer = QueryEnhancer.from_yaml(Path("config/product_dict.yaml"))
        retriever = Retriever(
            faq_cache=faq_cache,
            qdrant_client=qdrant_client,
            query_enhancer=query_enhancer,
            model_path=config.embedding.model_path,
        )
        llm_client = LLMClient.from_config(config.llm)
        alert_service = AlertService.from_config(config.alert)

        # ── RPA 网关 ──────────────────────────────────────────────────────────
        rpa_gateway = RpaGateway(redis_client=redis_client)
        _state["rpa_gateway"] = rpa_gateway

        for platform in Platform:
            gateway_registry.register(platform, rpa_gateway)

        # ── 调度层依赖注入 ────────────────────────────────────────────────────
        session_store = SessionStore(redis_client=redis_client)

        async def retrieve_fn(shop_config, question):
            return await retriever.retrieve(shop_config, question)

        async def llm_fn(request: LLMRequest):
            resp = await llm_client.generate(request)
            return resp.reply, resp.confidence

        async def send_fn(shop_config, buyer_id, content, metadata):
            return await send_reply(
                gateway_registry, shop_config, buyer_id, shop_config.platform, content, metadata
            )

        async def escalate_fn(ctx):
            shop = config.get_shop(ctx.shop_id)
            if shop is not None and ctx.message_id:
                await rpa_gateway.send(
                    shop_config=shop,
                    buyer_id=ctx.buyer_id,
                    content="",
                    metadata={"message_id": ctx.message_id, "escalated": True},
                )
            await alert_service.notify(ctx)

        # 空回写函数（保留接口但不执行实际操作）
        async def writeback_fn(task):
            logger.debug("记忆回写任务已接收: shop=%s buyer=%s", task.shop_id, task.buyer_id)

        scheduler = SessionScheduler(
            config=config,
            session_store=session_store,
            retrieve_fn=retrieve_fn,
            llm_fn=llm_fn,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
            writeback_fn=writeback_fn,
        )
        _state["scheduler"] = scheduler

        # ── 启动时加载动态关键词/搪塞话术到内存缓存 ─────────────────────────
        await scheduler.load_dynamic_config()

        # ── 启动后台任务 ──────────────────────────────────────────────────────
        _bg_tasks.append(asyncio.create_task(scheduler.run()))

        listener_keys: set[str] = set()
        _state["listener_keys"] = listener_keys
        for shop in config.shops:
            task_name = f"listener-{shop.shop_id}"
            _bg_tasks.append(
                asyncio.create_task(
                    _run_gateway_listener(rpa_gateway, shop, scheduler),
                    name=task_name,
                )
            )
            listener_keys.add(task_name)

        logger.info("所有服务已启动，监听 http://0.0.0.0:8080")

        yield

        # ── 优雅关闭 ──────────────────────────────────────────────────────────
        logger.info("开始优雅关闭…")
        _shutdown.set()
        for task in _bg_tasks:
            task.cancel()
        await asyncio.gather(*_bg_tasks, return_exceptions=True)
        await redis_client.aclose()
        logger.info("客服系统已停止")

    app = FastAPI(
        title="CS-Agent",
        version="1.0.0",
        description="多平台智能客服系统",
        lifespan=lifespan,
    )

    # ── /api/message 路由（通过 _state 延迟拿 gateway 实例）────────────────────
    from src.gateway.rpa import RpaMessageRequest, RpaMessageResponse, RpaMessageDebugResponse, RpaMessageDebugStep
    from src.utils.trace import DebugContext
    from fastapi import HTTPException

    @app.post("/api/message", response_model=RpaMessageDebugResponse)
    async def api_message(body: RpaMessageRequest) -> RpaMessageDebugResponse:
        gw: RpaGateway = _state.get("rpa_gateway")
        scheduler_inst = _state.get("scheduler")
        if gw is None or scheduler_inst is None:
            raise HTTPException(status_code=503, detail="服务尚未就绪")

        # 若该店铺还没有 listener，动态启动一个
        # 优先用 body.shop_id；否则用 body.shop 走 /shops/resolve-name 按店铺名查库
        shop_id = body.shop_id.strip()
        if not shop_id:
            from src.gateway.rpa import resolve_shop_info
            try:
                shop_id, _ = await resolve_shop_info(body.shop.strip())
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"无法解析店铺: {body.shop!r}: {exc}")
        if not shop_id:
            raise HTTPException(status_code=400, detail="缺少 shop_id 或 shop")
        listener_key = f"listener-{shop_id}"
        if listener_key not in _state.get("listener_keys", set()):
            from src.config.settings import get_config, ShopConfig
            shop_cfg = get_config().get_shop(shop_id)
            if shop_cfg is None:
                # 构造最小 ShopConfig 供 listener 使用
                from src.contracts import Platform
                platform_map = {"taobao": Platform.TAOBAO, "pinduoduo": Platform.PINDUODUO,
                                "jd": Platform.JD, "douyin": Platform.DOUYIN}
                shop_cfg = ShopConfig(
                    shop_id=shop_id,
                    platform=platform_map.get(body.platform.lower(), Platform.TAOBAO),
                    name=shop_id,
                )
            task = asyncio.create_task(
                _run_gateway_listener(gw, shop_cfg, scheduler_inst),
                name=listener_key,
            )
            _bg_tasks.append(task)
            listener_keys = _state.setdefault("listener_keys", set())
            listener_keys.add(listener_key)
            logger.info("动态启动网关监听 shop=%s", shop_id)

        # 在 API 层拦截，构造带调试信息的响应
        # 先解析出买家消息/店铺名等元信息（与 gw._handle_message 内部逻辑保持一致）
        resolved_shop_id = body.shop_id.strip() or body.shop.strip()
        resolved_shop_name = body.shop or resolved_shop_id

        # 调用处理入口
        try:
            resp, mid = await gw._handle_message(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # 获取 DebugContext（按 message_id 检索；调用后清理避免内存泄漏）
        debug_ctx = gw.get_debug_context(mid) if mid else None
        if mid:
            gw._pending_debug_ctx.pop(mid, None)
            # 清理 module-level registry（引擎写入的位置）
            from src.utils.trace import consume_debug_context
            consume_debug_context(mid)

        # 从请求体中提取买家消息（与 _handle_message 内部解析逻辑一致）
        extracted_message = ""
        history_turns_count = 0
        if body.chatList:
            from src.gateway.rpa_parser import extract_latest_buyer_message, extract_history_turns
            bubbles = [str(b) for b in body.chatList]
            extracted_message = extract_latest_buyer_message(bubbles) or ""
            history_turns = extract_history_turns(bubbles)
            history_turns_count = len(history_turns)
        elif body.history:
            from src.gateway.rpa import parse_rpa_json
            session = parse_rpa_json({"history": body.history})
            if session:
                extracted_message = session.latest_buyer_message or ""
                history_turns_count = len(session.history_turns)

        # 构造调试响应
        debug_steps: list[RpaMessageDebugStep] = []
        final_source = ""
        final_reply = resp.reply
        confidence_val: int | None = None
        confidence_threshold_val: int | None = None
        total_elapsed_ms = 0
        error_str = ""

        if debug_ctx:
            t_total_start = int(debug_ctx.created_at.timestamp() * 1000)
            for s in debug_ctx.steps:
                chunks_list: list[dict] = []
                for c in s.chunks:
                    if isinstance(c, dict):
                        chunks_list.append(c)
                    else:
                        chunks_list.append({"content": str(getattr(c, "content", c)), "score": getattr(c, "score", None)})

                debug_steps.append(RpaMessageDebugStep(
                    step=s.step,
                    label=s.label,
                    hit=s.hit,
                    reply=s.reply,
                    error=s.error,
                    elapsed_ms=s.elapsed_ms,
                    intent=s.intent,
                    entities=s.entities,
                    rewrite_query=s.rewrite_query,
                    faq_hit=s.faq_hit,
                    faq_reply=s.faq_reply,
                    chunks_count=s.chunks_count,
                    chunks=chunks_list,
                    confidence=s.confidence,
                    knowledge_chars=s.knowledge_chars,
                ))
                if s.elapsed_ms > 0:
                    total_elapsed_ms = max(total_elapsed_ms, s.elapsed_ms)

            # 从最后一步提取置信度/来源
            if debug_ctx.steps:
                last = debug_ctx.steps[-1]
                confidence_val = last.confidence
                final_reply = last.reply or resp.reply
                # 推断 final_source
                if last.step == "faq_cache":
                    final_source = "faq_cache"
                elif last.step == "llm":
                    final_source = "intent_rag"
                elif last.step == "intent" and last.hit is False:
                    final_source = "fallback"

            # 收集最后一个 error
            for s in reversed(debug_ctx.steps):
                if s.error:
                    error_str = s.error
                    break

        # 若前端请求带了 debug=true，返回扩展响应
        # 注意：始终返回 RpaMessageDebugResponse（兼容旧前端，额外字段由前端选择性使用）
        return RpaMessageDebugResponse(
            reply=resp.reply,
            escalated=resp.escalated,
            shop_id=resolved_shop_id,
            shop_name=resolved_shop_name,
            extracted_buyer=body.buyer,
            extracted_message=extracted_message,
            history_turns_count=history_turns_count,
            product_name=body.product if body.product not in ("无", "none", "") else "",
            steps=debug_steps,
            final_source=final_source,
            final_reply=final_reply,
            confidence=confidence_val,
            confidence_threshold=confidence_threshold_val,
            total_elapsed_ms=total_elapsed_ms,
            error=error_str,
        )

    # ── 健康检查 ──────────────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # ── 管理后台路由 ───────────────────────────────────────────────────────────
    from admin.app import build_router as build_admin_router

    app.include_router(build_admin_router(), prefix="/api")

    return app


# ── 启动入口 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import platform

    app = create_app()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if platform.system() != "Windows":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s))
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda s, _: _handle_signal(s))

    config = uvicorn.Config(app, host="0.0.0.0", port=8080, loop="none", log_level="info")
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())
