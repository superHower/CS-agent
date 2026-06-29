"""基于 contextvars 的 trace_id 生成与传递工具。

每个异步任务（协程）可携带独立的 trace_id，用于日志关联与问题追踪。
"""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

# ── 调试步骤上下文（贯穿整个请求生命周期）───────────────────────────────────────


@dataclass
class DebugStep:
    """单个调试步骤的数据。"""

    step: str = ""          # 步骤标识符（与前端 StepCard 对应）
    label: str = ""         # 步骤中文名称
    hit: bool | None = None # 是否命中（None=未尝试）
    reply: str = ""         # 步骤输出内容
    error: str = ""         # 错误信息
    elapsed_ms: int = 0     # 耗时
    intent: str = ""        # 意图类型
    entities: list[str] = field(default_factory=list)
    rewrite_query: str = "" # 改写后的查询词
    faq_hit: bool = False
    faq_reply: str = ""
    chunks_count: int = 0
    chunks: list[dict] = field(default_factory=list)  # [{content, score}]
    confidence: int | None = None
    knowledge_chars: int = 0


@dataclass
class DebugContext:
    """贯穿单个请求的调试上下文。"""

    steps: list[DebugStep] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def add_step(self, **kwargs) -> DebugStep:
        s = DebugStep(**kwargs)
        self.steps.append(s)
        return s


# 全局 contextvar，存放当前请求的 DebugContext（异步安全）
_debug_ctx_var: ContextVar[DebugContext] = ContextVar(
    "debug_context", default=DebugContext()
)

# 备选：跨任务传递 DebugContext（message_id → DebugContext）。
# 当请求通过 asyncio.create_task 派生任务时（如 dispatcher.handle），
# contextvars 不会自动传播（仅在创建任务那一刻的快照内），
# 因此需要按 message_id 显式查找。
_debug_ctx_registry: dict[str, DebugContext] = {}
_registry_lock_placeholder = None  # 避免引入额外依赖；写入只在本进程内


def register_debug_context(message_id: str, ctx: DebugContext) -> None:
    """注册 message_id → DebugContext 映射。"""
    _debug_ctx_registry[message_id] = ctx


def lookup_debug_context(message_id: str) -> DebugContext | None:
    """按 message_id 查找 DebugContext，未注册返回 None。"""
    return _debug_ctx_registry.get(message_id)


def consume_debug_context(message_id: str) -> DebugContext | None:
    """读取并清除 DebugContext（避免内存泄漏）。"""
    return _debug_ctx_registry.pop(message_id, None)


def get_debug_context() -> DebugContext:
    """获取当前上下文的 DebugContext。"""
    return _debug_ctx_var.get()


def set_debug_context(ctx: DebugContext) -> None:
    """设置当前上下文的 DebugContext。"""
    _debug_ctx_var.set(ctx)


def clear_debug_context() -> None:
    """清除当前上下文的 DebugContext。"""
    _debug_ctx_var.set(DebugContext())


def get_trace_id() -> str:
    """获取当前上下文的 trace_id，未设置时返回空字符串。"""
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    """设置当前上下文的 trace_id。

    Args:
        trace_id: 要设置的 trace_id 字符串。
    """
    _trace_id_var.set(trace_id)


def new_trace_id() -> str:
    """生成并设置一个新的 UUID4 trace_id，返回该 ID。

    Returns:
        新生成的 trace_id（不含连字符的 UUID4 字符串）。
    """
    tid = uuid.uuid4().hex
    _trace_id_var.set(tid)
    return tid


def clear_trace_id() -> None:
    """清除当前上下文的 trace_id（重置为空字符串）。"""
    _trace_id_var.set("")
