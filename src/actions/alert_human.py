"""人工告警模块。

将转人工事件通过企业微信机器人 Webhook 推送通知。
推送失败不影响主流程（已转人工状态已写入 Redis）。
"""

import logging
from datetime import UTC

import aiohttp

from src.contracts import EscalationContext, EscalationReason

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10

_REASON_LABELS = {
    EscalationReason.HARD_KEYWORD: "命中敏感词",
    EscalationReason.LOW_CONFIDENCE: "置信度不足",
    EscalationReason.EXCEPTION: "系统异常",
    EscalationReason.SEND_FAILED: "消息发送失败",
}


def _format_wecom_payload(ctx: EscalationContext) -> dict:
    """构造企业微信 Markdown Webhook payload。"""
    reason_label = _REASON_LABELS.get(ctx.reason, str(ctx.reason))
    ts = ctx.timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    history_text = ""
    for turn in ctx.recent_history[-3:]:
        role = "买家" if turn.role == "user" else "客服"
        history_text += f"\n>{role}：{turn.content}"

    text = (
        f"**客服转人工通知**\n"
        f">店铺：{ctx.shop_id}\n"
        f">买家：{ctx.buyer_id}\n"
        f">平台：{ctx.platform}\n"
        f">原因：{reason_label}\n"
        f">触发消息：{ctx.trigger_message}\n"
        f">时间：{ts}"
        f"{history_text}"
    )

    return {"msgtype": "markdown", "markdown": {"content": text}}


class AlertService:
    """企业微信机器人告警推送服务。

    Args:
        webhook_url: 企业微信机器人 Webhook 地址。
        timeout_s: 推送超时秒数。
    """

    def __init__(self, webhook_url: str, timeout_s: int = _TIMEOUT_S) -> None:
        self._url = webhook_url
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)

    async def notify(self, ctx: EscalationContext) -> None:
        """推送转人工告警通知。

        推送失败记录错误日志，不向上抛出异常，不影响主流程。

        Args:
            ctx: EscalationContext 转人工上下文对象。
        """
        if not self._url:
            logger.warning("告警 Webhook 未配置，跳过推送 shop=%s", ctx.shop_id)
            return

        payload = _format_wecom_payload(ctx)

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(self._url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(
                            "告警推送成功 shop=%s buyer=%s reason=%s",
                            ctx.shop_id,
                            ctx.buyer_id,
                            ctx.reason,
                        )
                    else:
                        body = await resp.text()
                        logger.error(
                            "告警推送失败 HTTP %d shop=%s: %s",
                            resp.status,
                            ctx.shop_id,
                            body[:100],
                        )
        except TimeoutError:
            logger.error("告警推送超时 shop=%s buyer=%s", ctx.shop_id, ctx.buyer_id)
        except Exception as exc:
            logger.error("告警推送异常 shop=%s: %s", ctx.shop_id, exc)

    @classmethod
    def from_config(cls, alert_config) -> "AlertService":
        """从 AlertConfig 构建 AlertService 实例。"""
        return cls(webhook_url=alert_config.webhook_url)
