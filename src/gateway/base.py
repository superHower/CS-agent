"""网关抽象基类，定义所有平台网关必须实现的统一接口。"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.config.settings import ShopConfig
from src.contracts import StandardMessage


class BaseGateway(ABC):
    """所有平台网关的抽象基类。

    子类必须实现 listen 和 send 两个方法，平台差异完全封装在子类内部，
    调度层通过此接口与网关交互，无需感知平台细节。
    """

    @abstractmethod
    async def listen(self, shop_config: ShopConfig) -> AsyncIterator[StandardMessage]:
        """监听指定店铺的买家消息，以异步迭代器形式逐条产出标准化消息。

        Args:
            shop_config: 店铺配置，包含平台凭证等信息。

        Yields:
            StandardMessage: 标准化后的买家消息。

        Notes:
            - 实现类必须保证消息去重（按 message_id 幂等）。
            - 网络断开时应自动重连，不得让迭代器静默退出。
            - 任何单条消息解析失败应记录日志并跳过，不中断迭代。
        """
        # 使迭代器类型检查通过
        return
        yield  # noqa: unreachable

    @abstractmethod
    async def send(
        self,
        shop_config: ShopConfig,
        buyer_id: str,
        content: str,
        metadata: dict,
    ) -> bool:
        """向指定买家发送消息。

        Args:
            shop_config: 店铺配置。
            buyer_id: 买家唯一标识。
            content: 要发送的消息内容。
            metadata: 平台附加元数据（如消息类型、业务标签等）。

        Returns:
            True 表示发送成功，False 表示发送失败。

        Notes:
            - 实现类内部不做重试，重试逻辑由 actions/send_message.py 负责。
            - 发送失败应记录详细日志，方便排查。
        """
        ...
