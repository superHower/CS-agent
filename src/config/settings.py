"""配置定义与单例加载模块。

通过 pydantic-settings 加载 config/settings.yaml，并支持通过 Redis Pub/Sub
接收 config_updated 消息后原子化热更新单例对象。
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.contracts import Platform

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"

# 环境变量占位符正则，如 ${SOME_VAR}
_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _resolve_env_vars(value: Any) -> Any:
    """递归将 YAML 中的 ${ENV_VAR} 替换为实际环境变量值。"""
    if isinstance(value, str):

        def replacer(m: re.Match) -> str:
            return os.environ.get(m.group(1), "")

        return _ENV_VAR_RE.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    """加载并解析 YAML 配置文件，解析环境变量占位符。"""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return _resolve_env_vars(raw)


# ── 子配置模型 ────────────────────────────────────────────────────────────────


class RedisConfig(BaseSettings):
    """Redis 连接配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    host: str = Field(default="127.0.0.1", description="Redis 主机地址")
    port: int = Field(default=6379, description="Redis 端口")
    db: int = Field(default=0, description="Redis 数据库编号")
    password: str | None = Field(default=None, description="Redis 密码，无密码时为 null")
    socket_timeout: float = Field(default=1.0, description="Socket 超时（秒）")
    socket_connect_timeout: float = Field(default=1.0, description="连接超时（秒）")


class QdrantConfig(BaseSettings):
    """Qdrant 向量库连接配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    host: str = Field(default="127.0.0.1", description="Qdrant 主机地址")
    port: int = Field(default=6333, description="Qdrant 端口")
    timeout: float = Field(default=5.0, description="请求超时（秒）")


class EmbeddingConfig(BaseSettings):
    """嵌入模型配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    model_name: str = Field(default="bge-small-zh", description="嵌入模型名称")
    model_path: str = Field(default="models/bge-small-zh", description="本地模型路径")
    batch_size: int = Field(default=32, description="批量推理 batch size")


class LLMConfig(BaseSettings):
    """LLM 推理层配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    backend: str = Field(default="cloud", description="后端类型：cloud | local")
    timeout: float = Field(default=5.0, description="推理超时（秒），超时转人工")
    model: str = Field(default="gpt-4o-mini", description="模型名称")
    base_url: str | None = Field(default=None, description="本地模式时的 API base URL")
    max_tokens: int = Field(default=512, description="最大输出 token 数")
    temperature: float = Field(default=0.3, description="采样温度")


class ThresholdsConfig(BaseSettings):
    """全局阈值配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    default_confidence: int = Field(default=85, description="默认置信度阈值（百分比）")
    session_ttl: int = Field(default=7200, description="会话 TTL（秒）")
    message_dedup_ttl: int = Field(default=86400, description="消息去重 TTL（秒）")


class AlertConfig(BaseSettings):
    """告警推送配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    type: str = Field(default="dingtalk", description="告警类型：dingtalk | wechat_work")
    webhook_url: str | None = Field(default=None, description="Webhook 地址（通过环境变量注入）")


class LoggingConfig(BaseSettings):
    """日志配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    level: str = Field(default="INFO", description="日志级别")
    dir: str = Field(default="logs", description="日志输出目录")
    retention_days: int = Field(default=30, description="日志保留天数")


class ShopConfig(BaseSettings):
    """单个店铺配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    shop_id: str = Field(description="店铺唯一标识，格式如 tb_lamp_001")
    platform: Platform = Field(description="所属平台")
    name: str = Field(description="店铺名称")
    api_key: str = Field(default="", description="平台 API Key（通过环境变量注入）")
    api_secret: str = Field(default="", description="平台 API Secret（通过环境变量注入）")
    obsidian_vault: str = Field(description="该店铺 Obsidian 知识库路径（相对项目根目录）")
    confidence_threshold: int = Field(
        default=85,
        ge=0,
        le=100,
        description="该店铺置信度阈值，覆盖全局默认值",
    )
    enabled: bool = Field(default=True, description="是否启用该店铺")

    @field_validator("shop_id")
    @classmethod
    def validate_shop_id(cls, v: str) -> str:
        if not v or "_" not in v:
            raise ValueError(f"shop_id 格式无效: {v!r}，期望格式如 tb_lamp_001")
        return v


class Config(BaseSettings):
    """系统主配置，从 settings.yaml 加载，通过单例访问。"""

    model_config = SettingsConfigDict(extra="ignore")

    redis: RedisConfig = Field(default_factory=RedisConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    alert: AlertConfig = Field(default_factory=AlertConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    escalation_keywords: list[str] = Field(
        default_factory=lambda: ["投诉", "12315", "工商", "差评", "曝光", "赔偿", "假货"],
        description="硬转人工关键词列表",
    )
    greeting_patterns: list[str] = Field(
        default_factory=lambda: ["在吗", "你好", "您好", "亲", "hello", "hi"],
        description="模糊寒暄模式，低置信度时不转人工",
    )
    shops: list[ShopConfig] = Field(default_factory=list, description="店铺配置列表")

    @classmethod
    def from_yaml(cls, path: Path = _CONFIG_PATH) -> "Config":
        """从 YAML 文件加载配置。"""
        data = _load_yaml(path)
        # 嵌套子配置需要单独实例化
        nested = {}
        for key, model_cls in [
            ("redis", RedisConfig),
            ("qdrant", QdrantConfig),
            ("embedding", EmbeddingConfig),
            ("llm", LLMConfig),
            ("thresholds", ThresholdsConfig),
            ("alert", AlertConfig),
            ("logging", LoggingConfig),
        ]:
            if key in data:
                nested[key] = model_cls(**data.pop(key))
        if "shops" in data:
            nested["shops"] = [ShopConfig(**s) for s in data.pop("shops")]
        return cls(**nested, **data)

    def get_shop(self, shop_id: str) -> ShopConfig | None:
        """按 shop_id 查找店铺配置，不存在返回 None。"""
        for shop in self.shops:
            if shop.shop_id == shop_id:
                return shop
        return None

    def enabled_shops(self) -> list[ShopConfig]:
        """返回所有已启用的店铺配置。"""
        return [s for s in self.shops if s.enabled]


# ── 全局单例 ──────────────────────────────────────────────────────────────────

_config: Config | None = None
_config_lock = asyncio.Lock()


def get_config() -> Config:
    """获取全局配置单例，首次调用时从 YAML 加载。

    Returns:
        当前有效的 Config 对象。

    Raises:
        RuntimeError: 配置未初始化时（仅在极端情况下发生）。
    """
    global _config
    if _config is None:
        _config = Config.from_yaml()
        logger.info("配置已加载，店铺数量: %d", len(_config.shops))
    return _config


async def reload_config(path: Path = _CONFIG_PATH) -> Config:
    """原子化重新加载配置并更新单例。

    由 Redis Pub/Sub 监听器在收到 config_updated 消息后调用。

    Args:
        path: YAML 配置文件路径。

    Returns:
        新的 Config 对象。
    """
    global _config
    async with _config_lock:
        new_config = Config.from_yaml(path)
        _config = new_config
        logger.info(
            "配置热更新完成，店铺数量: %d",
            len(new_config.shops),
        )
    return _config
