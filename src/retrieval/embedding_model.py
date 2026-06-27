"""嵌入模型加载模块，支持本地 SentenceTransformer 和 API 调用。"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 本地模型缓存
_local_models: dict[str, Any] = {}


@lru_cache(maxsize=4)
def get_embedding_model(model_path: str) -> Any:
    """获取嵌入模型实例（带缓存）。

    Args:
        model_path: 模型路径，如 "models/bge-small-zh" 或 "bge-small-zh"

    Returns:
        SentenceTransformer 模型实例
    """
    from sentence_transformers import SentenceTransformer

    # 标准化路径
    if not model_path.startswith("models/") and not model_path.startswith("./"):
        model_path = f"models/{model_path}"

    if model_path in _local_models:
        logger.debug("复用缓存模型: %s", model_path)
        return _local_models[model_path]

    logger.info("加载嵌入模型: %s", model_path)
    model = SentenceTransformer(model_path)
    _local_models[model_path] = model
    return model


def clear_model_cache() -> None:
    """清除模型缓存（用于热更新）。"""
    _local_models.clear()
    get_embedding_model.cache_clear()
