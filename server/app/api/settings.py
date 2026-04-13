"""
System settings API — GET/PUT /api/settings
Aggregates SystemSettings (scrape, webhooks) + FollowUpSettings (follow-up strategy).
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.deps import get_current_user, require_manager_or_above
from app.schemas.auth import TokenData
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services.settings_service import (
    get_or_create_system_settings,
    update_system_settings,
)
from app.services.follow_up_service import get_or_create_settings, update_settings as update_follow_up
from app.services.webhook_service import test_webhook_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


async def get_db():  # type: ignore[return]
    async with AsyncSessionLocal() as db:
        yield db


@router.get("", response_model=SettingsOut)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
) -> SettingsOut:
    """Return merged system settings."""
    sys = await get_or_create_system_settings(db)
    fu = await get_or_create_settings(db)
    return SettingsOut(
        follow_up_enabled=fu.enabled,
        interval_days=fu.interval_days,
        max_count=fu.max_count,
        hour_utc=fu.hour_utc,
        scrape_concurrency=sys.scrape_concurrency,
        webhook_feishu=sys.webhook_feishu,
        webhook_slack=sys.webhook_slack,
    )


@router.put("", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_manager_or_above),
) -> SettingsOut:
    """Update system settings (manager/admin only)."""
    # Update SystemSettings
    sys = await update_system_settings(
        db,
        scrape_concurrency=body.scrape_concurrency,
        webhook_feishu=body.webhook_feishu,
        webhook_slack=body.webhook_slack,
    )

    # Update FollowUpSettings
    fu = await update_follow_up(
        db,
        enabled=body.follow_up_enabled,
        interval_days=body.interval_days,
        max_count=body.max_count,
        hour_utc=body.hour_utc,
    )

    # Reschedule follow-up job if hour changed
    if body.hour_utc is not None:
        try:
            from app.scheduler import scheduler
            from apscheduler.triggers.cron import CronTrigger
            scheduler.reschedule_job(
                "monthly_follow_up",
                trigger=CronTrigger(hour=fu.hour_utc, minute=0, timezone="UTC"),
            )
        except Exception as exc:
            logger.warning("Failed to reschedule follow-up job: %s", exc)

    return SettingsOut(
        follow_up_enabled=fu.enabled,
        interval_days=fu.interval_days,
        max_count=fu.max_count,
        hour_utc=fu.hour_utc,
        scrape_concurrency=sys.scrape_concurrency,
        webhook_feishu=sys.webhook_feishu,
        webhook_slack=sys.webhook_slack,
    )


@router.post("/test-webhook")
async def test_webhook(
    body: dict,
    current_user: TokenData = Depends(require_manager_or_above),
) -> dict:
    """Test a webhook URL by sending a test message."""
    platform = body.get("platform", "")
    url = body.get("url", "")
    if platform not in ("feishu", "slack"):
        raise HTTPException(status_code=400, detail="platform must be 'feishu' or 'slack'")
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    ok = await test_webhook_url(platform, url)
    return {"success": ok, "platform": platform}
