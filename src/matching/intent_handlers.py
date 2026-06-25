"""意图处理器模块。

每个 IntentType 对应一个处理器，负责：
1. 补充检索策略（如物流查询注入订单信息）
2. 调整生成 Prompt
3. 返回处理结果
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from src.contracts.models import IntentHandlerResult, IntentType

if TYPE_CHECKING:
    from src.matching.engine import MatchRequest, ShopConfig


class BaseIntentHandler(ABC):
    """意图处理器基类。"""

    intent_type: IntentType

    @abstractmethod
    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """处理对应意图类型的请求。"""
        ...


def _build_extra_context(
    request: "MatchRequest",
    include_order: bool = False,
    include_product: bool = False,
) -> str:
    """构建意图处理器的额外上下文。"""
    parts = []
    if include_order and request.order_detail:
        parts.append(f"【订单详情】\n{request.order_detail[:300]}")
    if include_product and request.product_name:
        parts.append(f"【当前商品】{request.product_name}")
    return "\n".join(parts)


class LogisticsHandler(BaseIntentHandler):
    """物流询问处理器。"""

    intent_type = IntentType.LOGISTICS

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """物流询问：优先使用订单详情作为上下文。"""
        from src.matching.engine import MatchEngine

        extra = _build_extra_context(request, include_order=True, include_product=True)
        engine = MatchEngine()
        return await engine._generate_with_context(
            request, shop_config, extra_knowledge=extra, confidence_adjustment=0.0
        )


class AfterSaleHandler(BaseIntentHandler):
    """售后问题处理器。"""

    intent_type = IntentType.AFTER_SALE

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """售后问题：可适当降低置信度阈值。"""
        from src.matching.engine import MatchEngine

        extra = _build_extra_context(request, include_order=True, include_product=True)
        engine = MatchEngine()
        return await engine._generate_with_context(
            request,
            shop_config,
            extra_knowledge=extra,
            confidence_adjustment=-0.05,  # 稍宽松
        )


class ComplaintHandler(BaseIntentHandler):
    """投诉/情绪化处理器。"""

    intent_type = IntentType.COMPLAINT

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """投诉/情绪化：更严格置信度，低于0.6直接转人工。"""
        from src.matching.engine import MatchEngine

        extra = _build_extra_context(request, include_order=True, include_product=True)
        engine = MatchEngine()
        result = await engine._generate_with_context(
            request,
            shop_config,
            extra_knowledge=extra,
            confidence_adjustment=-0.1,
        )

        # 情绪化投诉降低阈值
        if result.confidence < 0.6:
            result.needs_escalation = True

        return result


class ProductInquiryHandler(BaseIntentHandler):
    """产品咨询处理器。"""

    intent_type = IntentType.PRODUCT_INQUIRY

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """产品咨询：补充商品信息上下文。"""
        from src.matching.engine import MatchEngine

        extra = _build_extra_context(request, include_product=True)
        engine = MatchEngine()
        return await engine._generate_with_context(request, shop_config, extra_knowledge=extra)


class InstallGuideHandler(BaseIntentHandler):
    """安装指导处理器。"""

    intent_type = IntentType.INSTALL_GUIDE

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """安装指导：标准 RAG 流程。"""
        from src.matching.engine import MatchEngine

        engine = MatchEngine()
        return await engine._generate_with_context(request, shop_config)


class RecommendHandler(BaseIntentHandler):
    """产品推荐处理器。"""

    intent_type = IntentType.RECOMMEND

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """产品推荐：补充商品信息 + 热销推荐知识。"""
        from src.matching.engine import MatchEngine

        extra = _build_extra_context(request, include_product=True)
        engine = MatchEngine()
        return await engine._generate_with_context(request, shop_config, extra_knowledge=extra)


class ChitchatHandler(BaseIntentHandler):
    """闲聊处理器。"""

    intent_type = IntentType.CHITCHAT

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """闲聊：简短回复 + 低置信度阈值。"""
        from src.matching.engine import MatchEngine

        engine = MatchEngine()
        return await engine._generate_with_context(
            request,
            shop_config,
            extra_knowledge="",
            confidence_adjustment=-0.1,
        )


class OtherHandler(BaseIntentHandler):
    """其他/未知意图处理器。"""

    intent_type = IntentType.OTHER

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """其他意图：标准 RAG 流程。"""
        from src.matching.engine import MatchEngine

        engine = MatchEngine()
        return await engine._generate_with_context(request, shop_config)


# ── 处理器注册表 ───────────────────────────────────────────────────────────────

_INTENT_HANDLERS: dict[IntentType, BaseIntentHandler] = {
    IntentType.LOGISTICS: LogisticsHandler(),
    IntentType.AFTER_SALE: AfterSaleHandler(),
    IntentType.COMPLAINT: ComplaintHandler(),
    IntentType.PRODUCT_INQUIRY: ProductInquiryHandler(),
    IntentType.INSTALL_GUIDE: InstallGuideHandler(),
    IntentType.RECOMMEND: RecommendHandler(),
    IntentType.CHITCHAT: ChitchatHandler(),
    IntentType.OTHER: OtherHandler(),
}


async def dispatch_intent(
    intent: IntentType,
    request: "MatchRequest",
    shop_config: "ShopConfig",
) -> IntentHandlerResult:
    """根据意图类型分发到对应处理器。"""
    handler = _INTENT_HANDLERS.get(intent, _INTENT_HANDLERS[IntentType.OTHER])
    return await handler.handle(request, shop_config)
