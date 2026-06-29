"""影刀 RPA 网关。

替代原有四平台 Webhook 网关。影刀 RPA 机器人抓取到买家消息后，将聊天记录
以 JSON 对象形式 POST 到本服务 /api/message 接口；本服务处理后将回复文本
同步返回给 RPA，由 RPA 写入聊天框。

接口规范（新格式）：
    POST /api/message
    Request Body (JSON):
        {
            "shop_id":    "tb_lamp_001",        // 店铺唯一ID（必填）
            "history": [                        // RPA 会话历史（必填）
                {
                    "platform": "淘宝",
                    "shop": "艾睿斯旗舰店",
                    "buyer": "买家昵称",
                    "product": "商品名或无",
                    "chatList": ["气泡1", "气泡2"],
                    "detail": "订单详情或无"
                }
            ],
            "message_id": "唯一ID",              // 可选，缺省时自动生成
            "last_interaction_at": "2026-06-28T16:30:00+08:00"  // 可选：chatList
                                             // 最后一条气泡的 UTC 时刻（ISO8601）
                                             // 用于人工处理 10 分钟去抖锚点判断
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
    normalize_bubbles_line_breaks,
    normalize_line_breaks,
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


def _parse_interaction_at(value: str | None) -> datetime | None:
    """解析 RPA 客户端传入的 last_interaction_at（ISO8601 字符串）。

    - 接受带时区偏移的 ISO 字符串（如 "2026-06-28T08:30:00+08:00"），统一归一为 UTC
    - 接受 "Z" 后缀
    - 解析失败返回 None（不抛异常，让上层走 fallback 锚点）
    """
    if not value:
        return None
    try:
        # 兼容 "Z" → "+00:00"
        normalized = value.replace("Z", "+00:00") if isinstance(value, str) else value
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            # 无时区信息则按 UTC 处理（兜底，避免 naive datetime 误用）
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        return dt
    except (ValueError, AttributeError) as exc:
        logger.warning("解析 last_interaction_at 失败: %r, err=%s", value, exc)
        return None


def _filter_douyin_bubbles(bubbles: list[str], kefu: str = "") -> list[str]:
    """过滤抖音系统消息气泡"""
    from src.gateway.rpa_parser import filter_douyin_bubbles
    return filter_douyin_bubbles(bubbles, kefu)


async def _resolve_shop_id_by_name(shop_name: str) -> str:
    """根据店铺名称查数据库获取 shop_id。"""
    import os
    try:
        from admin.crud import get_or_create_shop_by_name
        from admin.database import get_db
        conn = await get_db()
        try:
            shop = await get_or_create_shop_by_name(conn, shop_name)
            return shop.shop_id
        finally:
            await conn.close()
    except Exception:
        pass
    return shop_name  # fallback: 用店铺名称本身作为 shop_id


async def resolve_shop_info(shop_name: str) -> tuple[str, str]:
    """根据店铺名称解析 shop_id 和 category_id。

    Returns:
        (shop_id, category_id)
    """
    import os
    try:
        base_url = os.environ.get("ADMIN_API_URL", "http://localhost:8000")
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/shops/resolve-name", params={"name": shop_name})
            if resp.status_code == 200:
                data = resp.json()
                return data.get("shop_id", shop_name), data.get("category_id", "")
    except Exception:
        pass
    return shop_name, ""  # fallback


# ── FastAPI 请求/响应模型 ──────────────────────────────────────────────────────


class RpaMessageRequest(BaseModel):
    """RPA 消息请求模型，支持三种格式：

    1. 新格式（推荐）：传入 history 数组（RPA JSON 格式）
        {"shop_id": "tb_001", "history": [{"platform": "...", "shop": "...", "chatList": [...]}]}

    2. 平铺格式（前端直接传）：直接传 session 对象
        {"platform": "抖音", "shop": "抖音艾睿斯旗舰店", "kefu": "...", "buyer": "...",
         "product": "无", "chatList": [...], "detail": "..."}

    3. 旧格式（兼容）：传入 buyer_id + content + platform
        {"shop_id": "tb_001", "buyer_id": "...", "content": "...", "platform": "taobao"}
    """
    # 通用可选字段
    shop_id: str = ""
    shop: str = ""  # 平铺格式时直接放店铺名；新格式下店铺名在 body.history[0].shop
    platform: str = "taobao"
    message_id: str = ""
    # 新格式
    history: list[dict] = []
    # 平铺格式（前端直接传 session）
    kefu: str = ""
    buyer: str = ""
    product: str = ""
    chatList: list[str] = []
    detail: str = ""
    # 旧格式兼容
    buyer_id: str = ""
    content: str | list | None = None
    # 平台最近互动时间（chatList 最后一条气泡的 UTC 时间戳）
    # 由 RPA 客户端从平台读取后传入；用于人工处理中 10 分钟去抖锚点判断
    # 缺失则 dispatcher 退化为用 ctx 自身时间戳判断（行为兼容）
    last_interaction_at: str | None = None


class RpaMessageResponse(BaseModel):
    reply: str
    escalated: bool


class RpaMessageDebugStep(BaseModel):
    """单个调试步骤，对应前端 StepCard。"""
    step: str = ""
    label: str = ""
    hit: bool | None = None
    reply: str = ""
    error: str = ""
    elapsed_ms: int = 0
    intent: str = ""
    entities: list[str] = []
    rewrite_query: str = ""
    faq_hit: bool = False
    faq_reply: str = ""
    chunks_count: int = 0
    chunks: list[dict] = []
    confidence: int | None = None
    knowledge_chars: int = 0


class RpaMessageDebugResponse(BaseModel):
    """带调试信息的 API 响应。"""
    reply: str
    escalated: bool
    shop_id: str = ""
    shop_name: str = ""
    extracted_buyer: str = ""
    extracted_message: str = ""
    history_turns_count: int = 0
    product_name: str = ""
    steps: list[RpaMessageDebugStep] = []
    final_source: str = ""
    final_reply: str = ""
    confidence: int | None = None
    confidence_threshold: int | None = None
    total_elapsed_ms: int = 0
    error: str = ""


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
        # message_id -> DebugContext（调试步骤，供前端展示）
        from src.utils.trace import DebugContext
        self._pending_debug_ctx: dict[str, DebugContext] = {}

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    def get_debug_context(self, message_id: str):
        """获取指定消息的 DebugContext，用于 API 响应构造。"""
        return self._pending_debug_ctx.get(message_id)

    async def _is_duplicate(self, shop_id: str, message_id: str) -> bool:
        """幂等去重：同一消息 60 秒内不重复处理。"""
        key = f"{_DEDUP_KEY_PREFIX}:{shop_id}:{message_id}"
        try:
            result = await self._redis.set(key, "1", ex=self._dedup_ttl, nx=True)
            return result is None
        except Exception as exc:
            logger.warning("去重 Redis 操作失败，跳过去重: %s", exc)
            return False

    async def _handle_message(self, body: RpaMessageRequest) -> tuple[RpaMessageResponse, str]:
        """处理 RPA 消息请求的核心逻辑（供 FastAPI 路由调用）。

        Returns:
            (RpaMessageResponse, message_id)

        支持三种请求格式：
        1. 平铺格式（前端直接传）：platform/shop/buyer/chatList 等字段平铺在根对象
        2. 新格式：传入 history 数组（RPA JSON 格式），自动解析 buyer/platform/product/detail
        3. 旧格式：传入 buyer_id + content + platform（向后兼容）
        """
        # ── 检测请求格式 ──────────────────────────────────────────────────────────
        # 优先检测平铺格式：根对象有 platform/chatList/buyer 但没有 shop_id/history
        is_flat = bool(body.platform and body.chatList and body.buyer)
        is_new = bool(body.history)

        if is_flat and not is_new:
            # 格式 1：平铺格式
            platform_str = body.platform.strip()
            platform = _PLATFORM_MAP.get(platform_str.lower(), Platform.TAOBAO)
            if platform_str in _CN_PLATFORM_MAP:
                platform = _CN_PLATFORM_MAP[platform_str]
            shop_id = body.shop_id.strip()
            if not shop_id:
                shop_id = (await resolve_shop_info(body.shop.strip()))[0] or body.shop.strip()
            buyer_id = body.buyer.strip()
            bubbles = [str(b) for b in body.chatList]
            # 抖音平台过滤系统消息（基于原始带 \n 的气泡做关键词包含匹配）
            if platform == Platform.DOUYIN:
                bubbles = _filter_douyin_bubbles(bubbles, body.kefu)
            # 注意：先提取最新买家消息 / 历史，再做 || 替换，避免破坏 _clean_bubble 的换行分割
            latest_msg = extract_latest_buyer_message(bubbles)
            history_turns = extract_history_turns(bubbles)
            product_name = "" if body.product in ("无", "none", "") else body.product
            order_detail = normalize_line_breaks(body.detail) if body.detail not in ("无", "none", "") else ""
            kefu = body.kefu.strip()
            # 把气泡内的换行替换为 ||，方便下游展示 / LLM 上下文阅读
            raw_chat_list = normalize_bubbles_line_breaks(bubbles)

        elif is_new:
            # 格式 2：新格式（history 数组）
            session = parse_rpa_json({"history": body.history})
            if session is None:
                raise ValueError("invalid history format")

            buyer_id = session.buyer or "unknown"
            latest_msg = session.latest_buyer_message
            history_turns = session.history_turns
            platform = _PLATFORM_MAP.get(session.platform.lower(), Platform.TAOBAO)
            if session.platform in _CN_PLATFORM_MAP:
                platform = _CN_PLATFORM_MAP[session.platform]
            shop_id = body.shop_id.strip()
            if not shop_id:
                shop_id = (await resolve_shop_info(session.shop))[0] or session.shop
            product_name = session.product
            order_detail = normalize_line_breaks(session.detail) if session.detail else ""
            kefu = session.kefu
            # 把气泡内的换行替换为 ||，方便下游展示 / LLM 上下文阅读
            raw_chat_list = normalize_bubbles_line_breaks(session.filtered_bubbles)

        else:
            # 格式 3：旧格式
            shop_id = body.shop_id.strip()
            if not shop_id:
                raise ValueError("shop_id required")
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
            product_name = ""
            order_detail = ""
            kefu = ""
            # 把气泡内的换行替换为 ||，方便下游展示 / LLM 上下文阅读
            raw_chat_list = normalize_bubbles_line_breaks(bubbles)

        if not shop_id:
            raise ValueError("cannot resolve shop_id from request")
        if not latest_msg:
            logger.warning(
                "无法提取买家消息 shop=%s buyer=%s",
                shop_id,
                buyer_id,
            )
            return RpaMessageResponse(reply="", escalated=True), ""

        history_for_payload = [{"role": t.role, "content": t.content} for t in history_turns]
        message_id = body.message_id.strip() or _make_message_id(shop_id, buyer_id, latest_msg)

        new_trace_id()

        # 去重检查
        if await self._is_duplicate(shop_id, message_id):
            logger.debug("重复消息跳过 shop=%s buyer=%s msg_id=%s", shop_id, buyer_id, message_id)
            return RpaMessageResponse(reply="", escalated=False), message_id

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
                "last_interaction_at": body.last_interaction_at,
            },
            raw_chat_list=raw_chat_list,
            kefu=kefu,
            chat_list_latest_at=_parse_interaction_at(body.last_interaction_at),
        )

        # 创建 Future，等待调度层填充回复
        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending_replies[message_id] = future
        self._escalated[message_id] = False

        # 初始化 DebugContext，供调度层/引擎层记录步骤
        from src.utils.trace import DebugContext, register_debug_context, set_debug_context
        debug_ctx = DebugContext()
        self._pending_debug_ctx[message_id] = debug_ctx
        # 同时按 message_id 注册，供异步子任务（dispatcher 任务链）查找
        register_debug_context(message_id, debug_ctx)
        # 同时设置 contextvar，让同 task 的下游协程也能访问（兜底）
        set_debug_context(debug_ctx)

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
            # 注意：_pending_debug_ctx 不在 finally 中清理，由调用方读取后清理

        return RpaMessageResponse(reply=reply, escalated=escalated), message_id

    # ── FastAPI Router / App ──────────────────────────────────────────────────

    def build_router(self) -> APIRouter:
        """构建并返回 FastAPI APIRouter，注册 /api/message 路由。"""
        router = APIRouter()
        gateway = self  # 闭包引用

        @router.post("/api/message", response_model=RpaMessageResponse)
        async def handle_message(body: RpaMessageRequest) -> RpaMessageResponse:
            try:
                resp, _mid = await gateway._handle_message(body)
                return resp
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
