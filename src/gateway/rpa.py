"""影刀 RPA 网关。

替代原有四平台 Webhook 网关。影刀 RPA 机器人抓取到买家消息后，将聊天记录
以 JSON 对象形式 POST 到本服务 /api/message 接口；本服务处理后将回复文本
同步返回给 RPA，由 RPA 写入聊天框。

接口规范（新格式）：
    POST /api/message
    Request Body (JSON):
        {
            "shop_id":    "tb_lamp_001",   // 店铺唯一ID（必填）
            "history": [                   // RPA 会话历史（必填）
                {
                    "platform": "淘宝",
                    "shop": "艾睿斯旗舰店",
                    "buyer": "买家昵称",
                    "product": "商品名或无",
                    "chatList": ["气泡1", "气泡2"],
                    "detail": "订单详情或无"
                }
            ],
            "message_id": "唯一ID"        // 可选，缺省时自动生成
        }

    兼容旧格式（直接传 content/buyer_id/platform）：
        {
            "shop_id":  "tb_lamp_001",
            "buyer_id": "买家昵称",
            "content":  ["气泡1", "气泡2"],
            "platform": "taobao",
            "message_id": "唯一ID"
        }

    Response Body (JSON):
        {
            "reply":     "回复文本",  // 自动回复内容；转人工时为空字符串
            "escalated": false        // true 表示已转人工，RPA 不需要输入回复
        }
"""

import asyncio
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import APIRouter
from pydantic import BaseModel

from src.config.settings import ShopConfig
from src.contracts import MessageSource, Platform, StandardMessage
from src.gateway.base import BaseGateway
from src.gateway.rpa_parser import (
    extract_history_turns,
    extract_latest_buyer_message,
    parse_rpa_json,
)
from src.utils.trace import new_trace_id

logger = logging.getLogger(__name__)

# 消息去重 Redis key 前缀
_DEDUP_KEY_PREFIX = "msg_dedup"

_PLATFORM_MAP = {
    "taobao": Platform.TAOBAO,
    "pinduoduo": Platform.PINDUODUO,
    "jd": Platform.JD,
    "jingdong": Platform.JD,
    "douyin": Platform.DOUYIN,
}

# 中文平台名 → Platform 映射（RPA 新格式传入中文名）
_CN_PLATFORM_MAP = {
    "淘宝": Platform.TAOBAO,
    "拼多多": Platform.PINDUODUO,
    "京东": Platform.JD,
    "抖音": Platform.DOUYIN,
}


def _make_message_id(shop_id: str, buyer_id: str, content: str) -> str:
    """根据内容生成消息唯一 ID（用于去重）。"""
    raw = f"{shop_id}:{buyer_id}:{content}:{int(time.time() // 60)}"
    return hashlib.md5(raw.encode()).hexdigest()


# ── FastAPI 请求/响应模型 ──────────────────────────────────────────────────────


class RpaMessageRequest(BaseModel):
    shop_id: str
    # 新格式：RPA JSON 会话历史
    history: list[dict] = []
    # 旧格式兼容字段
    buyer_id: str = ""
    content: str | list | None = None
    platform: str = "taobao"
    message_id: str = ""


class RpaMessageResponse(BaseModel):
    reply: str
    escalated: bool


class RpaGateway(BaseGateway):
    """影刀 RPA 消息网关。

    职责：
    - 提供 FastAPI router，注册 POST /api/message 路由。
    - 解析聊天记录气泡数组，提取买家最新消息与历史上下文。
    - 将标准化消息投入内部队列供调度层消费。
    - 调度层处理完成后，通过 asyncio.Future 将回复同步返回给 RPA HTTP 响应。
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        dedup_ttl: int = 86400,
        reply_timeout: float = 30.0,
    ) -> None:
        """初始化 RPA 网关。

        Args:
            redis_client: 异步 Redis 客户端（用于消息去重）。
            dedup_ttl: 消息去重 TTL（秒），默认 24 小时。
            reply_timeout: 等待调度层回复的超时秒数，超时返回空回复并转人工。
        """
        self._redis = redis_client
        self._dedup_ttl = dedup_ttl
        self._reply_timeout = reply_timeout

        # shop_id -> asyncio.Queue[StandardMessage]
        self._queues: dict[str, asyncio.Queue[StandardMessage]] = {}
        # message_id -> asyncio.Future[str]（reply 文本）
        self._pending_replies: dict[str, asyncio.Future[str]] = {}
        # message_id -> bool（是否转人工）
        self._escalated: dict[str, bool] = {}

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    async def _is_duplicate(self, shop_id: str, message_id: str) -> bool:
        """幂等去重：同一消息 60 秒内不重复处理。"""
        key = f"{_DEDUP_KEY_PREFIX}:{shop_id}:{message_id}"
        try:
            result = await self._redis.set(key, "1", ex=self._dedup_ttl, nx=True)
            return result is None
        except Exception as exc:
            logger.warning("去重 Redis 操作失败，跳过去重: %s", exc)
            return False

    async def _handle_message(self, body: RpaMessageRequest) -> RpaMessageResponse:
        """处理 RPA 消息请求的核心逻辑（供 FastAPI 路由调用）。

        支持两种请求格式：
        1. 新格式：传入 history 数组（RPA JSON 格式），自动解析 buyer/platform/product/detail
        2. 旧格式：传入 buyer_id + content + platform（向后兼容）
        """
        shop_id = body.shop_id.strip()
        if not shop_id:
            raise ValueError("shop_id required")

        message_id = body.message_id.strip()
        product_name = ""
        order_detail = ""
        kefu = ""
        raw_chat_list: list[str] = []

        if body.history:
            # 新格式：从 history JSON 解析
            session = parse_rpa_json({"history": body.history})
            if session is None:
                raise ValueError("invalid history format")

            buyer_id = session.buyer or "unknown"
            latest_msg = session.latest_buyer_message
            history_turns = session.history_turns
            platform = _PLATFORM_MAP.get(session.platform.lower(), Platform.TAOBAO)
            if session.platform in _CN_PLATFORM_MAP:
                platform = _CN_PLATFORM_MAP[session.platform]
            product_name = session.product
            order_detail = session.detail
            kefu = session.kefu
            # 抖音：raw_chat_list 使用已过滤的气泡（系统消息已移除）
            raw_chat_list = session.filtered_bubbles
        else:
            # 旧格式：兼容 buyer_id + content + platform
            buyer_id = body.buyer_id.strip()
            raw_content = body.content
            platform_str = body.platform.strip().lower()

            if not buyer_id:
                raise ValueError("buyer_id required when not using history format")
            if not raw_content:
                raise ValueError("content required when not using history format")

            if isinstance(raw_content, str):
                bubbles = [raw_content]
            elif isinstance(raw_content, list):
                bubbles = [str(b) for b in raw_content]
            else:
                raise ValueError("content must be string or array")

            platform = _PLATFORM_MAP.get(platform_str, Platform.TAOBAO)
            latest_msg = extract_latest_buyer_message(bubbles)
            history_turns = extract_history_turns(bubbles)

        if not latest_msg:
            logger.warning(
                "无法提取买家消息 shop=%s buyer=%s",
                shop_id,
                buyer_id,
            )
            return RpaMessageResponse(reply="", escalated=True)

        history_for_payload = [{"role": t.role, "content": t.content} for t in history_turns]

        # 生成 message_id
        if not message_id:
            message_id = _make_message_id(shop_id, buyer_id, latest_msg)

        new_trace_id()

        # 去重检查
        if await self._is_duplicate(shop_id, message_id):
            logger.debug("重复消息跳过 shop=%s buyer=%s msg_id=%s", shop_id, buyer_id, message_id)
            return RpaMessageResponse(reply="", escalated=False)

        msg = StandardMessage(
            shop_id=shop_id,
            platform=platform,
            buyer_id=buyer_id,
            content=latest_msg,
            timestamp=datetime.now(tz=UTC),
            message_id=message_id,
            source=MessageSource.RPA,
            product_name=product_name,
            order_detail=order_detail,
            raw_payload={
                "history": history_for_payload,
                "bubbles_count": len(history_for_payload) + 1,
            },
            # 抖音专用字段（filtered_bubbles 已过滤系统消息）
            raw_chat_list=raw_chat_list,
            kefu=kefu if body.history else "",
        )

        # 创建 Future，等待调度层填充回复
        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending_replies[message_id] = future
        self._escalated[message_id] = False

        # 投入队列
        queue = self._queues.setdefault(shop_id, asyncio.Queue())
        await queue.put(msg)
        logger.info(
            "RPA 消息入队 shop=%s buyer=%s msg_id=%s content=%r",
            shop_id,
            buyer_id,
            message_id,
            latest_msg[:50],
        )

        # 同步等待调度层回复
        try:
            reply = await asyncio.wait_for(future, timeout=self._reply_timeout)
            escalated = self._escalated.get(message_id, False)
        except TimeoutError:
            logger.warning(
                "等待回复超时 shop=%s buyer=%s msg_id=%s，转人工",
                shop_id,
                buyer_id,
                message_id,
            )
            reply = ""
            escalated = True
        finally:
            self._pending_replies.pop(message_id, None)
            self._escalated.pop(message_id, None)

        return RpaMessageResponse(reply=reply, escalated=escalated)

    # ── FastAPI Router / App ──────────────────────────────────────────────────

    def build_router(self) -> APIRouter:
        """构建并返回 FastAPI APIRouter，注册 /api/message 路由。"""
        router = APIRouter()
        gateway = self  # 闭包引用

        @router.post("/api/message", response_model=RpaMessageResponse)
        async def handle_message(body: RpaMessageRequest) -> RpaMessageResponse:
            try:
                return await gateway._handle_message(body)
            except ValueError as exc:
                from fastapi import HTTPException

                raise HTTPException(status_code=400, detail=str(exc))

        return router

    def _build_app(self):
        """构建独立 FastAPI 应用（用于测试）。"""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(self.build_router())

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        return app

    # ── BaseGateway 接口实现 ──────────────────────────────────────────────────

    async def listen(self, shop_config: ShopConfig) -> AsyncIterator[StandardMessage]:
        """从内部队列持续产出指定店铺的标准化消息。"""
        shop_id = shop_config.shop_id
        queue: asyncio.Queue[StandardMessage] = self._queues.setdefault(shop_id, asyncio.Queue())

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("shop=%s RPA 消息监听已停止", shop_id)
                return

    async def send(
        self,
        shop_config: ShopConfig,
        buyer_id: str,
        content: str,
        metadata: dict,
    ) -> bool:
        """将回复文本填充到对应请求的 Future，由 HTTP 响应返回给 RPA。"""
        message_id = metadata.get("message_id", "")
        escalated = bool(metadata.get("escalated", False))

        future = self._pending_replies.get(message_id)
        if future is None:
            logger.warning(
                "找不到对应 Future shop=%s buyer=%s msg_id=%s，请求可能已超时",
                shop_config.shop_id,
                buyer_id,
                message_id,
            )
            return False

        if not future.done():
            self._escalated[message_id] = escalated
            future.set_result(content)
            logger.info(
                "回复已填充 shop=%s buyer=%s msg_id=%s escalated=%s",
                shop_config.shop_id,
                buyer_id,
                message_id,
                escalated,
            )
        return True
