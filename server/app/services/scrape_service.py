import json
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.influencer import Influencer
from app.models.scrape_task import ScrapeTask, ScrapeTaskStatus
from app.models.scrape_task_influencer import ScrapeTaskInfluencer
from app.schemas.scrape import ScrapeTaskCreate

logger = logging.getLogger(__name__)


async def delete_scrape_task(db: AsyncSession, task_id: int) -> bool:
    """Delete a scrape task and its influencer join rows.
    Only allowed for terminal states: completed / failed / cancelled.
    Influencer records themselves are NOT deleted (they may be linked
    to other tasks or used downstream).
    Returns True on success, False if task not found."""
    task = await get_scrape_task(db, task_id)
    if task is None:
        return False
    if task.status not in (
        ScrapeTaskStatus.completed,
        ScrapeTaskStatus.failed,
        ScrapeTaskStatus.cancelled,
    ):
        raise ValueError(
            f"Cannot delete task in status={task.status.value}; "
            "only completed/failed/cancelled tasks can be deleted"
        )
    await db.execute(
        delete(ScrapeTaskInfluencer).where(ScrapeTaskInfluencer.scrape_task_id == task_id)
    )
    await db.delete(task)
    await db.commit()
    return True


async def create_scrape_task(
    db: AsyncSession, data: ScrapeTaskCreate, user_id: int | None = None
) -> ScrapeTask:
    task = ScrapeTask(
        platforms=json.dumps(data.platforms),
        industry=data.industry,
        target_count=data.target_count,
        created_by=user_id,
        target_market=data.target_market,
        competitor_brands=data.competitor_brands,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def list_scrape_tasks(db: AsyncSession) -> list[ScrapeTask]:
    result = await db.execute(
        select(ScrapeTask).order_by(ScrapeTask.created_at.desc())
    )
    return list(result.scalars().all())


async def get_scrape_task(db: AsyncSession, task_id: int) -> ScrapeTask | None:
    result = await db.execute(select(ScrapeTask).where(ScrapeTask.id == task_id))
    return result.scalar_one_or_none()


async def get_task_influencers(
    db: AsyncSession, task_id: int, sort_by_followers: bool = False
) -> list[Influencer]:
    stmt = (
        select(Influencer)
        .join(ScrapeTaskInfluencer, ScrapeTaskInfluencer.influencer_id == Influencer.id)
        .where(ScrapeTaskInfluencer.scrape_task_id == task_id)
    )
    if sort_by_followers:
        stmt = stmt.order_by(Influencer.followers.desc().nullslast())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_task_status(
    db: AsyncSession,
    task: ScrapeTask,
    status: ScrapeTaskStatus,
    progress: int | None = None,
    found_count: int | None = None,
    valid_count: int | None = None,
    new_count: int | None = None,
    reused_count: int | None = None,
    error_message: str | None = None,
) -> None:
    task.status = status
    if progress is not None:
        # Monotonic enforcement at function level: progress must never
        # regress while a task is running. Multiple call sites (on_found
        # new-based formula, _process_channel finally visit-based formula,
        # _scrape_youtube per-scroll, _enrich_results per-batch, gap-fill
        # walks) push progress concurrently — without this guard the
        # smaller value would overwrite the larger and the UI would
        # see a backward jump (the task #64 "猛地倒退" symptom).
        # Terminal states (completed/failed/cancelled) bypass the guard
        # so the task can land on its true final value (typically 100).
        if status in (ScrapeTaskStatus.completed, ScrapeTaskStatus.failed, ScrapeTaskStatus.cancelled):
            task.progress = progress
        else:
            task.progress = max(task.progress or 0, progress)
    if found_count is not None:
        task.found_count = found_count
    if valid_count is not None:
        task.valid_count = valid_count
    if new_count is not None:
        task.new_count = new_count
    if reused_count is not None:
        task.reused_count = reused_count
    if error_message is not None:
        task.error_message = error_message
    if status == ScrapeTaskStatus.running and task.started_at is None:
        task.started_at = datetime.now(timezone.utc)
    if status in (ScrapeTaskStatus.completed, ScrapeTaskStatus.failed, ScrapeTaskStatus.cancelled):
        task.completed_at = datetime.now(timezone.utc)
    await db.commit()
