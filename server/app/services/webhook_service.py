"""
Webhook notification service — optional Feishu / Slack / Server酱 push.

URLs / SendKeys are stored in the SystemSettings database table (editable
via Settings UI). Env vars FEISHU_WEBHOOK_URL / SLACK_WEBHOOK_URL /
SERVERCHAN_SEND_KEY serve as initial defaults.

Every push is recorded into the `webhook_push_logs` table by
`_send_with_log` so the dashboard "Server酱 推送" card + modal can show
real-time status. The send_* primitives now return a (success, http_code,
error) tuple so the audit row gets populated correctly.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

# Send functions return (success, http_code_or_none, error_message_or_none)
SendResult = tuple[bool, int | None, str | None]


async def _post_json_full(
    url: str, payload: dict, channel: str,
) -> SendResult:
    """POST JSON to a webhook URL. Returns (success, http_code, error_msg)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code not in (200, 204):
                err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning("%s webhook %s", channel, err)
                return False, resp.status_code, err
            return True, resp.status_code, None
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        logger.error("%s webhook error: %s", channel, err)
        return False, None, err[:300]


async def _get_effective_urls() -> tuple[str, str, str]:
    """Return (feishu_url, slack_url, serverchan_send_key) from database
    settings, falling back to env vars when DB value is empty."""
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


async def send_feishu(url: str, title: str, content: str) -> SendResult:
    """Send a card message to a Feishu webhook URL."""
    if not url:
        return False, None, "missing url"
    return await _post_json_full(
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


async def send_slack(url: str, title: str, content: str) -> SendResult:
    """Send a block message to a Slack webhook URL."""
    if not url:
        return False, None, "missing url"
    return await _post_json_full(
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


async def send_serverchan(send_key: str, title: str, content: str) -> SendResult:
    """Send a push to WeChat via Server酱 (sct.ftqq.com).

    Endpoint: https://sctapi.ftqq.com/{send_key}.send
    Form params: title (≤32 chars), desp (≤32KB markdown body).
    Returns (success, http_code, error_msg).
    """
    if not send_key:
        return False, None, "missing send_key"
    url = f"https://sctapi.ftqq.com/{send_key.strip()}.send"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url,
                data={"title": title[:32], "desp": content[:30000]},
            )
            if resp.status_code != 200:
                err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning("Server酱 %s", err)
                return False, resp.status_code, err
            try:
                payload = resp.json()
                if payload.get("code") != 0:
                    err = (
                        f"Server酱 code={payload.get('code')}: "
                        f"{payload.get('message', '')}"
                    )[:300]
                    logger.warning("Server酱 push failed: %s", payload)
                    return False, resp.status_code, err
            except Exception:
                # Non-JSON 200 — treat as success (Server酱 occasionally
                # answers with a redirect HTML page on success).
                pass
            return True, resp.status_code, None
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"[:300]
        logger.error("Server酱 webhook error: %s", err)
        return False, None, err


async def _send_with_log(
    channel: str,
    title: str,
    content: str,
    email_id: int | None,
    influencer_id: int | None,
    send_func: Callable[[], Awaitable[SendResult]],
) -> None:
    """Run a send_* call, persist a webhook_push_logs row + broadcast
    a `webhook:pushed` WS event. Failures inside the audit-write path
    are logged but never re-raised — push success must not depend on
    log success."""
    start = time.monotonic()
    success = False
    http_code: int | None = None
    error: str | None = None

    try:
        success, http_code, error = await send_func()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]

    duration_ms = int((time.monotonic() - start) * 1000)

    # Persist audit row
    log_id: int | None = None
    try:
        from app.database import AsyncSessionLocal
        from app.models.webhook_push_log import WebhookPushLog
        async with AsyncSessionLocal() as db:
            log = WebhookPushLog(
                channel=channel,
                email_id=email_id,
                influencer_id=influencer_id,
                title=title[:256],
                content_preview=content[:512],
                status="success" if success else "failed",
                http_code=http_code,
                error_message=error[:500] if error else None,
                duration_ms=duration_ms,
            )
            db.add(log)
            await db.commit()
            await db.refresh(log)
            log_id = log.id
    except Exception as exc:
        logger.warning("Failed to persist webhook_push_log: %s", exc)

    # Broadcast for real-time UI. Use Python-side `now` to avoid the
    # SQLAlchemy server_default lazy-refresh / greenlet trap that bit
    # the Notification path earlier today.
    try:
        from app.websocket.manager import manager
        await manager.broadcast("webhook:pushed", {
            "id": log_id,
            "channel": channel,
            "email_id": email_id,
            "influencer_id": influencer_id,
            "title": title[:256],
            "content_preview": content[:512],
            "status": "success" if success else "failed",
            "http_code": http_code,
            "error_message": error[:500] if error else None,
            "duration_ms": duration_ms,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.debug("Failed to broadcast webhook:pushed: %s", exc)


async def send_notification_webhooks(
    title: str,
    content: str,
    *,
    email_id: int | None = None,
    influencer_id: int | None = None,
) -> None:
    """
    Broadcast a notification to all configured webhook channels.
    Non-blocking — errors are logged + recorded in webhook_push_logs.
    """
    feishu_url, slack_url, serverchan_key = await _get_effective_urls()

    if feishu_url:
        await _send_with_log(
            "feishu", title, content, email_id, influencer_id,
            lambda: send_feishu(feishu_url, title, content),
        )

    if slack_url:
        await _send_with_log(
            "slack", title, content, email_id, influencer_id,
            lambda: send_slack(slack_url, title, content),
        )

    if serverchan_key:
        await _send_with_log(
            "serverchan", title, content, email_id, influencer_id,
            lambda: send_serverchan(serverchan_key, title, content),
        )


async def test_webhook_url(platform: str, url: str) -> bool:
    """Test a specific webhook URL (or Server酱 SendKey) by sending a test
    message. Returns plain bool for backwards-compat with existing
    /api/settings/test endpoint. Test pushes are NOT logged to the
    audit table — they're config-validation, not real notifications."""
    title = "Influencer Trigger — 通知测试"
    content = "✅ Webhook 连接测试成功!通知配置正确。"
    if platform == "feishu":
        success, _, _ = await send_feishu(url, title, content)
    elif platform == "slack":
        success, _, _ = await send_slack(url, title, content)
    elif platform == "serverchan":
        success, _, _ = await send_serverchan(url, title, content)
    else:
        return False
    return success
