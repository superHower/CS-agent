"""FAQ 精确缓存，基于 Redis 存储问题→回复映射，命中直接返回无需 LLM。

FAQ 缓存按「店铺专属」和「分类共享」分离存储：
- 店铺专属 FAQ: key = faq:shop:{shop_id}:{question_hash}
- 分类共享 FAQ: key = faq:category:{category_id}:{question_hash}
"""

import hashlib
import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


def _normalize(question: str) -> str:
    """标准化问题文本：去首尾空白、转小写，用于 hash key 计算。"""
    return question.strip().lower()


def _hash_question(question: str) -> str:
    """将标准化后的问题文本 hash 为 32 位 hex 串。"""
    return hashlib.md5(_normalize(question).encode("utf-8")).hexdigest()


class FaqCache:
    """FAQ 精确缓存，按店铺/分类隔离存储于 Redis。

    FAQ 有两类所有者：
    1. 店铺专属 FAQ：shop_id 为具体店铺ID
    2. 分类共享 FAQ：shop_id 为 'global'，属于某个分类

    Key 格式：
    - 店铺专属: faq:shop:{shop_id}:{question_hash}
    - 分类共享: faq:category:{category_id}:{question_hash}
    """

    def __init__(self, redis_client: aioredis.Redis, ttl: int = 0) -> None:
        """
        Args:
            redis_client: 异步 Redis 客户端。
            ttl: key 过期时间（秒），0 表示永不过期。
        """
        self._redis = redis_client
        self._ttl = ttl

    def _shop_key(self, shop_id: str, question: str) -> str:
        """店铺专属 FAQ 的 Redis key。"""
        return f"faq:shop:{shop_id}:{_hash_question(question)}"

    def _category_key(self, category_id: str, question: str) -> str:
        """分类共享 FAQ 的 Redis key。"""
        return f"faq:category:{category_id}:{_hash_question(question)}"

    async def get(self, owner_id: str, question: str, is_shop: bool = True) -> str | None:
        """精确匹配 FAQ，命中返回回复文本，未命中返回 None。

        Args:
            owner_id: 店铺ID或分类ID。
            is_shop: True=店铺专属 FAQ，False=分类共享 FAQ。

        Returns:
            预置回复字符串，或 None。
        """
        key = self._shop_key(owner_id, question) if is_shop else self._category_key(owner_id, question)
        try:
            val = await self._redis.get(key)
            if val:
                logger.debug("FAQ 命中 key=%s owner=%s is_shop=%s", key, owner_id, is_shop)
                return val if isinstance(val, str) else val.decode("utf-8")
            return None
        except Exception as exc:
            logger.warning("FAQ 缓存读取失败 key=%s: %s", key, exc)
            return None

    async def set(self, owner_id: str, question: str, reply: str, is_shop: bool = True) -> None:
        """写入一条 FAQ 缓存。

        Args:
            owner_id: 店铺ID或分类ID。
            question: 问题文本（会自动标准化）。
            reply: 对应回复文本。
            is_shop: True=店铺专属 FAQ，False=分类共享 FAQ。
        """
        key = self._shop_key(owner_id, question) if is_shop else self._category_key(owner_id, question)
        try:
            if self._ttl > 0:
                await self._redis.set(key, reply, ex=self._ttl)
            else:
                await self._redis.set(key, reply)
            logger.debug("FAQ 写入 key=%s", key)
        except Exception as exc:
            logger.warning("FAQ 缓存写入失败 key=%s: %s", key, exc)

    async def delete(self, owner_id: str, question: str, is_shop: bool = True) -> None:
        """删除一条 FAQ 缓存。"""
        key = self._shop_key(owner_id, question) if is_shop else self._category_key(owner_id, question)
        try:
            await self._redis.delete(key)
        except Exception as exc:
            logger.warning("FAQ 缓存删除失败 key=%s: %s", key, exc)

    async def batch_set_shop(self, shop_id: str, faq_pairs: list[tuple[str, str]]) -> None:
        """批量写入店铺专属 FAQ 缓存。

        Args:
            shop_id: 店铺 ID。
            faq_pairs: [(question, reply), ...] 列表。
        """
        try:
            pipe = self._redis.pipeline()
            for question, reply in faq_pairs:
                key = self._shop_key(shop_id, question)
                if self._ttl > 0:
                    pipe.set(key, reply, ex=self._ttl)
                else:
                    pipe.set(key, reply)
            await pipe.execute()
            logger.info("店铺专属 FAQ 批量写入 shop=%s 共 %d 条", shop_id, len(faq_pairs))
        except Exception as exc:
            logger.error("店铺专属 FAQ 批量写入失败 shop=%s: %s", shop_id, exc)

    async def batch_set_category(self, category_id: str, faq_pairs: list[tuple[str, str]]) -> None:
        """批量写入分类共享 FAQ 缓存。

        Args:
            category_id: 分类 ID。
            faq_pairs: [(question, reply), ...] 列表。
        """
        try:
            pipe = self._redis.pipeline()
            for question, reply in faq_pairs:
                key = self._category_key(category_id, question)
                if self._ttl > 0:
                    pipe.set(key, reply, ex=self._ttl)
                else:
                    pipe.set(key, reply)
            await pipe.execute()
            logger.info("分类共享 FAQ 批量写入 category=%s 共 %d 条", category_id, len(faq_pairs))
        except Exception as exc:
            logger.error("分类共享 FAQ 批量写入失败 category=%s: %s", category_id, exc)
