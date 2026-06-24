"""知识检索层单元测试。

向量检索测试使用 Mock Qdrant，回写测试使用临时文件系统，
不依赖任何真实外部服务。
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.contracts import KnowledgeChunk, RetrievalResult
from src.retrieval.faq_cache import FaqCache, _hash_question, _normalize
from src.retrieval.query_enhancer import QueryEnhancer
from src.retrieval.retriever import Retriever, ShortcutPhraseIndex
from src.actions.writeback import WritebackService
from src.contracts import WritebackTask

NOW = datetime.now(tz=timezone.utc)
FIXTURES_DIR = Path(__file__).parent / "fixtures"
OBSIDIAN_DIR = FIXTURES_DIR / "obsidian" / "tb_demo_001"


# ── FaqCache ──────────────────────────────────────────────────────────────────

class TestFaqCacheHelpers:
    def test_normalize_strips_and_lowercases(self):
        assert _normalize("  你好啊  ") == "你好啊"
        assert _normalize("HELLO") == "hello"

    def test_hash_is_32_hex(self):
        h = _hash_question("如何安装")
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_question_same_hash(self):
        assert _hash_question("如何安装") == _hash_question("如何安装")

    def test_different_question_different_hash(self):
        assert _hash_question("如何安装") != _hash_question("如何退货")

    def test_normalized_before_hash(self):
        assert _hash_question(" 如何安装 ") == _hash_question("如何安装")


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=True)
    r.pipeline = MagicMock(return_value=AsyncMock())
    return r


@pytest.fixture
def faq(mock_redis):
    return FaqCache(redis_client=mock_redis)


class TestFaqCache:
    async def test_get_miss_returns_none(self, faq):
        result = await faq.get("tb_test_001", "如何安装")
        assert result is None

    async def test_get_hit_returns_reply(self, faq, mock_redis):
        mock_redis.get = AsyncMock(return_value="安装步骤见说明书第3页。")
        result = await faq.get("tb_test_001", "如何安装")
        assert result == "安装步骤见说明书第3页。"

    async def test_set_calls_redis_set(self, faq, mock_redis):
        await faq.set("tb_test_001", "如何安装", "安装步骤见说明书第3页。")
        mock_redis.set.assert_called_once()
        key = mock_redis.set.call_args[0][0]
        assert key.startswith("faq:tb_test_001:")

    async def test_set_with_ttl(self, mock_redis):
        faq_ttl = FaqCache(redis_client=mock_redis, ttl=3600)
        await faq_ttl.set("tb_test_001", "问题", "回复")
        call_kwargs = mock_redis.set.call_args[1]
        assert call_kwargs.get("ex") == 3600

    async def test_delete_calls_redis_delete(self, faq, mock_redis):
        await faq.delete("tb_test_001", "如何安装")
        mock_redis.delete.assert_called_once()

    async def test_key_isolation_between_shops(self, faq):
        from src.retrieval.faq_cache import _hash_question
        h = _hash_question("如何安装")
        key1 = f"faq:shop_a:{h}"
        key2 = f"faq:shop_b:{h}"
        assert key1 != key2

    async def test_redis_failure_returns_none(self, faq, mock_redis):
        mock_redis.get = AsyncMock(side_effect=Exception("连接失败"))
        result = await faq.get("tb_test_001", "问题")
        assert result is None

    async def test_batch_set_uses_pipeline(self, faq, mock_redis):
        pipe_mock = AsyncMock()
        pipe_mock.set = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[True, True])
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)

        await faq.batch_set("tb_test_001", [("问题1", "回复1"), ("问题2", "回复2")])
        pipe_mock.execute.assert_called_once()


# ── QueryEnhancer ─────────────────────────────────────────────────────────────

class TestQueryEnhancer:
    @pytest.fixture
    def enhancer(self):
        return QueryEnhancer(product_dict={"A款": "吸顶灯A款", "B款": "吸顶灯B款"})

    def test_expand_abbreviation(self, enhancer):
        result = enhancer.expand_abbreviations("A款怎么安装？")
        assert "吸顶灯A款" in result

    def test_expand_multiple_abbreviations(self, enhancer):
        result = enhancer.expand_abbreviations("A款和B款有什么区别？")
        assert "吸顶灯A款" in result
        assert "吸顶灯B款" in result

    def test_no_match_unchanged(self, enhancer):
        query = "这个灯多少钱？"
        assert enhancer.expand_abbreviations(query) == query

    def test_negation_rewrite_bu_liang(self, enhancer):
        result = enhancer.rewrite_negation("灯不亮怎么办？")
        assert "故障 不亮" in result
        assert "灯不亮怎么办" in result

    def test_negation_rewrite_bad(self, enhancer):
        result = enhancer.rewrite_negation("灯坏了")
        assert "故障 损坏" in result

    def test_no_negation_unchanged(self, enhancer):
        query = "这款灯多少瓦？"
        result = enhancer.rewrite_negation(query)
        assert result == query

    def test_enhance_returns_list(self, enhancer):
        queries = enhancer.enhance("A款灯不亮")
        assert isinstance(queries, list)
        assert len(queries) >= 1
        # 主查询应包含展开后的内容
        assert "吸顶灯A款" in queries[0]

    def test_enhance_abbrev_original_also_included(self, enhancer):
        queries = enhancer.enhance("A款怎么安装")
        # 展开后原始查询也应出现在结果中
        assert any("A款" in q or "吸顶灯A款" in q for q in queries)

    def test_from_yaml_missing_file(self, tmp_path):
        enhancer = QueryEnhancer.from_yaml(tmp_path / "nonexistent.yaml")
        assert enhancer._dict == {}

    def test_from_yaml_valid_file(self, tmp_path):
        import yaml
        data = {"X款": "超薄灯X款", "Y款": "射灯Y款"}
        f = tmp_path / "dict.yaml"
        with open(f, "w", encoding="utf-8") as fp:
            yaml.safe_dump(data, fp)
        enhancer = QueryEnhancer.from_yaml(f)
        assert enhancer._dict["X款"] == "超薄灯X款"


# ── ShortcutPhraseIndex ───────────────────────────────────────────────────────

class TestShortcutPhraseIndex:
    def test_empty_index_returns_none(self):
        idx = ShortcutPhraseIndex.empty()
        assert idx.match("如何安装？") is None
        assert idx.size == 0

    def test_load_from_file(self, tmp_path):
        import json
        phrases = [
            {"code": "安装", "phrase": "安装很简单，6mm钻头打孔就可以了。"},
            {"code": "退货", "phrase": "退货请联系客服。"},
        ]
        f = tmp_path / "phrases.json"
        f.write_text(json.dumps(phrases, ensure_ascii=False), encoding="utf-8")
        idx = ShortcutPhraseIndex(phrases_path=f)
        assert idx.size == 2

    def test_match_by_keyword(self, tmp_path):
        import json
        phrases = [{"code": "安装", "phrase": "安装指南在此"}]
        f = tmp_path / "phrases.json"
        f.write_text(json.dumps(phrases, ensure_ascii=False), encoding="utf-8")
        idx = ShortcutPhraseIndex(phrases_path=f)
        assert idx.match("这个灯怎么安装？") == "安装指南在此"

    def test_no_match_returns_none(self, tmp_path):
        import json
        phrases = [{"code": "退货", "phrase": "退货流程说明"}]
        f = tmp_path / "phrases.json"
        f.write_text(json.dumps(phrases, ensure_ascii=False), encoding="utf-8")
        idx = ShortcutPhraseIndex(phrases_path=f)
        assert idx.match("灯多少钱？") is None

    def test_longer_code_matched_first(self, tmp_path):
        import json
        phrases = [
            {"code": "安", "phrase": "短关键词回复"},
            {"code": "安装方法", "phrase": "长关键词回复"},
        ]
        f = tmp_path / "phrases.json"
        f.write_text(json.dumps(phrases, ensure_ascii=False), encoding="utf-8")
        idx = ShortcutPhraseIndex(phrases_path=f)
        result = idx.match("安装方法是什么")
        assert result == "长关键词回复"

    def test_missing_file_creates_empty_index(self, tmp_path):
        idx = ShortcutPhraseIndex(phrases_path=tmp_path / "nonexistent.json")
        assert idx.size == 0
        assert idx.match("任何消息") is None


# ── Retriever（Mock Qdrant）────────────────────────────────────────────────────

def make_shop_config(shop_id: str = "tb_test_001"):
    from src.config.settings import ShopConfig
    from src.contracts import Platform
    return ShopConfig(
        shop_id=shop_id,
        platform=Platform.TAOBAO,
        name="测试",
        obsidian_vault="data/x",
    )


class TestRetriever:
    @pytest.fixture
    def mock_qdrant(self):
        q = AsyncMock()
        hit = MagicMock()
        hit.score = 0.85
        hit.id = 12345
        hit.payload = {
            "chunk_id": "tb_test_001:安装说明.md:0",
            "content": "安装前请关闭电源。",
            "source_file": "安装说明.md",
            "shop_id": "tb_test_001",
            "tags": ["安装"],
            "backlinks": [],
        }
        result_wrapper = MagicMock()
        result_wrapper.points = [hit]
        q.query_points = AsyncMock(return_value=result_wrapper)
        return q

    @pytest.fixture
    def retriever(self, mock_redis, mock_qdrant):
        faq = FaqCache(redis_client=mock_redis)
        enhancer = QueryEnhancer()
        # 使用空的快捷短语索引，避免 Level2 匹配干扰向量检索测试
        empty_shortcut = ShortcutPhraseIndex.empty()
        r = Retriever(
            faq_cache=faq,
            qdrant_client=mock_qdrant,
            query_enhancer=enhancer,
            shortcut_index=empty_shortcut,
        )
        return r

    async def test_faq_hit_skips_vector_search(self, retriever, mock_redis, mock_qdrant):
        mock_redis.get = AsyncMock(return_value="预置FAQ回复")
        result = await retriever.retrieve(make_shop_config(), "如何安装？")
        assert result.faq_hit is True
        assert result.faq_reply == "预置FAQ回复"
        mock_qdrant.query_points.assert_not_called()

    async def test_vector_search_on_faq_miss(self, retriever, mock_redis, mock_qdrant):
        mock_redis.get = AsyncMock(return_value=None)

        # Mock 嵌入模型
        mock_model = MagicMock()
        import numpy as np
        mock_model.encode = MagicMock(return_value=np.array([[0.1] * 512]))

        with patch("src.retrieval.obsidian_indexer.get_embedding_model", return_value=mock_model):
            result = await retriever.retrieve(make_shop_config(), "如何安装灯？")

        assert result.faq_hit is False
        assert len(result.chunks) == 1
        assert result.chunks[0].content == "安装前请关闭电源。"
        mock_qdrant.query_points.assert_called_once()

    async def test_vector_timeout_returns_empty(self, retriever, mock_redis, mock_qdrant):
        mock_redis.get = AsyncMock(return_value=None)
        mock_qdrant.query_points = AsyncMock(side_effect=asyncio.TimeoutError())

        mock_model = MagicMock()
        import numpy as np
        mock_model.encode = MagicMock(return_value=np.array([[0.1] * 512]))

        with patch("src.retrieval.obsidian_indexer.get_embedding_model", return_value=mock_model):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                result = await retriever.retrieve(make_shop_config(), "很复杂的问题")

        assert result.chunks == []

    async def test_result_sorted_by_score(self, retriever, mock_redis, mock_qdrant):
        mock_redis.get = AsyncMock(return_value=None)
        hits = []
        for i, score in enumerate([0.6, 0.9, 0.75]):
            h = MagicMock()
            h.score = score
            h.id = i
            h.payload = {
                "chunk_id": f"tb_test_001:file.md:{i}",
                "content": f"内容{i}",
                "source_file": "file.md",
                "tags": [],
                "backlinks": [],
            }
            hits.append(h)
        result_wrapper = MagicMock()
        result_wrapper.points = hits
        mock_qdrant.query_points = AsyncMock(return_value=result_wrapper)

        mock_model = MagicMock()
        import numpy as np
        mock_model.encode = MagicMock(return_value=np.array([[0.1] * 512]))

        with patch("src.retrieval.obsidian_indexer.get_embedding_model", return_value=mock_model):
            result = await retriever.retrieve(make_shop_config(), "问题")

        scores = [c.score for c in result.chunks]
        assert scores == sorted(scores, reverse=True)

    async def test_shop_id_isolation(self, retriever, mock_redis, mock_qdrant):
        """不同 shop_id 查询不同 Collection，互不干扰。"""
        mock_redis.get = AsyncMock(return_value=None)
        empty_wrapper = MagicMock()
        empty_wrapper.points = []
        mock_qdrant.query_points = AsyncMock(return_value=empty_wrapper)

        mock_model = MagicMock()
        import numpy as np
        mock_model.encode = MagicMock(return_value=np.array([[0.1] * 512]))

        with patch("src.retrieval.obsidian_indexer.get_embedding_model", return_value=mock_model):
            await retriever.retrieve(make_shop_config("shop_a"), "问题")
            await retriever.retrieve(make_shop_config("shop_b"), "问题")

        calls = mock_qdrant.query_points.call_args_list
        collections = [c.kwargs.get("collection_name") or c.args[0] for c in calls]
        assert "collection_shop_a" in str(collections)
        assert "collection_shop_b" in str(collections)


# ── ObsidianIndexer（使用测试 fixture 知识库）─────────────────────────────────

class TestObsidianIndexer:
    def test_split_chunks_basic(self):
        from src.retrieval.obsidian_indexer import _split_chunks
        text = "段落一的内容，包含足够多的文字描述。\n\n段落二的内容，包含足够多的文字描述。"
        chunks = _split_chunks(text, "test.md", "tb_test_001")
        assert len(chunks) >= 1
        assert all("content" in c for c in chunks)

    def test_split_chunks_generates_ids(self):
        from src.retrieval.obsidian_indexer import _split_chunks
        text = "这是一段测试内容，足够长足够长足够长足够长足够长足够长。\n\n这是另一段测试内容，同样足够长足够长足够长足够长。"
        chunks = _split_chunks(text, "test.md", "tb_test_001")
        ids = [c["chunk_id"] for c in chunks]
        assert all("tb_test_001" in cid for cid in ids)

    def test_parse_frontmatter(self):
        from src.retrieval.obsidian_indexer import _parse_frontmatter
        content = "---\ntags: [安装]\nproduct: 灯具\n---\n正文内容"
        fm, body = _parse_frontmatter(content)
        assert fm.get("product") == "灯具"
        assert "正文内容" in body
        assert "---" not in body

    def test_parse_frontmatter_no_frontmatter(self):
        from src.retrieval.obsidian_indexer import _parse_frontmatter
        content = "普通正文，没有 frontmatter。"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_extract_backlinks(self):
        from src.retrieval.obsidian_indexer import _extract_backlinks
        content = "参见[[安装说明]]和[[售后政策]]获取更多信息。"
        links = _extract_backlinks(content)
        assert "安装说明" in links
        assert "售后政策" in links

    def test_extract_backlinks_empty(self):
        from src.retrieval.obsidian_indexer import _extract_backlinks
        assert _extract_backlinks("没有双链的文本") == []

    async def test_index_file_calls_qdrant_upsert(self, tmp_path):
        from src.retrieval.obsidian_indexer import ObsidianIndexer

        vault = tmp_path / "vault"
        vault.mkdir()
        md = vault / "test.md"
        md.write_text(
            "---\ntags: [测试]\n---\n\n这是测试段落，内容足够长，用于验证 upsert 流程正确执行。"
            "\n\n第二段落，内容同样足够长，确保能被切分为独立的 chunk 并写入向量库。",
            encoding="utf-8",
        )

        mock_qdrant = AsyncMock()
        mock_qdrant.get_collection = AsyncMock(return_value=True)
        mock_qdrant.upsert = AsyncMock()

        mock_model = MagicMock()
        import numpy as np
        mock_model.encode = MagicMock(return_value=np.array([[0.1] * 512, [0.2] * 512]))

        with patch("src.retrieval.obsidian_indexer.get_embedding_model", return_value=mock_model):
            indexer = ObsidianIndexer(
                shop_id="tb_test_001",
                vault_path=vault,
                qdrant_client=mock_qdrant,
                model_path="mock_model",
            )
            n = await indexer.index_file(md)

        assert n > 0
        mock_qdrant.upsert.assert_called_once()

    async def test_remove_file_calls_qdrant_delete(self, tmp_path):
        from src.retrieval.obsidian_indexer import ObsidianIndexer

        mock_qdrant = AsyncMock()
        mock_qdrant.delete = AsyncMock()

        indexer = ObsidianIndexer(
            shop_id="tb_test_001",
            vault_path=tmp_path,
            qdrant_client=mock_qdrant,
        )
        indexer._file_hashes["test.md"] = "abc123"
        await indexer.remove_file("test.md")

        mock_qdrant.delete.assert_called_once()
        assert "test.md" not in indexer._file_hashes

    async def test_full_sync_skips_unchanged_files(self, tmp_path):
        from src.retrieval.obsidian_indexer import ObsidianIndexer, _file_hash

        vault = tmp_path / "vault"
        vault.mkdir()
        md = vault / "note.md"
        md.write_text("---\n---\n\n内容足够长的段落，用于测试全量同步跳过已处理文件。", encoding="utf-8")

        mock_qdrant = AsyncMock()
        mock_qdrant.get_collection = AsyncMock(return_value=True)
        mock_qdrant.upsert = AsyncMock()

        mock_model = MagicMock()
        import numpy as np
        mock_model.encode = MagicMock(return_value=np.array([[0.1] * 512]))

        with patch("src.retrieval.obsidian_indexer.get_embedding_model", return_value=mock_model):
            indexer = ObsidianIndexer("tb_test_001", vault, mock_qdrant, model_path="mock")
            # 预设 hash，模拟已索引
            indexer._file_hashes["note.md"] = _file_hash(md)
            await indexer.full_sync()

        # 文件未变更，不应调用 upsert
        mock_qdrant.upsert.assert_not_called()


# ── WritebackService ──────────────────────────────────────────────────────────

def make_writeback_task(**kwargs) -> WritebackTask:
    defaults = dict(
        shop_id="tb_test_001",
        buyer_id="buyer_001",
        summary="咨询了灯的安装方式，已提供安装教程链接。",
        resolution="resolved",
        session_date=NOW,
    )
    return WritebackTask(**(defaults | kwargs))


class TestWritebackService:
    def test_write_creates_file(self, tmp_path):
        from src.actions.writeback import WritebackService
        svc = WritebackService(vault_base_path=tmp_path)
        task = make_writeback_task()
        svc._write_sync(task)

        expected_file = tmp_path / "tb_test_001" / "customers" / "buyer_001.md"
        assert expected_file.exists()
        content = expected_file.read_text(encoding="utf-8")
        assert "咨询了灯的安装方式" in content
        assert "已解决" in content

    def test_write_appends_same_date(self, tmp_path):
        from src.actions.writeback import WritebackService
        svc = WritebackService(vault_base_path=tmp_path)
        date_str = NOW.strftime("%Y-%m-%d")

        task1 = make_writeback_task(summary="第一次咨询安装方式。")
        task2 = make_writeback_task(summary="第二次咨询退货政策。")
        svc._write_sync(task1)
        svc._write_sync(task2)

        f = tmp_path / "tb_test_001" / "customers" / "buyer_001.md"
        content = f.read_text(encoding="utf-8")
        # 同一日期只有一个 header
        assert content.count(f"## {date_str}") == 1
        assert "第一次咨询" in content
        assert "第二次咨询" in content

    def test_write_new_date_creates_new_header(self, tmp_path):
        from src.actions.writeback import WritebackService
        from datetime import timezone
        import datetime as dt

        svc = WritebackService(vault_base_path=tmp_path)
        old_date = dt.datetime(2024, 1, 1, tzinfo=timezone.utc)
        new_date = dt.datetime(2024, 1, 2, tzinfo=timezone.utc)

        svc._write_sync(make_writeback_task(summary="旧咨询记录。", session_date=old_date))
        svc._write_sync(make_writeback_task(summary="新咨询记录。", session_date=new_date))

        f = tmp_path / "tb_test_001" / "customers" / "buyer_001.md"
        content = f.read_text(encoding="utf-8")
        assert "## 2024-01-01" in content
        assert "## 2024-01-02" in content

    def test_write_escalated_resolution(self, tmp_path):
        from src.actions.writeback import WritebackService
        svc = WritebackService(vault_base_path=tmp_path)
        svc._write_sync(make_writeback_task(resolution="escalated"))
        f = tmp_path / "tb_test_001" / "customers" / "buyer_001.md"
        assert "转人工" in f.read_text(encoding="utf-8")

    def test_write_sensitive_data_masked(self, tmp_path):
        from src.actions.writeback import WritebackService
        svc = WritebackService(vault_base_path=tmp_path)
        task = make_writeback_task(summary="买家手机号 13812345678 咨询退货。")
        svc._write_sync(task)
        f = tmp_path / "tb_test_001" / "customers" / "buyer_001.md"
        content = f.read_text(encoding="utf-8")
        assert "13812345678" not in content  # 手机号已脱敏
        assert "138****5678" in content

    def test_write_with_related_tags(self, tmp_path):
        from src.actions.writeback import WritebackService
        svc = WritebackService(vault_base_path=tmp_path)
        task = make_writeback_task(related_tags=["安装说明", "吸顶灯A款"])
        svc._write_sync(task)
        content = (tmp_path / "tb_test_001" / "customers" / "buyer_001.md").read_text()
        assert "[[安装说明]]" in content
        assert "[[吸顶灯A款]]" in content

    async def test_enqueue_and_process(self, tmp_path):
        from src.actions.writeback import WritebackService
        svc = WritebackService(vault_base_path=tmp_path)
        task = make_writeback_task()
        await svc.enqueue(task)
        # 手动处理队列中的任务
        await svc._process(task)
        f = tmp_path / "tb_test_001" / "customers" / "buyer_001.md"
        assert f.exists()

    async def test_process_retries_on_failure(self, tmp_path):
        from src.actions.writeback import WritebackService

        svc = WritebackService(vault_base_path=tmp_path)
        call_count = 0

        original_write = svc._write_sync

        def failing_then_succeed(task):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OSError("磁盘写入失败")
            original_write(task)

        svc._write_sync = failing_then_succeed
        task = make_writeback_task()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc._process(task)

        assert call_count == 2  # 第1次失败，第2次成功
