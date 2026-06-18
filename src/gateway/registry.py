"""网关注册表，按平台类型管理网关实例。"""

import logging

from src.contracts import Platform
from src.gateway.base import BaseGateway

logger = logging.getLogger(__name__)


class GatewayRegistry:
    """平台网关注册表，维护 Platform -> BaseGateway 映射。

    使用单例模式，应用启动时注册所有网关，运行时按平台查找。
    """

    def __init__(self) -> None:
        self._registry: dict[Platform, BaseGateway] = {}

    def register(self, platform: Platform, gateway: BaseGateway) -> None:
        """注册平台网关。

        Args:
            platform: 平台枚举值。
            gateway: 对应的网关实例。
        """
        self._registry[platform] = gateway
        logger.info("已注册网关: %s -> %s", platform.value, type(gateway).__name__)

    def get(self, platform: Platform) -> BaseGateway:
        """获取指定平台的网关实例。

        Args:
            platform: 平台枚举值。

        Returns:
            对应的网关实例。

        Raises:
            KeyError: 该平台尚未注册网关。
        """
        if platform not in self._registry:
            raise KeyError(f"平台 {platform.value!r} 未注册网关，请检查启动配置")
        return self._registry[platform]

    def all_platforms(self) -> list[Platform]:
        """返回所有已注册的平台列表。"""
        return list(self._registry.keys())


# 全局单例
gateway_registry = GatewayRegistry()
