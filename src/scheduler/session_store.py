"""Redis 会话上下文存储，负责 SessionContext 的加载、保存和 TTL 续期。"""

import logging
from datetime import UTC, datetime

import redis.asyncio as aioredis

from src.contracts import SessionContext, SessionState, StandardMessage

logger = logging.getLogger(__name__)

_SESSION_KEY_PREFIX = "session"
_MAX_HISTORY_TURNS = 10  # 保留最近 N 轮对话历史


class SessionStore:
    """基于 Redis 的会话上下文存储。

    Key 格式：session:{shop_id}:{buyer_id}
    Value：SessionContext JSON 序列化字符串
    TTL：由 settings.thresholds.session_ttl 控制（默认 2h）
    """

    def __init__(self, redis_client: aioredis.Redis, session_ttl: int = 7200) -> None:
        self._redis = redis_client
        self._ttl = session_ttl

    def _key(self, shop_id: str, buyer_id: str) -> str:
        return f"{_SESSION_KEY_PREFIX}:{shop_id}:{buyer_id}"

    async def load_or_create(self, msg: StandardMessage) -> SessionContext:
        """加载已有会话上下文，不存在则新建。

        Args:
            msg: 触发本次会话的标准化消息。

        Returns:
            SessionContext，已有时续期 TTL，新建时初始化空上下文。
        """
        key = self._key(msg.shop_id, msg.buyer_id)
        try:
            raw = await self._redis.get(key)
            if raw:
                ctx = SessionContext.model_validate_json(raw)
                await self._redis.expire(key, self._ttl)
                logger.debug("加载已有会话 shop=%s buyer=%s", msg.shop_id, msg.buyer_id)
                return ctx
        except Exception as exc:
            logger.warning("Redis 读取会话失败，降级新建: %s", exc)

        now = datetime.now(tz=UTC)
        ctx = SessionContext(
            shop_id=msg.shop_id,
            buyer_id=msg.buyer_id,
            platform=msg.platform,
            state=SessionState.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        logger.info("新建会话 shop=%s buyer=%s", msg.shop_id, msg.buyer_id)
        return ctx

    async def save(self, ctx: SessionContext) -> None:
        """保存会话上下文到 Redis，自动设置 TTL。

        Args:
            ctx: 要保存的会话上下文。
        """
        key = self._key(ctx.shop_id, ctx.buyer_id)
        try:
            ctx = ctx.model_copy(update={"updated_at": datetime.now(tz=UTC)})
            # 仅保留最近 N 轮历史，控制 Redis 内存
            if len(ctx.history) > _MAX_HISTORY_TURNS:
                ctx = ctx.model_copy(update={"history": ctx.history[-_MAX_HISTORY_TURNS:]})
            await self._redis.set(key, ctx.model_dump_json(), ex=self._ttl)
        except (aioredis.RedisError, ConnectionError) as exc:
            logger.error("Redis 保存会话失败 shop=%s buyer=%s: %s", ctx.shop_id, ctx.buyer_id, exc)

    async def delete(self, shop_id: str, buyer_id: str) -> None:
        """删除会话（会话结束/超时归档后调用）。"""
        key = self._key(shop_id, buyer_id)
        try:
            await self._redis.delete(key)
            await self._redis.delete(self._handoff_key(shop_id, buyer_id))
            logger.info("会话已删除 shop=%s buyer=%s", shop_id, buyer_id)
        except (aioredis.RedisError, ConnectionError) as exc:
            logger.warning("Redis 删除会话失败: %s", exc)

    # ── 转人工时间戳（用于 10 分钟内重复消息去重）───────────────────────────────

    def _handoff_key(self, shop_id: str, buyer_id: str) -> str:
        return f"{_SESSION_KEY_PREFIX}:{shop_id}:{buyer_id}:handoff_at"

    async def read_handoff_at(self, shop_id: str, buyer_id: str) -> datetime | None:
        """读取最近一次转人工的时间戳。无记录或解析失败返回 None。"""
        try:
            raw = await self._redis.get(self._handoff_key(shop_id, buyer_id))
            if not raw:
                return None
            value = raw.decode() if isinstance(raw, bytes) else raw
            return datetime.fromisoformat(value)
        except (aioredis.RedisError, ConnectionError, ValueError) as exc:
            logger.warning("读取 handoff_at 失败: %s", exc)
            return None

    async def write_handoff_at(self, shop_id: str, buyer_id: str, ts: datetime) -> None:
        """写入转人工时间戳，TTL 与会话一致。"""
        try:
            await self._redis.set(
                self._handoff_key(shop_id, buyer_id),
                ts.isoformat(),
                ex=self._ttl,
            )
        except (aioredis.RedisError, ConnectionError) as exc:
            logger.warning("写入 handoff_at 失败: %s", exc)

    async def clear_handoff_at(self, shop_id: str, buyer_id: str) -> None:
        """清除转人工时间戳（10 分钟过了，认作新对话时调用）。"""
        try:
            await self._redis.delete(self._handoff_key(shop_id, buyer_id))
        except (aioredis.RedisError, ConnectionError) as exc:
            logger.warning("清除 handoff_at 失败: %s", exc)
