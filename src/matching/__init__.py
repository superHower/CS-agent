"""匹配决策层：FAQ 直达 + 意图识别 + 向量检索 + LLM 生成。"""

from src.matching.engine import MatchEngine, MatchRequest, MatchResult

__all__ = ["MatchEngine", "MatchRequest", "MatchResult"]
