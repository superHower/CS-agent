"""通用工具模块，包含日志、trace_id 管理和数据脱敏。"""

from src.utils.logger import get_logger, setup_logging
from src.utils.sensitive import mask_address, mask_phone, mask_sensitive
from src.utils.trace import clear_trace_id, get_trace_id, new_trace_id, set_trace_id

__all__ = [
    "setup_logging",
    "get_logger",
    "get_trace_id",
    "set_trace_id",
    "new_trace_id",
    "clear_trace_id",
    "mask_phone",
    "mask_address",
    "mask_sensitive",
]
