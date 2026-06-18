"""本地 LLM 后端（Qwen2 via Ollama HTTP API）。

通过 Ollama 本地服务调用 Qwen2-7B/14B，接口为 /api/chat（Ollama 格式）。
不依赖任何 transformers 库直调，保持单进程异步。
"""

import logging
import time

import aiohttp

from src.contracts import LLMRequest, LLMResponse
from src.exceptions import LLMResponseParseError, LLMTimeoutException

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 60  # 本地模型推理较慢，超时适当放宽
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 512


class LocalLLMBackend:
    """Ollama 本地 LLM 后端（Qwen2 等）。

    Args:
        base_url: Ollama 服务地址，默认 http://localhost:11434。
        model: 模型名称，如 "qwen2:7b"。
        timeout_s: 请求超时秒数。
        temperature: 采样温度。
        max_tokens: 最大输出 token 数。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2:7b",
        timeout_s: int = _DEFAULT_TIMEOUT_S,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def call(self, request: LLMRequest) -> LLMResponse:
        """向本地 Ollama 服务发起请求。

        Args:
            request: LLMRequest 契约对象。

        Returns:
            LLMResponse 契约对象。

        Raises:
            LLMTimeoutException: 请求超时。
            LLMResponseParseError: 响应解析失败。
        """
        from src.llm.confidence import parse_confidence
        from src.llm.prompt import build_messages

        model = request.model_override or self._model
        knowledge_chunks = [request.knowledge] if request.knowledge else []
        history = [{"role": t.role, "content": t.content} for t in request.history]

        messages = build_messages(
            shop_name=request.shop_name,
            buyer_message=request.buyer_message,
            history=history,
            knowledge_chunks=knowledge_chunks,
        )

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self._temperature,
                "num_predict": self._max_tokens,
            },
        }

        start_ms = int(time.time() * 1000)

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error("本地 LLM 返回错误 %d: %s", resp.status, body[:200])
                        raise LLMResponseParseError(f"HTTP {resp.status}: {body[:100]}")
                    data = await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise LLMTimeoutException(f"本地 LLM 超时: {exc}") from exc
        except (LLMTimeoutException, LLMResponseParseError):
            raise
        except Exception as exc:
            logger.error("本地 LLM 请求异常: %s", exc)
            raise LLMResponseParseError(f"请求异常: {exc}") from exc

        elapsed = int(time.time() * 1000) - start_ms

        try:
            raw_text = data["message"]["content"]
            # Ollama 不返回 token 计数，使用估算值
            input_tokens = data.get("prompt_eval_count", 0)
            output_tokens = data.get("eval_count", 0)
        except (KeyError, TypeError) as exc:
            raise LLMResponseParseError(f"Ollama 响应解析失败: {exc}") from exc

        reply, confidence = parse_confidence(raw_text)

        return LLMResponse(
            raw_text=raw_text,
            reply=reply,
            confidence=confidence,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed_ms=elapsed,
            model_used=model,
        )
