"""知识检索层单元测试。

向量检索测试使用 Mock Qdrant，不依赖任何真实外部服务。
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

NOW = datetime.now(tz=timezone.utc)
FIXTURES_DIR = Path(__file__).parent / "fixtures"


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

        with patch("src.retrieval.embedding_model.get_embedding_model", return_value=mock_model):
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

        with patch("src.retrieval.embedding_model.get_embedding_model", return_value=mock_model):
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

        with patch("src.retrieval.embedding_model.get_embedding_model", return_value=mock_model):
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

        with patch("src.retrieval.embedding_model.get_embedding_model", return_value=mock_model):
            await retriever.retrieve(make_shop_config("shop_a"), "问题")
            await retriever.retrieve(make_shop_config("shop_b"), "问题")

        calls = mock_qdrant.query_points.call_args_list
        collections = [c.kwargs.get("collection_name") or c.args[0] for c in calls]
        assert "collection_shop_a" in str(collections)
        assert "collection_shop_b" in str(collections)
