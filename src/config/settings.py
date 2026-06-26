"""配置定义与单例加载模块。

通过 pydantic-settings 加载 config/settings.yaml（全局参数），店铺配置从
SQLite（data/admin.db）异步加载，并支持通过 Redis Pub/Sub 接收 config_updated
消息后原子化热更新单例对象。
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
    api_key: str = Field(default="", description="云端 API Key（由管理后台写入数据库）")
    base_url: str = Field(default="https://api.openai.com/v1", description="API Base URL")
    max_tokens: int = Field(default=512, description="最大输出 token 数")
    temperature: float = Field(default=0.3, description="采样温度")


class ThresholdsConfig(BaseSettings):
    """全局阈值配置。"""

    model_config = SettingsConfigDict(extra="ignore")

    default_confidence: int = Field(default=85, description="默认置信度阈值（百分比）")
    session_ttl: int = Field(default=7200, description="会话 TTL（秒）")
    message_dedup_ttl: int = Field(default=86400, description="消息去重 TTL（秒）")


class AlertConfig(BaseSettings):
    """告警推送配置（企业微信机器人）。"""

    model_config = SettingsConfigDict(extra="ignore")

    webhook_url: str = Field(default="", description="企业微信机器人 Webhook 地址（由管理后台写入数据库）")


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
    category_id: str = Field(default="default", description="所属分类 ID，共享知识层")
    platform: Platform = Field(description="所属平台")
    name: str = Field(description="店铺名称")
    api_key: str = Field(default="", description="平台 API Key（通过环境变量注入）")
    api_secret: str = Field(default="", description="平台 API Secret（通过环境变量注入）")
    obsidian_vault: str = Field(default="", description="该店铺 Obsidian 知识库路径（相对项目根目录）")
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
        if not v:
            raise ValueError("shop_id 不能为空")
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


# ── 从 SQLite 加载店铺 ────────────────────────────────────────────────────────

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "admin.db"


async def _load_shops_from_db(db_path: Path = _DB_PATH) -> list[ShopConfig]:
    """从 SQLite admin.db 读取所有已启用的店铺配置。

    若数据库不存在或读取失败，返回空列表（不崩溃）。
    """
    if not db_path.exists():
        logger.warning("SQLite 数据库不存在: %s，店铺列表为空", db_path)
        return []
    try:
        import aiosqlite

        shops: list[ShopConfig] = []
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM shops ORDER BY shop_id") as cur:
                rows = await cur.fetchall()
        for row in rows:
            d = dict(row)
            d["enabled"] = bool(d.get("enabled", 1))
            # 移除 admin 专有字段
            d.pop("created_at", None)
            d.pop("updated_at", None)
            try:
                shops.append(ShopConfig(**d))
            except Exception as exc:
                logger.warning("跳过无效店铺配置 %s: %s", d.get("shop_id"), exc)
        logger.info("从 SQLite 加载店铺数量: %d", len(shops))
        return shops
    except Exception as exc:
        logger.error("从 SQLite 加载店铺配置失败: %s", exc)
        return []


async def _load_alert_config_from_db(db_path: Path = _DB_PATH) -> AlertConfig | None:
    """从 SQLite 读取告警配置。表为空或 DB 不存在时返回 None。"""
    if not db_path.exists():
        return None
    try:
        import aiosqlite

        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT webhook_url FROM alert_config WHERE id = 1") as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return AlertConfig(webhook_url=dict(row)["webhook_url"])
    except Exception as exc:
        logger.error("从 SQLite 加载告警配置失败: %s", exc)
        return None


async def _load_llm_config_from_db(db_path: Path = _DB_PATH) -> tuple["LLMConfig | None", "EmbeddingConfig | None"]:
    """从 SQLite 读取 LLM 配置，覆盖 YAML 默认值。

    返回 (LLMConfig | None, EmbeddingConfig | None)。
    若数据库不存在或表为空，返回 (None, None)。
    """
    if not db_path.exists():
        return None, None
    try:
        import aiosqlite

        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM llm_config WHERE id = 1") as cur:
                row = await cur.fetchone()
        if row is None:
            return None, None
        d = dict(row)
        d.pop("id", None)
        d.pop("backend", None)
        d.pop("updated_at", None)
        # 取出 embedding_model，不传给 LLMConfig
        embedding_model = d.pop("embedding_model", None)
        embedding_cfg = EmbeddingConfig(model_path=embedding_model, model_name=embedding_model) if embedding_model else None
        # base_url 为空字符串时用默认值
        if not d.get("base_url"):
            d["base_url"] = "https://api.openai.com/v1"
        logger.info("从 SQLite 加载 LLM 配置 model=%s", d.get("model"))
        return LLMConfig(**d), embedding_cfg
    except Exception as exc:
        logger.error("从 SQLite 加载 LLM 配置失败: %s", exc)
        return None, None


# ── 全局单例 ──────────────────────────────────────────────────────────────────

_config: Config | None = None
_config_lock = asyncio.Lock()


def get_config() -> Config:
    """获取全局配置单例，首次调用时从 YAML 加载（不含店铺，店铺需异步初始化）。

    Returns:
        当前有效的 Config 对象。

    Note:
        店铺配置从 SQLite 异步加载，启动时应调用 init_config() 代替此函数。
        此函数保留用于测试与无需店铺配置的场景。
    """
    global _config
    if _config is None:
        _config = Config.from_yaml()
        logger.info("配置已加载（无店铺），调用 init_config() 以加载店铺")
    return _config


async def init_config(path: Path = _CONFIG_PATH, db_path: Path = _DB_PATH) -> Config:
    """初始化全局配置单例：YAML 加载全局参数 + SQLite 加载店铺与 LLM 配置。

    Args:
        path: YAML 配置文件路径。
        db_path: SQLite 数据库路径。

    Returns:
        初始化后的 Config 对象。
    """
    global _config
    async with _config_lock:
        base = Config.from_yaml(path)
        shops = await _load_shops_from_db(db_path)
        llm_cfg, embedding_cfg = await _load_llm_config_from_db(db_path)
        alert_cfg = await _load_alert_config_from_db(db_path)
        updates: dict[str, Any] = {"shops": shops}
        if llm_cfg is not None:
            updates["llm"] = llm_cfg
        if embedding_cfg is not None:
            updates["embedding"] = embedding_cfg
        if alert_cfg is not None:
            updates["alert"] = alert_cfg
        _config = base.model_copy(update=updates)
        logger.info("配置初始化完成，店铺数量: %d，LLM model=%s", len(shops), _config.llm.model)
    return _config


async def reload_config(path: Path = _CONFIG_PATH, db_path: Path = _DB_PATH) -> Config:
    """原子化重新加载配置并更新单例（YAML 全局参数 + SQLite 店铺/LLM/告警）。

    由 Redis Pub/Sub 监听器在收到 config_updated 消息后调用。

    Args:
        path: YAML 配置文件路径。
        db_path: SQLite 数据库路径。

    Returns:
        新的 Config 对象。
    """
    global _config
    async with _config_lock:
        base = Config.from_yaml(path)
        shops = await _load_shops_from_db(db_path)
        llm_cfg, embedding_cfg = await _load_llm_config_from_db(db_path)
        alert_cfg = await _load_alert_config_from_db(db_path)
        updates: dict[str, Any] = {"shops": shops}
        if llm_cfg is not None:
            updates["llm"] = llm_cfg
        if embedding_cfg is not None:
            updates["embedding"] = embedding_cfg
        if alert_cfg is not None:
            updates["alert"] = alert_cfg
        new_config = base.model_copy(update=updates)
        _config = new_config
        logger.info(
            "配置热更新完成，店铺数量: %d，LLM model=%s",
            len(new_config.shops),
            new_config.llm.model,
        )
    return _config
