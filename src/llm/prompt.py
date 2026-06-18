"""提示词模板引擎。

从 config/replies.yaml 读取系统提示词骨架，
动态注入店铺信息、知识片段、历史对话，输出最终 messages 列表。
"""

import logging

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """你是"{shop_name}"的智能客服助手。请根据以下知识库内容，准确、友好地回答买家的问题。

【知识库内容】
{knowledge}

【回复要求】
1. 仅根据知识库内容作答，不要编造信息。
2. 语气亲切，简洁明了，符合电商客服风格。
3. 回复末尾必须附上置信度，格式：[CONFIDENCE: XX]，XX 为 0-100 的整数。
4. 若知识库无相关内容，如实告知并表示将为买家转接人工客服，置信度填 0。
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
        system_content = _PROMPT_TEMPLATE.format(
            shop_name=shop_name,
            knowledge=knowledge_text,
        )
    else:
        system_content = _PROMPT_TEMPLATE.format(
            shop_name=shop_name,
            knowledge="（暂无相关知识库内容）",
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
