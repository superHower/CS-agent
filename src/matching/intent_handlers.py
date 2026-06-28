"""意图处理器模块。

每个 IntentType 对应一个处理器，负责：
1. 补充检索策略（如物流查询注入订单信息）
2. 调整生成 Prompt / 置信度阈值
3. 返回处理结果

12 个一级意图 + 风险等级联动：
- low: 标准 RAG
- mid: 标准 RAG + 置信度阈值更严
- high: 安抚话术模式（不答实质内容），同时打 needs_escalation=True 转人工
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
        parts.append(f"【订单详情】\n{request.order_detail}")
    if include_product and request.product_name:
        parts.append(f"【当前商品】{request.product_name}")
    return "\n".join(parts)


# ── 风险等级常量 ──────────────────────────────────────────────────────────────

_RISK_LOW = "low"
_RISK_MID = "mid"
_RISK_HIGH = "high"


# ── 1. 售前产品咨询 ────────────────────────────────────────────────────────────


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
        return await engine._generate_with_context(
            request, shop_config, extra_knowledge=extra, risk_level=_RISK_LOW,
        )


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
        return await engine._generate_with_context(
            request, shop_config, extra_knowledge=extra, risk_level=_RISK_LOW,
        )


# ── 2. 订单物流 ────────────────────────────────────────────────────────────────


class LogisticsHandler(BaseIntentHandler):
    """物流询问处理器。"""

    intent_type = IntentType.LOGISTICS

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """物流询问：mid 风险，置信度阈值更严。"""
        from src.matching.engine import MatchEngine

        extra = _build_extra_context(request, include_order=True, include_product=True)
        engine = MatchEngine()
        return await engine._generate_with_context(
            request,
            shop_config,
            extra_knowledge=extra,
            confidence_adjustment=-0.05,
            risk_level=_RISK_MID,
        )


# ── 3. 安装使用 ────────────────────────────────────────────────────────────────


class InstallGuideHandler(BaseIntentHandler):
    """安装指导处理器。"""

    intent_type = IntentType.INSTALL_GUIDE

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """安装指导：标准 RAG 流程（mid 风险，安全相关已由 LLM 标 high 在 step 2.4 拦了）。"""
        from src.matching.engine import MatchEngine

        engine = MatchEngine()
        return await engine._generate_with_context(
            request, shop_config, risk_level=_RISK_MID,
        )


# ── 4. 售后故障退换 ────────────────────────────────────────────────────────────


class AfterSaleHandler(BaseIntentHandler):
    """售后问题处理器。"""

    intent_type = IntentType.AFTER_SALE

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """售后问题：mid 风险，置信度阈值更严。"""
        from src.matching.engine import MatchEngine

        extra = _build_extra_context(request, include_order=True, include_product=True)
        engine = MatchEngine()
        return await engine._generate_with_context(
            request,
            shop_config,
            extra_knowledge=extra,
            confidence_adjustment=-0.05,
            risk_level=_RISK_MID,
        )


# ── 5. 价格优惠权益 ────────────────────────────────────────────────────────────


class PricePromoHandler(BaseIntentHandler):
    """价格优惠处理器。"""

    intent_type = IntentType.PRICE_PROMO

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """价格优惠：mid 风险（涉及议价/改价，置信度更严）。"""
        from src.matching.engine import MatchEngine

        extra = _build_extra_context(request, include_product=True)
        engine = MatchEngine()
        return await engine._generate_with_context(
            request,
            shop_config,
            extra_knowledge=extra,
            confidence_adjustment=-0.05,
            risk_level=_RISK_MID,
        )


# ── 6. 投诉情绪升级 ────────────────────────────────────────────────────────────


class ComplaintHandler(BaseIntentHandler):
    """投诉/情绪化处理器。"""

    intent_type = IntentType.COMPLAINT

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """投诉/情绪化：低风险，AI 可安抚，但置信度更严（<0.6 转人工）。"""
        from src.matching.engine import MatchEngine

        extra = _build_extra_context(request, include_order=True, include_product=True)
        engine = MatchEngine()
        result = await engine._generate_with_context(
            request,
            shop_config,
            extra_knowledge=extra,
            confidence_adjustment=-0.1,
            risk_level=_RISK_LOW,
        )

        # 情绪化投诉降低阈值
        if result.confidence < 0.6:
            result.needs_escalation = True

        return result


# ── 7. 工程批量定制 ────────────────────────────────────────────────────────────


class BulkOrderHandler(BaseIntentHandler):
    """工程批量定制处理器。"""

    intent_type = IntentType.BULK_ORDER

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """工程批量：mid 风险，基础政策可答，深度需求已由 LLM 标 high 在 step 2.4 拦了。"""
        from src.matching.engine import MatchEngine

        extra = _build_extra_context(request, include_product=True)
        engine = MatchEngine()
        return await engine._generate_with_context(
            request,
            shop_config,
            extra_knowledge=extra,
            risk_level=_RISK_MID,
        )


# ── 8. 高风险类：安抚话术 + 转人工 ──────────────────────────────────────────────


class PlatformRiskHandler(BaseIntentHandler):
    """平台违规处理器：高风险，AI 只出安抚话术，转人工。"""

    intent_type = IntentType.PLATFORM_RISK

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """平台违规（加微信/刷单/好评返现）：安抚话术 + 转人工。

        提示词必须锁住：不能答实质内容，只能表达"已记录，稍后客服联系"。
        """
        from src.matching.engine import MatchEngine

        engine = MatchEngine()
        result = await engine._generate_with_context(
            request,
            shop_config,
            extra_knowledge=_build_appeasement_prompt("platform_risk"),
            risk_level=_RISK_HIGH,
            is_appeasement=True,
        )
        result.needs_escalation = True
        return result


class HealthRiskHandler(BaseIntentHandler):
    """健康相关处理器：高风险，AI 只出安抚话术，转人工。"""

    intent_type = IntentType.HEALTH_RISK

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """健康相关（眼睛不适/视力下降/孩子不舒服）：安抚话术 + 转人工。"""
        from src.matching.engine import MatchEngine

        engine = MatchEngine()
        result = await engine._generate_with_context(
            request,
            shop_config,
            extra_knowledge=_build_appeasement_prompt("health_risk"),
            risk_level=_RISK_HIGH,
            is_appeasement=True,
        )
        result.needs_escalation = True
        return result


def _build_appeasement_prompt(risk_kind: str) -> str:
    """构建安抚话术 prompt（注入到 knowledge 字段，引导 LLM 输出安抚回复）。"""
    if risk_kind == "platform_risk":
        return (
            "【回复规则 - 平台违规安抚】\n"
            "买家诉求涉及平台违规行为（加微信/私下交易/刷单/好评返现等），"
            "你不能直接答应或拒绝其具体要求。\n"
            "请生成一条简短、礼貌的回复：表示已记录其需求，会安排专业客服尽快联系，"
            "引导买家稍作等待。不要使用「亲」等过度亲昵称呼，避免承诺具体结果。\n"
            "长度控制在 30~60 字。"
        )
    if risk_kind == "health_risk":
        return (
            "【回复规则 - 健康相关安抚】\n"
            "买家反映因产品产生健康不适（眼睛/视力/儿童相关）。\n"
            "请生成一条共情且专业的回复：先表达理解与关切，说明会安排专业客服尽快对接，"
            "并建议如有明显不适先咨询医生。不要承诺赔偿或定性产品问题。\n"
            "长度控制在 30~60 字。"
        )
    return ""


# ── 9. 兜底类 ──────────────────────────────────────────────────────────────────


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
            risk_level=_RISK_LOW,
        )


class OtherHandler(BaseIntentHandler):
    """其他/未知意图处理器。"""

    intent_type = IntentType.OTHER

    async def handle(
        self,
        request: "MatchRequest",
        shop_config: "ShopConfig",
    ) -> IntentHandlerResult:
        """其他意图：mid 风险，标准 RAG 流程。"""
        from src.matching.engine import MatchEngine

        engine = MatchEngine()
        return await engine._generate_with_context(
            request, shop_config, risk_level=_RISK_MID,
        )


# ── 处理器注册表 ───────────────────────────────────────────────────────────────

_INTENT_HANDLERS: dict[IntentType, BaseIntentHandler] = {
    IntentType.PRODUCT_INQUIRY: ProductInquiryHandler(),
    IntentType.RECOMMEND: RecommendHandler(),
    IntentType.LOGISTICS: LogisticsHandler(),
    IntentType.INSTALL_GUIDE: InstallGuideHandler(),
    IntentType.AFTER_SALE: AfterSaleHandler(),
    IntentType.PRICE_PROMO: PricePromoHandler(),
    IntentType.COMPLAINT: ComplaintHandler(),
    IntentType.BULK_ORDER: BulkOrderHandler(),
    IntentType.PLATFORM_RISK: PlatformRiskHandler(),
    IntentType.HEALTH_RISK: HealthRiskHandler(),
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
