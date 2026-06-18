"""千牛网关单元测试与集成测试。"""

import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import ShopConfig
from src.contracts import MessageSource, Platform, StandardMessage
from src.gateway.base import BaseGateway
from src.gateway.registry import GatewayRegistry
from src.gateway.taobao import TaobaoGateway, _taobao_sign


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def shop_config() -> ShopConfig:
    return ShopConfig(
        shop_id="tb_test_001",
        platform=Platform.TAOBAO,
        name="测试店铺",
        api_key="test_app_key",
        api_secret="test_app_secret",
        obsidian_vault="data/obsidian/tb_test_001",
    )


@pytest.fixture
def mock_redis():
    """模拟 Redis 客户端，set 操作默认返回 True（首次写入成功）。"""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def gateway(mock_redis) -> TaobaoGateway:
    return TaobaoGateway(redis_client=mock_redis, host="127.0.0.1", port=18090)


def make_raw_message(
    buyer_id: str = "buyer_001",
    content: str = "你好，想咨询一下",
    message_id: str = "msg_001",
    ts_ms: int | None = None,
) -> dict:
    return {
        "fromUserId": buyer_id,
        "content": content,
        "msgId": message_id,
        "timestamp": ts_ms or int(time.time() * 1000),
    }


# ── 签名算法 ──────────────────────────────────────────────────────────────────

class TestTaobaoSign:
    def test_sign_is_uppercase_hex(self):
        params = {"method": "test", "app_key": "key"}
        sign = _taobao_sign(params, "secret")
        assert len(sign) == 32
        assert sign == sign.upper()

    def test_sign_deterministic(self):
        params = {"a": "1", "b": "2"}
        s1 = _taobao_sign(params, "secret")
        s2 = _taobao_sign(params, "secret")
        assert s1 == s2

    def test_sign_changes_with_secret(self):
        params = {"method": "test"}
        s1 = _taobao_sign(params, "secret1")
        s2 = _taobao_sign(params, "secret2")
        assert s1 != s2

    def test_sign_changes_with_params(self):
        s1 = _taobao_sign({"a": "1"}, "secret")
        s2 = _taobao_sign({"a": "2"}, "secret")
        assert s1 != s2


# ── 消息解析 ──────────────────────────────────────────────────────────────────

class TestParseMessage:
    def test_valid_message(self, gateway, shop_config):
        raw = make_raw_message()
        msg = gateway._parse_message(shop_config, raw)
        assert msg is not None
        assert msg.shop_id == "tb_test_001"
        assert msg.platform == Platform.TAOBAO
        assert msg.buyer_id == "buyer_001"
        assert msg.content == "你好，想咨询一下"
        assert msg.message_id == "msg_001"
        assert msg.source == MessageSource.TOP_API

    def test_missing_buyer_id_returns_none(self, gateway, shop_config):
        raw = make_raw_message()
        raw.pop("fromUserId")
        msg = gateway._parse_message(shop_config, raw)
        assert msg is None

    def test_missing_content_returns_none(self, gateway, shop_config):
        raw = make_raw_message()
        raw.pop("content")
        msg = gateway._parse_message(shop_config, raw)
        assert msg is None

    def test_missing_message_id_returns_none(self, gateway, shop_config):
        raw = make_raw_message()
        raw.pop("msgId")
        msg = gateway._parse_message(shop_config, raw)
        assert msg is None

    def test_timestamp_converted_to_utc(self, gateway, shop_config):
        ts_ms = 1700000000000
        raw = make_raw_message(ts_ms=ts_ms)
        msg = gateway._parse_message(shop_config, raw)
        assert msg is not None
        assert msg.timestamp.tzinfo is not None
        assert msg.timestamp == datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

    def test_raw_payload_preserved(self, gateway, shop_config):
        raw = make_raw_message()
        raw["extra_field"] = "extra_value"
        msg = gateway._parse_message(shop_config, raw)
        assert msg is not None
        assert msg.raw_payload["extra_field"] == "extra_value"


# ── 消息去重 ──────────────────────────────────────────────────────────────────

class TestDeduplication:
    async def test_first_message_not_duplicate(self, gateway, mock_redis):
        mock_redis.set = AsyncMock(return_value=True)  # nx=True 写入成功
        result = await gateway._is_duplicate("tb_test_001", "msg_001")
        assert result is False

    async def test_duplicate_message_detected(self, gateway, mock_redis):
        mock_redis.set = AsyncMock(return_value=None)  # nx=True 已存在返回 None
        result = await gateway._is_duplicate("tb_test_001", "msg_001")
        assert result is True

    async def test_redis_failure_allows_message(self, gateway, mock_redis):
        """Redis 故障时降级为不去重，避免丢消息。"""
        mock_redis.set = AsyncMock(side_effect=Exception("Redis 连接失败"))
        result = await gateway._is_duplicate("tb_test_001", "msg_001")
        assert result is False

    async def test_dedup_key_format(self, gateway, mock_redis):
        await gateway._is_duplicate("tb_test_001", "msg_abc")
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "msg_dedup:tb_test_001:msg_abc"
        assert call_args[1]["nx"] is True
        assert call_args[1]["ex"] == gateway._dedup_ttl


# ── Webhook HTTP 处理 ─────────────────────────────────────────────────────────

class TestWebhookHandler:
    async def test_webhook_normal_message(self, gateway, shop_config):
        """正常消息推送进入队列。"""
        raw = make_raw_message()
        gateway._queues["tb_test_001"] = asyncio.Queue()

        app = gateway._build_app([shop_config])
        from aiohttp.test_utils import TestClient, TestServer

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/webhook/tb_test_001",
                data=json.dumps(raw),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status == 200

        assert gateway._queues["tb_test_001"].qsize() == 1
        msg = gateway._queues["tb_test_001"].get_nowait()
        assert msg.buyer_id == "buyer_001"

    async def test_webhook_unknown_shop_returns_404(self, gateway, shop_config):
        app = gateway._build_app([shop_config])
        from aiohttp.test_utils import TestClient, TestServer

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/webhook/unknown_shop",
                data=json.dumps(make_raw_message()),
            )
            assert resp.status == 404

    async def test_webhook_invalid_json_returns_400(self, gateway, shop_config):
        app = gateway._build_app([shop_config])
        from aiohttp.test_utils import TestClient, TestServer

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/webhook/tb_test_001",
                data="not json",
            )
            assert resp.status == 400

    async def test_webhook_duplicate_message_not_queued(self, gateway, shop_config, mock_redis):
        """重复消息不进入队列。"""
        mock_redis.set = AsyncMock(return_value=None)  # 模拟重复
        gateway._queues["tb_test_001"] = asyncio.Queue()

        app = gateway._build_app([shop_config])
        from aiohttp.test_utils import TestClient, TestServer

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/webhook/tb_test_001",
                data=json.dumps(make_raw_message()),
            )
            assert resp.status == 200  # 仍返回 200，但不入队

        assert gateway._queues["tb_test_001"].empty()

    async def test_webhook_batch_messages(self, gateway, shop_config):
        """批量推送（JSON 数组）正确解析。"""
        messages = [
            make_raw_message(message_id="msg_1", content="消息1"),
            make_raw_message(message_id="msg_2", content="消息2"),
        ]
        gateway._queues["tb_test_001"] = asyncio.Queue()

        app = gateway._build_app([shop_config])
        from aiohttp.test_utils import TestClient, TestServer

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/webhook/tb_test_001",
                data=json.dumps(messages),
            )
            assert resp.status == 200

        assert gateway._queues["tb_test_001"].qsize() == 2


# ── 消息发送 ──────────────────────────────────────────────────────────────────

class TestSendMessage:
    async def test_send_success(self, gateway, shop_config):
        """发送成功时返回 True。"""
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"qianniu_cloud_message_send_response": {"result": True}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await gateway.send(shop_config, "buyer_001", "您好！", {})

        assert result is True

    async def test_send_api_error_returns_false(self, gateway, shop_config):
        """API 返回 error_response 时返回 False。"""
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={
            "error_response": {"code": 50, "zh_desc": "Invalid session"}
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await gateway.send(shop_config, "buyer_001", "您好！", {})

        assert result is False

    async def test_send_network_error_returns_false(self, gateway, shop_config):
        """网络异常时返回 False，不抛出。"""
        import aiohttp
        with patch("aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("超时"))
            result = await gateway.send(shop_config, "buyer_001", "您好！", {})

        assert result is False


# ── listen 迭代器 ─────────────────────────────────────────────────────────────

class TestListen:
    async def test_listen_yields_queued_messages(self, gateway, shop_config):
        """队列中有消息时能正确产出。"""
        q: asyncio.Queue = asyncio.Queue()
        msg = StandardMessage(
            shop_id="tb_test_001",
            platform=Platform.TAOBAO,
            buyer_id="buyer_001",
            content="测试",
            timestamp=datetime.now(tz=timezone.utc),
            message_id="msg_001",
            source=MessageSource.TOP_API,
        )
        await q.put(msg)
        gateway._queues["tb_test_001"] = q

        received = []
        async for m in gateway.listen(shop_config):
            received.append(m)
            break  # 取一条即停止

        assert len(received) == 1
        assert received[0].message_id == "msg_001"


# ── GatewayRegistry ──────────────────────────────────────────────────────────

class TestGatewayRegistry:
    def test_register_and_get(self, gateway):
        registry = GatewayRegistry()
        registry.register(Platform.TAOBAO, gateway)
        assert registry.get(Platform.TAOBAO) is gateway

    def test_get_unregistered_raises(self):
        registry = GatewayRegistry()
        with pytest.raises(KeyError, match="未注册网关"):
            registry.get(Platform.TAOBAO)

    def test_all_platforms(self, gateway):
        registry = GatewayRegistry()
        registry.register(Platform.TAOBAO, gateway)
        assert Platform.TAOBAO in registry.all_platforms()


# ── 集成测试：本地 HTTP 服务器完整流程 ─────────────────────────────────────────

class TestTaobaoGatewayIntegration:
    """启动真实 aiohttp 服务器，验证完整 Webhook → 队列流程。"""

    async def test_full_webhook_to_queue_flow(self, mock_redis):
        """模拟千牛推送 → 消息标准化 → 入队的完整流程。"""
        import aiohttp

        gateway = TaobaoGateway(redis_client=mock_redis, host="127.0.0.1", port=18091)
        shop = ShopConfig(
            shop_id="tb_integ_001",
            platform=Platform.TAOBAO,
            name="集成测试店铺",
            api_key="key",
            api_secret="",
            obsidian_vault="data/x",
        )
        gateway._queues["tb_integ_001"] = asyncio.Queue()
        app = gateway._build_app([shop])

        from aiohttp.test_utils import TestClient, TestServer

        raw = make_raw_message(buyer_id="buyer_integ", content="集成测试消息", message_id="integ_001")

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/webhook/tb_integ_001",
                data=json.dumps(raw),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status == 200

        msg = gateway._queues["tb_integ_001"].get_nowait()
        assert msg.shop_id == "tb_integ_001"
        assert msg.buyer_id == "buyer_integ"
        assert msg.content == "集成测试消息"
        assert msg.platform == Platform.TAOBAO
        assert msg.source == MessageSource.TOP_API
        assert msg.timestamp.tzinfo is not None
