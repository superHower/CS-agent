"""平台消息发送路由。

根据 StandardMessage 中的 platform 字段，将回复路由到对应平台网关的 send() 方法。
失败时重试 2 次，最终失败抛出 SendFailedException，由调度层降级处理。
"""

import asyncio
import logging

from src.contracts import Platform
from src.exceptions import SendFailedException

logger = logging.getLogger(__name__)

_MAX_RETRY = 2
_RETRY_DELAY_S = 1.0


async def send_reply(
    gateway_registry,
    shop_config,
    buyer_id: str,
    platform: Platform,
    content: str,
    metadata: dict | None = None,
) -> bool:
    """通过对应平台网关发送回复消息。

    Args:
        gateway_registry: GatewayRegistry 单例。
        shop_config: ShopConfig 对象（含 shop_id、platform 等）。
        buyer_id: 买家唯一标识。
        platform: 消息所属平台。
        content: 回复正文（已过滤，非 LLM 原始输出）。
        metadata: 平台特定附加参数（可选）。

    Returns:
        True 表示发送成功。

    Raises:
        SendFailedException: 重试后仍失败。
    """
    try:
        gateway = gateway_registry.get(platform)
    except KeyError as exc:
        raise SendFailedException(
            buyer_id=buyer_id,
            shop_id=shop_config.shop_id,
            context={"reason": f"平台 {platform} 未注册网关"},
        ) from exc

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRY + 1):
        try:
            ok = await gateway.send(
                shop_config=shop_config,
                buyer_id=buyer_id,
                content=content,
                metadata=metadata or {},
            )
            if ok:
                logger.info(
                    "消息发送成功 shop=%s buyer=%s platform=%s",
                    shop_config.shop_id,
                    buyer_id,
                    platform,
                )
                return True
            logger.warning(
                "消息发送返回失败 shop=%s buyer=%s attempt=%d",
                shop_config.shop_id,
                buyer_id,
                attempt,
            )
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "消息发送异常（第%d次）shop=%s buyer=%s: %s",
                attempt,
                shop_config.shop_id,
                buyer_id,
                exc,
            )
        if attempt < _MAX_RETRY:
            await asyncio.sleep(_RETRY_DELAY_S)

    raise SendFailedException(
        buyer_id=buyer_id,
        shop_id=shop_config.shop_id,
        context={"retries": _MAX_RETRY},
    ) from last_exc
