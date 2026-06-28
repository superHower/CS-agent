"""数据契约层单元测试。

验证所有 Pydantic v2 模型的序列化、反序列化、字段验证及 extra='forbid' 行为。
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.contracts import (
    EscalationContext,
    EscalationReason,
    KnowledgeChunk,
    LLMRequest,
    LLMResponse,
    MessageSource,
    Platform,
    RetrievalResult,
    SessionContext,
    SessionState,
    StandardMessage,
    TurnRecord,
    WritebackTask,
)

NOW = datetime.now(tz=timezone.utc)


# ── 辅助工厂 ─────────────────────────────────────────────────────────────────

def make_standard_message(**kwargs) -> StandardMessage:
    defaults = dict(
        shop_id="tb_demo_001",
        platform=Platform.TAOBAO,
        buyer_id="buyer_123",
        content="你好，这个灯怎么安装？",
        timestamp=NOW,
        message_id="msg_001",
        source=MessageSource.TOP_API,
    )
    return StandardMessage(**(defaults | kwargs))


def make_session_context(**kwargs) -> SessionContext:
    defaults = dict(
        shop_id="tb_demo_001",
        buyer_id="buyer_123",
        platform=Platform.TAOBAO,
        created_at=NOW,
        updated_at=NOW,
    )
    return SessionContext(**(defaults | kwargs))


# ── StandardMessage ───────────────────────────────────────────────────────────

class TestStandardMessage:
    def test_valid_creation(self):
        msg = make_standard_message()
        assert msg.shop_id == "tb_demo_001"
        assert msg.platform == Platform.TAOBAO
        assert msg.source == MessageSource.TOP_API

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError) as exc_info:
            StandardMessage(
                shop_id="tb_demo_001",
                platform=Platform.TAOBAO,
                buyer_id="buyer_123",
                content="test",
                timestamp=NOW,
                message_id="msg_001",
                source=MessageSource.TOP_API,
                unknown_field="should_fail",  # 额外字段，应被拒绝
            )
        assert "Extra inputs are not permitted" in str(exc_info.value)

    def test_serialization_roundtrip(self):
        msg = make_standard_message()
        data = msg.model_dump()
        restored = StandardMessage(**data)
        assert restored == msg

    def test_json_roundtrip(self):
        msg = make_standard_message()
        json_str = msg.model_dump_json()
        restored = StandardMessage.model_validate_json(json_str)
        assert restored.message_id == msg.message_id

    def test_platform_enum_validation(self):
        with pytest.raises(ValidationError):
            make_standard_message(platform="unknown_platform")

    def test_all_platforms(self):
        for platform in Platform:
            msg = make_standard_message(platform=platform)
            assert msg.platform == platform

    def test_default_raw_payload_empty(self):
        msg = make_standard_message()
        assert msg.raw_payload == {}

    def test_raw_payload_preserved(self):
        payload = {"original_key": "original_value"}
        msg = make_standard_message(raw_payload=payload)
        assert msg.raw_payload == payload

    def test_chat_list_latest_at_optional(self):
        """chat_list_latest_at 是可选字段，默认 None。"""
        msg = make_standard_message()
        assert msg.chat_list_latest_at is None

    def test_chat_list_latest_at_preserved(self):
        ts = NOW
        msg = make_standard_message(chat_list_latest_at=ts)
        assert msg.chat_list_latest_at == ts


# ── TurnRecord ────────────────────────────────────────────────────────────────

class TestTurnRecord:
    def test_valid_creation(self):
        turn = TurnRecord(role="user", content="你好", timestamp=NOW)
        assert turn.role == "user"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            TurnRecord(role="user", content="hello", timestamp=NOW, extra="bad")

    def test_both_roles(self):
        user_turn = TurnRecord(role="user", content="问题", timestamp=NOW)
        assistant_turn = TurnRecord(role="assistant", content="回答", timestamp=NOW)
        assert user_turn.role == "user"
        assert assistant_turn.role == "assistant"


# ── SessionContext ────────────────────────────────────────────────────────────

class TestSessionContext:
    def test_valid_creation(self):
        ctx = make_session_context()
        assert ctx.state == SessionState.ACTIVE
        assert ctx.history == []
        assert ctx.last_confidence == 0

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            SessionContext(
                shop_id="tb_demo_001",
                buyer_id="buyer_123",
                platform=Platform.TAOBAO,
                created_at=NOW,
                updated_at=NOW,
                bad_field="fail",
            )

    def test_with_history(self):
        history = [
            TurnRecord(role="user", content="你好", timestamp=NOW),
            TurnRecord(role="assistant", content="您好！", timestamp=NOW),
        ]
        ctx = make_session_context(history=history)
        assert len(ctx.history) == 2

    def test_state_transitions(self):
        ctx = make_session_context()
        assert ctx.state == SessionState.ACTIVE
        ctx2 = ctx.model_copy(update={"state": SessionState.WAITING_HUMAN})
        assert ctx2.state == SessionState.WAITING_HUMAN

    def test_confidence_bounds(self):
        ctx = make_session_context(last_confidence=85)
        assert ctx.last_confidence == 85

        with pytest.raises(ValidationError):
            make_session_context(last_confidence=101)

        with pytest.raises(ValidationError):
            make_session_context(last_confidence=-1)

    def test_serialization_roundtrip(self):
        ctx = make_session_context()
        data = ctx.model_dump()
        restored = SessionContext(**data)
        assert restored == ctx


# ── KnowledgeChunk ────────────────────────────────────────────────────────────

class TestKnowledgeChunk:
    def test_valid_creation(self):
        chunk = KnowledgeChunk(
            chunk_id="tb_demo_001:faq/install.md:0",
            content="安装步骤：1. 关闭电源...",
            source_file="faq/install.md",
            score=0.92,
        )
        assert chunk.score == 0.92
        assert chunk.tags == []
        assert chunk.backlinks == []

    def test_score_bounds(self):
        with pytest.raises(ValidationError):
            KnowledgeChunk(
                chunk_id="x",
                content="test",
                source_file="test.md",
                score=1.5,  # 超出 [0, 1]
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            KnowledgeChunk(
                chunk_id="x",
                content="test",
                source_file="test.md",
                score=0.5,
                bad="field",
            )


# ── RetrievalResult ───────────────────────────────────────────────────────────

class TestRetrievalResult:
    def test_faq_hit(self):
        result = RetrievalResult(
            shop_id="tb_demo_001",
            query="如何安装",
            faq_hit=True,
            faq_reply="安装步骤请参考说明书第3页。",
        )
        assert result.faq_hit is True
        assert result.faq_reply != ""
        assert result.chunks == []

    def test_vector_result(self):
        chunk = KnowledgeChunk(
            chunk_id="tb_demo_001:faq.md:0",
            content="安装说明...",
            source_file="faq.md",
            score=0.88,
        )
        result = RetrievalResult(
            shop_id="tb_demo_001",
            query="灯怎么安装",
            chunks=[chunk],
            elapsed_ms=120,
        )
        assert len(result.chunks) == 1
        assert result.elapsed_ms == 120

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            RetrievalResult(shop_id="x", query="q", extra_field="bad")


# ── LLMRequest / LLMResponse ──────────────────────────────────────────────────

class TestLLMRequest:
    def test_valid_creation(self):
        req = LLMRequest(
            shop_id="tb_demo_001",
            shop_name="淘宝示例店铺",
            buyer_message="这个灯多少瓦？",
        )
        assert req.knowledge == ""
        assert req.history == []
        assert req.model_override == ""

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            LLMRequest(
                shop_id="x",
                shop_name="x",
                buyer_message="x",
                bad="field",
            )


class TestLLMResponse:
    def test_valid_creation(self):
        resp = LLMResponse(
            raw_text="这个灯是18瓦。[CONFIDENCE: 92]",
            reply="这个灯是18瓦。",
            confidence=92,
        )
        assert resp.confidence == 92
        assert resp.input_tokens == 0

    def test_confidence_parse_failure_default_zero(self):
        resp = LLMResponse(
            raw_text="无法确认。",
            reply="无法确认。",
            confidence=0,  # 解析失败应为 0
        )
        assert resp.confidence == 0

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            LLMResponse(raw_text="x", reply="x", confidence=150)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            LLMResponse(raw_text="x", reply="x", confidence=80, bad="field")


# ── EscalationContext ─────────────────────────────────────────────────────────

class TestEscalationContext:
    def test_hard_keyword_escalation(self):
        ctx = EscalationContext(
            shop_id="tb_demo_001",
            buyer_id="buyer_***",
            platform=Platform.TAOBAO,
            reason=EscalationReason.HARD_KEYWORD,
            trigger_message="我要投诉你们！",
            triggered_keyword="投诉",
            timestamp=NOW,
        )
        assert ctx.reason == EscalationReason.HARD_KEYWORD
        assert ctx.triggered_keyword == "投诉"

    def test_low_confidence_escalation(self):
        ctx = EscalationContext(
            shop_id="tb_demo_001",
            buyer_id="buyer_***",
            platform=Platform.TAOBAO,
            reason=EscalationReason.LOW_CONFIDENCE,
            trigger_message="这个能退货吗？",
            confidence=42,
            timestamp=NOW,
        )
        assert ctx.confidence == 42
        assert ctx.triggered_keyword == ""

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            EscalationContext(
                shop_id="x",
                buyer_id="x",
                platform=Platform.TAOBAO,
                reason=EscalationReason.EXCEPTION,
                trigger_message="x",
                timestamp=NOW,
                bad="field",
            )

    def test_serialization_roundtrip(self):
        ctx = EscalationContext(
            shop_id="tb_demo_001",
            buyer_id="buyer_***",
            platform=Platform.TAOBAO,
            reason=EscalationReason.EXCEPTION,
            trigger_message="test",
            timestamp=NOW,
        )
        data = ctx.model_dump()
        restored = EscalationContext(**data)
        assert restored == ctx


# ── WritebackTask ─────────────────────────────────────────────────────────────

class TestWritebackTask:
    def test_valid_creation(self):
        task = WritebackTask(
            shop_id="tb_demo_001",
            buyer_id="buyer_1**",
            summary="买家咨询灯的安装方式，已提供安装说明。",
            session_date=NOW,
        )
        assert task.resolution == "resolved"
        assert task.retry_count == 0
        assert task.related_tags == []

    def test_escalated_resolution(self):
        task = WritebackTask(
            shop_id="tb_demo_001",
            buyer_id="buyer_1**",
            summary="买家投诉质量问题，已转人工。",
            resolution="escalated",
            session_date=NOW,
        )
        assert task.resolution == "escalated"

    def test_retry_count_non_negative(self):
        with pytest.raises(ValidationError):
            WritebackTask(
                shop_id="x",
                buyer_id="x",
                summary="x",
                session_date=NOW,
                retry_count=-1,
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            WritebackTask(
                shop_id="x",
                buyer_id="x",
                summary="x",
                session_date=NOW,
                bad="field",
            )

    def test_serialization_roundtrip(self):
        task = WritebackTask(
            shop_id="tb_demo_001",
            buyer_id="buyer_1**",
            summary="测试总结",
            session_date=NOW,
        )
        data = task.model_dump()
        restored = WritebackTask(**data)
        assert restored == task
