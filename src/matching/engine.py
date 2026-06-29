"""匹配决策引擎（MatchEngine）。

三步管道：
  Step 1 - FAQ 精确缓存命中 → 直接返回，source="faq_cache"
  Step 2 - LLM 意图识别 + 查询改写（超时/失败则降级）
  Step 3 - Qdrant 向量检索 + LLM 生成 + 置信度判断

设计原则：
  - 所有外部依赖通过构造函数注入，本模块不感知具体实现。
  - 超时/异常层层降级，宁可转人工也不乱回复。
  - 意图识别失败不影响检索和生成，直接用原始消息检索。
"""

import asyncio
import json
import logging
import re
import time

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

from src.config.settings import ShopConfig

logger = logging.getLogger(__name__)

# 意图识别超时（秒）
_INTENT_TIMEOUT_S = 2
# 整个非FAQ路径总超时（秒）
_TOTAL_TIMEOUT_S = 7


def _get_debug_ctx(request: "MatchRequest"):
    """按 message_id 查找 DebugContext（异步跨任务用）。"""
    from src.utils.trace import lookup_debug_context, get_debug_context
    if request.message_id:
        ctx = lookup_debug_context(request.message_id)
        if ctx is not None:
            return ctx
    return get_debug_context()


def _add_step(request: "MatchRequest", **kwargs):
    """向 DebugContext 追加一个步骤（若无上下文则跳过）。"""
    ctx = _get_debug_ctx(request)
    if ctx is None:
        return None
    return ctx.add_step(**kwargs)


class IntentResult(BaseModel):
    """意图识别结果。"""

    model_config = ConfigDict(extra="ignore")

    intent: str = Field(default="other", description="一级意图字符串，对应 IntentType.value")
    sub_intent: str = Field(default="", description="二级子意图，自由字符串，不入枚举")
    risk_level: str = Field(default="low", description="风险等级：low / mid / high")
    needs_escalation: bool = Field(default=False, description="是否需要转人工")
    escalate_reason: str = Field(default="", description="转人工原因描述")
    entities: list[str] = Field(default_factory=list)
    rewrite_query: str = Field(default="")


class MatchRequest(BaseModel):
    """匹配决策层输入。"""

    model_config = ConfigDict(extra="forbid")

    user_msg: str
    product_name: str = ""
    order_detail: str = ""
    history: list[dict[str, str]] = Field(default_factory=list)
    shop_id: str = ""
    # 调试用：用于跨任务查找 DebugContext
    message_id: str = ""
    # 意图识别补充字段
    rewrite_query: str = Field(default="", description="意图识别改写后的查询词")
    knowledge: str = Field(default="", description="向量检索返回的知识片段")
    # 抖音专用字段
    is_douyin: bool = Field(
        default=False,
        description="是否为抖音平台，用于判断是否使用 filtered_chat_list 构建上下文",
    )
    filtered_chat_list: list[str] = Field(
        default_factory=list,
        description="抖音已过滤的气泡数组（系统消息已移除），用于 LLM 意图识别上下文",
    )
    kefu: str = Field(
        default="",
        description="抖音客服名字",
    )


class MatchResult(BaseModel):
    """匹配决策层输出。"""

    model_config = ConfigDict(extra="forbid")

    reply: str
    source: str = Field(description="faq_cache | intent_rag | fallback")
    confidence: int = Field(ge=0, le=100)
    needs_escalation: bool = False
    intent: str = ""
    elapsed_ms: int = 0


class MatchEngine:
    """匹配决策引擎，统一 FAQ/意图/RAG 三路径。

    Args:
        retriever: Retriever 实例（提供 retrieve 方法）。
        llm_client: LLMClient 实例（提供 generate 方法）。
        intent_llm_client: 意图识别专用 LLMClient（可与主客户端相同）。
    """

    def __init__(self, retriever, llm_client, intent_llm_client=None) -> None:
        self._retriever = retriever
        self._llm = llm_client
        self._intent_llm = intent_llm_client or llm_client

    async def match(self, shop_config: ShopConfig, request: MatchRequest) -> MatchResult:
        """执行完整匹配流程，含超时保护。"""
        t0 = time.time()
        try:
            result = await asyncio.wait_for(
                self._match_inner(shop_config, request),
                timeout=_TOTAL_TIMEOUT_S,
            )
        except TimeoutError:
            logger.warning(
                "MatchEngine 总超时 %ds shop=%s msg=%s",
                _TOTAL_TIMEOUT_S, shop_config.shop_id, request.user_msg[:30],
            )
            result = MatchResult(reply="", source="fallback", confidence=0, needs_escalation=True)
        except Exception as exc:
            logger.error("MatchEngine 异常 shop=%s: %s", shop_config.shop_id, exc, exc_info=True)
            result = MatchResult(reply="", source="fallback", confidence=0, needs_escalation=True)

        result = result.model_copy(update={"elapsed_ms": int((time.time() - t0) * 1000)})
        logger.info(
            "MatchEngine 完成 shop=%s source=%s confidence=%d needs_escalation=%s elapsed=%dms",
            shop_config.shop_id, result.source, result.confidence, result.needs_escalation, result.elapsed_ms,
        )
        return result

    async def _match_inner(self, shop_config: ShopConfig, request: MatchRequest) -> MatchResult:
        # ── 抖音模式：is_douyin 时直接用已过滤的气泡数组 ─────────────────────────
        if request.is_douyin and request.filtered_chat_list:
            filtered_chat = request.filtered_chat_list
            chat_context = "\n".join(filtered_chat)
            detail_text = request.order_detail
            product_text = request.product_name
        else:
            chat_context = ""
            detail_text = ""
            product_text = ""

        # ── Step 1: FAQ 精确缓存（店铺专属 + 分类共享）─────────────────────────
        # 抖音模式：用过滤后 chatList 最后一条买家消息做 FAQ 命中
        if request.is_douyin and request.filtered_chat_list:
            faq_query = self._extract_last_user_message(filtered_chat)
        else:
            faq_query = request.user_msg

        # 检索层内部已处理店铺专属 FAQ → 分类共享 FAQ 的优先级
        retrieval = await self._retriever.retrieve(shop_config, faq_query)

        if retrieval.faq_hit:
            logger.info("Step1 FAQ 命中 shop=%s is_douyin=%s", shop_config.shop_id, request.is_douyin)
            # 记录 FAQ 命中详情
            logger.info(
                "Step1 FAQ 命中详情 shop=%s reply_chars=%d reply_preview=%s",
                shop_config.shop_id,
                len(retrieval.faq_reply),
                retrieval.faq_reply[:60].replace("\n", " "),
            )
            _add_step(
                request,
                step="faq_cache",
                label="Step1 FAQ 精确缓存",
                hit=True,
                reply=retrieval.faq_reply,
                faq_hit=True,
                faq_reply=retrieval.faq_reply,
                elapsed_ms=int((time.time() - t0) * 1000),
            )
            return MatchResult(
                reply=retrieval.faq_reply,
                source="faq_cache",
                confidence=100,
                needs_escalation=False,
                intent="faq",
            )

        # ── Step 1.5: 向量检索结果日志 ───────────────────────────────────────
        if retrieval.chunks:
            chunks_preview = "; ".join(
                f"[{c.score:.3f}]{c.content[:40].replace(chr(10), ' ')}"
                for c in retrieval.chunks[:3]
            )
            logger.info(
                "Step1 向量检索命中 shop=%s chunks=%d top1_score=%.3f preview=%s",
                shop_config.shop_id,
                len(retrieval.chunks),
                retrieval.chunks[0].score,
                chunks_preview[:200],
            )
            _add_step(
                request,
                step="rag",
                label="Step1 向量检索（RAG）",
                hit=True,
                chunks_count=len(retrieval.chunks),
                chunks=[
                    {"content": c.content, "score": c.score}
                    for c in retrieval.chunks
                ],
                elapsed_ms=int((time.time() - t0) * 1000),
            )
        else:
            logger.info(
                "Step1 向量检索未命中 shop=%s query=%s",
                shop_config.shop_id,
                request.user_msg[:30],
            )
            _add_step(
                request,
                step="rag",
                label="Step1 向量检索（RAG）",
                hit=False,
                chunks_count=0,
                elapsed_ms=int((time.time() - t0) * 1000),
            )

        # ── Step 2: LLM 意图识别 ─────────────────────────────────────────────
        t_intent = time.time()
        # 抖音模式：传入过滤后 chatList + detail + product 构建上下文
        intent_request = self._build_intent_request(request, chat_context, detail_text, product_text)
        intent_result = await self._recognize_intent(intent_request)
        intent_elapsed_ms = int((time.time() - t_intent) * 1000)

        # 映射字符串意图到 IntentType 枚举（未知意图降级为 OTHER）
        from src.contracts.models import IntentType
        try:
            intent_type = IntentType(intent_result.intent.lower())
        except ValueError:
            logger.warning("未知意图字符串 %s → OTHER", intent_result.intent)
            intent_type = IntentType.OTHER
        query = intent_result.rewrite_query or request.user_msg

        logger.info(
            "意图识别完成 shop=%s intent=%s sub_intent=%s risk=%s entities=%s rewrite=%r "
            "needs_escalation=%s escalate_reason=%s",
            shop_config.shop_id,
            intent_type.value,
            intent_result.sub_intent,
            intent_result.risk_level,
            intent_result.entities,
            intent_result.rewrite_query or request.user_msg,
            intent_result.needs_escalation,
            intent_result.escalate_reason,
        )

        _add_step(
            request,
            step="intent",
            label="Step2 意图识别",
            hit=not intent_result.needs_escalation,
            intent=intent_type.value,
            entities=intent_result.entities,
            rewrite_query=intent_result.rewrite_query,
            elapsed_ms=intent_elapsed_ms,
            error=intent_result.escalate_reason if intent_result.needs_escalation else "",
        )

        # ── Step 2.4: 意图层风险判定（先于检索/生成） ───────────────────────
        # high 风险且需要安抚话术的意图（platform_risk / health_risk）
        # → 走对应 handler 出安抚话术 + needs_escalation
        # 其余 high 风险（情绪维权 / 安全事故 / 识别失败等）
        # → 直接返回，不再走 RAG/生成（handler 出安抚话不合适）
        appeasement_intents = {IntentType.PLATFORM_RISK, IntentType.HEALTH_RISK}
        is_high_risk = intent_result.risk_level == "high" or intent_result.needs_escalation
        is_appeasement_intent = intent_type in appeasement_intents
        if is_high_risk and not is_appeasement_intent:
            logger.info(
                "Step2 风险拦截 shop=%s intent=%s risk=%s reason=%s",
                shop_config.shop_id, intent_type.value,
                intent_result.risk_level, intent_result.escalate_reason,
            )
            return MatchResult(
                reply="",
                source=f"intent_{intent_type.value}_risk_blocked",
                confidence=0,
                needs_escalation=True,
                intent=intent_type.value,
            )

        # ── Step 2.5: 用改写后的查询做向量检索（若检索层未检索到向量）──────
        # 高风险安抚类意图跳过二次检索（安抚话术不需要 RAG）
        if not is_high_risk and not retrieval.chunks and query != request.user_msg:
            try:
                retrieval2 = await asyncio.wait_for(
                    self._retriever.retrieve(shop_config, query),
                    timeout=0.5,
                )
                if retrieval2.chunks:
                    retrieval = retrieval2
                    chunks_preview = "; ".join(
                        f"[{c.score:.3f}]{c.content[:40].replace(chr(10), ' ')}"
                        for c in retrieval2.chunks[:3]
                    )
                    logger.info(
                        "Step2.5 改写查询检索 shop=%s rewrite=%r chunks=%d top1_score=%.3f preview=%s",
                        shop_config.shop_id,
                        query,
                        len(retrieval2.chunks),
                        retrieval2.chunks[0].score,
                        chunks_preview[:200],
                    )
            except Exception:
                pass  # 降级使用原检索结果（可能为空）

        # ── Step 3: 按意图类型路由到对应处理器 ───────────────────────────────
        from src.matching.intent_handlers import dispatch_intent

        # 补充检索到的知识到 request
        knowledge_text = "\n".join(c.content for c in retrieval.chunks)
        request_with_knowledge = request.model_copy(update={
            "knowledge": knowledge_text,
        })

        try:
            handler_result = await dispatch_intent(intent_type, request_with_knowledge, shop_config)
        except Exception as exc:
            logger.warning("意图处理器异常，降级为标准生成: %s", exc)
            handler_result = await self._generate_with_context(request_with_knowledge, shop_config)

        logger.info(
            "Step3 意图处理器完成 shop=%s intent=%s confidence=%.2f needs_escalation=%s "
            "reply_chars=%d reply_preview=%s",
            shop_config.shop_id,
            intent_type.value,
            handler_result.confidence,
            handler_result.needs_escalation,
            len(handler_result.reply),
            handler_result.reply[:80].replace("\n", " "),
        )

        # 记录 LLM 生成步骤（含检索到的知识字符数 + 置信度 + 回复）
        _add_step(
            request,
            step="llm",
            label="Step3 LLM 生成",
            hit=not handler_result.needs_escalation,
            reply=handler_result.reply,
            confidence=int(handler_result.confidence * 100),
            knowledge_chars=len(knowledge_text),
            elapsed_ms=int((time.time() - t0) * 1000),
        )

        return MatchResult(
            reply=handler_result.reply,
            source=f"intent_{intent_type.value}",
            confidence=int(handler_result.confidence * 100),
            needs_escalation=handler_result.needs_escalation,
            intent=intent_type.value,
        )

    @staticmethod
    def _build_intent_request(
        request: MatchRequest,
        chat_context: str,
        detail_text: str,
        product_text: str,
    ) -> MatchRequest:
        """构建意图识别用的 MatchRequest（抖音模式注入额外上下文）。

        抖音模式：user_msg 追加过滤后的 chatList + detail + product 作为上下文。
        """
        if not chat_context:
            return request

        # 拼装抖音扩展上下文（各字段独立区块，分隔清晰）
        extra_context_parts = []
        if product_text and product_text not in ("无", "none", ""):
            extra_context_parts.append(f"【商品名称】{product_text}")
        if detail_text and detail_text not in ("无", "none", ""):
            # detail 保留完整内容，让 LLM 看清哪些是订单信息
            extra_context_parts.append(f"【订单详情】{detail_text}")
        extra_context_parts.append(f"【买卖双方对话记录】（按时间正序）\n{chat_context}")

        extended_msg = (
            f"【买家当前问题】{request.user_msg}\n\n"
            + "\n\n".join(extra_context_parts)
        )

        return request.model_copy(update={
            "user_msg": extended_msg,
            "product_name": product_text or request.product_name,
            "order_detail": detail_text or request.order_detail,
        })

    @staticmethod
    def _extract_last_user_message(filtered_chat: list[str]) -> str:
        """从过滤后的抖音气泡数组中提取最后一条买家消息。

        反向遍历，找最后一个非系统/非客服的气泡内容作为买家消息。
        """
        for item in reversed(filtered_chat):
            # 简单启发式：不含 kefu 名字、不含系统关键词、可能是买家发的
            if item.strip():
                # 取第一行作为代表（去掉时间戳等杂项）
                first_line = item.strip().split("\n")[0].strip()
                # 排除纯时间戳（如 "10:03"）
                if re.match(r"^\d{1,2}:\d{2}$", first_line):
                    continue
                return item
        return ""

    async def _recognize_intent(self, request: MatchRequest) -> IntentResult:
        """调用意图识别 LLM，失败/超时/解析失败统一按 high risk 转人工。

        降级策略：识别失败时不静默走 RAG，而是直接标记为高风险 + 转人工，
        避免在用户表达情绪/违规诉求时系统答非所问。
        """
        from src.matching.intent_prompt import build_intent_messages
        from src.contracts.models import LLMRequest

        messages = build_intent_messages(request.user_msg, product_name=request.product_name)

        try:
            raw = await asyncio.wait_for(
                self._call_intent_raw(messages),
                timeout=_INTENT_TIMEOUT_S,
            )
        except (TimeoutError, Exception) as exc:
            logger.warning("意图识别失败 → 转人工: %s", exc)
            return IntentResult(
                intent="other",
                risk_level="high",
                needs_escalation=True,
                escalate_reason="意图识别失败",
                rewrite_query=request.user_msg,
            )

        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                # 防御：缺少 risk_level 时默认 low
                if "risk_level" not in data:
                    data["risk_level"] = "low"
                # 防御：needs_escalation 字段缺失时按 risk_level 推算
                if "needs_escalation" not in data:
                    data["needs_escalation"] = data["risk_level"] == "high"
                return IntentResult(**data)
        except Exception as exc:
            logger.warning("意图识别结果解析失败 → 转人工: %s raw=%s", exc, raw[:100])
            return IntentResult(
                intent="other",
                risk_level="high",
                needs_escalation=True,
                escalate_reason="意图识别结果解析失败",
                rewrite_query=request.user_msg,
            )

        logger.warning("意图识别返回无 JSON 段 → 转人工 raw=%s", raw[:100])
        return IntentResult(
            intent="other",
            risk_level="high",
            needs_escalation=True,
            escalate_reason="意图识别返回格式异常",
            rewrite_query=request.user_msg,
        )

    async def _call_intent_raw(self, messages: list[dict[str, str]]) -> str:
        """直接调用底层 HTTP 接口做意图识别（低温度、短tokens）。"""
        from src.config.settings import get_config

        cfg = get_config().llm
        import aiohttp as _aiohttp

        payload = {
            "model": cfg.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 200,
        }
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }
        timeout = _aiohttp.ClientTimeout(total=_INTENT_TIMEOUT_S + 1)
        async with _aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{cfg.base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"意图识别 HTTP {resp.status}")
                data = await resp.json()
        return data["choices"][0]["message"]["content"]

    async def _generate_with_context(
        self,
        request: MatchRequest,
        shop_config: "ShopConfig",
        extra_knowledge: str = "",
        confidence_adjustment: float = 0.0,
        risk_level: str = "low",
        is_appeasement: bool = False,
    ) -> "IntentHandlerResult":
        """生成回复：合并检索知识 + 额外上下文 + LLM 生成。

        Args:
            request: 匹配请求（已含 request.knowledge）
            shop_config: 店铺配置
            extra_knowledge: 额外的知识文本（如订单详情、商品信息）
            confidence_adjustment: 置信度调整值
            risk_level: 风险等级（low/mid/high）
            is_appeasement: 是否为安抚话术模式（高风险意图专用，prompt 锁住只输出安抚）
        """
        from src.contracts.models import LLMRequest, TurnRecord, IntentHandlerResult

        # 合并知识
        knowledge_parts = []
        if request.knowledge:
            knowledge_parts.append(request.knowledge)
        if extra_knowledge:
            knowledge_parts.append(extra_knowledge)
        knowledge_text = "\n".join(knowledge_parts)

        # 构建历史
        history_turns: list[TurnRecord] = []
        for h in request.history[-6:]:
            try:
                history_turns.append(TurnRecord(
                    role=h.get("role", "user"),
                    content=h.get("content", ""),
                    timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                ))
            except Exception:
                pass

        llm_req = LLMRequest(
            shop_id=shop_config.shop_id,
            shop_name=shop_config.name,
            buyer_message=request.user_msg,
            history=history_turns,
            knowledge=knowledge_text,
        )

        try:
            response = await self._llm.generate(llm_req)
            logger.info(
                "LLM 生成完成 shop=%s reply_chars=%d confidence=%.2f preview=%s",
                shop_config.shop_id,
                len(response.reply),
                response.confidence,
                response.reply[:80].replace("\n", " "),
            )
        except Exception as exc:
            logger.error("LLM 生成失败 shop=%s: %s", shop_config.shop_id, exc)
            return IntentHandlerResult(
                reply="",
                confidence=0.0,
                needs_escalation=True,
            )

        adjusted_confidence = max(0.0, min(1.0, response.confidence + confidence_adjustment))
        # 安抚话术模式：置信度阈值降一档（不再因"不准确"而转人工）
        if is_appeasement:
            needs_escalation = False
        else:
            needs_escalation = adjusted_confidence < shop_config.confidence_threshold / 100.0

        return IntentHandlerResult(
            reply=response.reply,
            confidence=adjusted_confidence,
            needs_escalation=needs_escalation,
        )
