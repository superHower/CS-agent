"""Obsidian 向量同步模块，将 .md 文件分段嵌入并存入 Qdrant。

启动时全量同步，运行时通过 watchdog 监听增量更新。
嵌入模型以全局单例加载，避免重复初始化。
"""

import hashlib
import logging
import re
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 段落最大字符数（超出则截断）
_CHUNK_MAX_CHARS = 500
# 段落最小字符数（过短则合并到上一段）
_CHUNK_MIN_CHARS = 50

_embedding_model = None
_embedding_model_path: str = ""
_embedding_lock = threading.Lock()


def get_embedding_model(model_path: str):
    """按 model_path 加载嵌入模型，path 变化时自动重新加载。

    Args:
        model_path: 模型名称或本地目录路径。

    Returns:
        SentenceTransformer 实例。
    """
    global _embedding_model, _embedding_model_path
    if _embedding_model is not None and _embedding_model_path == model_path:
        return _embedding_model
    with _embedding_lock:
        if _embedding_model is None or _embedding_model_path != model_path:
            try:
                from sentence_transformers import SentenceTransformer

                _embedding_model = SentenceTransformer(model_path)
                _embedding_model_path = model_path
                logger.info("嵌入模型加载成功: %s", model_path)
            except Exception as exc:
                logger.error("嵌入模型加载失败: %s: %s", model_path, exc)
                raise
    return _embedding_model


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """解析 Obsidian Markdown frontmatter。

    Args:
        content: .md 文件全文。

    Returns:
        (frontmatter_dict, body_text) 元组。
    """
    import yaml

    fm: dict[str, Any] = {}
    body = content
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            try:
                fm = yaml.safe_load(content[3:end]) or {}
            except Exception:
                pass
            body = content[end + 3 :].lstrip("\n")
    return fm, body


def _extract_backlinks(content: str) -> list[str]:
    """从 Obsidian 双链语法中提取引用笔记名称列表。

    例如 [[安装说明]] → ["安装说明"]
    """
    return re.findall(r"\[\[([^\]]+)\]\]", content)


def _split_chunks(text: str, source_file: str, shop_id: str) -> list[dict]:
    """将文本按段落切分为检索片段列表。

    Args:
        text: 笔记正文（已去除 frontmatter）。
        source_file: 相对 vault 根目录的文件路径。
        shop_id: 店铺 ID（用于生成 chunk_id）。

    Returns:
        chunk 字典列表，每个 chunk 包含 chunk_id、content、source_file。
    """
    # 按两个或以上空行分段
    raw_paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: list[dict] = []
    buffer = ""
    idx = 0

    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        buffer = (buffer + "\n" + para).strip() if buffer else para
        if len(buffer) >= _CHUNK_MIN_CHARS:
            # 超长时截断
            while len(buffer) > _CHUNK_MAX_CHARS:
                chunks.append(
                    {
                        "chunk_id": f"{shop_id}:{source_file}:{idx}",
                        "content": buffer[:_CHUNK_MAX_CHARS],
                        "source_file": source_file,
                        "idx": idx,
                    }
                )
                buffer = buffer[_CHUNK_MAX_CHARS:]
                idx += 1
            chunks.append(
                {
                    "chunk_id": f"{shop_id}:{source_file}:{idx}",
                    "content": buffer,
                    "source_file": source_file,
                    "idx": idx,
                }
            )
            buffer = ""
            idx += 1

    if buffer:
        chunks.append(
            {
                "chunk_id": f"{shop_id}:{source_file}:{idx}",
                "content": buffer,
                "source_file": source_file,
                "idx": idx,
            }
        )

    return chunks


def _file_hash(path: Path) -> str:
    """计算文件内容 MD5，用于变更检测。"""
    return hashlib.md5(path.read_bytes()).hexdigest()


class ObsidianIndexer:
    """Obsidian 知识库向量同步器。

    职责：
    - 启动时全量扫描 vault，将所有 .md 文件嵌入并 upsert 到 Qdrant。
    - 使用 watchdog 监听文件变更，增量更新（新增/修改 → upsert，删除 → remove）。
    - 嵌入模型以全局单例加载，多店铺共享同一模型实例。
    """

    def __init__(
        self,
        shop_id: str,
        vault_path: str | Path,
        qdrant_client,
        model_path: str = "models/bge-small-zh",
        vector_size: int = 512,
    ) -> None:
        self._shop_id = shop_id
        self._vault = Path(vault_path)
        self._qdrant = qdrant_client
        self._model_path = model_path
        self._vector_size = vector_size
        self._collection = f"collection_{shop_id}"
        self._file_hashes: dict[str, str] = {}
        self._observer = None

    def _get_model(self):
        return get_embedding_model(self._model_path)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入文本，返回向量列表。"""
        model = self._get_model()
        embeddings = model.encode(texts, batch_size=32, show_progress_bar=False)
        return embeddings.tolist()

    async def _ensure_collection(self) -> None:
        """确保 Qdrant Collection 存在，不存在则创建。"""
        from qdrant_client.models import Distance, VectorParams

        try:
            await self._qdrant.get_collection(self._collection)
        except Exception:
            await self._qdrant.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self._vector_size, distance=Distance.COSINE),
            )
            logger.info("创建 Qdrant Collection: %s", self._collection)

    async def index_file(self, md_path: Path) -> int:
        """将单个 .md 文件嵌入并 upsert 到 Qdrant。

        Args:
            md_path: .md 文件绝对路径。

        Returns:
            upsert 的 chunk 数量。
        """
        from qdrant_client.models import PointStruct

        relative = str(md_path.relative_to(self._vault))
        content = md_path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(content)
        backlinks = _extract_backlinks(body)
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]

        chunks = _split_chunks(body, relative, self._shop_id)
        if not chunks:
            return 0

        texts = [c["content"] for c in chunks]
        vectors = self._embed(texts)

        points = []
        for chunk, vec in zip(chunks, vectors):
            point_id = int(hashlib.md5(chunk["chunk_id"].encode()).hexdigest()[:8], 16)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vec,
                    payload={
                        "chunk_id": chunk["chunk_id"],
                        "content": chunk["content"],
                        "source_file": chunk["source_file"],
                        "shop_id": self._shop_id,
                        "tags": tags,
                        "backlinks": backlinks,
                        # category 字段通过 ObsidianVault 的父目录推断（空则不写入）
                        **({"category": self._infer_category_from_path(relative)} if self._infer_category_from_path(relative) else {}),
                    },
                )
            )

        await self._qdrant.upsert(collection_name=self._collection, points=points)
        self._file_hashes[relative] = _file_hash(md_path)
        logger.debug("索引文件 %s: %d chunks", relative, len(chunks))
        return len(chunks)

    def _infer_category_from_path(self, relative_path: str) -> str:
        """从文件相对路径推断分类标签。

        取第一层目录作为分类参考，不再使用预设关键词。
        """
        parts = Path(relative_path).parts
        if len(parts) >= 2:
            # 直接使用第一层目录名作为分类标签
            return parts[0]
        return ""

    async def remove_file(self, relative_path: str) -> None:
        """从 Qdrant 删除指定文件的所有向量点。"""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        await self._qdrant.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[FieldCondition(key="source_file", match=MatchValue(value=relative_path))]
            ),
        )
        self._file_hashes.pop(relative_path, None)
        logger.info("已从索引删除文件: %s", relative_path)

    async def full_sync(self) -> None:
        """全量同步：扫描 vault 所有 .md 文件，变更才重新嵌入。"""
        await self._ensure_collection()
        total = 0
        for md_file in self._vault.rglob("*.md"):
            relative = str(md_file.relative_to(self._vault))
            current_hash = _file_hash(md_file)
            if self._file_hashes.get(relative) == current_hash:
                continue  # 内容未变，跳过
            n = await self.index_file(md_file)
            total += n
        logger.info("全量同步完成 shop=%s: %d chunks", self._shop_id, total)

    def start_watch(self) -> None:
        """启动 watchdog 文件监听，实现增量更新。"""
        import asyncio

        from watchdog.events import (
            FileSystemEventHandler,
        )
        from watchdog.observers import Observer

        indexer = self

        class _Handler(FileSystemEventHandler):
            def __init__(self):
                self._loop = None

            def _get_loop(self):
                if self._loop is None or self._loop.is_closed():
                    try:
                        self._loop = asyncio.get_event_loop()
                    except RuntimeError:
                        self._loop = asyncio.new_event_loop()
                return self._loop

            def on_modified(self, event):
                if not event.is_directory and event.src_path.endswith(".md"):
                    path = Path(event.src_path)
                    logger.info("检测到文件变更: %s", path)
                    loop = self._get_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(indexer.index_file(path), loop)

            def on_created(self, event):
                self.on_modified(event)

            def on_deleted(self, event):
                if not event.is_directory and event.src_path.endswith(".md"):
                    path = Path(event.src_path)
                    relative = str(path.relative_to(indexer._vault))
                    logger.info("检测到文件删除: %s", relative)
                    loop = self._get_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(indexer.remove_file(relative), loop)

        self._observer = Observer()
        self._observer.schedule(_Handler(), str(self._vault), recursive=True)
        self._observer.start()
        logger.info("watchdog 已启动监听: %s", self._vault)

    def stop_watch(self) -> None:
        """停止 watchdog 文件监听。"""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("watchdog 已停止")
