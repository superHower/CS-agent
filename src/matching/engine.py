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
import time

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

from src.config.settings import ShopConfig

logger = logging.getLogger(__name__)

# 意图识别超时（秒）
_INTENT_TIMEOUT_S = 2
# 整个非FAQ路径总超时（秒）
_TOTAL_TIMEOUT_S = 7


class IntentResult(BaseModel):
    """意图识别结果。"""

    model_config = ConfigDict(extra="ignore")

    intent: str = Field(default="其他")
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
        # ── Step 1: FAQ 精确缓存 ──────────────────────────────────────────────
        retrieval = await self._retriever.retrieve(shop_config, request.user_msg)

        if retrieval.faq_hit:
            logger.info("Step1 FAQ 命中 shop=%s", shop_config.shop_id)
            return MatchResult(
                reply=retrieval.faq_reply,
                source="faq_cache",
                confidence=100,
                needs_escalation=False,
                intent="faq",
            )

        # ── Step 2: LLM 意图识别（超时/失败降级）────────────────────────────
        intent_result = await self._recognize_intent(request)
        query = intent_result.rewrite_query or request.user_msg

        # ── Step 2.5: 用改写后的查询做向量检索（若检索层未检索到向量）──────
        if not retrieval.chunks and query != request.user_msg:
            try:
                retrieval2 = await asyncio.wait_for(
                    self._retriever.retrieve(shop_config, query),
                    timeout=0.5,
                )
                if retrieval2.chunks:
                    retrieval = retrieval2
            except Exception:
                pass  # 降级使用原检索结果（可能为空）

        # ── Step 3: LLM 生成回复 ──────────────────────────────────────────────
        from src.contracts.models import LLMRequest, TurnRecord
        from src.contracts.models import Platform

        knowledge_text = "\n".join(c.content for c in retrieval.chunks)

        # 构建 history TurnRecord 列表（dict 转换）
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
        except Exception as exc:
            logger.error("LLM 生成失败 shop=%s: %s", shop_config.shop_id, exc)
            return MatchResult(reply="", source="intent_rag", confidence=0, needs_escalation=True, intent=intent_result.intent)

        return MatchResult(
            reply=response.reply,
            source="intent_rag",
            confidence=response.confidence,
            needs_escalation=(response.confidence < shop_config.confidence_threshold),
            intent=intent_result.intent,
        )

    async def _recognize_intent(self, request: MatchRequest) -> IntentResult:
        """调用意图识别 LLM，失败/超时返回空 IntentResult（降级用原始消息检索）。"""
        from src.matching.intent_prompt import build_intent_messages
        from src.contracts.models import LLMRequest

        messages = build_intent_messages(request.user_msg, product_name=request.product_name)

        # 意图识别直接用底层 HTTP 调用，绕过 build_messages 的生成Prompt
        try:
            raw = await asyncio.wait_for(
                self._call_intent_raw(messages),
                timeout=_INTENT_TIMEOUT_S,
            )
        except (TimeoutError, Exception) as exc:
            logger.warning("意图识别失败（降级）: %s", exc)
            return IntentResult(rewrite_query=request.user_msg)

        try:
            # 尝试提取 JSON（LLM 可能有多余文本）
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                return IntentResult(**data)
        except Exception as exc:
            logger.warning("意图识别结果解析失败: %s raw=%s", exc, raw[:100])

        return IntentResult(rewrite_query=request.user_msg)

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
