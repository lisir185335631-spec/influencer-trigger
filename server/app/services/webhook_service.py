"""
Webhook notification service — optional Feishu / Slack push.

URLs are stored in the SystemSettings database table (editable via Settings UI).
Env vars FEISHU_WEBHOOK_URL / SLACK_WEBHOOK_URL serve as initial defaults.
"""
import logging

import httpx

logger = logging.getLogger(__name__)


async def _post_json(url: str, payload: dict, channel: str) -> bool:
    """POST JSON to a webhook URL. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code not in (200, 204):
                logger.warning(
                    "%s webhook returned HTTP %d: %s",
                    channel, resp.status_code, resp.text[:200],
                )
                return False
            return True
    except Exception as exc:
        logger.error("%s webhook error: %s", channel, exc)
        return False


async def _get_effective_urls() -> tuple[str, str]:
    """Return (feishu_url, slack_url) from database settings (fall back to env vars)."""
    try:
        from app.database import AsyncSessionLocal
        from app.services.settings_service import get_or_create_system_settings
        async with AsyncSessionLocal() as db:
            sys_settings = await get_or_create_system_settings(db)
            feishu = sys_settings.webhook_feishu or ""
            slack = sys_settings.webhook_slack or ""
    except Exception:
        feishu = ""
        slack = ""

    # Fall back to env vars if database has no URL configured
    if not feishu or not slack:
        from app.config import get_settings
        env_settings = get_settings()
        if not feishu:
            feishu = env_settings.feishu_webhook_url or ""
        if not slack:
            slack = env_settings.slack_webhook_url or ""

    return feishu, slack


async def send_feishu(url: str, title: str, content: str) -> bool:
    """Send a card message to a Feishu webhook URL."""
    if not url:
        return False
    return await _post_json(
        url,
        {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "plain_text", "content": content},
                    }
                ],
            },
        },
        "Feishu",
    )


async def send_slack(url: str, title: str, content: str) -> bool:
    """Send a block message to a Slack webhook URL."""
    if not url:
        return False
    return await _post_json(
        url,
        {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": title},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": content},
                },
            ]
        },
        "Slack",
    )


async def send_notification_webhooks(title: str, content: str) -> None:
    """
    Broadcast a notification to all configured webhook channels.
    Non-blocking — errors are logged and swallowed.
    """
    feishu_url, slack_url = await _get_effective_urls()
    msg = f"[Influencer Trigger] {title}\n{content}"

    if feishu_url:
        await send_feishu(feishu_url, title, content)

    if slack_url:
        await send_slack(slack_url, title, content)


async def test_webhook_url(platform: str, url: str) -> bool:
    """Test a specific webhook URL by sending a test message."""
    title = "Influencer Trigger — 通知测试"
    content = "✅ Webhook 连接测试成功！通知配置正确。"
    if platform == "feishu":
        return await send_feishu(url, title, content)
    elif platform == "slack":
        return await send_slack(url, title, content)
    return False
