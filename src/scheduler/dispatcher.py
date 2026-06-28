"""会话调度核心状态机。

实现 7 条固定分支的 dispatch 函数，严格控制在 300 行以内（不含注释/docstring）。
所有平台差异不得出现在本模块，仅通过接口调用网关/检索/LLM/动作层。
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from src.config.settings import Config, ShopConfig, get_config
from src.contracts import (
    EscalationContext,
    EscalationReason,
    LLMRequest,
    Platform,
    RetrievalResult,
    SessionContext,
    SessionState,
    StandardMessage,
    TurnRecord,
    WritebackTask,
)
from src.matching.engine import MatchEngine, MatchRequest
from src.scheduler.session_store import SessionStore
from src.utils.trace import new_trace_id
from src.gateway.rpa import resolve_shop_info

logger = logging.getLogger(__name__)

# ── 接口类型定义（由各层实现注入）────────────────────────────────────────────

RetrieveFn = Callable[[ShopConfig, str], Awaitable[RetrievalResult]]
LLMCallFn = Callable[[LLMRequest], Awaitable[tuple[str, int]]]  # -> (reply, confidence)
SendFn = Callable[[ShopConfig, str, str, dict], Awaitable[bool]]
EscalateFn = Callable[[EscalationContext], Awaitable[None]]
WritebackFn = Callable[[WritebackTask], Awaitable[None]]


# 默认搪塞话术（数据库未加载前的兜底）
_DEFAULT_DECOY_PHRASES = [
    "亲，稍等我查一下哈~",
    "您好，这个问题我需要确认一下，请稍候~",
    "感谢您的耐心等待，我这边帮您查询一下~",
    "亲，我这边帮您了解一下，请稍等~",
]

# 人工处理中的去抖窗口：买家在此间隔内重复发消息，静默忽略（不回复、不告警）
# 超过该间隔视为新一轮对话，按新流程处理（重置为 ACTIVE 再走正常分支）
_HUMAN_HANDOFF_DEBOUNCE_S = 600  # 10 分钟


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
        match_engine: MatchEngine | None = None,
    ) -> None:
        self._config = config
        self._store = session_store
        self._retrieve = retrieve_fn
        self._llm = llm_fn
        self._send = send_fn
        self._escalate = escalate_fn
        self._writeback = writeback_fn
        self._match_engine = match_engine
        self._queue: asyncio.Queue[StandardMessage] = asyncio.Queue()
        self._running = False
        # 动态关键词和话术（从数据库加载，按 category_id+shop_id 缓存）
        # 结构: dict[category_id, dict[shop_id, list[str]]]
        self._dynamic_keywords: dict[str, dict[str, list[str]]] = {}
        self._dynamic_decoy_phrases: dict[str, dict[str, list[str]]] = {}

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

    async def load_dynamic_config(self) -> None:
        """从数据库加载动态配置（告警关键词、搪塞话术）。启动时调用一次，按分类+店铺缓存。"""
        try:
            from admin.crud import load_decoy_phrases, load_escalation_keywords
            from admin.database import get_db

            conn = await get_db()
            try:
                # 加载所有 category_id 已设置的记录（含 shop_id='global' 表示分类共享）
                async with conn.execute(
                    "SELECT category_id, shop_id, keyword FROM escalation_keywords WHERE category_id IS NOT NULL ORDER BY category_id, shop_id"
                ) as cur:
                    kw_rows = await cur.fetchall()
                async with conn.execute(
                    "SELECT category_id, shop_id, phrase FROM decoy_phrases_pool WHERE category_id IS NOT NULL ORDER BY category_id, shop_id"
                ) as cur:
                    ph_rows = await cur.fetchall()
            finally:
                await conn.close()

            # 按 category_id+shop_id 构建缓存
            kw_cache: dict[str, dict[str, list[str]]] = {}
            for row in kw_rows:
                cat_id = row["category_id"] or "default"
                shop_id = row["shop_id"]
                kw_cache.setdefault(cat_id, {}).setdefault(shop_id, []).append(row["keyword"])

            ph_cache: dict[str, dict[str, list[str]]] = {}
            for row in ph_rows:
                cat_id = row["category_id"] or "default"
                shop_id = row["shop_id"]
                ph_cache.setdefault(cat_id, {}).setdefault(shop_id, []).append(row["phrase"])

            if kw_cache:
                self._dynamic_keywords = kw_cache
                total_kw = sum(len(v) for inner in kw_cache.values() for v in inner.values())
                logger.info("动态加载告警关键词 %d 条，分布: %s", total_kw, {k: len(v) for k, v in kw_cache.items()})
            if ph_cache:
                self._dynamic_decoy_phrases = ph_cache
                total_ph = sum(len(v) for inner in ph_cache.values() for v in inner.values())
                logger.info("动态加载搪塞话术 %d 条，分布: %s", total_ph, {k: len(v) for k, v in ph_cache.items()})
        except Exception as exc:
            logger.warning("动态配置加载失败，使用静态配置: %s", exc)

    async def _get_escalation_keywords(self, shop_config: ShopConfig) -> list[str]:
        """返回指定店铺的有效关键词列表（动态优先，其次数据库，其次 YAML 静态）。

        优先级：店铺专属 + 类目共享(global) + 类目默认(default) 取并集去重。
        """
        cat_id = shop_config.category_id or "default"
        shop_id = shop_config.shop_id
        # 动态: 店铺专属 + 类目共享(global) 取并集
        dyn = self._dynamic_keywords
        if dyn:
            cat_map = dyn.get(cat_id, {})
            merged: list[str] = []
            seen: set[str] = set()
            for source_id in (shop_id, "global"):
                for kw in cat_map.get(source_id, []):
                    if kw not in seen:
                        seen.add(kw)
                        merged.append(kw)
            if merged:
                return merged
        # 降级：从数据库查（实时查询，支持后创建的店铺）
        keywords = await self._load_keywords_from_db(cat_id, shop_id)
        if keywords:
            return keywords
        return self._config.escalation_keywords

    async def _load_keywords_from_db(self, category_id: str, shop_id: str) -> list[str]:
        """从数据库查询告警关键词（运行时降级，不缓存）。"""
        try:
            from admin.crud import load_escalation_keywords
            from admin.database import get_db
            conn = await get_db()
            try:
                result = await load_escalation_keywords(conn, category_id, shop_id)
                return result
            finally:
                await conn.close()
        except Exception as exc:
            logger.warning("_load_keywords_from_db 异常 cat=%s shop=%s: %s", category_id, shop_id, exc)
            return []

    def _get_decoy_phrase(self, shop_config: ShopConfig) -> str:
        """随机取一条搪塞话术（店铺专属 + 类目共享 + 默认兜底 合并池）。"""
        cat_id = shop_config.category_id or "default"
        shop_id = shop_config.shop_id
        dyn = self._dynamic_decoy_phrases
        pool: list[str] = []
        if dyn:
            cat_map = dyn.get(cat_id, {})
            seen: set[str] = set()
            for source_id in (shop_id, "global"):
                for p in cat_map.get(source_id, []):
                    if p not in seen:
                        seen.add(p)
                        pool.append(p)
        if not pool:
            pool = _DEFAULT_DECOY_PHRASES
        return random.choice(pool)

    # ── 核心 dispatch（≤300行，含此注释以上所有代码行不计入）────────────────

    async def _handle(self, msg: StandardMessage) -> None:
        """单条消息的完整调度流程，任何分支异常均降级转人工。"""
        new_trace_id()
        # 先从数据库获取最新配置（管理员后台是真实数据源）
        db_shop_id, category_id = await resolve_shop_info(msg.shop_id)
        # 尝试在静态配置中匹配（优先按 shop_id，其次按名称）
        shop_config = self._config.get_shop(msg.shop_id)
        if shop_config is None:
            shop_config = get_config().get_shop(msg.shop_id)
        if shop_config is None and db_shop_id:
            shop_config = self._config.get_shop(db_shop_id)
        # 按名称兜底匹配（静态配置中的 name 可能对应数据库的 shop_id）
        if shop_config is None:
            for cfg in (get_config().shops or []):
                if cfg.name == msg.shop_id or cfg.shop_id == db_shop_id:
                    shop_config = cfg
                    break
        if shop_config is None:
            # 静态配置完全没有，构造一个
            logger.warning("shop_id %s 未在静态配置中找到，从数据库构造配置", msg.shop_id)
            shop_config = ShopConfig(
                shop_id=db_shop_id or msg.shop_id,
                name=msg.shop_id,
                platform=msg.platform,
                category_id=category_id or "default",
                enabled=True,
                confidence_threshold=85,
            )
        elif category_id:
            # 静态配置存在，但 category_id 以数据库为准（覆盖静态值）
            shop_config = ShopConfig(
                shop_id=shop_config.shop_id,
                category_id=category_id,
                platform=shop_config.platform,
                name=shop_config.name,
                api_key=shop_config.api_key,
                api_secret=shop_config.api_secret,
                confidence_threshold=shop_config.confidence_threshold,
                enabled=shop_config.enabled,
            )
            logger.debug("category_id 覆盖为 %s (来自数据库)", category_id)
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
            # 已在人工处理中：检查距离上次互动是否超过 10 分钟
            # 锚点优先级（max）：
            #   1. handoff_at（服务端上次转人工的时间，最精确）
            #   2. msg.chat_list_latest_at（平台 chatList 最后一条气泡时间，含买家和客服互动）
            #   3. ctx.updated_at（fallback，Redis TTL 蒸发的兜底）
            # chat_list_latest_at 关键：即使客服在平台上回了买家、但没回调给我们，
            # 平台时间推进了，我们也能识别"还在人工处理中"。
            last_handoff_at = await self._store.read_handoff_at(msg.shop_id, msg.buyer_id)
            candidates: list[datetime] = []
            if last_handoff_at:
                candidates.append(last_handoff_at)
            if msg.chat_list_latest_at:
                candidates.append(msg.chat_list_latest_at)
            candidates.append(ctx.updated_at)
            anchor_ts = max(candidates)
            now = datetime.now(tz=UTC)
            if (now - anchor_ts).total_seconds() >= _HUMAN_HANDOFF_DEBOUNCE_S:
                # 超过 10 分钟 → 视为新一轮对话，重置状态走正常分支
                logger.info(
                    "会话处于人工处理中但已过 %d 分钟，按新对话处理 shop=%s buyer=%s anchor=%s",
                    _HUMAN_HANDOFF_DEBOUNCE_S // 60, msg.shop_id, msg.buyer_id, anchor_ts.isoformat(),
                )
                ctx = ctx.model_copy(update={"state": SessionState.ACTIVE})
                await self._store.save(ctx)
                await self._store.clear_handoff_at(msg.shop_id, msg.buyer_id)
                # 不 return，继续走下方分支 2/3/4
            else:
                # 10 分钟内重复消息：买家不感知新动作，但不调 _do_escalate 避免重复告警
                # 同时 fill Future 让 RPA HTTP 接口正常返回（否则会等超时）
                logger.info(
                    "会话处于人工处理中（%d 分钟内重复消息），静默忽略 shop=%s buyer=%s anchor=%s",
                    _HUMAN_HANDOFF_DEBOUNCE_S // 60, msg.shop_id, msg.buyer_id, anchor_ts.isoformat(),
                )
                await self._send(
                    shop_config,
                    msg.buyer_id,
                    "",
                    {"message_id": msg.message_id, "escalated": True},
                )
                return

        ctx = ctx.model_copy(update={"current_message": msg.content})

        # 分支 2：订单/物流意图（预留接口，当前跳过）
        if self._is_order_query(msg.content):
            # TODO: 接入订单查询模块后实现
            logger.debug("订单查询意图预留，暂跳过 shop=%s", msg.shop_id)

        # 分支 3：硬转人工关键词检查（最高优先级）
        keywords = await self._get_escalation_keywords(shop_config)
        keyword = self._check_hard_keywords(msg.content, keywords)
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

        # 分支 4 & 5：通过 MatchEngine 决策（FAQ直达 / 意图识别+RAG）
        t0 = __import__("time").time()
        if self._match_engine is not None:
            match_req = MatchRequest(
                user_msg=msg.content,
                product_name=getattr(msg, "product_name", ""),
                order_detail=getattr(msg, "order_detail", ""),
                history=[{"role": t.role, "content": t.content} for t in ctx.history[-6:]],
                shop_id=msg.shop_id,
                is_douyin=(msg.platform == Platform.DOUYIN),
                filtered_chat_list=getattr(msg, "raw_chat_list", []),
            )
            try:
                match_result = await self._match_engine.match(shop_config, match_req)
                logger.info(
                    "MatchEngine 完成 shop=%s source=%s confidence=%d elapsed=%.2fs",
                    msg.shop_id, match_result.source, match_result.confidence,
                    __import__("time").time() - t0,
                )
            except Exception as exc:
                logger.error("MatchEngine 异常，转人工 shop=%s: %s", msg.shop_id, exc)
                await self._do_escalate(msg, shop_config, EscalationReason.EXCEPTION, ctx=ctx)
                return

            if match_result.needs_escalation:
                logger.info("MatchEngine 决策转人工 shop=%s confidence=%d", msg.shop_id, match_result.confidence)
                await self._do_escalate(msg, shop_config, EscalationReason.LOW_CONFIDENCE, ctx=ctx, confidence=match_result.confidence)
                return

            is_greeting = self._is_greeting(msg.content, self._config.greeting_patterns)
            if match_result.confidence >= shop_config.confidence_threshold or (is_greeting and match_result.confidence > 0):
                await self._reply_and_save(ctx, msg, shop_config, match_result.reply, match_result.confidence)
            else:
                await self._do_escalate(msg, shop_config, EscalationReason.LOW_CONFIDENCE, ctx=ctx, confidence=match_result.confidence)
            return

        # ── 兼容旧模式（无 MatchEngine 时回退到直接检索 + LLM）──────────────
        try:
            retrieval = await self._retrieve(shop_config, msg.content)
            logger.info(
                "检索完成 shop=%s faq_hit=%s chunks=%d 耗时=%.2fs",
                msg.shop_id, retrieval.faq_hit, len(retrieval.chunks), __import__("time").time() - t0,
            )
        except Exception as exc:
            logger.error("检索层异常，转人工 shop=%s 耗时=%.2fs: %s", msg.shop_id, __import__("time").time() - t0, exc)
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
        logger.info(
            "调用 LLM shop=%s buyer=%s knowledge_chars=%d history_turns=%d",
            msg.shop_id, msg.buyer_id, len(knowledge_text), len(ctx.history),
        )
        t1 = __import__("time").time()
        try:
            reply, confidence = await self._llm(llm_req)
            logger.info(
                "LLM 返回 shop=%s 耗时=%.2fs confidence=%d reply_preview=%s",
                msg.shop_id, __import__("time").time() - t1, confidence, reply[:60].replace("\n", " "),
            )
        except Exception as exc:
            logger.error("LLM 层异常，转人工 shop=%s 耗时=%.2fs: %s", msg.shop_id, __import__("time").time() - t1, exc)
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
        ok = await self._send(shop_config, msg.buyer_id, reply, {"message_id": msg.message_id})
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
        """执行转人工：发送搪塞话术、标记会话状态、保存上下文、触发告警。"""
        # 发送搪塞话术（重复转人工场景已由分支 1 静默忽略，不会再走到这里）
        decoy = self._get_decoy_phrase(shop_config)
        try:
            await self._send(shop_config, msg.buyer_id, decoy, {"message_id": msg.message_id})
        except Exception as exc:
            logger.warning("搪塞话术发送失败 shop=%s: %s", msg.shop_id, exc)

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
            message_id=msg.message_id,
            timestamp=datetime.now(tz=UTC),
        )
        if ctx is not None:
            ctx = ctx.model_copy(update={"state": SessionState.WAITING_HUMAN})
            await self._store.save(ctx)
            # 记录转人工时间戳（用于 10 分钟内重复消息去重判断）
            await self._store.write_handoff_at(msg.shop_id, msg.buyer_id, datetime.now(tz=UTC))

        try:
            await self._escalate(escalation)
        except Exception as exc:
            logger.error("告警推送失败，仍继续 shop=%s: %s", msg.shop_id, exc)

    async def _async_writeback(self, ctx: SessionContext, msg: StandardMessage, reply: str) -> None:
        """异步记忆回写，失败不影响主流程。"""
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

