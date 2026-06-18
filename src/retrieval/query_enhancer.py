"""查询增强模块，对买家原始问题进行改写以提升向量检索质量。

改写逻辑基于正则 + 词典，不调用大模型。
"""

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 否定句式改写规则：(pattern, replacement_prefix)
_NEGATION_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"不亮"), "故障 不亮"),
    (re.compile(r"不工作"), "故障 不工作"),
    (re.compile(r"坏了"), "故障 损坏"),
    (re.compile(r"打不开"), "故障 无法开启"),
    (re.compile(r"安装不上"), "安装问题 安装失败"),
    (re.compile(r"收不到货"), "物流 未收到"),
    (re.compile(r"没发货"), "发货 未发货"),
]


class QueryEnhancer:
    """查询增强器，支持型号缩写展开和否定句式改写。

    每个店铺可配置独立的商品词典（YAML 格式），实现个性化改写。
    """

    def __init__(self, product_dict: dict[str, str] | None = None) -> None:
        """
        Args:
            product_dict: 型号缩写 -> 全称映射字典，如 {"A款": "吸顶灯A款"}。
        """
        self._dict: dict[str, str] = product_dict or {}
        # 按缩写长度降序排列，确保长缩写优先匹配
        self._sorted_keys = sorted(self._dict.keys(), key=len, reverse=True)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "QueryEnhancer":
        """从 YAML 词典文件加载商品词典。

        YAML 格式示例：
            A款: 吸顶灯A款
            B款: 吸顶灯B款

        Args:
            path: YAML 文件路径。

        Returns:
            QueryEnhancer 实例。
        """
        try:
            with open(path, encoding="utf-8") as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
            product_dict = {str(k): str(v) for k, v in data.items()}
            logger.info("商品词典加载成功: %s 共 %d 条", path, len(product_dict))
            return cls(product_dict)
        except FileNotFoundError:
            logger.warning("商品词典文件不存在: %s，使用空词典", path)
            return cls({})
        except Exception as exc:
            logger.error("商品词典加载失败: %s: %s", path, exc)
            return cls({})

    def expand_abbreviations(self, query: str) -> str:
        """将查询中的型号缩写展开为全称。

        Args:
            query: 原始查询字符串。

        Returns:
            展开后的查询字符串。
        """
        result = query
        for abbr in self._sorted_keys:
            if abbr in result:
                full = self._dict[abbr]
                result = result.replace(abbr, full)
        return result

    def rewrite_negation(self, query: str) -> str:
        """改写否定/故障句式，避免向量语义漂移。

        例如："灯不亮" → "故障 不亮 灯不亮"（保留原文并追加改写结果）

        Args:
            query: 原始查询字符串。

        Returns:
            改写后的查询字符串。
        """
        additions: list[str] = []
        for pattern, prefix in _NEGATION_RULES:
            if pattern.search(query):
                additions.append(prefix)
        if additions:
            return " ".join(additions) + " " + query
        return query

    def enhance(self, query: str) -> list[str]:
        """对查询执行全量增强，返回增强后的查询列表。

        返回多个变体供检索层合并使用。

        Args:
            query: 原始买家消息。

        Returns:
            增强后的查询字符串列表（第一个为主查询）。
        """
        queries: list[str] = []

        # 主查询：先展开缩写，再改写否定
        expanded = self.expand_abbreviations(query)
        main = self.rewrite_negation(expanded)
        queries.append(main)

        # 如果展开后与原始不同，也保留原始作为备用
        if expanded != query:
            queries.append(query)

        return queries
