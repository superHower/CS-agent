"""统一异常定义模块，所有自定义异常继承自 AppException。"""


class AppException(Exception):
    """应用基础异常，携带可选的错误码与上下文信息。"""

    def __init__(self, message: str, code: str = "UNKNOWN", context: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.context = context or {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


# ── 网关层 ────────────────────────────────────────────────────────────────────


class GatewayException(AppException):
    """平台网关通用异常（消息接收/发送失败等）。"""

    def __init__(self, message: str, platform: str = "", context: dict | None = None) -> None:
        super().__init__(message, code="GATEWAY_ERROR", context=context)
        self.platform = platform


class MessageDeduplicationError(GatewayException):
    """消息去重操作异常。"""

    def __init__(self, message_id: str, context: dict | None = None) -> None:
        super().__init__(
            f"消息去重检查失败: {message_id}",
            context=context,
        )
        self.message_id = message_id


class WebhookValidationError(GatewayException):
    """Webhook 签名或格式验证失败。"""

    def __init__(self, reason: str, context: dict | None = None) -> None:
        super().__init__(f"Webhook 验证失败: {reason}", context=context)


# ── 消息发送层 ────────────────────────────────────────────────────────────────


class SendFailedException(AppException):
    """消息发送失败（已重试仍失败）。"""

    def __init__(self, buyer_id: str, shop_id: str, context: dict | None = None) -> None:
        super().__init__(
            f"消息发送失败: shop={shop_id} buyer={buyer_id}",
            code="SEND_FAILED",
            context=context,
        )
        self.buyer_id = buyer_id
        self.shop_id = shop_id


# ── LLM 层 ───────────────────────────────────────────────────────────────────


class LLMTimeoutException(AppException):
    """LLM 推理超时。"""

    def __init__(self, timeout: float, context: dict | None = None) -> None:
        super().__init__(
            f"LLM 推理超时（>{timeout}s）",
            code="LLM_TIMEOUT",
            context=context,
        )
        self.timeout = timeout


class LLMResponseParseError(AppException):
    """LLM 响应解析失败（置信度缺失或格式异常）。"""

    def __init__(self, raw_response: str, context: dict | None = None) -> None:
        super().__init__(
            "LLM 响应解析失败",
            code="LLM_PARSE_ERROR",
            context=context,
        )
        self.raw_response = raw_response


# ── 检索层 ───────────────────────────────────────────────────────────────────


class RetrievalTimeoutException(AppException):
    """向量检索超时。"""

    def __init__(self, timeout_ms: int, context: dict | None = None) -> None:
        super().__init__(
            f"向量检索超时（>{timeout_ms}ms）",
            code="RETRIEVAL_TIMEOUT",
            context=context,
        )
        self.timeout_ms = timeout_ms


class EmbeddingModelError(AppException):
    """嵌入模型加载或推理失败。"""

    def __init__(self, message: str, context: dict | None = None) -> None:
        super().__init__(message, code="EMBEDDING_ERROR", context=context)


# ── 配置层 ───────────────────────────────────────────────────────────────────


class ConfigLoadError(AppException):
    """配置文件加载或解析失败。"""

    def __init__(self, path: str, reason: str, context: dict | None = None) -> None:
        super().__init__(
            f"配置加载失败 [{path}]: {reason}",
            code="CONFIG_ERROR",
            context=context,
        )
        self.path = path


# ── Redis 层 ─────────────────────────────────────────────────────────────────


class RedisUnavailableError(AppException):
    """Redis 不可用，系统应降级为转人工模式。"""

    def __init__(self, context: dict | None = None) -> None:
        super().__init__(
            "Redis 不可用，系统降级为转人工模式",
            code="REDIS_UNAVAILABLE",
            context=context,
        )


# ── 回写层 ───────────────────────────────────────────────────────────────────


class WritebackError(AppException):
    """Obsidian 记忆回写失败。"""

    def __init__(self, buyer_id: str, reason: str, context: dict | None = None) -> None:
        super().__init__(
            f"记忆回写失败 [buyer={buyer_id}]: {reason}",
            code="WRITEBACK_ERROR",
            context=context,
        )
        self.buyer_id = buyer_id


# ── 告警层 ───────────────────────────────────────────────────────────────────


class AlertDeliveryError(AppException):
    """人工告警推送失败。"""

    def __init__(self, shop_id: str, reason: str, context: dict | None = None) -> None:
        super().__init__(
            f"告警推送失败 [shop={shop_id}]: {reason}",
            code="ALERT_ERROR",
            context=context,
        )
        self.shop_id = shop_id
