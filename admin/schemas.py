"""管理后台请求/响应 Pydantic 模型。"""

from pydantic import BaseModel, ConfigDict, Field


class ShopCreate(BaseModel):
    """创建店铺请求体。"""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(description="店铺唯一标识，如 tb_lamp_001")
    category_id: str = Field(default="default", description="所属分类 ID，如 lamp_store")
    platform: str = Field(description="平台：taobao / pinduoduo / jd / douyin")
    name: str = Field(description="店铺名称")
    confidence_threshold: int = Field(default=85, ge=0, le=100, description="置信度阈值")
    enabled: bool = Field(default=True, description="是否启用")


class ShopUpdate(BaseModel):
    """更新店铺请求体（所有字段可选）。"""

    model_config = ConfigDict(extra="forbid")

    category_id: str | None = None
    name: str | None = None
    confidence_threshold: int | None = Field(default=None, ge=0, le=100)
    enabled: bool | None = None


class ShopOut(BaseModel):
    """店铺响应体。"""

    shop_id: str
    category_id: str
    platform: str
    name: str
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
    embedding_model: str | None = Field(default=None, description="文本嵌入模型名称或本地路径")


class LLMConfigOut(BaseModel):
    """LLM 配置响应体。"""

    model: str
    api_key: str
    base_url: str
    max_tokens: int
    temperature: float
    timeout: float
    embedding_model: str = Field(default="", description="嵌入模型名称或路径")
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


# ── 分类管理 ──────────────────────────────────────────────────────────────────


class CategoryCreate(BaseModel):
    """创建分类请求体。"""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=50, description="分类ID，如 lamp_store")
    name: str = Field(min_length=1, max_length=100, description="分类名称，如 灯具店")
    description: str = Field(default="", max_length=500)
    model_path: str = Field(default="models/bge-small-zh", description="该分类专属嵌入模型路径")


class CategoryUpdate(BaseModel):
    """更新分类请求体。"""
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    model_path: str | None = None


class CategoryOut(BaseModel):
    """分类响应体。"""
    id: str
    name: str
    description: str
    model_path: str
    created_at: str
    updated_at: str


# ── FAQ 管理 ──────────────────────────────────────────────────────────────────


class FaqAliasIn(BaseModel):
    """FAQ 别名（问法）输入。"""
    question: str = Field(min_length=1, max_length=200, description="问法文本")
    is_primary: bool = Field(default=False, description="是否为主问法（展示用）")


class FaqCreate(BaseModel):
    """创建 FAQ 请求体。"""
    model_config = ConfigDict(extra="forbid")

    category_id: str = Field(default="default", description="所属分类 ID，共享内容填分类ID")
    shop_id: str = Field(default="global", description="所属店铺 ID，共享内容填 global")
    answer: str = Field(min_length=1, max_length=2000, description="回复内容")
    category: str = Field(default="", max_length=50, description="分类标签，如 发货/退款/产品")
    priority: int = Field(default=0, ge=0, le=100, description="优先级，数值越大越优先")
    enabled: bool = Field(default=True, description="是否启用")
    aliases: list[FaqAliasIn] = Field(min_length=1, description="问法列表，至少一条")


class FaqUpdate(BaseModel):
    """更新 FAQ 请求体（所有字段可选）。"""
    model_config = ConfigDict(extra="forbid")

    answer: str | None = Field(default=None, min_length=1, max_length=2000)
    category: str | None = Field(default=None, max_length=50)
    priority: int | None = Field(default=None, ge=0, le=100)
    enabled: bool | None = None
    aliases: list[FaqAliasIn] | None = Field(default=None, min_length=1, description="全量替换别名列表")


class FaqAliasOut(BaseModel):
    """FAQ 别名响应体。"""
    id: int
    faq_id: int
    question: str
    is_primary: bool


class FaqOut(BaseModel):
    """FAQ 响应体。"""
    id: int
    category_id: str
    shop_id: str
    answer: str
    category: str
    priority: int
    enabled: bool
    aliases: list[FaqAliasOut]
    created_at: str
    updated_at: str


class FaqImportRow(BaseModel):
    """CSV 批量导入单行。"""
    model_config = ConfigDict(extra="ignore")

    question: str = Field(min_length=1, max_length=200)
    answer: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="")
    priority: int = Field(default=0, ge=0, le=100)
    aliases: str = Field(default="", description="用 | 分隔的额外问法")


# ── 产品管理 ──────────────────────────────────────────────────────────────────


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: str = Field(default="default", description="所属分类 ID，共享内容填分类ID")
    shop_id: str = Field(default="global", description="店铺ID，共享内容填 global")
    model: str = Field(min_length=1, max_length=100, description="产品型号，同一 category_id+shop_id 下唯一")
    attributes: str = Field(default="", description="自然语言属性描述")
    tags: str = Field(default="", description="标签，逗号分隔")


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attributes: str | None = None
    tags: str | None = None


class ProductOut(BaseModel):
    id: int
    category_id: str
    shop_id: str
    model: str
    attributes: str
    tags: str
    qdrant_sync: int
    created_at: str
    updated_at: str


class ProductImportRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = Field(min_length=1, max_length=100)
    attributes: str = Field(default="")
    tags: str = Field(default="")


# ── 知识库管理 ────────────────────────────────────────────────────────────────


class KnowledgeEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: str = Field(default="default", description="所属分类 ID，共享内容填分类ID")
    shop_id: str = Field(default="global", description="所属店铺 ID，共享内容填 global")
    category: str = Field(default="shortcut", description="分类：shortcut/policy/tutorial/faq_supplement")
    code: str = Field(default="", max_length=100, description="快捷短语code标签")
    title: str = Field(default="", max_length=200)
    content: str = Field(min_length=1, description="完整文本内容")


class KnowledgeEntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    status: int | None = Field(default=None, description="1=已发布, 0=草稿, -1=已删除")


class KnowledgeEntryOut(BaseModel):
    id: int
    shop_id: str
    category: str
    code: str
    title: str
    content: str
    status: int
    qdrant_sync: int
    created_at: str
    updated_at: str


# ── MD 文件管理 ────────────────────────────────────────────────────────────────


class KnowledgeFileOut(BaseModel):
    """已上传的 MD 文件响应体。"""
    id: int
    category_id: str
    shop_id: str
    filename: str
    chunk_count: int
    total_chars: int
    status: int
    created_at: str
    updated_at: str


class KnowledgeFileUpdate(BaseModel):
    """更新文件状态。"""
    status: int | None = Field(default=None, description="1=已索引, 0=未索引")


# ── 告警关键词 ────────────────────────────────────────────────────────────────


class EscalationKeywordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(default="global")
    keyword: str = Field(min_length=1, max_length=100)


class EscalationKeywordOut(BaseModel):
    id: int
    shop_id: str
    keyword: str


# ── 搪塞话术 ──────────────────────────────────────────────────────────────────


class DecoyPhraseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(default="global")
    phrase: str = Field(min_length=1)


class DecoyPhraseOut(BaseModel):
    id: int
    shop_id: str
    phrase: str


# ── 消息日志 ──────────────────────────────────────────────────────────────────


class MessageLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_id: str | None = None
    buyer_id: str | None = None
    message_id: str | None = None
    user_msg: str | None = None
    match_source: str | None = None
    reply: str | None = None
    confidence: float | None = None
    elapsed_ms: int | None = None
    llm_tokens_in: int | None = None
    llm_tokens_out: int | None = None
    is_escalated: bool = False


class MessageLogOut(BaseModel):
    id: int
    shop_id: str | None
    buyer_id: str | None
    message_id: str | None
    user_msg: str | None
    match_source: str | None
    reply: str | None
    confidence: float | None
    elapsed_ms: int | None
    llm_tokens_in: int | None
    llm_tokens_out: int | None
    is_escalated: bool
    created_at: str


# ── 对话归档 ──────────────────────────────────────────────────────────────────


class ConversationArchiveCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_id: str
    buyer_id: str
    session_id: str | None = None
    summary: str | None = None
    full_history: str | None = None  # JSON字符串
    resolution: str | None = None


class ConversationArchiveOut(BaseModel):
    id: int
    shop_id: str
    buyer_id: str
    session_id: str | None
    summary: str | None
    full_history: str | None
    resolution: str | None
    created_at: str
