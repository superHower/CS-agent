"""云端 LLM 后端（OpenAI 兼容接口）。

支持 GPT-4o-mini、通义千问、豆包等兼容 OpenAI Chat Completions API 的模型。
通过 base_url + api_key 配置，无其他三方依赖。
"""

import logging
import time

import aiohttp

from src.contracts import LLMRequest, LLMResponse
from src.exceptions import LLMResponseParseError, LLMTimeoutException

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 30
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 512


class CloudLLMBackend:
    """OpenAI 兼容云端 LLM 后端。

    Args:
        api_key: API 密钥。
        base_url: API 基础 URL，默认 OpenAI，可替换为通义千问/豆包等。
        model: 默认模型名称。
        timeout_s: 请求超时秒数。
        temperature: 采样温度。
        max_tokens: 最大输出 token 数。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout_s: int = _DEFAULT_TIMEOUT_S,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def call(self, request: LLMRequest) -> LLMResponse:
        """向云端 LLM 发起请求并返回标准化响应。

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
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        start_ms = int(time.time() * 1000)
        logger.info("LLM HTTP 请求开始 model=%s url=%s/chat/completions", model, self._base_url)

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error("LLM API 返回错误 %d: %s", resp.status, body[:200])
                        raise LLMResponseParseError(f"HTTP {resp.status}: {body[:100]}")
                    data = await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise LLMTimeoutException(f"LLM 请求超时: {exc}") from exc
        except (LLMTimeoutException, LLMResponseParseError):
            raise
        except Exception as exc:
            logger.error("LLM 请求异常: %s", exc)
            raise LLMResponseParseError(f"请求异常: {exc}") from exc

        elapsed = int(time.time() * 1000) - start_ms

        try:
            choice = data["choices"][0]
            raw_text = choice["message"]["content"]
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
        except (KeyError, IndexError) as exc:
            raise LLMResponseParseError(f"响应结构解析失败: {exc}") from exc

        reply, confidence = parse_confidence(raw_text)
        logger.info(
            "LLM 响应解析完成 model=%s 耗时=%dms tokens=%d+%d confidence=%d raw_preview=%s",
            model, elapsed, input_tokens, output_tokens, confidence, raw_text[:80].replace("\n", " "),
        )

        return LLMResponse(
            raw_text=raw_text,
            reply=reply,
            confidence=confidence,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed_ms=elapsed,
            model_used=model,
        )
