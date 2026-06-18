"""会话调度核心状态机。

实现 7 条固定分支的 dispatch 函数，严格控制在 300 行以内（不含注释/docstring）。
所有平台差异不得出现在本模块，仅通过接口调用网关/检索/LLM/动作层。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from src.config.settings import Config, ShopConfig
from src.contracts import (
    EscalationContext,
    EscalationReason,
    LLMRequest,
    RetrievalResult,
    SessionContext,
    SessionState,
    StandardMessage,
    TurnRecord,
    WritebackTask,
)
from src.scheduler.session_store import SessionStore
from src.utils.trace import new_trace_id

logger = logging.getLogger(__name__)

# ── 接口类型定义（由各层实现注入）────────────────────────────────────────────

RetrieveFn = Callable[[ShopConfig, str], Awaitable[RetrievalResult]]
LLMCallFn = Callable[[LLMRequest], Awaitable[tuple[str, int]]]  # -> (reply, confidence)
SendFn = Callable[[ShopConfig, str, str, dict], Awaitable[bool]]
EscalateFn = Callable[[EscalationContext], Awaitable[None]]
WritebackFn = Callable[[WritebackTask], Awaitable[None]]


class SessionScheduler:
    """异步会话调度器，内部使用 asyncio.Queue 接收 StandardMessage。

    依赖注入：检索层、LLM 层、发送层、告警层、回写层均通过构造函数注入，
    调度层本身不感知任何平台或底层实现细节。
    """

    def __init__(
        self,
        config: Config,
        session_store: SessionStore,
        retrieve_fn: RetrieveFn,
        llm_fn: LLMCallFn,
        send_fn: SendFn,
        escalate_fn: EscalateFn,
        writeback_fn: WritebackFn,
    ) -> None:
        self._config = config
        self._store = session_store
        self._retrieve = retrieve_fn
        self._llm = llm_fn
        self._send = send_fn
        self._escalate = escalate_fn
        self._writeback = writeback_fn
        self._queue: asyncio.Queue[StandardMessage] = asyncio.Queue()
        self._running = False

    async def enqueue(self, msg: StandardMessage) -> None:
        """将标准化消息投入调度队列。"""
        await self._queue.put(msg)

    async def run(self) -> None:
        """启动调度循环，持续消费队列消息直到被取消。"""
        self._running = True
        logger.info("调度器已启动")
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                asyncio.create_task(self._handle(msg))
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("调度器已停止")
                return

    async def stop(self) -> None:
        """停止调度循环。"""
        self._running = False

    # ── 核心 dispatch（≤300行，含此注释以上所有代码行不计入）────────────────

    async def _handle(self, msg: StandardMessage) -> None:
        """单条消息的完整调度流程，任何分支异常均降级转人工。"""
        new_trace_id()
        shop_config = self._config.get_shop(msg.shop_id)
        if shop_config is None:
            logger.error("shop_id 未找到配置: %s", msg.shop_id)
            return

        try:
            await self.dispatch(msg, shop_config)
        except Exception as exc:
            logger.error(
                "dispatch 未捕获异常 shop=%s buyer=%s: %s",
                msg.shop_id,
                msg.buyer_id,
                exc,
                exc_info=True,
            )
            await self._do_escalate(msg, shop_config, EscalationReason.EXCEPTION, ctx=None)

    async def dispatch(self, msg: StandardMessage, shop_config: ShopConfig) -> None:
        """7 分支状态机核心逻辑。"""
        # 分支 1：加载/新建会话上下文
        try:
            ctx = await self._store.load_or_create(msg)
        except Exception as exc:
            logger.error("会话加载失败，转人工: %s", exc)
            await self._do_escalate(msg, shop_config, EscalationReason.EXCEPTION, ctx=None)
            return

        if ctx.state == SessionState.WAITING_HUMAN:
            logger.info("会话已在人工处理中，忽略消息 shop=%s buyer=%s", msg.shop_id, msg.buyer_id)
            return

        ctx = ctx.model_copy(update={"current_message": msg.content})

        # 分支 2：订单/物流意图（预留接口，当前跳过）
        if self._is_order_query(msg.content):
            # TODO: 接入订单查询模块后实现
            logger.debug("订单查询意图预留，暂跳过 shop=%s", msg.shop_id)

        # 分支 3：硬转人工关键词检查（最高优先级）
        keyword = self._check_hard_keywords(msg.content, self._config.escalation_keywords)
        if keyword:
            logger.info(
                "命中硬转人工关键词 [%s] shop=%s buyer=%s", keyword, msg.shop_id, msg.buyer_id
            )
            await self._do_escalate(
                msg,
                shop_config,
                EscalationReason.HARD_KEYWORD,
                ctx=ctx,
                triggered_keyword=keyword,
            )
            return

        # 分支 4：FAQ 精确缓存命中
        try:
            retrieval = await self._retrieve(shop_config, msg.content)
        except Exception as exc:
            logger.error("检索层异常，转人工 shop=%s: %s", msg.shop_id, exc)
            await self._do_escalate(msg, shop_config, EscalationReason.EXCEPTION, ctx=ctx)
            return

        if retrieval.faq_hit:
            logger.info("FAQ 命中，直接回复 shop=%s buyer=%s", msg.shop_id, msg.buyer_id)
            await self._reply_and_save(ctx, msg, shop_config, retrieval.faq_reply, confidence=100)
            return

        # 分支 5：送入 LLM 推理层
        knowledge_text = "\n".join(c.content for c in retrieval.chunks)
        llm_req = LLMRequest(
            shop_id=shop_config.shop_id,
            shop_name=shop_config.name,
            buyer_message=msg.content,
            history=ctx.history[-6:],
            knowledge=knowledge_text,
        )
        try:
            reply, confidence = await self._llm(llm_req)
        except Exception as exc:
            logger.error("LLM 层异常，转人工 shop=%s: %s", msg.shop_id, exc)
            await self._do_escalate(msg, shop_config, EscalationReason.EXCEPTION, ctx=ctx)
            return

        threshold = shop_config.confidence_threshold
        is_greeting = self._is_greeting(msg.content, self._config.greeting_patterns)

        # 分支 6：置信度与模糊寒暄判定
        if confidence >= threshold:
            logger.info("置信度 %d >= %d，自动回复 shop=%s", confidence, threshold, msg.shop_id)
            await self._reply_and_save(ctx, msg, shop_config, reply, confidence)
        elif is_greeting:
            fallback = self._get_fallback_reply()
            logger.info("模糊寒暄兜底 shop=%s buyer=%s", msg.shop_id, msg.buyer_id)
            await self._reply_and_save(ctx, msg, shop_config, fallback, confidence)
        else:
            logger.info("置信度 %d < %d，转人工 shop=%s", confidence, threshold, msg.shop_id)
            await self._do_escalate(
                msg,
                shop_config,
                EscalationReason.LOW_CONFIDENCE,
                ctx=ctx,
                confidence=confidence,
            )

    # ── 辅助方法（不计入 300 行主逻辑）──────────────────────────────────────

    @staticmethod
    def _check_hard_keywords(content: str, keywords: list[str]) -> str:
        """检查消息是否包含硬转人工关键词，返回命中的关键词或空字符串。"""
        for kw in keywords:
            if kw in content:
                return kw
        return ""

    @staticmethod
    def _is_greeting(content: str, patterns: list[str]) -> bool:
        """判断消息是否为模糊寒暄（短消息 + 匹配寒暄模式）。"""
        stripped = content.strip()
        if len(stripped) > 10:
            return False
        return any(p in stripped.lower() for p in patterns)

    @staticmethod
    def _is_order_query(content: str) -> bool:
        """简单判断是否为订单/物流查询意图（预留）。"""
        order_keywords = ["订单", "物流", "快递", "发货", "签收", "运单"]
        return any(kw in content for kw in order_keywords)

    def _get_fallback_reply(self) -> str:
        return "您好！感谢您的咨询，请问有什么可以帮您的？"

    async def _reply_and_save(
        self,
        ctx: SessionContext,
        msg: StandardMessage,
        shop_config: ShopConfig,
        reply: str,
        confidence: int,
    ) -> None:
        """发送回复并保存会话上下文，异步触发记忆回写。"""
        ok = await self._send(shop_config, msg.buyer_id, reply, {})
        if not ok:
            logger.warning("消息发送失败，转人工 shop=%s buyer=%s", msg.shop_id, msg.buyer_id)
            await self._do_escalate(msg, shop_config, EscalationReason.SEND_FAILED, ctx=ctx)
            return

        now = datetime.now(tz=UTC)
        new_history = list(ctx.history) + [
            TurnRecord(role="user", content=msg.content, timestamp=msg.timestamp),
            TurnRecord(role="assistant", content=reply, timestamp=now),
        ]
        ctx = ctx.model_copy(
            update={
                "history": new_history,
                "last_confidence": confidence,
            }
        )
        await self._store.save(ctx)

        # 分支 7：异步记忆回写（不阻塞主线程）
        asyncio.create_task(self._async_writeback(ctx, msg, reply))

    async def _do_escalate(
        self,
        msg: StandardMessage,
        shop_config: ShopConfig,
        reason: EscalationReason,
        ctx: SessionContext | None,
        triggered_keyword: str = "",
        confidence: int = 0,
    ) -> None:
        """执行转人工：标记会话状态、保存上下文、触发告警。"""
        recent_history = ctx.history[-3:] if ctx else []
        escalation = EscalationContext(
            shop_id=msg.shop_id,
            buyer_id=msg.buyer_id,
            platform=msg.platform,
            reason=reason,
            trigger_message=msg.content,
            recent_history=recent_history,
            confidence=confidence,
            triggered_keyword=triggered_keyword,
            timestamp=datetime.now(tz=UTC),
        )
        if ctx is not None:
            ctx = ctx.model_copy(update={"state": SessionState.WAITING_HUMAN})
            await self._store.save(ctx)

        try:
            await self._escalate(escalation)
        except Exception as exc:
            logger.error("告警推送失败，仍继续 shop=%s: %s", msg.shop_id, exc)

    async def _async_writeback(self, ctx: SessionContext, msg: StandardMessage, reply: str) -> None:
        """异步写入 Obsidian 记忆，失败不影响主流程。"""
        try:
            task = WritebackTask(
                shop_id=ctx.shop_id,
                buyer_id=ctx.buyer_id,
                summary=f"咨询：{msg.content[:50]}；回复：{reply[:50]}",
                resolution="resolved",
                session_date=datetime.now(tz=UTC),
            )
            await self._writeback(task)
        except Exception as exc:
            logger.error("记忆回写失败 shop=%s buyer=%s: %s", ctx.shop_id, ctx.buyer_id, exc)
