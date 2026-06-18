"""基于 contextvars 的 trace_id 生成与传递工具。

每个异步任务（协程）可携带独立的 trace_id，用于日志关联与问题追踪。
"""

import uuid
from contextvars import ContextVar

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


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
