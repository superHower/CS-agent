"""会话调度层单元测试。

使用 Mock 替换检索层/LLM层/发送层/告警层/回写层，全部测试不依赖真实外部服务。
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import Config, ShopConfig
from src.contracts import (
    EscalationContext,
    EscalationReason,
    LLMRequest,
    MessageSource,
    Platform,
    RetrievalResult,
    SessionContext,
    SessionState,
    StandardMessage,
)
from src.scheduler.dispatcher import SessionScheduler
from src.scheduler.session_store import SessionStore

NOW = datetime.now(tz=timezone.utc)


# ── 辅助工厂 ──────────────────────────────────────────────────────────────────

def make_msg(
    content: str = "你好，请问有货吗？",
    shop_id: str = "tb_test_001",
    buyer_id: str = "buyer_001",
    message_id: str = "msg_001",
) -> StandardMessage:
    return StandardMessage(
        shop_id=shop_id,
        platform=Platform.TAOBAO,
        buyer_id=buyer_id,
        content=content,
        timestamp=NOW,
        message_id=message_id,
        source=MessageSource.TOP_API,
    )


def make_shop(shop_id: str = "tb_test_001", threshold: int = 85) -> ShopConfig:
    return ShopConfig(
        shop_id=shop_id,
        platform=Platform.TAOBAO,
        name="测试店铺",
        api_key="key",
        api_secret="secret",
        confidence_threshold=threshold,
    )


def make_config(shop_id: str = "tb_test_001", threshold: int = 85) -> Config:
    """构造一个最小化 Config，包含一个测试店铺。"""
    import yaml
    from pathlib import Path
    from src.config.settings import Config as _Config

    data = {
        "shops": [{
            "shop_id": shop_id,
            "platform": "taobao",
            "name": "测试店铺",
            "confidence_threshold": threshold,
        }]
    }
    cfg = _Config.model_validate({"shops": []})
    from src.config.settings import ShopConfig as _SC
    shops = [_SC(**s) for s in data["shops"]]
    return cfg.model_copy(update={"shops": shops})


def faq_hit_result(reply: str = "预置FAQ回复") -> RetrievalResult:
    return RetrievalResult(
        shop_id="tb_test_001",
        query="test",
        faq_hit=True,
        faq_reply=reply,
    )


def no_faq_result() -> RetrievalResult:
    return RetrievalResult(shop_id="tb_test_001", query="test")


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)  # 默认无已有会话
    redis.set = AsyncMock(return_value=True)
    redis.expire = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def session_store(mock_redis):
    return SessionStore(redis_client=mock_redis, session_ttl=7200)


def make_scheduler(
    config: Config | None = None,
    session_store: SessionStore | None = None,
    retrieve_fn=None,
    llm_fn=None,
    send_fn=None,
    escalate_fn=None,
    writeback_fn=None,
    mock_redis=None,
) -> SessionScheduler:
    if config is None:
        config = make_config()
    if session_store is None:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock(return_value=True)
        redis.expire = AsyncMock(return_value=True)
        session_store = SessionStore(redis_client=redis)

    return SessionScheduler(
        config=config,
        session_store=session_store,
        retrieve_fn=retrieve_fn or AsyncMock(return_value=no_faq_result()),
        llm_fn=llm_fn or AsyncMock(return_value=("默认回复", 90)),
        send_fn=send_fn or AsyncMock(return_value=True),
        escalate_fn=escalate_fn or AsyncMock(),
        writeback_fn=writeback_fn or AsyncMock(),
    )


# ── SessionStore 单元测试 ─────────────────────────────────────────────────────

class TestSessionStore:
    async def test_create_new_session(self, session_store, mock_redis):
        msg = make_msg()
        ctx = await session_store.load_or_create(msg)
        assert ctx.shop_id == "tb_test_001"
        assert ctx.buyer_id == "buyer_001"
        assert ctx.state == SessionState.ACTIVE
        assert ctx.history == []

    async def test_load_existing_session(self, session_store, mock_redis):
        existing = SessionContext(
            shop_id="tb_test_001",
            buyer_id="buyer_001",
            platform=Platform.TAOBAO,
            state=SessionState.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            history=[],
            last_confidence=90,
        )
        mock_redis.get = AsyncMock(return_value=existing.model_dump_json())
        msg = make_msg()
        ctx = await session_store.load_or_create(msg)
        assert ctx.last_confidence == 90
        mock_redis.expire.assert_called_once()

    async def test_save_session(self, session_store, mock_redis):
        ctx = SessionContext(
            shop_id="tb_test_001",
            buyer_id="buyer_001",
            platform=Platform.TAOBAO,
            created_at=NOW,
            updated_at=NOW,
        )
        await session_store.save(ctx)
        mock_redis.set.assert_called_once()
        key = mock_redis.set.call_args[0][0]
        assert key == "session:tb_test_001:buyer_001"

    async def test_history_trimmed_to_max_turns(self, session_store, mock_redis):
        from src.contracts import TurnRecord
        history = [TurnRecord(role="user", content=f"msg{i}", timestamp=NOW) for i in range(15)]
        ctx = SessionContext(
            shop_id="tb_test_001",
            buyer_id="buyer_001",
            platform=Platform.TAOBAO,
            history=history,
            created_at=NOW,
            updated_at=NOW,
        )
        await session_store.save(ctx)
        saved_json = mock_redis.set.call_args[0][1]
        saved_ctx = SessionContext.model_validate_json(saved_json)
        assert len(saved_ctx.history) == 10  # _MAX_HISTORY_TURNS

    async def test_redis_failure_on_load_creates_new(self, session_store, mock_redis):
        mock_redis.get = AsyncMock(side_effect=Exception("Redis 断线"))
        ctx = await session_store.load_or_create(make_msg())
        assert ctx.state == SessionState.ACTIVE
        assert ctx.history == []

    async def test_delete_session(self, session_store, mock_redis):
        await session_store.delete("tb_test_001", "buyer_001")
        # 删除会清掉主 key 和 handoff_at key（联动清理，避免遗留）
        delete_calls = [c.args[0] for c in mock_redis.delete.call_args_list]
        assert "session:tb_test_001:buyer_001" in delete_calls
        assert "session:tb_test_001:buyer_001:handoff_at" in delete_calls


# ── 状态机——FAQ 命中 ───────────────────────────────────────────────────────────

class TestDispatchFAQHit:
    async def test_faq_hit_directly_replies(self):
        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()
        retrieve_fn = AsyncMock(return_value=faq_hit_result("安装步骤见说明书第3页。"))

        scheduler = make_scheduler(
            retrieve_fn=retrieve_fn,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        msg = make_msg("如何安装？")
        shop = make_shop()
        await scheduler.dispatch(msg, shop)

        send_fn.assert_called_once()
        call_args = send_fn.call_args
        assert "安装步骤见说明书第3页" in call_args[0][2]
        escalate_fn.assert_not_called()

    async def test_faq_hit_does_not_call_llm(self):
        llm_fn = AsyncMock(return_value=("LLM回复", 95))
        retrieve_fn = AsyncMock(return_value=faq_hit_result())

        scheduler = make_scheduler(retrieve_fn=retrieve_fn, llm_fn=llm_fn)
        await scheduler.dispatch(make_msg(), make_shop())

        llm_fn.assert_not_called()


# ── 状态机——硬转人工关键词 ────────────────────────────────────────────────────

class TestDispatchHardKeyword:
    async def test_complaint_keyword_escalates(self):
        escalate_fn = AsyncMock()
        send_fn = AsyncMock(return_value=True)

        scheduler = make_scheduler(escalate_fn=escalate_fn, send_fn=send_fn)
        msg = make_msg("我要投诉你们，质量太差了！")
        await scheduler.dispatch(msg, make_shop())

        escalate_fn.assert_called_once()
        ctx: EscalationContext = escalate_fn.call_args[0][0]
        assert ctx.reason == EscalationReason.HARD_KEYWORD
        assert ctx.triggered_keyword == "投诉"
        # 新行为：命中硬关键词时发搪塞话术安抚买家
        send_fn.assert_called_once()

    async def test_all_hard_keywords_trigger_escalation(self):
        """遍历 yaml 默认所有硬关键词，验证都能触发转人工。
        修复：每个关键词用不同 buyer_id 隔离（避免上一个转人工后 WAITING_HUMAN 状态干扰）。
        修复：手动注入 _dynamic_keywords 覆盖 DB 默认值（避免受本地 admin.db 数据影响）。
        """
        from src.scheduler.dispatcher import SessionScheduler
        from src.config.settings import Config
        from src.contracts import SessionState
        from src.scheduler.session_store import SessionStore

        # 用 yaml 默认的全部 7 个关键词
        config = Config()
        keywords = config.escalation_keywords
        assert len(keywords) == 7, f"yaml 默认关键词应 7 个，实际 {len(keywords)}: {keywords}"

        for i, kw in enumerate(keywords):
            escalate_fn = AsyncMock()
            # 用不同 buyer_id 隔离会话
            msg = make_msg(f"我要{kw}", buyer_id=f"buyer_kw_{i}")
            scheduler = make_scheduler(escalate_fn=escalate_fn, config=config)
            # 注入 yaml 默认关键词到动态缓存，绕开 DB（DB 可能只有部分词）
            scheduler._dynamic_keywords = {
                "default": {"global": list(config.escalation_keywords)},
            }
            await scheduler.dispatch(msg, make_shop())
            escalate_fn.assert_called_once(), f"关键词 {kw!r} 未触发转人工"


# ── 状态机——低置信度转人工 ────────────────────────────────────────────────────

class TestDispatchLowConfidence:
    async def test_low_confidence_escalates(self):
        escalate_fn = AsyncMock()
        send_fn = AsyncMock(return_value=True)
        llm_fn = AsyncMock(return_value=("不确定回复", 50))

        scheduler = make_scheduler(
            retrieve_fn=AsyncMock(return_value=no_faq_result()),
            llm_fn=llm_fn,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        await scheduler.dispatch(make_msg("退货流程是什么？"), make_shop(threshold=85))

        escalate_fn.assert_called_once()
        ctx: EscalationContext = escalate_fn.call_args[0][0]
        assert ctx.reason == EscalationReason.LOW_CONFIDENCE
        assert ctx.confidence == 50
        # 新行为：低置信度转人工时发搪塞话术安抚买家
        send_fn.assert_called_once()

    async def test_high_confidence_auto_replies(self):
        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()
        llm_fn = AsyncMock(return_value=("这款灯是18瓦，铝合金材质。", 92))

        scheduler = make_scheduler(
            retrieve_fn=AsyncMock(return_value=no_faq_result()),
            llm_fn=llm_fn,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        await scheduler.dispatch(make_msg("这款灯多少瓦？"), make_shop(threshold=85))

        send_fn.assert_called_once()
        escalate_fn.assert_not_called()


# ── 状态机——模糊寒暄兜底 ──────────────────────────────────────────────────────

class TestDispatchGreetingFallback:
    async def test_low_confidence_greeting_uses_fallback(self):
        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()
        llm_fn = AsyncMock(return_value=("我也不知道", 30))

        scheduler = make_scheduler(
            retrieve_fn=AsyncMock(return_value=no_faq_result()),
            llm_fn=llm_fn,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        await scheduler.dispatch(make_msg("在吗"), make_shop(threshold=85))

        # 低置信度但是寒暄 → 兜底回复，不转人工
        send_fn.assert_called_once()
        escalate_fn.assert_not_called()

    async def test_greeting_detection(self):
        from src.scheduler.dispatcher import SessionScheduler as S
        patterns = ["在吗", "你好", "您好", "亲", "hello", "hi"]
        for p in patterns:
            assert S._is_greeting(p, patterns), f"{p!r} 应被识别为寒暄"
        assert not S._is_greeting("这款灯的功率是多少瓦？", patterns)
        assert not S._is_greeting("投诉你们！" * 3, patterns)


# ── 状态机——异常降级 ──────────────────────────────────────────────────────────

class TestDispatchExceptionFallback:
    async def test_retrieval_exception_escalates(self):
        escalate_fn = AsyncMock()
        send_fn = AsyncMock(return_value=True)
        retrieve_fn = AsyncMock(side_effect=Exception("Qdrant 连接失败"))

        scheduler = make_scheduler(
            retrieve_fn=retrieve_fn,
            escalate_fn=escalate_fn,
            send_fn=send_fn,
        )
        await scheduler.dispatch(make_msg(), make_shop())

        escalate_fn.assert_called_once()
        ctx: EscalationContext = escalate_fn.call_args[0][0]
        assert ctx.reason == EscalationReason.EXCEPTION

    async def test_llm_exception_escalates(self):
        escalate_fn = AsyncMock()
        llm_fn = AsyncMock(side_effect=Exception("LLM 超时"))

        scheduler = make_scheduler(
            retrieve_fn=AsyncMock(return_value=no_faq_result()),
            llm_fn=llm_fn,
            escalate_fn=escalate_fn,
        )
        await scheduler.dispatch(make_msg(), make_shop())

        escalate_fn.assert_called_once()

    async def test_session_load_exception_escalates(self):
        escalate_fn = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("Redis 不可用"))
        mock_redis.set = AsyncMock(return_value=True)
        store = SessionStore(redis_client=mock_redis)
        # Redis 不可用时 load_or_create 降级为新建，不抛异常，因此不会触发 EXCEPTION
        # 此测试验证降级为新建后流程继续正常运行
        send_fn = AsyncMock(return_value=True)
        llm_fn = AsyncMock(return_value=("正常回复", 90))
        scheduler = make_scheduler(
            session_store=store,
            llm_fn=llm_fn,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        await scheduler.dispatch(make_msg(), make_shop())
        send_fn.assert_called_once()

    async def test_send_failure_escalates(self):
        escalate_fn = AsyncMock()
        send_fn = AsyncMock(return_value=False)  # 发送失败
        llm_fn = AsyncMock(return_value=("回复内容", 92))

        scheduler = make_scheduler(
            retrieve_fn=AsyncMock(return_value=no_faq_result()),
            llm_fn=llm_fn,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        await scheduler.dispatch(make_msg(), make_shop())

        escalate_fn.assert_called_once()
        ctx: EscalationContext = escalate_fn.call_args[0][0]
        assert ctx.reason == EscalationReason.SEND_FAILED


# ── 状态机——已转人工会话忽略 ──────────────────────────────────────────────────

class TestDispatchWaitingHuman:
    async def test_waiting_human_within_debounce_silently_ignores(self):
        """10 分钟内重复消息：fill Future 让 RPA 不超时，但不告警、不发买家可见消息。"""
        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()
        existing_ctx = SessionContext(
            shop_id="tb_test_001",
            buyer_id="buyer_001",
            platform=Platform.TAOBAO,
            state=SessionState.WAITING_HUMAN,
            created_at=NOW,
            updated_at=NOW,
        )
        mock_redis = AsyncMock()
        # 第一次 get 返回会话 JSON，后续 get（读 handoff_at）返回 None
        mock_redis.get = AsyncMock(side_effect=[existing_ctx.model_dump_json(), None])
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.expire = AsyncMock(return_value=True)
        store = SessionStore(redis_client=mock_redis)

        scheduler = make_scheduler(
            session_store=store,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        await scheduler.dispatch(make_msg("继续发消息"), make_shop())

        # fill Future：调用 _send 一次（reply="" + escalated=True）
        send_fn.assert_called_once()
        call_args = send_fn.call_args
        assert call_args[0][2] == ""  # reply 为空
        assert call_args[0][3].get("escalated") is True  # 标记转人工
        # 不告警
        escalate_fn.assert_not_called()

    async def test_waiting_human_after_debounce_resets_to_active(self):
        """超过 10 分钟视为新对话：重置为 ACTIVE 继续走正常流程。"""
        from datetime import timedelta

        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()
        existing_ctx = SessionContext(
            shop_id="tb_test_001",
            buyer_id="buyer_001",
            platform=Platform.TAOBAO,
            state=SessionState.WAITING_HUMAN,
            created_at=NOW,
            updated_at=NOW,
        )
        # 模拟 handoff_at 发生在 15 分钟前
        old_handoff = (NOW - timedelta(minutes=15)).isoformat()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=[existing_ctx.model_dump_json(), old_handoff.encode()])
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock(return_value=True)
        store = SessionStore(redis_client=mock_redis)

        # 后续流程要能跑通：配 retrieve + llm + send
        retrieve_fn = AsyncMock(return_value=no_faq_result())
        llm_fn = AsyncMock(return_value=("新对话的回复", 92))
        scheduler = make_scheduler(
            session_store=store,
            retrieve_fn=retrieve_fn,
            llm_fn=llm_fn,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        await scheduler.dispatch(make_msg("新问题"), make_shop())

        # 重置后会话状态变 ACTIVE，走正常流程，应该 send 一次
        send_fn.assert_called_once()
        # 不应触发告警
        escalate_fn.assert_not_called()

    async def test_waiting_human_fallback_to_ctx_updated_at(self):
        """handoff_at 已蒸发（Redis TTL 过期），用 ctx.updated_at 作 fallback 判断。
        修复 bug：避免转人工 2 小时后买家再发消息永远静默忽略。"""
        from datetime import timedelta

        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()
        # ctx.updated_at 在 15 分钟前（说明进入 WAITING_HUMAN 是 15 分钟前）
        old_updated = NOW - timedelta(minutes=15)
        existing_ctx = SessionContext(
            shop_id="tb_test_001",
            buyer_id="buyer_001",
            platform=Platform.TAOBAO,
            state=SessionState.WAITING_HUMAN,
            created_at=old_updated,
            updated_at=old_updated,
        )
        mock_redis = AsyncMock()
        # 第一次 get 返回 ctx JSON，第二次 get（读 handoff_at）返回 None → 模拟 Redis TTL 蒸发
        mock_redis.get = AsyncMock(side_effect=[existing_ctx.model_dump_json(), None])
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock(return_value=True)
        store = SessionStore(redis_client=mock_redis)

        retrieve_fn = AsyncMock(return_value=no_faq_result())
        llm_fn = AsyncMock(return_value=("fallback 后的正常回复", 92))
        scheduler = make_scheduler(
            session_store=store,
            retrieve_fn=retrieve_fn,
            llm_fn=llm_fn,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        await scheduler.dispatch(make_msg("新问题"), make_shop())

        # 走 fallback 路径：ctx.updated_at 距今 > 10 分钟 → 当新对话处理
        send_fn.assert_called_once()
        escalate_fn.assert_not_called()
        # 清掉 handoff_at（虽然本来就是 None 蒸发）
        mock_redis.delete.assert_called()

    async def test_waiting_human_chat_list_recent_extends_debounce(self):
        """chat_list_latest_at 比 handoff_at 更新：客服 3 分钟前还在聊天 → 静默忽略。
        关键场景：转人工后客服在平台上回复了买家（chatList 时间推进）但没回调给我们，
        我们用 chatList 时间作锚点，避免误判为新对话。
        """
        from datetime import timedelta

        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()
        existing_ctx = SessionContext(
            shop_id="tb_test_001",
            buyer_id="buyer_001",
            platform=Platform.TAOBAO,
            state=SessionState.WAITING_HUMAN,
            created_at=NOW,
            updated_at=NOW,
        )
        # handoff_at 在 15 分钟前，但 chatList 最后一条气泡在 3 分钟前（客服刚刚还在聊）
        old_handoff = (NOW - timedelta(minutes=15)).isoformat()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=[existing_ctx.model_dump_json(), old_handoff.encode()])
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.expire = AsyncMock(return_value=True)
        store = SessionStore(redis_client=mock_redis)

        scheduler = make_scheduler(
            session_store=store,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )

        # 构造带 chat_list_latest_at 的消息（3 分钟前）
        msg = make_msg("新问题")
        msg.chat_list_latest_at = NOW - timedelta(minutes=3)
        await scheduler.dispatch(msg, make_shop())

        # chat_list_latest_at 距今 3 分钟 < 10 分钟 → 静默忽略
        send_fn.assert_called_once()  # fill Future
        assert send_fn.call_args[0][2] == ""
        escalate_fn.assert_not_called()

    async def test_waiting_human_chat_list_old_resets(self):
        """chat_list_latest_at 超过 10 分钟：说明客服也不聊了 → 视为新对话。"""
        from datetime import timedelta

        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()
        existing_ctx = SessionContext(
            shop_id="tb_test_001",
            buyer_id="buyer_001",
            platform=Platform.TAOBAO,
            state=SessionState.WAITING_HUMAN,
            created_at=NOW,
            updated_at=NOW,
        )
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=[existing_ctx.model_dump_json(), None])
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock(return_value=True)
        store = SessionStore(redis_client=mock_redis)

        retrieve_fn = AsyncMock(return_value=no_faq_result())
        llm_fn = AsyncMock(return_value=("新对话", 92))
        scheduler = make_scheduler(
            session_store=store,
            retrieve_fn=retrieve_fn,
            llm_fn=llm_fn,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )

        # chat_list_latest_at 距今 15 分钟（老的）+ handoff_at 也是 15 分钟前 + ctx 也是
        msg = make_msg("新问题")
        msg.chat_list_latest_at = NOW - timedelta(minutes=15)
        await scheduler.dispatch(msg, make_shop())

        # 三个锚点都 > 10 分钟 → 走新对话
        send_fn.assert_called_once()
        escalate_fn.assert_not_called()

    async def test_waiting_human_no_chat_list_at_uses_ctx_fallback(self):
        """RPA 没传 chat_list_latest_at（旧客户端）：退化为 max(handoff_at, ctx.updated_at) 行为。"""
        from datetime import timedelta

        send_fn = AsyncMock(return_value=True)
        escalate_fn = AsyncMock()
        existing_ctx = SessionContext(
            shop_id="tb_test_001",
            buyer_id="buyer_001",
            platform=Platform.TAOBAO,
            state=SessionState.WAITING_HUMAN,
            created_at=NOW,
            updated_at=NOW,
        )
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=[existing_ctx.model_dump_json(), None])
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.expire = AsyncMock(return_value=True)
        store = SessionStore(redis_client=mock_redis)

        scheduler = make_scheduler(
            session_store=store,
            send_fn=send_fn,
            escalate_fn=escalate_fn,
        )
        # 不传 chat_list_latest_at
        msg = make_msg("新问题")
        assert msg.chat_list_latest_at is None
        await scheduler.dispatch(msg, make_shop())

        # fallback 到 ctx.updated_at = NOW，< 10 分钟 → 静默
        send_fn.assert_called_once()
        escalate_fn.assert_not_called()


# ── 状态机——会话超时归档 ──────────────────────────────────────────────────────

class TestSessionTimeout:
    async def test_session_deleted_after_dispatch(self, session_store, mock_redis):
        """会话结束后可以被删除（模拟超时归档）。"""
        await session_store.delete("tb_test_001", "buyer_001")
        # delete 会联动清理主 key 和 handoff_at key（避免遗留）
        delete_calls = [c.args[0] for c in mock_redis.delete.call_args_list]
        assert "session:tb_test_001:buyer_001" in delete_calls
        assert "session:tb_test_001:buyer_001:handoff_at" in delete_calls

    async def test_writeback_called_after_reply(self):
        writeback_fn = AsyncMock()
        send_fn = AsyncMock(return_value=True)
        llm_fn = AsyncMock(return_value=("回复内容", 92))

        scheduler = make_scheduler(
            retrieve_fn=AsyncMock(return_value=no_faq_result()),
            llm_fn=llm_fn,
            send_fn=send_fn,
            writeback_fn=writeback_fn,
        )
        await scheduler.dispatch(make_msg(), make_shop())

        # 等待异步 writeback 完成
        await asyncio.sleep(0.01)
        writeback_fn.assert_called_once()


# ── 状态机——无平台分支 ────────────────────────────────────────────────────────

class TestNoPlatformBranch:
    async def test_dispatch_works_for_all_platforms(self):
        """验证同一 dispatch 函数无需平台分支，四平台消息处理一致。"""
        for platform in Platform:
            send_fn = AsyncMock(return_value=True)
            llm_fn = AsyncMock(return_value=("回复", 92))

            shop_id = f"{platform.value}_test_001"
            # 构造对应平台的 Config
            from src.config.settings import Config as _Config, ShopConfig as _SC
            shop = _SC(
                shop_id=shop_id,
                platform=platform,
                name="test",
                confidence_threshold=85,
            )
            cfg = _Config.model_validate({"shops": []}).model_copy(update={"shops": [shop]})

            scheduler = make_scheduler(
                config=cfg,
                retrieve_fn=AsyncMock(return_value=RetrievalResult(shop_id=shop_id, query="test")),
                llm_fn=llm_fn,
                send_fn=send_fn,
            )
            msg = StandardMessage(
                shop_id=shop_id,
                platform=platform,
                buyer_id="buyer_001",
                content="你好",
                timestamp=NOW,
                message_id=f"msg_{platform.value}",
                source=MessageSource.WEBHOOK,
            )
            await scheduler.dispatch(msg, shop)
            send_fn.assert_called_once(), f"{platform.value} 未正常发送"
