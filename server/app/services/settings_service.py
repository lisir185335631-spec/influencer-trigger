"""System settings service — singleton CRUD for SystemSettings table."""
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_settings import SystemSettings

logger = logging.getLogger(__name__)


async def get_or_create_system_settings(db: AsyncSession) -> SystemSettings:
    """Return the singleton system settings row, creating it with defaults if absent."""
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.id == 1)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = SystemSettings(id=1)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def update_system_settings(
    db: AsyncSession,
    scrape_concurrency: Optional[int] = None,
    webhook_feishu: Optional[str] = None,
    webhook_slack: Optional[str] = None,
) -> SystemSettings:
    """Partial update of system settings."""
    settings = await get_or_create_system_settings(db)

    if scrape_concurrency is not None:
        settings.scrape_concurrency = scrape_concurrency
    if webhook_feishu is not None:
        settings.webhook_feishu = webhook_feishu
    if webhook_slack is not None:
        settings.webhook_slack = webhook_slack

    await db.commit()
    await db.refresh(settings)
    return settings
