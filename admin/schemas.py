"""管理后台请求/响应 Pydantic 模型。"""

from pydantic import BaseModel, ConfigDict, Field


class ShopCreate(BaseModel):
    """创建店铺请求体。"""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(description="店铺唯一标识，如 tb_lamp_001")
    platform: str = Field(description="平台：taobao / pinduoduo / jd / douyin")
    name: str = Field(description="店铺名称")
    api_key: str = Field(default="", description="平台 API Key")
    api_secret: str = Field(default="", description="平台 API Secret")
    obsidian_vault: str = Field(default="", description="Obsidian Vault 相对路径")
    confidence_threshold: int = Field(default=85, ge=0, le=100, description="置信度阈值")
    enabled: bool = Field(default=True, description="是否启用")


class ShopUpdate(BaseModel):
    """更新店铺请求体（所有字段可选）。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    obsidian_vault: str | None = None
    confidence_threshold: int | None = Field(default=None, ge=0, le=100)
    enabled: bool | None = None


class ShopOut(BaseModel):
    """店铺响应体。"""

    shop_id: str
    platform: str
    name: str
    api_key: str
    api_secret: str
    obsidian_vault: str
    confidence_threshold: int
    enabled: bool
    created_at: str
    updated_at: str


class AlertConfigUpdate(BaseModel):
    """更新告警配置请求体。"""

    model_config = ConfigDict(extra="forbid")

    webhook_url: str | None = Field(default=None, description="企业微信机器人 Webhook 地址")


class AlertConfigOut(BaseModel):
    """告警配置响应体。"""

    webhook_url: str
    updated_at: str


class LLMConfigUpdate(BaseModel):
    """更新 LLM 配置请求体（所有字段可选）。"""

    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, description="模型名称，如 gpt-4o-mini / qwen-turbo")
    api_key: str | None = Field(default=None, description="云端模型 API Key")
    base_url: str | None = Field(default=None, description="API Base URL")
    max_tokens: int | None = Field(default=None, ge=1, le=32768, description="最大输出 token 数")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="采样温度")
    timeout: float | None = Field(default=None, gt=0, description="超时秒数")


class LLMConfigOut(BaseModel):
    """LLM 配置响应体。"""

    model: str
    api_key: str
    base_url: str
    max_tokens: int
    temperature: float
    timeout: float
    updated_at: str


class DashboardStats(BaseModel):
    """仪表盘统计响应体。"""

    shop_id: str
    stat_date: str
    total_sessions: int
    faq_hits: int
    llm_calls: int
    escalations: int
    faq_hit_rate: float = Field(description="FAQ 命中率（0-1）")
