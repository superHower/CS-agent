"""提示词模板引擎。

从 config/replies.yaml 读取系统提示词骨架，
动态注入店铺信息、知识片段、历史对话，输出最终 messages 列表。
"""

import logging

logger = logging.getLogger(__name__)

# 固定售后决策规则 + 产品核心知识（嵌入系统提示词，无需检索）
_PRODUCT_KNOWLEDGE = """【售后处理原则】
1. 处理优先级：优先补偿 → 其次补发 → 最后退货退款
2. 补偿上限：商品金额 × 15~16%，以红包或优惠券形式发放
3. 禁止主动提退款，先给补偿方案，买家坚持退才走退款流程
4. 极兔/邮政快递破损：联系快递公司索赔；顺丰/丹鸟：直接补发

【产品核心知识】
- 瓦数与面积：24W≈5㎡, 36W≈9㎡, 48W≈15㎡, 72W≈18㎡, 96W≈30㎡, 120W≈40㎡
- 无极调光：带遥控，可调三色+明暗，价格较高
- 三色灯：墙壁开关变色（关-开-关-开切换色温），无遥控
- 白光/暖光/中性光：单色不可调
- 安装方法：6mm钻头打孔，接零线和火线，中间线不用接，左右两根线接就可以
- 安装注意：收货先检查包裹和灯具是否完好，通电试亮，再联系师傅安装；师傅二次上门费用买家承担
- 质保政策：3~5年（9.9元款无质保），第1年免费补发配件，之后买家承担运费
- 光源批次：批次不同导致外观略有差异属正常，功率相同，使用螺丝固定光源即可
- 过质保维修：自行在线下五金店或网上搜"LED光源驱动"购买配件"""

_PROMPT_TEMPLATE = """你是"{shop_name}"的专业客服，销售吸顶灯。

{product_knowledge}

【相关知识】
{knowledge}

【回复要求】
1. 优先根据相关知识和产品核心知识作答；若无相关内容，可结合通用电商常识回答。
2. 语气亲切，简洁明了，符合电商客服风格，用口语化表达。
3. 回复末尾必须附上置信度，格式：[CONFIDENCE: XX]，XX 为 0-100 的整数。
4. 置信度含义：知识库有明确答案填 90-100；依赖通用常识回答填 60-80；完全无法回答填 0。
5. 只有在完全无法给出任何有用回复时，置信度才填 0。
"""

_GREETING_SYSTEM = """你是智能客服助手。买家发来的是寒暄问候，请简短友好地回应，无需查阅知识库。
回复末尾附上：[CONFIDENCE: 95]"""


def build_messages(
    shop_name: str,
    buyer_message: str,
    history: list[dict[str, str]],
    knowledge_chunks: list[str],
) -> list[dict[str, str]]:
    """组装发送给 LLM 的 messages 列表。

    Args:
        shop_name: 店铺名称（注入系统提示词）。
        buyer_message: 买家当前消息。
        history: 历史对话列表，每条为 {"role": "user"/"assistant", "content": "..."}。
        knowledge_chunks: 已检索到的知识片段文本列表。

    Returns:
        OpenAI Chat 格式的 messages 列表。
    """
    if knowledge_chunks:
        knowledge_text = "\n\n".join(
            f"[片段{i + 1}] {chunk}" for i, chunk in enumerate(knowledge_chunks)
        )
    else:
        knowledge_text = "（暂无相关知识库内容）"

    system_content = _PROMPT_TEMPLATE.format(
        shop_name=shop_name,
        product_knowledge=_PRODUCT_KNOWLEDGE,
        knowledge=knowledge_text,
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]

    # 追加历史对话（最近 N 轮，已由 SessionStore 截断）
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({"role": "user", "content": buyer_message})
    return messages


def build_greeting_messages(buyer_message: str) -> list[dict[str, str]]:
    """为寒暄类消息构建轻量提示词。"""
    return [
        {"role": "system", "content": _GREETING_SYSTEM},
        {"role": "user", "content": buyer_message},
    ]
