"""FAQ 精确缓存，基于 Redis 存储问题→回复映射，命中直接返回无需 LLM。"""

import hashlib
import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_FAQ_KEY_PREFIX = "faq"


def _normalize(question: str) -> str:
    """标准化问题文本：去首尾空白、转小写，用于 hash key 计算。"""
    return question.strip().lower()


def _hash_question(question: str) -> str:
    """将标准化后的问题文本 hash 为 32 位 hex 串。"""
    return hashlib.md5(_normalize(question).encode("utf-8")).hexdigest()


class FaqCache:
    """FAQ 精确缓存，按店铺隔离存储于 Redis。

    Key 格式：faq:{shop_id}:{question_hash}
    Value：回复文本字符串
    """

    def __init__(self, redis_client: aioredis.Redis, ttl: int = 0) -> None:
        """
        Args:
            redis_client: 异步 Redis 客户端。
            ttl: key 过期时间（秒），0 表示永不过期。
        """
        self._redis = redis_client
        self._ttl = ttl

    def _key(self, shop_id: str, question: str) -> str:
        return f"{_FAQ_KEY_PREFIX}:{shop_id}:{_hash_question(question)}"

    async def get(self, shop_id: str, question: str) -> str | None:
        """精确匹配 FAQ，命中返回回复文本，未命中返回 None。

        Args:
            shop_id: 店铺 ID。
            question: 买家原始问题（会自动标准化后 hash）。

        Returns:
            预置回复字符串，或 None。
        """
        key = self._key(shop_id, question)
        try:
            val = await self._redis.get(key)
            if val:
                logger.debug("FAQ 命中 shop=%s key=%s", shop_id, key)
                return val if isinstance(val, str) else val.decode("utf-8")
            return None
        except Exception as exc:
            logger.warning("FAQ 缓存读取失败 shop=%s: %s", shop_id, exc)
            return None

    async def set(self, shop_id: str, question: str, reply: str) -> None:
        """写入一条 FAQ 缓存。

        Args:
            shop_id: 店铺 ID。
            question: 问题文本（会自动标准化）。
            reply: 对应回复文本。
        """
        key = self._key(shop_id, question)
        try:
            if self._ttl > 0:
                await self._redis.set(key, reply, ex=self._ttl)
            else:
                await self._redis.set(key, reply)
            logger.debug("FAQ 写入 shop=%s question=%s", shop_id, question[:30])
        except Exception as exc:
            logger.warning("FAQ 缓存写入失败 shop=%s: %s", shop_id, exc)

    async def delete(self, shop_id: str, question: str) -> None:
        """删除一条 FAQ 缓存。"""
        key = self._key(shop_id, question)
        try:
            await self._redis.delete(key)
        except Exception as exc:
            logger.warning("FAQ 缓存删除失败 shop=%s: %s", shop_id, exc)

    async def batch_set(self, shop_id: str, faq_pairs: list[tuple[str, str]]) -> None:
        """批量写入 FAQ 缓存（使用 pipeline 提升性能）。

        Args:
            shop_id: 店铺 ID。
            faq_pairs: [(question, reply), ...] 列表。
        """
        try:
            pipe = self._redis.pipeline()
            for question, reply in faq_pairs:
                key = self._key(shop_id, question)
                if self._ttl > 0:
                    pipe.set(key, reply, ex=self._ttl)
                else:
                    pipe.set(key, reply)
            await pipe.execute()
            logger.info("FAQ 批量写入 shop=%s 共 %d 条", shop_id, len(faq_pairs))
        except Exception as exc:
            logger.error("FAQ 批量写入失败 shop=%s: %s", shop_id, exc)
