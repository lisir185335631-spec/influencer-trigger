"""
Follow-up API — settings management and follow-up log list.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.deps import get_current_user
from app.models.user import User
from app.services.follow_up_service import (
    get_or_create_settings,
    list_follow_up_logs,
    update_settings,
)

router = APIRouter(prefix="/follow-up", tags=["follow-up"])


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

async def get_db():  # type: ignore[return]
    async with AsyncSessionLocal() as db:
        yield db


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FollowUpSettingsOut(BaseModel):
    """Two-phase follow-up cadence settings.

    Note on field naming: `interval_days` and `max_count` are LEGACY names
    that semantically mean "phase-2 interval" and "phase-2 count" — kept
    for API/DB backward compatibility. Phase 1 is the new explicitly-named
    `phase1_*` pair.
    """
    id: int
    enabled: bool
    phase1_count: int           # phase 1 (intensive): number of follow-ups
    phase1_interval_days: int   # phase 1 (intensive): days between sends
    interval_days: int          # phase 2 (cold): days between sends [legacy name]
    max_count: int              # phase 2 (cold): number of follow-ups [legacy name]
    hour_utc: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class FollowUpSettingsUpdate(BaseModel):
    """Partial update — see FollowUpSettingsOut for field semantics."""
    enabled: Optional[bool] = None
    phase1_count: Optional[int] = Field(None, ge=0, le=20)
    phase1_interval_days: Optional[int] = Field(None, ge=1, le=365)
    # legacy name — semantically phase-2 interval
    interval_days: Optional[int] = Field(None, ge=1, le=365)
    # legacy name — semantically phase-2 count
    max_count: Optional[int] = Field(None, ge=0, le=50)
    hour_utc: Optional[int] = Field(None, ge=0, le=23)


class FollowUpLogItem(BaseModel):
    id: int
    influencer_id: int
    influencer_name: Optional[str]
    influencer_email: str
    influencer_platform: Optional[str]
    follow_up_count: int
    subject: str
    status: str
    sent_at: Optional[str]
    created_at: str


class FollowUpLogsResponse(BaseModel):
    items: list[FollowUpLogItem]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=FollowUpSettingsOut)
async def get_settings_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowUpSettingsOut:
    settings = await get_or_create_settings(db)
    return FollowUpSettingsOut(
        id=settings.id,
        enabled=settings.enabled,
        phase1_count=settings.phase1_count,
        phase1_interval_days=settings.phase1_interval_days,
        interval_days=settings.interval_days,
        max_count=settings.max_count,
        hour_utc=settings.hour_utc,
        created_at=settings.created_at.isoformat(),
        updated_at=settings.updated_at.isoformat(),
    )


@router.put("/settings", response_model=FollowUpSettingsOut)
async def update_settings_endpoint(
    body: FollowUpSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowUpSettingsOut:
    settings = await update_settings(
        db,
        enabled=body.enabled,
        interval_days=body.interval_days,
        max_count=body.max_count,
        hour_utc=body.hour_utc,
        phase1_count=body.phase1_count,
        phase1_interval_days=body.phase1_interval_days,
    )

    # Reschedule the APScheduler job if hour changed
    if body.hour_utc is not None:
        try:
            from app.scheduler import scheduler
            from apscheduler.triggers.cron import CronTrigger

            scheduler.reschedule_job(
                "daily_follow_up",
                trigger=CronTrigger(hour=settings.hour_utc, minute=0, timezone="UTC"),
            )
        except Exception as exc:
            # Non-fatal — settings saved, scheduler update failed
            import logging
            logging.getLogger(__name__).warning(
                "Failed to reschedule follow-up job: %s", exc
            )

    return FollowUpSettingsOut(
        id=settings.id,
        enabled=settings.enabled,
        phase1_count=settings.phase1_count,
        phase1_interval_days=settings.phase1_interval_days,
        interval_days=settings.interval_days,
        max_count=settings.max_count,
        hour_utc=settings.hour_utc,
        created_at=settings.created_at.isoformat(),
        updated_at=settings.updated_at.isoformat(),
    )


@router.get("/logs", response_model=FollowUpLogsResponse)
async def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowUpLogsResponse:
    rows, total = await list_follow_up_logs(db, page=page, page_size=page_size)
    return FollowUpLogsResponse(
        items=[FollowUpLogItem(**r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/trigger", status_code=202)
async def trigger_follow_up(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Manually trigger the follow-up check (runs in background)."""
    import asyncio
    from app.services.follow_up_service import daily_follow_up_check

    asyncio.create_task(daily_follow_up_check())
    return {"message": "Follow-up check triggered"}
