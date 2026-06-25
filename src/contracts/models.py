"""所有跨层 Pydantic v2 数据模型定义。

每个模型均配置 extra='forbid' 拒绝未知字段，所有字段携带 description。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── 枚举类型 ─────────────────────────────────────────────────────────────────


class Platform(str, Enum):
    """支持的电商平台枚举。"""

    TAOBAO = "taobao"
    PINDUODUO = "pinduoduo"
    JD = "jd"
    DOUYIN = "douyin"


class IntentType(str, Enum):
    """买家意图类型枚举（FAQ 未命中后进入智能处理管道）。"""

    LOGISTICS = "logistics"          # 物流询问
    AFTER_SALE = "after_sale"        # 售后问题
    COMPLAINT = "complaint"          # 投诉/情绪化
    PRODUCT_INQUIRY = "product_inquiry"  # 产品咨询
    INSTALL_GUIDE = "install_guide"  # 安装指导
    RECOMMEND = "recommend"          # 产品推荐
    CHITCHAT = "chitchat"            # 闲聊
    OTHER = "other"                  # 其他/未知


class MessageSource(str, Enum):
    """消息来源枚举（网关接入方式）。"""

    TOP_API = "top_api"  # 千牛 TOP API Webhook 推送
    LOCAL_DB = "local_db"  # 本地千牛数据库监听（方案B）
    WEBHOOK = "webhook"  # 通用 Webhook 推送（拼多多/京东/抖音）
    RPA = "rpa"  # 影刀 RPA 机器人推送


class SessionState(str, Enum):
    """会话状态枚举。"""

    ACTIVE = "active"  # 正常自动回复中
    WAITING_HUMAN = "waiting_human"  # 已转人工，等待人工介入
    CLOSED = "closed"  # 会话已结束/归档


class EscalationReason(str, Enum):
    """转人工原因枚举。"""

    HARD_KEYWORD = "hard_keyword"  # 命中硬转人工关键词
    LOW_CONFIDENCE = "low_confidence"  # 置信度低于阈值
    EXCEPTION = "exception"  # 系统异常兜底
    SEND_FAILED = "send_failed"  # 消息发送失败
    REPEAT_HUMAN = "repeat_human"  # 已在人工处理中，买家再次发消息
    UNKNOWN_INTENT = "unknown_intent"  # 意图无法识别


@dataclass
class IntentHandlerResult:
    """意图处理器返回结果。"""

    reply: str                      # 生成的回复
    confidence: float = 1.0         # 置信度 0-1
    needs_escalation: bool = False  # 是否转人工
    extra_context: dict[str, Any] = field(default_factory=dict)  # 额外上下文


# ── 接入层 ───────────────────────────────────────────────────────────────────


class StandardMessage(BaseModel):
    """标准化买家消息，由网关层转换后传入调度层。"""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(description="店铺唯一标识，格式如 tb_lamp_001")
    platform: Platform = Field(description="消息来源平台")
    buyer_id: str = Field(description="买家唯一标识（平台内）")
    content: str = Field(description="消息正文内容")
    timestamp: datetime = Field(description="消息发送时间（带时区）")
    message_id: str = Field(description="平台消息唯一 ID，用于幂等去重")
    source: MessageSource = Field(description="网关接入方式")
    product_name: str = Field(
        default="",
        description="商品名称，从 RPA JSON 的 product 字段提取",
    )
    order_detail: str = Field(
        default="",
        description="订单详情文本，从 RPA JSON 的 detail 字段提取",
    )
    raw_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="平台原始消息体，调试用，不参与业务逻辑",
    )
    # ── 抖音专用字段 ────────────────────────────────────────────────────────────
    raw_chat_list: list[str] = Field(
        default_factory=list,
        description="抖音 RPA 原始气泡数组，MatchEngine 抖音模式做系统消息过滤用",
    )
    kefu: str = Field(
        default="",
        description="抖音客服名字，来自 RPA JSON 的 kefu 字段",
    )


# ── 调度层 ───────────────────────────────────────────────────────────────────


class TurnRecord(BaseModel):
    """单轮对话记录。"""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(description="角色：user（买家）或 assistant（客服）")
    content: str = Field(description="本轮消息内容")
    timestamp: datetime = Field(description="本轮时间（带时区）")


class SessionContext(BaseModel):
    """会话上下文，存储于 Redis，键为 session:{shop_id}:{buyer_id}。"""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(description="店铺唯一标识")
    buyer_id: str = Field(description="买家唯一标识")
    platform: Platform = Field(description="会话所属平台")
    state: SessionState = Field(
        default=SessionState.ACTIVE,
        description="当前会话状态",
    )
    history: list[TurnRecord] = Field(
        default_factory=list,
        description="最近 N 轮对话历史（由配置控制保留轮数）",
    )
    current_message: str = Field(
        default="",
        description="当前待处理买家消息内容",
    )
    retrieved_chunks: list[str] = Field(
        default_factory=list,
        description="本轮检索到的知识片段列表",
    )
    last_confidence: int = Field(
        default=0,
        ge=0,
        le=100,
        description="上一次 LLM 输出的置信度（0-100）",
    )
    created_at: datetime = Field(description="会话创建时间（带时区）")
    updated_at: datetime = Field(description="会话最后更新时间（带时区）")


# ── 检索层 ───────────────────────────────────────────────────────────────────


class KnowledgeChunk(BaseModel):
    """单个知识片段，来自 Obsidian 笔记库检索结果。"""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(description="片段唯一 ID，格式：{shop_id}:{文件路径}:{段落序号}")
    content: str = Field(description="知识片段正文")
    source_file: str = Field(description="来源 Obsidian 笔记文件路径（相对 vault 根目录）")
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="相关性得分（0-1），越高越相关",
    )
    tags: list[str] = Field(default_factory=list, description="笔记 frontmatter 标签列表")
    backlinks: list[str] = Field(
        default_factory=list,
        description="关联的双链笔记路径列表",
    )


class RetrievalResult(BaseModel):
    """知识检索层返回结果。"""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(description="检索所属店铺 ID")
    query: str = Field(description="实际执行检索的增强后查询语句")
    chunks: list[KnowledgeChunk] = Field(
        default_factory=list,
        description="检索到的知识片段列表，按相关性降序排列",
    )
    faq_hit: bool = Field(
        default=False,
        description="是否命中 FAQ 精确缓存",
    )
    faq_reply: str = Field(
        default="",
        description="FAQ 命中时的预置回复内容，未命中时为空字符串",
    )
    elapsed_ms: int = Field(
        default=0,
        ge=0,
        description="本次检索总耗时（毫秒）",
    )


# ── LLM 层 ───────────────────────────────────────────────────────────────────


class LLMRequest(BaseModel):
    """LLM 推理层输入。"""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(description="店铺唯一标识，用于加载对应 prompt 模板")
    shop_name: str = Field(description="店铺名称，填充 prompt 模板")
    buyer_message: str = Field(description="买家当前消息内容")
    history: list[TurnRecord] = Field(
        default_factory=list,
        description="近期对话历史，传给 LLM 作为上下文",
    )
    knowledge: str = Field(
        default="",
        description="检索到的知识片段拼接文本，填充 prompt 模板",
    )
    model_override: str = Field(
        default="",
        description="临时覆盖使用的模型名称，空字符串表示使用配置默认值",
    )


class LLMResponse(BaseModel):
    """LLM 推理层输出。"""

    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(description="LLM 原始输出文本（含 [CONFIDENCE: XX] 标记）")
    reply: str = Field(description="提取出的回复正文（已去除置信度标记）")
    confidence: int = Field(
        ge=0,
        le=100,
        description="解析出的置信度（0-100），解析失败时为 0",
    )
    input_tokens: int = Field(default=0, ge=0, description="本次调用消耗的输入 token 数")
    output_tokens: int = Field(default=0, ge=0, description="本次调用消耗的输出 token 数")
    elapsed_ms: int = Field(default=0, ge=0, description="LLM 推理耗时（毫秒）")
    model_used: str = Field(default="", description="实际使用的模型名称")


# ── 动作层 ───────────────────────────────────────────────────────────────────


class EscalationContext(BaseModel):
    """转人工上下文，传递给告警模块。"""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(description="店铺唯一标识")
    buyer_id: str = Field(description="买家唯一标识（业务代码传入前应已脱敏）")
    platform: Platform = Field(description="会话所属平台")
    reason: EscalationReason = Field(description="触发转人工的原因")
    trigger_message: str = Field(description="触发转人工的买家消息内容")
    recent_history: list[TurnRecord] = Field(
        default_factory=list,
        description="最近 3 条对话记录，用于人工快速了解上下文",
    )
    confidence: int = Field(
        default=0,
        ge=0,
        le=100,
        description="触发时的置信度（软规则触发时有值，硬规则触发时为 0）",
    )
    triggered_keyword: str = Field(
        default="",
        description="命中的硬转人工关键词（硬规则触发时有值）",
    )
    message_id: str = Field(
        default="",
        description="触发转人工的原始消息 ID，RPA 网关用于匹配 pending Future",
    )
    timestamp: datetime = Field(description="转人工触发时间（带时区）")


class WritebackTask(BaseModel):
    """Obsidian 记忆回写任务，投入异步队列后由回写模块处理。"""

    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(description="店铺唯一标识，决定写入哪个 Obsidian Vault")
    buyer_id: str = Field(description="买家唯一标识（脱敏后）")
    summary: str = Field(description="本轮会话的结构化总结文本")
    intent_label: str = Field(
        default="",
        description="意图分类标签，如「售后-退款」「咨询-规格」",
    )
    resolution: str = Field(
        default="resolved",
        description="处理结果：resolved（已解决）/ escalated（转人工）",
    )
    related_tags: list[str] = Field(
        default_factory=list,
        description="关联商品/分类标签，写入 Obsidian 双链",
    )
    session_date: datetime = Field(description="会话日期（带时区），决定写入哪个日期块")
    retry_count: int = Field(
        default=0,
        ge=0,
        description="当前重试次数，超过 3 次后降级记录错误日志",
    )
