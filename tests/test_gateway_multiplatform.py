"""多平台网关单元测试与集成测试。

验证拼多多/京东/抖音网关消息解析、发送行为，以及四平台标准化集成测试。
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import ShopConfig
from src.contracts import MessageSource, Platform, StandardMessage
from src.gateway.douyin import DouyinGateway
from src.gateway.jd import JDGateway
from src.gateway.pinduoduo import PinduoduoGateway
from src.gateway.taobao import TaobaoGateway


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    return redis


def make_shop(platform: Platform, shop_id: str) -> ShopConfig:
    return ShopConfig(
        shop_id=shop_id,
        platform=platform,
        name=f"{platform.value} 测试店铺",
        api_key="test_key",
        api_secret="test_secret",
    )


# ── 拼多多网关 ────────────────────────────────────────────────────────────────

class TestPinduoduoGateway:
    @pytest.fixture
    def gw(self, mock_redis):
        return PinduoduoGateway(redis_client=mock_redis)

    @pytest.fixture
    def shop(self):
        return make_shop(Platform.PINDUODUO, "pdd_test_001")

    def test_parse_valid_message(self, gw, shop):
        raw = {
            "buyer_user_id": "pdd_buyer_001",
            "msg_content": "这个商品怎么用？",
            "msg_id": "pdd_msg_001",
            "timestamp": int(time.time() * 1000),
        }
        msg = gw._parse_message(shop, raw)
        assert msg is not None
        assert msg.platform == Platform.PINDUODUO
        assert msg.buyer_id == "pdd_buyer_001"
        assert msg.content == "这个商品怎么用？"
        assert msg.source == MessageSource.WEBHOOK

    def test_parse_missing_fields_returns_none(self, gw, shop):
        assert gw._parse_message(shop, {}) is None

    async def test_webhook_normal_flow(self, gw, shop):
        raw = {
            "buyer_user_id": "pdd_buyer_001",
            "msg_content": "有优惠吗？",
            "msg_id": "pdd_msg_002",
            "timestamp": int(time.time() * 1000),
        }
        gw._queues["pdd_test_001"] = asyncio.Queue()
        app = gw._build_app([shop])
        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/webhook/pdd_test_001", data=json.dumps(raw))
            assert resp.status == 200
        assert gw._queues["pdd_test_001"].qsize() == 1

    async def test_send_success(self, gw, shop):
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"result": True, "error_response": None})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await gw.send(shop, "pdd_buyer_001", "您好！", {})
        assert result is True

    async def test_send_failure(self, gw, shop):
        import aiohttp
        with patch("aiohttp.ClientSession") as cls:
            cls.return_value.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("连接失败"))
            result = await gw.send(shop, "pdd_buyer_001", "您好！", {})
        assert result is False


# ── 京东网关 ──────────────────────────────────────────────────────────────────

class TestJDGateway:
    @pytest.fixture
    def gw(self, mock_redis):
        return JDGateway(redis_client=mock_redis)

    @pytest.fixture
    def shop(self):
        return make_shop(Platform.JD, "jd_test_001")

    def test_parse_valid_message(self, gw, shop):
        raw = {
            "buyerPin": "jd_buyer_001",
            "content": "商品还有货吗？",
            "msgId": "jd_msg_001",
            "createTime": int(time.time() * 1000),
        }
        msg = gw._parse_message(shop, raw)
        assert msg is not None
        assert msg.platform == Platform.JD
        assert msg.buyer_id == "jd_buyer_001"
        assert msg.source == MessageSource.WEBHOOK

    def test_parse_missing_fields_returns_none(self, gw, shop):
        assert gw._parse_message(shop, {}) is None

    async def test_webhook_normal_flow(self, gw, shop):
        raw = {
            "buyerPin": "jd_buyer_001",
            "content": "发货了吗？",
            "msgId": "jd_msg_002",
            "createTime": int(time.time() * 1000),
        }
        gw._queues["jd_test_001"] = asyncio.Queue()
        app = gw._build_app([shop])
        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/webhook/jd_test_001", data=json.dumps(raw))
            assert resp.status == 200
        assert gw._queues["jd_test_001"].qsize() == 1

    async def test_send_failure(self, gw, shop):
        import aiohttp
        with patch("aiohttp.ClientSession") as cls:
            cls.return_value.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("超时"))
            result = await gw.send(shop, "jd_buyer_001", "您好！", {})
        assert result is False


# ── 抖音网关 ──────────────────────────────────────────────────────────────────

class TestDouyinGateway:
    @pytest.fixture
    def gw(self, mock_redis):
        return DouyinGateway(redis_client=mock_redis)

    @pytest.fixture
    def shop(self):
        return make_shop(Platform.DOUYIN, "dy_test_001")

    def test_parse_valid_message(self, gw, shop):
        raw = {
            "open_id": "dy_buyer_001",
            "content": "下单了为什么还没发货？",
            "message_id": "dy_msg_001",
            "timestamp": int(time.time() * 1000),
        }
        msg = gw._parse_message(shop, raw)
        assert msg is not None
        assert msg.platform == Platform.DOUYIN
        assert msg.buyer_id == "dy_buyer_001"
        assert msg.source == MessageSource.WEBHOOK

    def test_parse_missing_fields_returns_none(self, gw, shop):
        assert gw._parse_message(shop, {}) is None

    async def test_webhook_normal_flow(self, gw, shop):
        raw = {
            "open_id": "dy_buyer_001",
            "content": "质量怎么样？",
            "message_id": "dy_msg_002",
            "timestamp": int(time.time() * 1000),
        }
        gw._queues["dy_test_001"] = asyncio.Queue()
        app = gw._build_app([shop])
        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/webhook/dy_test_001", data=json.dumps(raw))
            assert resp.status == 200
        assert gw._queues["dy_test_001"].qsize() == 1

    async def test_send_failure(self, gw, shop):
        import aiohttp
        with patch("aiohttp.ClientSession") as cls:
            cls.return_value.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("超时"))
            result = await gw.send(shop, "dy_buyer_001", "您好！", {})
        assert result is False


# ── 多平台标准化集成测试 ───────────────────────────────────────────────────────

class TestMultiPlatformNormalization:
    """模拟四个平台各推送一条消息，验证全部转化为标准 StandardMessage 且 shop_id 正确。"""

    async def test_all_platforms_normalize_to_standard_message(self, mock_redis):
        platforms = [
            (
                Platform.TAOBAO, "tb_norm_001",
                TaobaoGateway(redis_client=mock_redis),
                {"fromUserId": "buyer_tb", "content": "淘宝消息", "msgId": "tb_001", "timestamp": int(time.time() * 1000)},
            ),
            (
                Platform.PINDUODUO, "pdd_norm_001",
                PinduoduoGateway(redis_client=mock_redis),
                {"buyer_user_id": "buyer_pdd", "msg_content": "拼多多消息", "msg_id": "pdd_001", "timestamp": int(time.time() * 1000)},
            ),
            (
                Platform.JD, "jd_norm_001",
                JDGateway(redis_client=mock_redis),
                {"buyerPin": "buyer_jd", "content": "京东消息", "msgId": "jd_001", "createTime": int(time.time() * 1000)},
            ),
            (
                Platform.DOUYIN, "dy_norm_001",
                DouyinGateway(redis_client=mock_redis),
                {"open_id": "buyer_dy", "content": "抖音消息", "message_id": "dy_001", "timestamp": int(time.time() * 1000)},
            ),
        ]

        from aiohttp.test_utils import TestClient, TestServer

        results: list[StandardMessage] = []

        for platform, shop_id, gw, raw in platforms:
            shop = make_shop(platform, shop_id)
            gw._queues[shop_id] = asyncio.Queue()
            app = gw._build_app([shop])

            async with TestClient(TestServer(app)) as client:
                resp = await client.post(f"/webhook/{shop_id}", data=json.dumps(raw))
                assert resp.status == 200, f"{platform.value} Webhook 返回异常"

            msg = gw._queues[shop_id].get_nowait()
            results.append(msg)

        # 验证四条消息全部转化为 StandardMessage
        assert len(results) == 4

        for i, (platform, shop_id, _, _) in enumerate(platforms):
            msg = results[i]
            assert isinstance(msg, StandardMessage), f"{platform.value} 消息类型错误"
            assert msg.platform == platform, f"{platform.value} platform 字段错误"
            assert msg.shop_id == shop_id, f"{platform.value} shop_id 字段错误"
            assert msg.timestamp.tzinfo is not None, f"{platform.value} 时间戳缺少时区"
            assert msg.message_id != "", f"{platform.value} message_id 为空"
            assert msg.content != "", f"{platform.value} content 为空"

    async def test_shop_id_isolation(self, mock_redis):
        """同平台不同店铺的消息队列严格隔离，不互串。"""
        gw = TaobaoGateway(redis_client=mock_redis)
        shop1 = make_shop(Platform.TAOBAO, "tb_iso_001")
        shop2 = make_shop(Platform.TAOBAO, "tb_iso_002")

        gw._queues["tb_iso_001"] = asyncio.Queue()
        gw._queues["tb_iso_002"] = asyncio.Queue()
        app = gw._build_app([shop1, shop2])

        from aiohttp.test_utils import TestClient, TestServer
        raw1 = {"fromUserId": "buyer_1", "content": "店铺1消息", "msgId": "iso_001", "timestamp": int(time.time() * 1000)}
        raw2 = {"fromUserId": "buyer_2", "content": "店铺2消息", "msgId": "iso_002", "timestamp": int(time.time() * 1000)}

        async with TestClient(TestServer(app)) as client:
            await client.post("/webhook/tb_iso_001", data=json.dumps(raw1))
            await client.post("/webhook/tb_iso_002", data=json.dumps(raw2))

        assert gw._queues["tb_iso_001"].qsize() == 1
        assert gw._queues["tb_iso_002"].qsize() == 1

        msg1 = gw._queues["tb_iso_001"].get_nowait()
        msg2 = gw._queues["tb_iso_002"].get_nowait()

        assert msg1.shop_id == "tb_iso_001"
        assert msg2.shop_id == "tb_iso_002"
        assert msg1.buyer_id != msg2.buyer_id
