"""统一 LLM 客户端，封装后端选择与超时兜底。

根据配置选择云端或本地后端，超时时抛出 LLMTimeoutException。
调用方无需关心后端实现细节。
"""

import asyncio
import logging

from src.contracts import LLMRequest, LLMResponse
from src.exceptions import LLMTimeoutException

logger = logging.getLogger(__name__)

# 总体调用超时（秒），包含网络 + 推理时间
_LLM_CALL_TIMEOUT_S = 30


class LLMClient:
    """统一 LLM 客户端。

    Args:
        backend: CloudLLMBackend 或 LocalLLMBackend 实例。
        timeout_s: asyncio.wait_for 超时秒数（覆盖后端自身 timeout）。
    """

    def __init__(self, backend, timeout_s: int = _LLM_CALL_TIMEOUT_S) -> None:
        self._backend = backend
        self._timeout_s = timeout_s

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """生成回复。

        Args:
            request: LLMRequest 契约对象。

        Returns:
            LLMResponse 契约对象。

        Raises:
            LLMTimeoutException: 超出 timeout_s 仍未返回。
            LLMResponseParseError: 后端响应解析失败。
        """
        try:
            response = await asyncio.wait_for(
                self._backend.call(request),
                timeout=self._timeout_s,
            )
        except TimeoutError as exc:
            logger.warning(
                "LLM 调用超时 shop=%s timeout=%ds",
                request.shop_id,
                self._timeout_s,
            )
            raise LLMTimeoutException(f"LLM 调用超时 ({self._timeout_s}s)") from exc

        logger.debug(
            "LLM 调用完成 shop=%s model=%s confidence=%d elapsed=%dms",
            request.shop_id,
            response.model_used,
            response.confidence,
            response.elapsed_ms,
        )
        return response

    @classmethod
    def from_config(cls, llm_config) -> "LLMClient":
        """从 LLMConfig 对象构建 LLMClient。

        Args:
            llm_config: src.config.settings.LLMConfig 实例。

        Returns:
            配置好的 LLMClient 实例。
        """
        import os

        if llm_config.backend == "local":
            from src.llm.local_backend import LocalLLMBackend

            backend = LocalLLMBackend(
                base_url=llm_config.base_url or "http://localhost:11434",
                model=llm_config.model,
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
            )
        else:
            from src.llm.cloud_backend import CloudLLMBackend

            backend = CloudLLMBackend(
                api_key=os.environ.get("LLM_API_KEY", ""),
                base_url=llm_config.base_url or "https://api.openai.com/v1",
                model=llm_config.model,
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
            )
        return cls(backend=backend, timeout_s=int(llm_config.timeout))
