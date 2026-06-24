"""全链路集成测试。

使用完整的 Mock 链路验证：
- FAQ 命中直接回复
- LLM 高置信度自动回复
- 低置信度转人工
- 敏感词硬转人工
- 40 店铺并发无串话
- Redis 不可用降级

不依赖任何真实外部服务。
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.contracts import (
    EscalationReason,
    MessageSource,
    Platform,
    RetrievalResult,
    LLMRequest,
    LLMResponse,
    StandardMessage,
    SessionState,
)
from src.config.settings import Config, ShopConfig, RedisConfig, QdrantConfig
from src.config.settings import EmbeddingConfig, LLMConfig, ThresholdsConfig, AlertConfig, LoggingConfig
from src.scheduler.dispatcher import SessionScheduler
from src.scheduler.session_store import SessionStore


NOW = datetime.now(tz=timezone.utc)


# ── 测试辅助 ──────────────────────────────────────────────────────────────────

def make_config(shops=None) -> Config:
    if shops is None:
        shops = [make_shop_config()]
    cfg = MagicMock(spec=Config)
    cfg.shops = shops
    cfg.escalation_keywords = ["投诉", "12315", "差评", "假货"]
    cfg.greeting_patterns = ["在吗", "你好", "hello"]
    cfg.thresholds = MagicMock()
    cfg.thresholds.default_confidence = 85
    shop_map = {s.shop_id: s for s in shops}
    cfg.get_shop = MagicMock(side_effect=lambda sid: shop_map.get(sid))
    return cfg


def make_shop_config(shop_id="tb_test_001", platform=Platform.TAOBAO) -> ShopConfig:
    return ShopConfig(
        shop_id=shop_id,
        platform=platform,
        name="测试店铺",
        obsidian_vault="data/x",
    )


def make_message(
    content="如何安装灯？",
    shop_id="tb_test_001",
    platform=Platform.TAOBAO,
    buyer_id="buyer_001",
) -> StandardMessage:
    return StandardMessage(
        shop_id=shop_id,
        platform=platform,
        buyer_id=buyer_id,
        content=content,
        timestamp=NOW,
        message_id=f"msg_{shop_id}_{buyer_id}",
        source=MessageSource.WEBHOOK,
    )


def make_active_ctx(shop_id="tb_test_001", buyer_id="buyer_001"):
    from src.contracts import SessionContext
    return SessionContext(
        shop_id=shop_id,
        buyer_id=buyer_id,
        platform=Platform.TAOBAO,
        state=SessionState.ACTIVE,
        history=[],
        current_message="",
        created_at=NOW,
        updated_at=NOW,
    )


def make_scheduler(config=None, store=None, **overrides):
    config = config or make_config()
    if store is None:
        store = AsyncMock(spec=SessionStore)
        store.load_or_create = AsyncMock(return_value=make_active_ctx())
        store.save = AsyncMock()

    defaults = dict(
        retrieve_fn=AsyncMock(return_value=RetrievalResult(
            shop_id="tb_test_001",
            query="如何安装灯？",
        )),
        llm_fn=AsyncMock(return_value=("安装请参考说明书。", 90)),
        send_fn=AsyncMock(return_value=True),
        escalate_fn=AsyncMock(),
        writeback_fn=AsyncMock(),
    )
    defaults.update(overrides)

    return SessionScheduler(
        config=config,
        session_store=store,
        **defaults,
    )


# ── 端到端场景测试 ─────────────────────────────────────────────────────────────

class TestEndToEnd:
    async def test_faq_hit_sends_reply_directly(self):
        """FAQ 命中 → 直接发送，不调用 LLM。"""
        faq_result = RetrievalResult(
            shop_id="tb_test_001",
            query="如何安装",
            faq_hit=True,
            faq_reply="安装步骤见说明书第3页。",
        )
        llm_fn = AsyncMock()
        send_fn = AsyncMock(return_value=True)

        sched = make_scheduler(
            retrieve_fn=AsyncMock(return_value=faq_result),
            llm_fn=llm_fn,
            send_fn=send_fn,
        )
        msg = make_message("如何安装？")
        await sched.dispatch(msg, make_shop_config())

        # FAQ 命中时不调用 LLM
        llm_fn.assert_not_called()
        # 发送了 FAQ 回复
        send_fn.assert_called_once()
        sent_content = send_fn.call_args[0][2]
        assert "安装步骤见说明书第3页" in sent_content

    async def test_high_confidence_sends_reply(self):
        """LLM 高置信度 → 自动发送回复。"""
        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()

        sched = make_scheduler(
            llm_fn=AsyncMock(return_value=("安装前请关闭电源。", 92)),
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        msg = make_message("安装要注意什么？")
        await sched.dispatch(msg, make_shop_config())

        send_fn.assert_called_once()
        escalate_fn.assert_not_called()

    async def test_low_confidence_escalates(self):
        """LLM 低置信度（非寒暄）→ 转人工。"""
        escalate_fn = AsyncMock()
        send_fn = AsyncMock(return_value=True)

        sched = make_scheduler(
            llm_fn=AsyncMock(return_value=("我不太确定。", 50)),
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        msg = make_message("这个产品质量怎么样？")
        await sched.dispatch(msg, make_shop_config())

        escalate_fn.assert_called_once()
        ctx_arg = escalate_fn.call_args[0][0]
        assert ctx_arg.reason == EscalationReason.LOW_CONFIDENCE

    async def test_hard_keyword_escalates_immediately(self):
        """硬转人工关键词 → 不调用检索/LLM，直接转人工。"""
        retrieve_fn = AsyncMock()
        llm_fn = AsyncMock()
        escalate_fn = AsyncMock()

        sched = make_scheduler(
            retrieve_fn=retrieve_fn,
            llm_fn=llm_fn,
            escalate_fn=escalate_fn,
        )
        msg = make_message("我要投诉你们！")
        await sched.dispatch(msg, make_shop_config())

        retrieve_fn.assert_not_called()
        llm_fn.assert_not_called()
        escalate_fn.assert_called_once()
        ctx_arg = escalate_fn.call_args[0][0]
        assert ctx_arg.reason == EscalationReason.HARD_KEYWORD
        assert "投诉" in ctx_arg.triggered_keyword

    async def test_greeting_uses_fallback_reply(self):
        """寒暄消息 → 发送安全话术，不转人工。"""
        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()

        sched = make_scheduler(
            llm_fn=AsyncMock(return_value=("您好！请问有什么可以帮您？", 40)),
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        msg = make_message("在吗")
        await sched.dispatch(msg, make_shop_config())

        send_fn.assert_called_once()
        escalate_fn.assert_not_called()

    async def test_exception_in_llm_escalates(self):
        """LLM 抛出异常 → 降级转人工，不崩溃。"""
        escalate_fn = AsyncMock()

        sched = make_scheduler(
            llm_fn=AsyncMock(side_effect=Exception("LLM 超时")),
            escalate_fn=escalate_fn,
        )
        msg = make_message("灯不亮怎么办？")
        await sched.dispatch(msg, make_shop_config())

        escalate_fn.assert_called_once()
        ctx_arg = escalate_fn.call_args[0][0]
        assert ctx_arg.reason == EscalationReason.EXCEPTION

    async def test_session_already_waiting_human_skips(self):
        """会话已转人工 → 忽略新消息。"""
        from src.contracts import SessionContext
        waiting_ctx = SessionContext(
            shop_id="tb_test_001",
            buyer_id="buyer_001",
            platform=Platform.TAOBAO,
            state=SessionState.WAITING_HUMAN,
            history=[],
            current_message="",
            created_at=NOW,
            updated_at=NOW,
        )
        store = AsyncMock(spec=SessionStore)
        store.load_or_create = AsyncMock(return_value=waiting_ctx)
        store.save = AsyncMock()
        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()

        sched = make_scheduler(store=store, send_fn=send_fn, escalate_fn=escalate_fn)
        msg = make_message("继续问题")
        await sched.dispatch(msg, make_shop_config())

        # 新行为：WAITING_HUMAN 时发安抚话术并通知告警，不静默忽略
        send_fn.assert_called_once()
        escalate_fn.assert_called_once()
        ctx_arg = escalate_fn.call_args[0][0]
        assert ctx_arg.reason == EscalationReason.REPEAT_HUMAN


# ── 40 店铺并发隔离测试 ────────────────────────────────────────────────────────

class TestMultiShopConcurrency:
    async def test_40_shops_no_cross_contamination(self):
        """40 店铺并发处理消息，各自调用 retrieve_fn 互不干扰。"""
        shops = [
            make_shop_config(shop_id=f"shop_{i:03d}", platform=Platform.TAOBAO)
            for i in range(40)
        ]
        config = make_config(shops)

        received_shop_ids = []

        async def retrieve_fn(shop_config, question):
            received_shop_ids.append(shop_config.shop_id)
            return RetrievalResult(shop_id=shop_config.shop_id, query=question)

        sched = make_scheduler(
            config=config,
            retrieve_fn=retrieve_fn,
            llm_fn=AsyncMock(return_value=("回复", 90)),
            send_fn=AsyncMock(return_value=True),
        )

        messages = [
            make_message(
                content=f"问题来自店铺{i}",
                shop_id=f"shop_{i:03d}",
                buyer_id=f"buyer_{i}",
            )
            for i in range(40)
        ]

        store = AsyncMock(spec=SessionStore)

        async def _load_ctx(msg):
            return make_active_ctx(shop_id=msg.shop_id, buyer_id=msg.buyer_id)

        store.load_or_create = AsyncMock(side_effect=_load_ctx)
        store.save = AsyncMock()
        sched._store = store

        # 并发处理所有消息
        await asyncio.gather(*[
            sched.dispatch(msg, make_shop_config(shop_id=msg.shop_id))
            for msg in messages
        ])

        # 每个店铺都有独立的 retrieve 调用
        assert len(received_shop_ids) == 40
        assert set(received_shop_ids) == {f"shop_{i:03d}" for i in range(40)}


# ── Redis 不可用降级测试 ──────────────────────────────────────────────────────

class TestRedisUnavailableDegradation:
    async def test_redis_failure_escalates_to_human(self):
        """Redis 不可用时，会话加载失败，应转人工而非崩溃。"""
        store = AsyncMock(spec=SessionStore)
        store.load_or_create = AsyncMock(side_effect=Exception("Redis 连接失败"))
        store.save = AsyncMock()

        escalate_fn = AsyncMock()

        sched = make_scheduler(store=store, escalate_fn=escalate_fn)
        msg = make_message()
        # dispatch 中 session 加载异常应触发 escalate
        await sched.dispatch(msg, make_shop_config())

        escalate_fn.assert_called_once()
        ctx_arg = escalate_fn.call_args[0][0]
        assert ctx_arg.reason == EscalationReason.EXCEPTION

    async def test_send_failure_escalates(self):
        """消息发送异常后，_handle 兜底转人工。"""
        from src.exceptions import SendFailedException
        escalate_fn = AsyncMock()

        sched = make_scheduler(
            llm_fn=AsyncMock(return_value=("回复内容", 92)),
            send_fn=AsyncMock(side_effect=SendFailedException(
                buyer_id="buyer_001", shop_id="tb_test_001"
            )),
            escalate_fn=escalate_fn,
        )
        msg = make_message()
        # _handle 包含最外层 except，会捕获 SendFailedException 并转人工
        await sched._handle(msg)

        escalate_fn.assert_called_once()
        ctx_arg = escalate_fn.call_args[0][0]
        assert ctx_arg.reason in (EscalationReason.SEND_FAILED, EscalationReason.EXCEPTION)

    async def test_system_never_crashes_on_any_exception(self):
        """任意异常均被兜底，_handle 不向外抛出。"""
        sched = make_scheduler(
            retrieve_fn=AsyncMock(side_effect=RuntimeError("意外错误")),
            escalate_fn=AsyncMock(),
        )
        msg = make_message()
        # _handle 是最外层兜底，不应抛出
        await sched._handle(msg)  # should not raise


# ── 多平台消息标准化集成测试 ──────────────────────────────────────────────────

class TestMultiPlatformIntegration:
    async def test_all_platforms_dispatch_correctly(self):
        """四个平台的消息均能正确调度，shop_id 互不干扰。"""
        platform_shops = [
            make_shop_config("taobao_001", Platform.TAOBAO),
            make_shop_config("pdd_001", Platform.PINDUODUO),
            make_shop_config("jd_001", Platform.JD),
            make_shop_config("douyin_001", Platform.DOUYIN),
        ]
        config = make_config(platform_shops)

        dispatched_shops = []

        async def retrieve_fn(shop_config, question):
            dispatched_shops.append(shop_config.shop_id)
            return RetrievalResult(shop_id=shop_config.shop_id, query=question)

        sched = make_scheduler(
            config=config,
            retrieve_fn=retrieve_fn,
            llm_fn=AsyncMock(return_value=("通用回复", 90)),
            send_fn=AsyncMock(return_value=True),
        )

        for shop in platform_shops:
            msg = make_message(
                content="测试问题",
                shop_id=shop.shop_id,
                platform=shop.platform,
                buyer_id="buyer_x",
            )
            await sched.dispatch(msg, shop)

        assert set(dispatched_shops) == {"taobao_001", "pdd_001", "jd_001", "douyin_001"}
