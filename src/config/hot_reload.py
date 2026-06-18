"""Redis Pub/Sub 配置热更新监听器。

订阅 config_updated 频道，收到消息后调用 reload_config() 原子化更新全局单例。
"""

import asyncio
import logging

import redis.asyncio as aioredis

from src.config.settings import get_config, reload_config

logger = logging.getLogger(__name__)

CONFIG_CHANNEL = "config_updated"


async def start_config_watcher() -> None:
    """启动 Redis Pub/Sub 配置变更监听器（持续运行的后台协程）。

    监听 config_updated 频道；Redis 不可用时每 30 秒重试连接，
    不影响主服务运行。
    """
    while True:
        try:
            cfg = get_config()
            redis_cfg = cfg.redis
            client = aioredis.Redis(
                host=redis_cfg.host,
                port=redis_cfg.port,
                db=redis_cfg.db,
                password=redis_cfg.password,
                socket_timeout=redis_cfg.socket_timeout,
                socket_connect_timeout=redis_cfg.socket_connect_timeout,
                decode_responses=True,
            )
            async with client.pubsub() as pubsub:
                await pubsub.subscribe(CONFIG_CHANNEL)
                logger.info("配置热更新监听器已启动，订阅频道: %s", CONFIG_CHANNEL)
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        logger.info(
                            "收到配置更新通知: %s，开始热更新...",
                            message.get("data"),
                        )
                        try:
                            await reload_config()
                        except Exception as exc:
                            logger.error("配置热更新失败: %s", exc)
        except (ConnectionError, OSError) as exc:
            logger.warning("Redis 连接失败，配置热更新暂停，30s 后重试: %s", exc)
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            logger.info("配置热更新监听器已停止")
            return
        except Exception as exc:
            logger.error("配置热更新监听器异常: %s", exc, exc_info=True)
            await asyncio.sleep(30)
