"""RPA 网关单元测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.contracts import MessageSource, Platform
from src.gateway.rpa import RpaGateway
from src.gateway.rpa_parser import (
    extract_history_turns,
    extract_latest_buyer_message,
    parse_chat_bubbles,
    parse_rpa_json,
)


# ── rpa_parser 测试 ──────────────────────────────────────────────────────────


DOUYIN_BUBBLES = [
    "昨天 12:29\n给个链接\n昨天 12:29:05",
    "智能客服\n亲，您可以直接在商品详情页选择喜欢的规格下单哦~\n昨天 12:29:13\n已读\n抖音电商智能客服发送",
    "超薄吸顶灯，家居照明优选\n客厅吸顶灯2026新款\n¥\n19\n.00\n节能环保：30小时1度电\n昨天 12:29:13\n已读\n抖音电商智能客服发送",
    "边框是黑色的嘛\n昨天 12:29:57",
    "智能客服\n亲，这款边框是银灰色\n昨天 12:30:06\n已读\n抖音电商智能客服发送",
    "昨天 12:31\n我看你发的链接上的图是金色的\n昨天 12:31:30",
    "智能客服\n抱歉让您误会啦～实物以您选择的规格为准\n昨天 12:31:37\n已读\n抖音电商智能客服发送",
    "银灰色可以\n昨天 12:32:19",
    "客服清博照明运营接入",
    "是白光吧\n昨天 12:32:48",
    "昨天 12:34\n当前会话已长时间未回复，若后续仍未回复，平台可能主动介入处理。",
    "用户超时未回复，系统关闭会话",
]


class TestRpaParser:
    def test_parse_bubbles_roles(self):
        turns = parse_chat_bubbles(DOUYIN_BUBBLES)
        roles = [t.role for t in turns]
        # 系统通知被过滤
        assert "system" not in roles
        # 有 user 和 assistant
        assert "user" in roles
        assert "assistant" in roles

    def test_extract_latest_buyer_message(self):
        # 最后一条 user 消息是 "是白光吧"
        msg = extract_latest_buyer_message(DOUYIN_BUBBLES)
        assert msg == "是白光吧"

    def test_extract_latest_buyer_message_simple(self):
        bubbles = ["你好\n昨天 10:00", "智能客服\n您好！\n已读\n抖音电商智能客服发送", "发货了吗\n昨天 10:05"]
        msg = extract_latest_buyer_message(bubbles)
        assert msg == "发货了吗"

    def test_extract_history_turns(self):
        history = extract_history_turns(DOUYIN_BUBBLES)
        # 历史不含最后一条 user 消息（"是白光吧"）
        contents = [t.content for t in history]
        assert "是白光吧" not in contents
        # 历史有买家和客服
        roles = {t.role for t in history}
        assert "user" in roles

    def test_extract_history_max_turns(self):
        history = extract_history_turns(DOUYIN_BUBBLES, max_turns=3)
        assert len(history) <= 3

    def test_no_buyer_message_returns_none(self):
        bubbles = [
            "智能客服\n您好！\n已读\n抖音电商智能客服发送",
            "当前会话已长时间未回复，若后续仍未回复，平台可能主动介入处理。",
        ]
        assert extract_latest_buyer_message(bubbles) is None

    def test_string_content_cleaned(self):
        bubbles = ["边框是黑色的嘛\n昨天 12:29:57"]
        msg = extract_latest_buyer_message(bubbles)
        assert msg == "边框是黑色的嘛"
        assert "昨天" not in msg


# ── parse_rpa_json 测试 ──────────────────────────────────────────────────────


RPA_JSON_PAYLOAD = {
    "history": [
        {
            "platform": "淘宝",
            "shop": "艾睿斯旗舰店",
            "buyer": "测试买家",
            "product": "无",
            "chatList": DOUYIN_BUBBLES,
            "detail": "无",
        }
    ]
}


class TestParseRpaJson:
    def test_parse_basic(self):
        result = parse_rpa_json(RPA_JSON_PAYLOAD)
        assert result is not None
        assert result.platform == "淘宝"
        assert result.shop == "艾睿斯旗舰店"
        assert result.buyer == "测试买家"
        assert result.product == ""  # "无" → ""
        assert result.detail == ""   # "无" → ""

    def test_parse_extracts_latest_message(self):
        result = parse_rpa_json(RPA_JSON_PAYLOAD)
        assert result is not None
        assert result.latest_buyer_message == "是白光吧"

    def test_parse_takes_last_history_item(self):
        payload = {
            "history": [
                {
                    "platform": "淘宝",
                    "shop": "店A",
                    "buyer": "旧买家",
                    "product": "无",
                    "chatList": ["旧消息\n10:00"],
                    "detail": "无",
                },
                {
                    "platform": "抖音",
                    "shop": "店B",
                    "buyer": "新买家",
                    "product": "无",
                    "chatList": ["新消息\n11:00"],
                    "detail": "无",
                },
            ]
        }
        result = parse_rpa_json(payload)
        assert result is not None
        assert result.buyer == "新买家"
        assert result.platform == "抖音"

    def test_parse_with_product_name(self):
        payload = {
            "history": [
                {
                    "platform": "淘宝",
                    "shop": "店A",
                    "buyer": "买家",
                    "product": "客厅吸顶灯48W",
                    "chatList": ["好安装吗\n10:00"],
                    "detail": "无",
                }
            ]
        }
        result = parse_rpa_json(payload)
        assert result is not None
        assert result.product == "客厅吸顶灯48W"

    def test_parse_with_order_detail(self):
        payload = {
            "history": [
                {
                    "platform": "淘宝",
                    "shop": "店A",
                    "buyer": "买家",
                    "product": "无",
                    "chatList": ["退款\n10:00"],
                    "detail": "申通快递 订单已发货",
                }
            ]
        }
        result = parse_rpa_json(payload)
        assert result is not None
        assert result.detail == "申通快递 订单已发货"

    def test_parse_missing_history_returns_none(self):
        assert parse_rpa_json({}) is None
        assert parse_rpa_json({"history": []}) is None

    def test_parse_invalid_session_returns_none(self):
        assert parse_rpa_json({"history": ["not a dict"]}) is None


# ── RpaGateway HTTP 接口测试 ──────────────────────────────────────────────────


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    # set 返回 True 表示首次写入（不重复）
    redis.set = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def rpa_gateway(mock_redis):
    return RpaGateway(redis_client=mock_redis, reply_timeout=2.0)


@pytest.fixture
def shop_config():
    cfg = MagicMock()
    cfg.shop_id = "dy_lamp_001"
    cfg.platform = Platform.DOUYIN
    cfg.api_key = ""
    cfg.api_secret = ""
    return cfg


@pytest.mark.asyncio
async def test_health_endpoint(rpa_gateway):
    app = rpa_gateway._build_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_missing_required_fields(rpa_gateway):
    app = rpa_gateway._build_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/message", json={"shop_id": "dy_lamp_001"})
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_invalid_json(rpa_gateway):
    app = rpa_gateway._build_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/message", content=b"not json", headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_no_buyer_message_in_bubbles(rpa_gateway):
    """气泡里找不到买家消息，应返回 escalated=True。"""
    app = rpa_gateway._build_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/message",
            json={
                "shop_id": "dy_lamp_001",
                "buyer_id": "user123",
                "content": ["智能客服\n您好！\n已读\n抖音电商智能客服发送"],
                "platform": "douyin",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["escalated"] is True


@pytest.mark.asyncio
async def test_message_enqueued_and_reply_returned(rpa_gateway):
    """消息入队后，模拟调度层填充回复，验证 HTTP 响应包含正确 reply。"""
    app = rpa_gateway._build_app()

    async def fake_scheduler():
        await asyncio.sleep(0.05)
        assert len(rpa_gateway._pending_replies) == 1
        msg_id = next(iter(rpa_gateway._pending_replies))
        shop = MagicMock()
        shop.shop_id = "dy_lamp_001"
        await rpa_gateway.send(
            shop_config=shop,
            buyer_id="user123",
            content="您好，这款边框是银灰色的哦～",
            metadata={"message_id": msg_id, "escalated": False},
        )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        sched_task = asyncio.create_task(fake_scheduler())
        resp = await client.post(
            "/api/message",
            json={
                "shop_id": "dy_lamp_001",
                "buyer_id": "user123",
                "content": DOUYIN_BUBBLES,
                "platform": "douyin",
            },
        )
        await sched_task
        assert resp.status_code == 200
        data = resp.json()
        assert data["reply"] == "您好，这款边框是银灰色的哦～"
        assert data["escalated"] is False


@pytest.mark.asyncio
async def test_escalated_reply(rpa_gateway):
    """调度层填充 escalated=True，响应应返回 escalated=True、reply 为空。"""
    app = rpa_gateway._build_app()

    async def fake_escalate():
        await asyncio.sleep(0.05)
        assert len(rpa_gateway._pending_replies) == 1
        msg_id = next(iter(rpa_gateway._pending_replies))
        shop = MagicMock()
        shop.shop_id = "dy_lamp_001"
        await rpa_gateway.send(
            shop_config=shop,
            buyer_id="user123",
            content="",
            metadata={"message_id": msg_id, "escalated": True},
        )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        sched_task = asyncio.create_task(fake_escalate())
        resp = await client.post(
            "/api/message",
            json={
                "shop_id": "dy_lamp_001",
                "buyer_id": "user123",
                "content": ["退款 投诉\n昨天 10:00"],
                "platform": "douyin",
            },
        )
        await sched_task
        assert resp.status_code == 200
        data = resp.json()
        assert data["reply"] == ""
        assert data["escalated"] is True


@pytest.mark.asyncio
async def test_platform_mapping(rpa_gateway):
    """验证 jingdong 映射到 JD 平台。"""
    app = rpa_gateway._build_app()
    received_msgs = []

    async def consume():
        queue = rpa_gateway._queues.setdefault("jd_test_001", asyncio.Queue())
        try:
            msg = await asyncio.wait_for(queue.get(), timeout=1.0)
            received_msgs.append(msg)
        except TimeoutError:
            pass

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        consume_task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        await client.post(
            "/api/message",
            json={
                "shop_id": "jd_test_001",
                "buyer_id": "buyer_jd",
                "content": ["帮我查一下订单\n今天 09:00"],
                "platform": "jingdong",
            },
        )
        await asyncio.wait_for(asyncio.shield(consume_task), timeout=2.0)

    if received_msgs:
        assert received_msgs[0].platform == Platform.JD


@pytest.mark.asyncio
async def test_reply_timeout_returns_escalated(rpa_gateway):
    """调度层超时未回复，HTTP 响应应返回 escalated=True。"""
    rpa_gateway._reply_timeout = 0.1  # 缩短超时便于测试
    app = rpa_gateway._build_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/message",
            json={
                "shop_id": "dy_lamp_001",
                "buyer_id": "user999",
                "content": ["这个灯多少瓦\n今天 10:00"],
                "platform": "douyin",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["escalated"] is True
        assert data["reply"] == ""


@pytest.mark.asyncio
async def test_new_rpa_json_format(rpa_gateway):
    """测试新 RPA JSON 格式（history 数组），验证能正确解析并入队。"""
    app = rpa_gateway._build_app()
    received_msgs = []

    async def consume():
        queue = rpa_gateway._queues.setdefault("tb_lamp_001", asyncio.Queue())
        try:
            msg = await asyncio.wait_for(queue.get(), timeout=1.0)
            received_msgs.append(msg)
        except TimeoutError:
            pass

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        consume_task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        await client.post(
            "/api/message",
            json={
                "shop_id": "tb_lamp_001",
                "history": [
                    {
                        "platform": "淘宝",
                        "shop": "艾睿斯旗舰店",
                        "buyer": "测试买家",
                        "product": "客厅吸顶灯48W",
                        "chatList": ["好安装吗\n10:00"],
                        "detail": "申通快递 已发货",
                    }
                ],
            },
        )
        await asyncio.wait_for(asyncio.shield(consume_task), timeout=2.0)

    if received_msgs:
        msg = received_msgs[0]
        assert msg.platform == Platform.TAOBAO
        assert msg.buyer_id == "测试买家"
        assert msg.content == "好安装吗"
        assert msg.product_name == "客厅吸顶灯48W"
        assert msg.order_detail == "申通快递 已发货"
