"""统一日志配置模块。

提供按天轮转、保留30天、携带 shop_id 和 trace_id 的结构化日志。
"""

import logging
import logging.handlers
from pathlib import Path

from src.utils.trace import get_trace_id

_LOG_DIR = Path("logs")
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(shop_id)s] [%(trace_id)s] %(name)s: %(message)s"

_setup_done = False


class _ContextFilter(logging.Filter):
    """日志过滤器，自动注入 shop_id 和 trace_id 上下文字段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "shop_id"):
            record.shop_id = "-"  # type: ignore[attr-defined]
        if not hasattr(record, "trace_id"):
            record.trace_id = get_trace_id() or "-"  # type: ignore[attr-defined]
        return True


def setup_logging(
    level: str = "INFO",
    log_dir: str | Path = _LOG_DIR,
    retention_days: int = 30,
) -> None:
    """初始化全局日志配置（幂等，多次调用无副作用）。

    Args:
        level: 日志级别，如 "INFO"、"DEBUG"。
        log_dir: 日志文件输出目录。
        retention_days: 日志文件保留天数。
    """
    global _setup_done
    if _setup_done:
        return

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    context_filter = _ContextFilter()
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(context_filter)
    root_logger.addHandler(console_handler)

    # 按天轮转文件处理器
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_dir / "app.log",
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
        utc=False,
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(context_filter)
    root_logger.addHandler(file_handler)

    _setup_done = True


def get_logger(name: str, shop_id: str = "-") -> logging.LoggerAdapter:
    """获取携带 shop_id 的 LoggerAdapter。

    Args:
        name: Logger 名称，通常传入 __name__。
        shop_id: 当前操作关联的店铺 ID。

    Returns:
        预绑定 shop_id 的 LoggerAdapter。

    Examples:
        >>> logger = get_logger(__name__, shop_id="tb_lamp_001")
        >>> logger.info("消息接收成功")
    """
    base_logger = logging.getLogger(name)
    return logging.LoggerAdapter(base_logger, {"shop_id": shop_id, "trace_id": ""})
