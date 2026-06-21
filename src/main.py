"""客服系统主入口。

初始化所有依赖，启动所有平台网关监听器与调度器，直到收到中断信号。

运行方式:
    conda activate knowledge_qa
    python -m src.main
"""

import asyncio
import signal
from pathlib import Path

from src.actions.alert_human import AlertService
from src.actions.send_message import send_reply
from src.actions.writeback import WritebackService
from src.config.hot_reload import start_config_watcher
from src.config.settings import init_config
from src.contracts import LLMRequest, Platform
from src.gateway.douyin import DouyinGateway
from src.gateway.jd import JDGateway
from src.gateway.pinduoduo import PinduoduoGateway
from src.gateway.registry import gateway_registry
from src.gateway.taobao import TaobaoGateway
from src.llm.client import LLMClient
from src.retrieval.faq_cache import FaqCache
from src.retrieval.query_enhancer import QueryEnhancer
from src.retrieval.retriever import Retriever
from src.scheduler.dispatcher import SessionScheduler
from src.scheduler.session_store import SessionStore
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

# ── 全局中断标志 ───────────────────────────────────────────────────────────────
_shutdown = asyncio.Event()


def _handle_signal(sig):
    logger.info("收到信号 %s，开始优雅关闭…", sig)
    _shutdown.set()


async def _run_gateway_listener(gateway, shop_config, scheduler):
    """持续监听单个平台单个店铺的消息，投入调度队列。"""
    try:
        async for msg in gateway.listen(shop_config):
            await scheduler.enqueue(msg)
            if _shutdown.is_set():
                break
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error(
            "网关监听异常 shop=%s platform=%s: %s",
            shop_config.shop_id,
            shop_config.platform,
            exc,
        )


async def main() -> None:
    """主协程：初始化所有组件并启动服务。"""
    # ── 配置初始化（YAML 全局参数 + SQLite 店铺配置）──────────────────────────
    config = await init_config()
    setup_logging(
        level=config.logging.level,
        log_dir=Path(config.logging.log_dir),
    )
    logger.info("客服系统启动，共 %d 个店铺", len(config.shops))

    # ── Redis 客户端 ────────────────────────────────────────────────────────────
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(
        f"redis://{config.redis.host}:{config.redis.port}/{config.redis.db}",
        password=config.redis.password or None,
        encoding="utf-8",
        decode_responses=True,
    )

    # ── Qdrant 客户端 ───────────────────────────────────────────────────────────
    from qdrant_client import AsyncQdrantClient

    qdrant_client = AsyncQdrantClient(
        host=config.qdrant.host,
        port=config.qdrant.port,
    )

    # ── 配置热更新 ──────────────────────────────────────────────────────────────
    asyncio.create_task(start_config_watcher(redis_client))

    # ── FAQ 缓存、检索器、LLM 客户端 ─────────────────────────────────────────
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
    writeback_service = WritebackService(vault_base_path=Path("data/obsidian"))

    # ── 网关注册 ────────────────────────────────────────────────────────────────
    gateway_registry.register(Platform.TAOBAO, TaobaoGateway(redis_client=redis_client))
    gateway_registry.register(Platform.PINDUODUO, PinduoduoGateway(redis_client=redis_client))
    gateway_registry.register(Platform.JD, JDGateway(redis_client=redis_client))
    gateway_registry.register(Platform.DOUYIN, DouyinGateway(redis_client=redis_client))

    # ── 调度层依赖注入 ──────────────────────────────────────────────────────────
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
        await alert_service.notify(ctx)

    async def writeback_fn(task):
        await writeback_service.enqueue(task)

    scheduler = SessionScheduler(
        config=config,
        session_store=session_store,
        retrieve_fn=retrieve_fn,
        llm_fn=llm_fn,
        send_fn=send_fn,
        escalate_fn=escalate_fn,
        writeback_fn=writeback_fn,
    )

    # ── 启动回写后台 worker ─────────────────────────────────────────────────────
    writeback_task = asyncio.create_task(writeback_service.run())

    # ── 启动调度器 ──────────────────────────────────────────────────────────────
    scheduler_task = asyncio.create_task(scheduler.run())

    # ── 为各店铺启动网关监听任务 ─────────────────────────────────────────────
    listener_tasks = []
    for shop in config.shops:
        gateway = gateway_registry.get(shop.platform)
        task = asyncio.create_task(
            _run_gateway_listener(gateway, shop, scheduler),
            name=f"listener-{shop.shop_id}",
        )
        listener_tasks.append(task)
    logger.info("所有网关监听器已启动，等待消息…")

    # ── 等待关闭信号 ────────────────────────────────────────────────────────────
    await _shutdown.wait()

    logger.info("开始优雅关闭…")
    for task in listener_tasks:
        task.cancel()
    scheduler_task.cancel()
    writeback_task.cancel()

    await asyncio.gather(*listener_tasks, scheduler_task, writeback_task, return_exceptions=True)
    await redis_client.aclose()
    logger.info("客服系统已停止")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s))

    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
