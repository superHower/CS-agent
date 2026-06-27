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
    from src.gateway.rpa import RpaMessageRequest, RpaMessageResponse
    from fastapi import HTTPException

    @app.post("/api/message", response_model=RpaMessageResponse)
    async def api_message(body: RpaMessageRequest) -> RpaMessageResponse:
        gw: RpaGateway = _state.get("rpa_gateway")
        scheduler_inst = _state.get("scheduler")
        if gw is None or scheduler_inst is None:
            raise HTTPException(status_code=503, detail="服务尚未就绪")

        # 若该店铺还没有 listener，动态启动一个
        shop_id = body.shop_id.strip()
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

        try:
            return await gw._handle_message(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

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
