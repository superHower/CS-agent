"""意图识别 Prompt 模板。

与生成回复的 Prompt 分离，使用低温度、短 max_tokens 模式。
"""

_INTENT_SYSTEM = """你是电商客服意图识别助手，负责分析买家消息。

请分析买家的问题，返回 JSON 格式结果（只输出 JSON，不要其他内容）：
{
  "intent": "安装咨询|产品推荐|售后问题|物流询问|价格优惠|产品参数|退款退货|闲聊|其他",
  "entities": ["关键词1", "关键词2"],
  "rewrite_query": "改写后的检索句子（完整、规范、适合语义搜索）"
}

规则：
- intent 从给定分类中选一个最匹配的
- entities 提取产品型号、参数名、问题类型等关键词，最多5个
- rewrite_query 用于向量数据库检索，应包含完整语义
"""


def build_intent_messages(buyer_message: str, product_name: str = "") -> list[dict[str, str]]:
    """构建意图识别所需的 messages。

    Args:
        buyer_message: 买家当前消息。
        product_name: 商品名（如有），帮助识别意图。

    Returns:
        OpenAI Chat 格式的 messages 列表。
    """
    context = ""
    if product_name:
        context = f"\n（买家正在咨询的商品：{product_name}）"

    return [
        {"role": "system", "content": _INTENT_SYSTEM},
        {"role": "user", "content": f"{buyer_message}{context}"},
    ]
