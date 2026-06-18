"""京东（京麦）开放平台网关实现。

通过京麦 Webhook 推送接收买家消息，调用京麦开放 API 发送消息。
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import aiohttp

from src.config.settings import ShopConfig
from src.contracts import MessageSource, Platform, StandardMessage
from src.gateway.base import BaseGateway
from src.utils.trace import new_trace_id

logger = logging.getLogger(__name__)

_JD_API_URL = "https://api.jd.com/routerjson"
_DEDUP_KEY_PREFIX = "msg_dedup"


def _jd_sign(params: dict[str, str], secret: str) -> str:
    """计算京东 API 签名（MD5 方式）。

    secret + 排序后 key=value& + secret，取 MD5 大写。
    """
    sorted_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sign_str = secret + sorted_str + secret
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()


class JDGateway(BaseGateway):
    """京东京麦开放平台网关。"""

    def __init__(
        self,
        redis_client,
        host: str = "0.0.0.0",
        port: int = 8092,
        dedup_ttl: int = 86400,
    ) -> None:
        self._redis = redis_client
        self._host = host
        self._port = port
        self._dedup_ttl = dedup_ttl
        self._queues: dict[str, asyncio.Queue[StandardMessage]] = {}
        self._runner = None

    async def _is_duplicate(self, shop_id: str, message_id: str) -> bool:
        key = f"{_DEDUP_KEY_PREFIX}:{shop_id}:{message_id}"
        try:
            result = await self._redis.set(key, "1", ex=self._dedup_ttl, nx=True)
            return result is None
        except Exception as exc:
            logger.warning("京东消息去重 Redis 失败，跳过去重: %s", exc)
            return False

    def _parse_message(self, shop_config: ShopConfig, raw: dict) -> StandardMessage | None:
        """适配京东推送消息格式。"""
        try:
            # 京东消息字段映射
            buyer_id = str(raw.get("buyerPin") or raw.get("buyer_id") or raw.get("buyerId", ""))
            content = str(raw.get("content") or raw.get("msgContent") or raw.get("message", ""))
            message_id = str(raw.get("msgId") or raw.get("message_id") or raw.get("id", ""))
            ts_ms = raw.get("createTime") or raw.get("timestamp") or int(time.time() * 1000)

            if not buyer_id or not content or not message_id:
                logger.warning("京东消息字段缺失 shop=%s", shop_config.shop_id)
                return None

            timestamp = datetime.fromtimestamp(int(ts_ms) / 1000, tz=UTC)

            return StandardMessage(
                shop_id=shop_config.shop_id,
                platform=Platform.JD,
                buyer_id=buyer_id,
                content=content,
                timestamp=timestamp,
                message_id=message_id,
                source=MessageSource.WEBHOOK,
                raw_payload=raw,
            )
        except Exception as exc:
            logger.error("京东消息解析失败 shop=%s: %s", shop_config.shop_id, exc)
            return None

    def _build_app(self, shop_configs: list[ShopConfig]):
        import asyncio

        from aiohttp import web

        shop_map = {s.shop_id: s for s in shop_configs}
        app = web.Application()

        async def handle_webhook(request: web.Request) -> web.Response:
            shop_id = request.match_info.get("shop_id", "")
            shop_config = shop_map.get(shop_id)
            if shop_config is None:
                return web.Response(status=404, text="shop not found")

            body = await request.read()
            try:
                raw = json.loads(body)
            except json.JSONDecodeError:
                return web.Response(status=400, text="invalid json")

            messages = raw if isinstance(raw, list) else [raw]
            new_trace_id()

            for msg_raw in messages:
                msg = self._parse_message(shop_config, msg_raw)
                if msg is None:
                    continue
                if await self._is_duplicate(shop_id, msg.message_id):
                    continue
                queue = self._queues.setdefault(shop_id, asyncio.Queue())
                await queue.put(msg)
                logger.info("京东消息入队 shop=%s buyer=%s", shop_id, msg.buyer_id)

            return web.Response(status=200, text="success")

        app.router.add_post("/webhook/{shop_id}", handle_webhook)
        return app

    async def listen(self, shop_config: ShopConfig) -> AsyncIterator[StandardMessage]:
        import asyncio

        shop_id = shop_config.shop_id
        queue = self._queues.setdefault(shop_id, asyncio.Queue())

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                return

    async def send(
        self,
        shop_config: ShopConfig,
        buyer_id: str,
        content: str,
        metadata: dict,
    ) -> bool:
        """通过京麦开放 API 发送消息。"""
        params: dict[str, str] = {
            "method": "jingdong.kefu.im.sendMsg",
            "app_key": shop_config.api_key,
            "timestamp": str(int(time.time())),
            "v": "2.0",
            "format": "json",
            "buyer_pin": buyer_id,
            "content": content,
        }
        params["sign"] = _jd_sign(params, shop_config.api_secret)

        try:
            timeout = aiohttp.ClientTimeout(total=3.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(_JD_API_URL, data=params) as resp:
                    resp_json = await resp.json(content_type=None)

            if resp_json.get("error_response") or resp_json.get("code", 0) != 0:
                logger.error(
                    "京东发送失败 shop=%s buyer=%s resp=%s",
                    shop_config.shop_id,
                    buyer_id,
                    resp_json,
                )
                return False

            logger.info("京东消息发送成功 shop=%s buyer=%s", shop_config.shop_id, buyer_id)
            return True

        except aiohttp.ClientError as exc:
            logger.error("京东发送网络异常 shop=%s: %s", shop_config.shop_id, exc)
            return False
        except Exception as exc:
            logger.error("京东发送未知异常 shop=%s: %s", shop_config.shop_id, exc, exc_info=True)
            return False
