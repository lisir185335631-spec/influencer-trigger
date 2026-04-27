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


async def _get_effective_urls() -> tuple[str, str, str]:
    """Return (feishu_url, slack_url, serverchan_send_key) from database
    settings, falling back to env vars when DB value is empty.

    Server 酱 uses a SendKey rather than a webhook URL — same fallback chain
    (DB row → env var) for consistency, even though the value isn't a URL.
    """
    try:
        from app.database import AsyncSessionLocal
        from app.services.settings_service import get_or_create_system_settings
        async with AsyncSessionLocal() as db:
            sys_settings = await get_or_create_system_settings(db)
            feishu = sys_settings.webhook_feishu or ""
            slack = sys_settings.webhook_slack or ""
            serverchan = sys_settings.webhook_serverchan or ""
    except Exception:
        feishu = ""
        slack = ""
        serverchan = ""

    # Fall back to env vars if database has no value configured
    if not feishu or not slack or not serverchan:
        from app.config import get_settings
        env_settings = get_settings()
        if not feishu:
            feishu = env_settings.feishu_webhook_url or ""
        if not slack:
            slack = env_settings.slack_webhook_url or ""
        if not serverchan:
            serverchan = env_settings.serverchan_send_key or ""

    return feishu, slack, serverchan


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


async def send_serverchan(send_key: str, title: str, content: str) -> bool:
    """Send a push to WeChat via Server 酱 (sct.ftqq.com).

    Endpoint: https://sctapi.ftqq.com/{send_key}.send
    Form params: title (≤32 chars), desp (≤32KB markdown body).
    """
    if not send_key:
        return False
    url = f"https://sctapi.ftqq.com/{send_key.strip()}.send"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Server 酱 expects form-encoded data, not JSON.
            # Limits: title ≤ 32 chars, desp ≤ 32 KB (we cap at 30 KB to
            # leave headroom for HTTP/form encoding overhead).
            resp = await client.post(
                url,
                data={"title": title[:32], "desp": content[:30000]},
            )
            if resp.status_code != 200:
                logger.warning(
                    "Server酱 webhook returned HTTP %d: %s",
                    resp.status_code, resp.text[:200],
                )
                return False
            # Server 酱 returns {"code": 0, ...} on success
            try:
                payload = resp.json()
                if payload.get("code") != 0:
                    logger.warning("Server酱 push failed: %s", payload)
                    return False
            except Exception:
                # Non-JSON 200 response — assume OK to avoid false negatives
                pass
            return True
    except Exception as exc:
        logger.error("Server酱 webhook error: %s", exc)
        return False


async def send_notification_webhooks(title: str, content: str) -> None:
    """
    Broadcast a notification to all configured webhook channels.
    Non-blocking — errors are logged and swallowed.
    """
    feishu_url, slack_url, serverchan_key = await _get_effective_urls()

    if feishu_url:
        await send_feishu(feishu_url, title, content)

    if slack_url:
        await send_slack(slack_url, title, content)

    if serverchan_key:
        await send_serverchan(serverchan_key, title, content)


async def test_webhook_url(platform: str, url: str) -> bool:
    """Test a specific webhook URL (or Server 酱 SendKey) by sending a test
    message. The `url` arg is the SendKey when platform == 'serverchan'."""
    title = "Influencer Trigger — 通知测试"
    content = "✅ Webhook 连接测试成功！通知配置正确。"
    if platform == "feishu":
        return await send_feishu(url, title, content)
    elif platform == "slack":
        return await send_slack(url, title, content)
    elif platform == "serverchan":
        return await send_serverchan(url, title, content)
    return False
