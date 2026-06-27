"""动作执行层单元测试：消息发送路由和人工告警推送。"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.contracts import EscalationContext, EscalationReason, Platform
from src.exceptions import SendFailedException


NOW = datetime.now(tz=timezone.utc)


# ── 辅助构造函数 ──────────────────────────────────────────────────────────────

def make_shop_config(shop_id: str = "tb_test_001", platform: Platform = Platform.TAOBAO):
    from src.config.settings import ShopConfig
    return ShopConfig(
        shop_id=shop_id,
        platform=platform,
        name="测试店铺",
    )


def make_escalation_ctx(**kwargs) -> EscalationContext:
    defaults = dict(
        shop_id="tb_test_001",
        buyer_id="buyer_001",
        platform=Platform.TAOBAO,
        reason=EscalationReason.LOW_CONFIDENCE,
        trigger_message="这个灯有质量问题！",
        confidence=60,
        timestamp=NOW,
    )
    return EscalationContext(**(defaults | kwargs))


# ── send_message.py ───────────────────────────────────────────────────────────

class TestSendReply:
    @pytest.fixture
    def mock_registry(self):
        gateway = AsyncMock()
        gateway.send = AsyncMock(return_value=True)
        registry = MagicMock()
        registry.get = MagicMock(return_value=gateway)
        return registry, gateway

    async def test_send_success(self, mock_registry):
        from src.actions.send_message import send_reply
        registry, gateway = mock_registry
        ok = await send_reply(
            registry, make_shop_config(), "buyer_001", Platform.TAOBAO, "您好！"
        )
        assert ok is True
        gateway.send.assert_called_once()

    async def test_send_passes_correct_args(self, mock_registry):
        from src.actions.send_message import send_reply
        registry, gateway = mock_registry
        await send_reply(
            registry, make_shop_config(), "buyer_001", Platform.TAOBAO, "回复内容",
            metadata={"extra": "data"},
        )
        call_kwargs = gateway.send.call_args[1]
        assert call_kwargs["buyer_id"] == "buyer_001"
        assert call_kwargs["content"] == "回复内容"

    async def test_send_retry_on_false(self, mock_registry):
        from src.actions.send_message import send_reply
        registry, gateway = mock_registry
        # 第1次返回 False，第2次返回 True
        gateway.send = AsyncMock(side_effect=[False, True])
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ok = await send_reply(
                registry, make_shop_config(), "buyer_001", Platform.TAOBAO, "回复"
            )
        assert ok is True
        assert gateway.send.call_count == 2

    async def test_send_raises_after_all_retries_fail(self, mock_registry):
        from src.actions.send_message import send_reply
        registry, gateway = mock_registry
        gateway.send = AsyncMock(return_value=False)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(SendFailedException):
                await send_reply(
                    registry, make_shop_config(), "buyer_001", Platform.TAOBAO, "回复"
                )

    async def test_send_raises_on_exception(self, mock_registry):
        from src.actions.send_message import send_reply
        registry, gateway = mock_registry
        gateway.send = AsyncMock(side_effect=Exception("网络错误"))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(SendFailedException):
                await send_reply(
                    registry, make_shop_config(), "buyer_001", Platform.TAOBAO, "回复"
                )

    async def test_unregistered_platform_raises(self, mock_registry):
        from src.actions.send_message import send_reply
        registry, _ = mock_registry
        registry.get = MagicMock(side_effect=KeyError("未注册"))
        with pytest.raises(SendFailedException):
            await send_reply(
                registry, make_shop_config(), "buyer_001", Platform.PINDUODUO, "回复"
            )


# ── alert_human.py ────────────────────────────────────────────────────────────

class TestAlertService:
    @pytest.fixture
    def wecom_service(self):
        from src.actions.alert_human import AlertService
        return AlertService(
            webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        )

    def _mock_session(self, status=200):
        mock_response = AsyncMock()
        mock_response.status = status
        mock_response.text = AsyncMock(return_value="ok")

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))
        return mock_session

    async def test_wecom_notify_success(self, wecom_service):
        ctx = make_escalation_ctx()
        mock_session = self._mock_session(200)
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await wecom_service.notify(ctx)
        mock_session.post.assert_called_once()

    async def test_notify_no_webhook_skips(self):
        from src.actions.alert_human import AlertService
        svc = AlertService(webhook_url="")
        ctx = make_escalation_ctx()
        with patch("aiohttp.ClientSession") as mock_cls:
            await svc.notify(ctx)
        mock_cls.assert_not_called()

    async def test_notify_http_error_does_not_raise(self, wecom_service):
        ctx = make_escalation_ctx()
        mock_session = self._mock_session(400)
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await wecom_service.notify(ctx)

    async def test_notify_exception_does_not_raise(self, wecom_service):
        ctx = make_escalation_ctx()
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(side_effect=Exception("连接失败"))
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await wecom_service.notify(ctx)

    async def test_wecom_payload_contains_shop_info(self):
        from src.actions.alert_human import _format_wecom_payload
        ctx = make_escalation_ctx(
            reason=EscalationReason.HARD_KEYWORD,
            triggered_keyword="12315",
        )
        payload = _format_wecom_payload(ctx)
        text = payload["markdown"]["content"]
        assert "tb_test_001" in text
        assert "buyer_001" in text
        assert "命中敏感词" in text

    async def test_wecom_payload_contains_reason(self):
        from src.actions.alert_human import _format_wecom_payload
        ctx = make_escalation_ctx(reason=EscalationReason.LOW_CONFIDENCE, confidence=72)
        payload = _format_wecom_payload(ctx)
        text = payload["markdown"]["content"]
        assert "置信度不足" in text
        assert "tb_test_001" in text

    async def test_notify_hard_keyword_reason(self, wecom_service):
        ctx = make_escalation_ctx(
            reason=EscalationReason.HARD_KEYWORD,
            triggered_keyword="投诉",
        )
        mock_session = self._mock_session(200)
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await wecom_service.notify(ctx)
        mock_session.post.assert_called_once()
