"""多平台消息网关包，提供统一的 BaseGateway 抽象接口与各平台实现。"""

from src.gateway.base import BaseGateway
from src.gateway.registry import GatewayRegistry

__all__ = ["BaseGateway", "GatewayRegistry"]
