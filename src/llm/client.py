"""统一 LLM 客户端，封装后端选择与超时兜底。

根据配置选择云端或本地后端，超时时抛出 LLMTimeoutException。
调用方无需关心后端实现细节。每次调用自动从全局配置读取最新参数。
"""

import asyncio
import logging

from src.contracts import LLMRequest, LLMResponse
from src.exceptions import LLMTimeoutException

logger = logging.getLogger(__name__)

# 总体调用超时（秒），包含网络 + 推理时间
_LLM_CALL_TIMEOUT_S = 30


def _build_backend(llm_config):
    """根据 LLMConfig 构建后端实例。"""
    if llm_config.backend == "local":
        from src.llm.local_backend import LocalLLMBackend
        return LocalLLMBackend(
            base_url=llm_config.base_url or "http://localhost:11434",
            model=llm_config.model,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )
    else:
        from src.llm.cloud_backend import CloudLLMBackend
        return CloudLLMBackend(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url or "https://api.openai.com/v1",
            model=llm_config.model,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )


class LLMClient:
    """统一 LLM 客户端，每次调用自动读取最新配置。

    Args:
        backend: CloudLLMBackend 或 LocalLLMBackend 实例（初始值）。
        timeout_s: asyncio.wait_for 超时秒数（覆盖后端自身 timeout）。
    """

    def __init__(self, backend, timeout_s: int = _LLM_CALL_TIMEOUT_S) -> None:
        self._backend = backend
        self._timeout_s = timeout_s
        # 缓存上次使用的配置签名，变了就重建 backend
        self._config_sig: str = ""

    def _refresh_if_needed(self) -> None:
        """若全局 LLM 配置有变更，重建 backend 和 timeout。"""
        try:
            from src.config.settings import get_config
            cfg = get_config().llm
            sig = f"{cfg.backend}|{cfg.base_url}|{cfg.model}|{cfg.api_key}|{cfg.temperature}|{cfg.max_tokens}|{cfg.timeout}"
            if sig != self._config_sig:
                self._backend = _build_backend(cfg)
                self._timeout_s = int(cfg.timeout)
                self._config_sig = sig
                logger.debug("LLM 配置已热更新 model=%s timeout=%ds", cfg.model, self._timeout_s)
        except Exception as exc:
            logger.warning("LLM 配置热更新检查失败，继续使用旧配置: %s", exc)

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
        self._refresh_if_needed()
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
        """从 LLMConfig 对象构建 LLMClient。"""
        backend = _build_backend(llm_config)
        return cls(backend=backend, timeout_s=int(llm_config.timeout))
