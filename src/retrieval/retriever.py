"""统一检索器，按优先级分层召回：FAQ缓存 → 快捷短语关键词 → 语义向量 Top5。"""

import asyncio
import json
import logging
import random
import time
from pathlib import Path

from src.config.settings import ShopConfig
from src.contracts import KnowledgeChunk, RetrievalResult
from src.retrieval.faq_cache import FaqCache
from src.retrieval.query_enhancer import QueryEnhancer

logger = logging.getLogger(__name__)

# 向量检索超时（毫秒），超出使用兜底
_RETRIEVAL_TIMEOUT_MS = 300
_TOP_K = 5

# 快捷短语文件默认路径
_DEFAULT_SHORTCUT_PATH = Path(__file__).parent.parent.parent / ".claude" / "快捷短语.json"


class ShortcutPhraseIndex:
    """快捷短语关键词倒排索引。

    加载快捷短语 JSON 文件，按 code 字段建立关键词 → 短语列表的映射。
    用于 Level 2 匹配：买家消息中包含 code 关键词时直接返回对应短语。

    快捷短语 JSON 格式：
        [{"code": "安装", "phrase": "安装说明..."}, ...]
    """

    def __init__(self, phrases_path: Path | None = None) -> None:
        self._index: dict[str, list[str]] = {}
        if phrases_path is None:
            path = _DEFAULT_SHORTCUT_PATH
        else:
            path = phrases_path
        self._load(path)

    @classmethod
    def empty(cls) -> "ShortcutPhraseIndex":
        """创建空快捷短语索引（用于测试或禁用 Level 2 匹配的场景）。"""
        obj = cls.__new__(cls)
        obj._index = {}
        return obj

    def _load(self, path: Path) -> None:
        """从 JSON 文件加载快捷短语，构建倒排索引。"""
        if not path.exists():
            logger.warning("快捷短语文件不存在: %s，Level 2 匹配将跳过", path)
            return
        try:
            with open(path, encoding="utf-8") as f:
                items = json.load(f)
            for item in items:
                code = str(item.get("code", "")).strip()
                phrase = str(item.get("phrase", "")).strip()
                if code and phrase:
                    self._index.setdefault(code, []).append(phrase)
            logger.info("快捷短语索引加载完成，关键词数量: %d", len(self._index))
        except Exception as exc:
            logger.error("加载快捷短语文件失败 %s: %s", path, exc)

    def match(self, user_msg: str) -> str | None:
        """在用户消息中匹配快捷短语关键词。

        按 code 长度降序匹配（优先匹配更具体的关键词）。

        Args:
            user_msg: 买家原始消息。

        Returns:
            匹配到的快捷短语文本，未命中返回 None。
        """
        # 按 code 长度降序，优先匹配较长（更具体）的关键词
        for code in sorted(self._index.keys(), key=len, reverse=True):
            if code in user_msg:
                phrases = self._index[code]
                chosen = random.choice(phrases)
                logger.debug("Level2 快捷短语命中 code=%r msg=%r", code, user_msg[:30])
                return chosen
        return None

    @property
    def size(self) -> int:
        return len(self._index)


class Retriever:
    """分层知识检索器。

    检索优先级：
    1. FAQ 精确缓存（Redis）→ 命中直接返回
    2. 快捷短语关键词匹配（ShortcutPhraseIndex）→ 命中直接返回
    3. Qdrant 向量语义检索（Top-K）+ 元数据/标签过滤加权
    4. 超时时返回空结果，由状态机决策兜底
    """

    def __init__(
        self,
        faq_cache: FaqCache,
        qdrant_client,
        query_enhancer: QueryEnhancer,
        model_path: str = "models/bge-small-zh",
        shortcut_index: ShortcutPhraseIndex | None = None,
    ) -> None:
        self._faq = faq_cache
        self._qdrant = qdrant_client
        self._enhancer = query_enhancer
        self._model_path = model_path
        self._shortcut = shortcut_index if shortcut_index is not None else ShortcutPhraseIndex()

    def _refresh_model_path(self) -> None:
        """从全局配置同步嵌入模型路径（支持热更新）。"""
        from src.config.settings import get_config
        new_path = get_config().embedding.model_path
        if new_path != self._model_path:
            logger.info("嵌入模型路径已更新: %s → %s", self._model_path, new_path)
            self._model_path = new_path

    def _get_model(self):
        from src.retrieval.obsidian_indexer import get_embedding_model

        return get_embedding_model(self._model_path)

    def _is_api_embedding(self) -> bool:
        """判断是否使用 API 接口嵌入（而非本地 SentenceTransformer）。"""
        p = self._model_path
        return not (p.startswith("models/") or p.startswith("./") or p.startswith("/"))

    def _embed_query_via_api(self, query: str) -> list[float]:
        """通过 OpenAI 兼容接口调用嵌入模型（如百炼 text-embedding-v3）。"""
        import openai

        from src.config.settings import get_config

        cfg = get_config().llm
        client = openai.OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        resp = client.embeddings.create(model=self._model_path, input=query)
        return resp.data[0].embedding

    def _embed_query(self, query: str) -> list[float]:
        self._refresh_model_path()
        import time
        t0 = time.time()
        if self._is_api_embedding():
            logger.info("Embedding API 调用开始 model=%s query=%s", self._model_path, query[:30])
            vec = self._embed_query_via_api(query)
            logger.info("Embedding API 完成 耗时=%.2fs dim=%d", time.time() - t0, len(vec))
            return vec
        logger.info("Embedding 本地推理开始 model=%s query=%s", self._model_path, query[:30])
        model = self._get_model()
        vec = model.encode([query], show_progress_bar=False)[0].tolist()
        logger.info("Embedding 本地推理完成 耗时=%.2fs dim=%d", time.time() - t0, len(vec))
        return vec

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

        # 第二层：快捷短语关键词匹配
        shortcut_reply = self._shortcut.match(question)
        if shortcut_reply:
            return RetrievalResult(
                shop_id=shop_id,
                query=question,
                faq_hit=True,
                faq_reply=shortcut_reply,
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
            results = await self._qdrant.query_points(
                collection_name=collection,
                query=vector,
                limit=_TOP_K,
                with_payload=True,
            )
            hits = results.points
        except Exception as exc:
            logger.warning("Qdrant 检索失败 shop=%s: %s", shop_id, exc)
            return []

        chunks: list[KnowledgeChunk] = []
        for hit in hits:
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
