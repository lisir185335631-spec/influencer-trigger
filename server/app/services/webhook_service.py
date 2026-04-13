"""
Webhook notification service — optional Feishu / Slack push.

URLs are configured via environment variables:
  FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/...
  SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

Both are optional; missing/empty URL means the channel is skipped silently.
"""
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def _post_json(url: str, payload: dict, channel: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code not in (200, 204):
                logger.warning(
                    "%s webhook returned HTTP %d: %s",
                    channel, resp.status_code, resp.text[:200],
                )
    except Exception as exc:
        logger.error("%s webhook error: %s", channel, exc)


async def send_notification_webhooks(title: str, content: str) -> None:
    """
    Broadcast a notification to all configured webhook channels.
    Non-blocking — errors are logged and swallowed.
    """
    settings = get_settings()

    if settings.feishu_webhook_url:
        await _post_json(
            settings.feishu_webhook_url,
            {
                "msg_type": "text",
                "content": {"text": f"[Influencer Trigger]\n{title}\n{content}"},
            },
            "Feishu",
        )

    if settings.slack_webhook_url:
        await _post_json(
            settings.slack_webhook_url,
            {"text": f"*[Influencer Trigger]* {title}\n{content}"},
            "Slack",
        )
