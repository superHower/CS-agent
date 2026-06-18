"""LLM 推理层单元测试。

所有测试使用 Mock aiohttp，不依赖真实网络或本地 Ollama 服务。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.contracts import LLMRequest, LLMResponse
from src.llm.confidence import parse_confidence
from src.llm.prompt import build_messages, build_greeting_messages
from src.llm.client import LLMClient
from src.exceptions import LLMTimeoutException, LLMResponseParseError


# ── confidence.py ─────────────────────────────────────────────────────────────

class TestParseConfidence:
    def test_extracts_confidence_at_end(self):
        reply, conf = parse_confidence("这款灯安装简单，请参考说明书第3页。[CONFIDENCE: 92]")
        assert conf == 92
        assert "CONFIDENCE" not in reply
        assert "这款灯安装简单" in reply

    def test_confidence_stripped_from_reply(self):
        reply, conf = parse_confidence("回复内容。[CONFIDENCE: 80]")
        assert reply == "回复内容。"

    def test_confidence_clamped_to_100(self):
        _, conf = parse_confidence("回复。[CONFIDENCE: 150]")
        assert conf == 100

    def test_confidence_clamped_to_0(self):
        # 解析出 0 则原样返回 0（不会出现负值，因为 \d+ 只匹配非负整数）
        _, conf = parse_confidence("回复。[CONFIDENCE: 0]")
        assert conf == 0

    def test_missing_confidence_returns_0(self):
        reply, conf = parse_confidence("这是一段没有置信度标记的回复。")
        assert conf == 0
        assert "这是一段没有置信度标记的回复" in reply

    def test_case_insensitive(self):
        _, conf = parse_confidence("回复。[confidence: 75]")
        assert conf == 75

    def test_confidence_with_spaces(self):
        _, conf = parse_confidence("回复。[CONFIDENCE:  88 ]")
        assert conf == 88

    def test_empty_string_returns_0(self):
        reply, conf = parse_confidence("")
        assert conf == 0
        assert reply == ""


# ── prompt.py ─────────────────────────────────────────────────────────────────

class TestBuildMessages:
    def test_system_message_present(self):
        msgs = build_messages("测试店", "如何安装？", [], [])
        assert msgs[0]["role"] == "system"
        assert "测试店" in msgs[0]["content"]

    def test_user_message_at_end(self):
        msgs = build_messages("测试店", "如何安装？", [], [])
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "如何安装？"

    def test_knowledge_chunks_injected(self):
        chunks = ["安装步骤一", "安装步骤二"]
        msgs = build_messages("测试店", "如何安装？", [], chunks)
        system = msgs[0]["content"]
        assert "安装步骤一" in system
        assert "[片段1]" in system
        assert "[片段2]" in system

    def test_no_knowledge_shows_placeholder(self):
        msgs = build_messages("测试店", "如何安装？", [], [])
        assert "暂无相关知识库内容" in msgs[0]["content"]

    def test_history_inserted(self):
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好！有什么可以帮您？"},
        ]
        msgs = build_messages("测试店", "如何安装？", history, [])
        # system + 2 history + 1 user = 4
        assert len(msgs) == 4
        assert msgs[1]["content"] == "你好"
        assert msgs[2]["content"] == "您好！有什么可以帮您？"

    def test_greeting_messages_structure(self):
        msgs = build_greeting_messages("在吗？")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "在吗？"


# ── LLMClient ─────────────────────────────────────────────────────────────────

def make_llm_request(**kwargs) -> LLMRequest:
    defaults = dict(
        shop_id="tb_test_001",
        shop_name="测试店铺",
        buyer_message="这款灯怎么安装？",
        knowledge="安装前请关闭电源，然后按说明书操作。",
    )
    return LLMRequest(**(defaults | kwargs))


class TestLLMClient:
    @pytest.fixture
    def mock_backend(self):
        backend = AsyncMock()
        backend.call = AsyncMock(return_value=LLMResponse(
            raw_text="安装请参考说明书第3页。[CONFIDENCE: 88]",
            reply="安装请参考说明书第3页。",
            confidence=88,
            input_tokens=100,
            output_tokens=50,
            elapsed_ms=1200,
            model_used="gpt-4o-mini",
        ))
        return backend

    async def test_generate_returns_response(self, mock_backend):
        client = LLMClient(backend=mock_backend)
        resp = await client.generate(make_llm_request())
        assert resp.confidence == 88
        assert resp.reply == "安装请参考说明书第3页。"
        mock_backend.call.assert_called_once()

    async def test_generate_timeout_raises(self, mock_backend):
        import asyncio
        mock_backend.call = AsyncMock(side_effect=asyncio.TimeoutError)
        client = LLMClient(backend=mock_backend, timeout_s=1)
        with pytest.raises(LLMTimeoutException):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                await client.generate(make_llm_request())

    async def test_generate_parse_error_propagates(self, mock_backend):
        mock_backend.call = AsyncMock(side_effect=LLMResponseParseError("解析失败"))
        client = LLMClient(backend=mock_backend)
        with pytest.raises(LLMResponseParseError):
            await client.generate(make_llm_request())

    async def test_backend_called_with_request(self, mock_backend):
        client = LLMClient(backend=mock_backend)
        req = make_llm_request()
        await client.generate(req)
        call_args = mock_backend.call.call_args[0][0]
        assert call_args.shop_id == "tb_test_001"
        assert call_args.buyer_message == "这款灯怎么安装？"


# ── CloudLLMBackend ────────────────────────────────────────────────────────────

class TestCloudLLMBackend:
    @pytest.fixture
    def backend(self):
        from src.llm.cloud_backend import CloudLLMBackend
        return CloudLLMBackend(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        )

    async def test_successful_call(self, backend):
        mock_resp_data = {
            "choices": [{"message": {"content": "安装说明如下。[CONFIDENCE: 90]"}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 30},
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_resp_data)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=mock_session):
            resp = await backend.call(make_llm_request())

        assert resp.confidence == 90
        assert resp.reply == "安装说明如下。"
        assert resp.input_tokens == 200
        assert resp.model_used == "gpt-4o-mini"

    async def test_http_error_raises(self, backend):
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Unauthorized")

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMResponseParseError):
                await backend.call(make_llm_request())

    async def test_model_override_used(self, backend):
        from src.llm.cloud_backend import CloudLLMBackend

        mock_resp_data = {
            "choices": [{"message": {"content": "回复。[CONFIDENCE: 85]"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_resp_data)

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_post_cm)

        req = make_llm_request(model_override="gpt-4o")
        with patch("aiohttp.ClientSession", return_value=mock_session):
            resp = await backend.call(req)

        # 验证 post 调用中的 payload 包含覆盖模型
        call_kwargs = mock_session.post.call_args
        payload = call_kwargs[1].get("json") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        assert resp.model_used == "gpt-4o"


# ── LocalLLMBackend ────────────────────────────────────────────────────────────

class TestLocalLLMBackend:
    @pytest.fixture
    def backend(self):
        from src.llm.local_backend import LocalLLMBackend
        return LocalLLMBackend(
            base_url="http://localhost:11434",
            model="qwen2:7b",
        )

    async def test_successful_call(self, backend):
        mock_resp_data = {
            "message": {"content": "Ollama 回复内容。[CONFIDENCE: 82]"},
            "prompt_eval_count": 150,
            "eval_count": 40,
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_resp_data)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=mock_session):
            resp = await backend.call(make_llm_request())

        assert resp.confidence == 82
        assert resp.reply == "Ollama 回复内容。"
        assert resp.input_tokens == 150
        assert resp.model_used == "qwen2:7b"

    async def test_http_error_raises(self, backend):
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMResponseParseError):
                await backend.call(make_llm_request())

    async def test_malformed_response_raises(self, backend):
        mock_resp_data = {"unexpected": "structure"}

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_resp_data)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMResponseParseError):
                await backend.call(make_llm_request())
