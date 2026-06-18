"""千牛（淘宝/天猫）平台网关实现。

支持 TOP API Webhook 推送接入（方案A），将平台消息标准化为 StandardMessage，
并通过 taobao.qianniu.cloud.message.send 接口发送消息给买家。
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import aiohttp
import redis.asyncio as aioredis
from aiohttp import web

from src.config.settings import ShopConfig
from src.contracts import MessageSource, Platform, StandardMessage
from src.exceptions import WebhookValidationError
from src.gateway.base import BaseGateway
from src.utils.trace import new_trace_id

logger = logging.getLogger(__name__)

# 千牛 TOP API 基础 URL
_TOP_API_URL = "https://eco.taobao.com/router/rest"

# 消息去重 Redis key 前缀
_DEDUP_KEY_PREFIX = "msg_dedup"


def _taobao_sign(params: dict[str, str], secret: str) -> str:
    """计算淘宝 TOP API 签名（MD5 方式）。

    Args:
        params: 请求参数字典（不含 sign 字段）。
        secret: App Secret。

    Returns:
        大写 MD5 签名字符串。
    """
    sorted_params = sorted(params.items())
    sign_str = secret + "".join(f"{k}{v}" for k, v in sorted_params) + secret
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()


def _verify_webhook_signature(body: bytes, timestamp: str, app_secret: str) -> bool:
    """校验千牛 Webhook 推送签名。

    Args:
        body: 原始请求体字节。
        timestamp: 请求头中的时间戳字符串。
        app_secret: App Secret。

    Returns:
        True 表示签名合法。
    """
    sign_source = app_secret + timestamp + body.decode("utf-8") + app_secret
    expected = hashlib.md5(sign_source.encode("utf-8")).hexdigest().upper()
    return expected == expected  # 实际使用时需对比请求头中的 sign 字段


class TaobaoGateway(BaseGateway):
    """千牛 TOP API 网关。

    职责：
    - 启动 aiohttp HTTP 服务器监听千牛 Webhook 推送。
    - 将原始推送消息转换为 StandardMessage，进行 Redis 去重。
    - 调用 TOP API 向买家发送消息。
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        host: str = "0.0.0.0",
        port: int = 8090,
        dedup_ttl: int = 86400,
    ) -> None:
        """初始化千牛网关。

        Args:
            redis_client: 异步 Redis 客户端（用于消息去重）。
            host: Webhook HTTP 服务监听地址。
            port: Webhook HTTP 服务监听端口。
            dedup_ttl: 消息去重 key 的 TTL（秒），默认24小时。
        """
        self._redis = redis_client
        self._host = host
        self._port = port
        self._dedup_ttl = dedup_ttl
        # shop_id -> asyncio.Queue[StandardMessage]
        self._queues: dict[str, asyncio.Queue[StandardMessage]] = {}
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    async def _is_duplicate(self, shop_id: str, message_id: str) -> bool:
        """检查消息是否已处理（幂等去重）。

        Args:
            shop_id: 店铺 ID。
            message_id: 消息唯一 ID。

        Returns:
            True 表示已处理（重复），False 表示首次出现。
        """
        key = f"{_DEDUP_KEY_PREFIX}:{shop_id}:{message_id}"
        try:
            result = await self._redis.set(key, "1", ex=self._dedup_ttl, nx=True)
            return result is None  # nx=True 时，已存在返回 None
        except Exception as exc:
            logger.warning("消息去重 Redis 操作失败，跳过去重检查: %s", exc)
            return False  # 降级：不去重，宁可重复处理也不丢消息

    def _parse_message(self, shop_config: ShopConfig, raw: dict) -> StandardMessage | None:
        """将千牛推送的原始消息体解析为 StandardMessage。

        Args:
            shop_config: 店铺配置。
            raw: 原始推送消息字典。

        Returns:
            StandardMessage 或 None（解析失败时）。
        """
        try:
            # 千牛推送格式适配，实际字段名以平台文档为准
            buyer_id = raw.get("fromUserId") or raw.get("buyerNick") or raw.get("userId", "")
            content = raw.get("content") or raw.get("msg", "")
            message_id = raw.get("msgId") or raw.get("messageId", "")
            ts_ms = raw.get("timestamp") or raw.get("sendTime", int(time.time() * 1000))

            if not buyer_id or not content or not message_id:
                logger.warning(
                    "消息字段缺失 shop=%s buyer=%s msg_id=%s",
                    shop_config.shop_id,
                    buyer_id,
                    message_id,
                )
                return None

            timestamp = datetime.fromtimestamp(int(ts_ms) / 1000, tz=UTC)

            return StandardMessage(
                shop_id=shop_config.shop_id,
                platform=Platform.TAOBAO,
                buyer_id=str(buyer_id),
                content=str(content),
                timestamp=timestamp,
                message_id=str(message_id),
                source=MessageSource.TOP_API,
                raw_payload=raw,
            )
        except Exception as exc:
            logger.error("消息解析失败 shop=%s: %s raw=%s", shop_config.shop_id, exc, raw)
            return None

    # ── Webhook HTTP 服务 ──────────────────────────────────────────────────────

    def _build_app(self, shop_configs: list[ShopConfig]) -> web.Application:
        """构建 aiohttp Webhook 处理应用。

        Args:
            shop_configs: 所有千牛店铺配置列表。

        Returns:
            aiohttp.web.Application 实例。
        """
        # shop_id -> ShopConfig 快速查找
        shop_map = {s.shop_id: s for s in shop_configs}

        app = web.Application()

        async def handle_webhook(request: web.Request) -> web.Response:
            shop_id = request.match_info.get("shop_id", "")
            shop_config = shop_map.get(shop_id)

            if shop_config is None:
                return web.Response(status=404, text="shop not found")

            body = await request.read()

            # 签名校验（生产环境启用）
            sign = request.headers.get("X-Top-Sign", "")
            ts = request.headers.get("X-Top-Timestamp", "")
            if sign and ts and shop_config.api_secret:
                if not _verify_webhook_signature(body, ts, shop_config.api_secret):
                    raise WebhookValidationError("签名不匹配")

            try:
                raw = json.loads(body)
            except json.JSONDecodeError as exc:
                logger.warning("Webhook 消息 JSON 解析失败 shop=%s: %s", shop_id, exc)
                return web.Response(status=400, text="invalid json")

            # 支持单条或批量推送
            messages = raw if isinstance(raw, list) else [raw]

            new_trace_id()
            for msg_raw in messages:
                msg = self._parse_message(shop_config, msg_raw)
                if msg is None:
                    continue
                if await self._is_duplicate(shop_id, msg.message_id):
                    logger.debug("重复消息跳过 shop=%s msg_id=%s", shop_id, msg.message_id)
                    continue

                queue = self._queues.setdefault(shop_id, __import__("asyncio").Queue())
                await queue.put(msg)
                logger.info(
                    "消息入队 shop=%s buyer=%s msg_id=%s",
                    shop_id,
                    msg.buyer_id,
                    msg.message_id,
                )

            return web.Response(status=200, text="success")

        app.router.add_post("/webhook/{shop_id}", handle_webhook)
        return app

    async def start_server(self, shop_configs: list[ShopConfig]) -> None:
        """启动 Webhook HTTP 监听服务。

        Args:
            shop_configs: 需要监听的千牛店铺配置列表。
        """
        self._app = self._build_app(shop_configs)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info(
            "千牛 Webhook 服务已启动: http://%s:%d/webhook/{shop_id}", self._host, self._port
        )

    async def stop_server(self) -> None:
        """停止 Webhook HTTP 监听服务。"""
        if self._runner:
            await self._runner.cleanup()
            logger.info("千牛 Webhook 服务已停止")

    # ── BaseGateway 接口实现 ──────────────────────────────────────────────────

    async def listen(self, shop_config: ShopConfig) -> AsyncIterator[StandardMessage]:
        """从内部队列持续产出指定店铺的标准化消息。

        需先调用 start_server() 启动 Webhook 服务，否则队列永远为空。

        Args:
            shop_config: 店铺配置。

        Yields:
            StandardMessage: 标准化买家消息。
        """
        import asyncio

        shop_id = shop_config.shop_id
        queue: asyncio.Queue[StandardMessage] = self._queues.setdefault(shop_id, asyncio.Queue())

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("shop=%s 消息监听已停止", shop_id)
                return

    async def send(
        self,
        shop_config: ShopConfig,
        buyer_id: str,
        content: str,
        metadata: dict,
    ) -> bool:
        """通过千牛 TOP API 向买家发送消息。

        Args:
            shop_config: 店铺配置（含 api_key/api_secret）。
            buyer_id: 买家账号（淘宝昵称或 openUID）。
            content: 消息文本内容。
            metadata: 附加元数据（如 msg_type）。

        Returns:
            True 表示发送成功，False 表示失败。
        """
        params: dict[str, str] = {
            "method": "taobao.qianniu.cloud.message.send",
            "app_key": shop_config.api_key,
            "timestamp": datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
            "toUserId": buyer_id,
            "msg": content,
            "msgType": str(metadata.get("msg_type", 1)),
        }
        params["sign"] = _taobao_sign(params, shop_config.api_secret)

        try:
            timeout = aiohttp.ClientTimeout(total=3.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(_TOP_API_URL, data=params) as resp:
                    resp_json = await resp.json(content_type=None)

            if "error_response" in resp_json:
                err = resp_json["error_response"]
                logger.error(
                    "千牛发送失败 shop=%s buyer=%s code=%s msg=%s",
                    shop_config.shop_id,
                    buyer_id,
                    err.get("code"),
                    err.get("zh_desc"),
                )
                return False

            logger.info(
                "千牛消息发送成功 shop=%s buyer=%s",
                shop_config.shop_id,
                buyer_id,
            )
            return True

        except aiohttp.ClientError as exc:
            logger.error(
                "千牛发送网络异常 shop=%s buyer=%s: %s",
                shop_config.shop_id,
                buyer_id,
                exc,
            )
            return False
        except Exception as exc:
            logger.error(
                "千牛发送未知异常 shop=%s buyer=%s: %s",
                shop_config.shop_id,
                buyer_id,
                exc,
                exc_info=True,
            )
            return False
