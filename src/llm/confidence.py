"""LLM 输出置信度解析。

约定：LLM 回复末尾必须包含 [CONFIDENCE: XX]，XX 为 0-100 整数。
解析失败时返回 0（触发转人工）。
"""

import logging
import re

logger = logging.getLogger(__name__)

_CONFIDENCE_RE = re.compile(r"\[CONFIDENCE:\s*(\d{1,3})\s*\]", re.IGNORECASE)


def parse_confidence(raw_text: str) -> tuple[str, int]:
    """从 LLM 原始输出中提取置信度并清理回复正文。

    Args:
        raw_text: LLM 原始输出，末尾应含 [CONFIDENCE: XX]。

    Returns:
        (clean_reply, confidence) 元组，其中：
        - clean_reply：去除置信度标记后的纯回复文本。
        - confidence：0-100 整数，解析失败返回 0。
    """
    match = _CONFIDENCE_RE.search(raw_text)
    if not match:
        logger.warning("LLM 输出缺少 [CONFIDENCE] 标记，默认置信度 0")
        return raw_text.strip(), 0

    raw_value = int(match.group(1))
    confidence = max(0, min(100, raw_value))  # clamp to [0, 100]

    # 清理回复：删除置信度标记及其前后空白
    clean = _CONFIDENCE_RE.sub("", raw_text).strip()
    return clean, confidence
