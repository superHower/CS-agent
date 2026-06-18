"""统一检索器，按优先级分层召回：FAQ缓存 → 元数据过滤 → 语义向量 Top5。"""

import asyncio
import logging
import time

from src.config.settings import ShopConfig
from src.contracts import KnowledgeChunk, RetrievalResult
from src.retrieval.faq_cache import FaqCache
from src.retrieval.query_enhancer import QueryEnhancer

logger = logging.getLogger(__name__)

# 向量检索超时（毫秒），超出使用兜底
_RETRIEVAL_TIMEOUT_MS = 300
_TOP_K = 5


class Retriever:
    """分层知识检索器。

    检索优先级：
    1. FAQ 精确缓存（Redis）→ 命中直接返回
    2. Qdrant 向量语义检索（Top-K）+ 元数据/标签过滤加权
    3. 超时时返回空结果，由状态机决策兜底
    """

    def __init__(
        self,
        faq_cache: FaqCache,
        qdrant_client,
        query_enhancer: QueryEnhancer,
        model_path: str = "models/bge-small-zh",
    ) -> None:
        self._faq = faq_cache
        self._qdrant = qdrant_client
        self._enhancer = query_enhancer
        self._model_path = model_path

    def _get_model(self):
        from src.retrieval.obsidian_indexer import get_embedding_model

        return get_embedding_model(self._model_path)

    def _embed_query(self, query: str) -> list[float]:
        model = self._get_model()
        return model.encode([query], show_progress_bar=False)[0].tolist()

    async def retrieve(self, shop_config: ShopConfig, question: str) -> RetrievalResult:
        """执行分层检索，返回 RetrievalResult。

        Args:
            shop_config: 店铺配置。
            question: 买家原始问题。

        Returns:
            RetrievalResult（FAQ命中时 chunks 为空，向量命中时填充 chunks）。
        """
        start_ms = int(time.time() * 1000)
        shop_id = shop_config.shop_id

        # 第一层：FAQ 精确缓存
        faq_reply = await self._faq.get(shop_id, question)
        if faq_reply:
            return RetrievalResult(
                shop_id=shop_id,
                query=question,
                faq_hit=True,
                faq_reply=faq_reply,
                elapsed_ms=int(time.time() * 1000) - start_ms,
            )

        # 查询增强
        queries = self._enhancer.enhance(question)
        main_query = queries[0]

        # 第二/三层：向量语义检索（含超时保护）
        try:
            chunks = await asyncio.wait_for(
                self._vector_search(shop_id, main_query),
                timeout=_RETRIEVAL_TIMEOUT_MS / 1000,
            )
        except TimeoutError:
            logger.warning("向量检索超时 shop=%s query=%s", shop_id, main_query[:30])
            chunks = []
        except Exception as exc:
            logger.error("向量检索异常 shop=%s: %s", shop_id, exc)
            chunks = []

        elapsed = int(time.time() * 1000) - start_ms
        return RetrievalResult(
            shop_id=shop_id,
            query=main_query,
            chunks=chunks,
            elapsed_ms=elapsed,
        )

    async def _vector_search(self, shop_id: str, query: str) -> list[KnowledgeChunk]:
        """执行 Qdrant 向量检索，返回 Top-K 知识片段。"""
        collection = f"collection_{shop_id}"
        vector = self._embed_query(query)

        try:
            results = await self._qdrant.search(
                collection_name=collection,
                query_vector=vector,
                limit=_TOP_K,
                with_payload=True,
            )
        except Exception as exc:
            logger.warning("Qdrant 检索失败 shop=%s: %s", shop_id, exc)
            return []

        chunks: list[KnowledgeChunk] = []
        for hit in results:
            payload = hit.payload or {}
            score = float(hit.score)

            # 标签/双链加权：命中店铺相关 tag 的片段提升分数
            tags = payload.get("tags", [])
            backlinks = payload.get("backlinks", [])
            if tags or backlinks:
                score = min(1.0, score * 1.1)

            chunks.append(
                KnowledgeChunk(
                    chunk_id=payload.get("chunk_id", f"{shop_id}:unknown:{hit.id}"),
                    content=payload.get("content", ""),
                    source_file=payload.get("source_file", ""),
                    score=round(score, 4),
                    tags=tags,
                    backlinks=backlinks,
                )
            )

        # 按分数降序排列
        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks
