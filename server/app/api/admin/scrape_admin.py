import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.platform_quota import PlatformQuota
from app.models.scrape_task import ScrapeTask, ScrapeTaskStatus
from app.models.user import User
from app.schemas.auth import TokenData
from app.services.scrape_service import update_task_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scrape", tags=["admin-scrape"])

PLATFORMS = ["tiktok", "instagram", "youtube", "twitter", "facebook"]


class QuotaPatchRequest(BaseModel):
    platform: str
    daily_limit: int


async def _ensure_quota(db, platform: str) -> PlatformQuota:
    result = await db.execute(
        select(PlatformQuota).where(PlatformQuota.platform == platform)
    )
    quota = result.scalar_one_or_none()
    if quota is None:
        quota = PlatformQuota(platform=platform, daily_limit=500, today_used=0)
        db.add(quota)
        await db.commit()
        await db.refresh(quota)
    return quota


@router.get("/tasks")
async def list_all_tasks(
    _: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ScrapeTask, User.username)
                .outerjoin(User, User.id == ScrapeTask.created_by)
                .order_by(ScrapeTask.created_at.desc())
            )
        ).all()

        items = []
        for task, username in rows:
            items.append({
                "id": task.id,
                "platforms": json.loads(task.platforms) if task.platforms else [],
                "industry": task.industry,
                "target_count": task.target_count,
                "status": task.status.value,
                "progress": task.progress,
                "found_count": task.found_count,
                "valid_count": task.valid_count,
                "error_message": task.error_message,
                "target_market": task.target_market,
                "created_by": task.created_by,
                "creator_username": username,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "created_at": task.created_at.isoformat(),
            })

        running_count = sum(1 for i in items if i["status"] == "running")
        return {"total": len(items), "running": running_count, "items": items}


@router.post("/tasks/{task_id}/force-terminate")
async def force_terminate_task(
    task_id: int,
    _: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        task = await db.get(ScrapeTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status not in (ScrapeTaskStatus.running, ScrapeTaskStatus.pending):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot terminate task in status: {task.status.value}",
            )
        await update_task_status(
            db, task, ScrapeTaskStatus.cancelled,
            error_message="Force terminated by admin",
        )
        return {"ok": True, "task_id": task_id}


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    _: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        task = await db.get(ScrapeTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status not in (ScrapeTaskStatus.failed, ScrapeTaskStatus.cancelled):
            raise HTTPException(
                status_code=400,
                detail=f"Can only retry failed/cancelled tasks, current: {task.status.value}",
            )
        task.status = ScrapeTaskStatus.pending
        task.progress = 0
        task.error_message = None
        task.started_at = None
        task.completed_at = None
        await db.commit()

    background_tasks.add_task(_launch_scraper_bg, task_id)
    return {"ok": True, "task_id": task_id}


async def _launch_scraper_bg(task_id: int) -> None:
    from app.agents.scraper import run_scraper_agent
    try:
        await run_scraper_agent(task_id)
    except Exception:
        logger.exception("Admin retry scraper task %d raised unexpectedly", task_id)


@router.get("/platform-quota")
async def get_platform_quota(
    _: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        items = []
        for platform in PLATFORMS:
            quota = await _ensure_quota(db, platform)
            items.append({
                "platform": quota.platform,
                "daily_limit": quota.daily_limit,
                "today_used": quota.today_used,
                "last_reset_at": quota.last_reset_at.isoformat() if quota.last_reset_at else None,
            })
        return {"items": items}


@router.patch("/platform-quota")
async def update_platform_quota(
    body: QuotaPatchRequest,
    _: TokenData = Depends(require_admin),
) -> dict:
    if body.platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {body.platform}")
    if body.daily_limit < 0:
        raise HTTPException(status_code=400, detail="daily_limit must be >= 0")

    async with AsyncSessionLocal() as db:
        quota = await _ensure_quota(db, body.platform)
        quota.daily_limit = body.daily_limit
        await db.commit()
        return {
            "platform": quota.platform,
            "daily_limit": quota.daily_limit,
            "today_used": quota.today_used,
        }
