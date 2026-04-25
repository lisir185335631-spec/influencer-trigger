import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.scrape import ScrapeTaskCreate, ScrapeTaskResponse, ScrapeInfluencerResult
from app.services.scrape_service import (
    create_scrape_task,
    delete_scrape_task,
    get_scrape_task,
    get_task_influencers,
    list_scrape_tasks,
)
from sqlalchemy import func, select
from app.models.scrape_task import ScrapeTask
from app.agents.supervisor import run_scraper_with_tracking

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scrape", tags=["scrape"])


@router.post("/tasks", response_model=ScrapeTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: ScrapeTaskCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    # Validate platforms
    supported = {"instagram", "youtube", "tiktok", "twitter", "facebook"}
    invalid = [p for p in body.platforms if p not in supported]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported platforms: {invalid}. Supported: {sorted(supported)}",
        )

    user_id = current_user.user_id
    task = await create_scrape_task(db, body, user_id)

    # Fire scraper in background
    background_tasks.add_task(_launch_scraper, task.id)

    return task


async def _launch_scraper(task_id: int) -> None:
    """Wrapper to run the scraper coroutine in the background."""
    try:
        await run_scraper_with_tracking(task_id)
    except Exception:
        logger.exception("Background scraper for task %d raised unexpectedly", task_id)


@router.get("/tasks", response_model=list[ScrapeTaskResponse])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    tasks = await list_scrape_tasks(db)
    # Map id → display_number by enumerating tasks sorted by id ascending.
    # Earliest-created task (smallest id) is #1; deleting any task makes
    # later tasks shift down on the next request. Cheap because list
    # size is in the hundreds at most.
    sorted_ids = sorted(t.id for t in tasks)
    display_map = {tid: idx + 1 for idx, tid in enumerate(sorted_ids)}
    out: list[ScrapeTaskResponse] = []
    for t in tasks:
        resp = ScrapeTaskResponse.model_validate(t)
        resp.display_number = display_map[t.id]
        out.append(resp)
    return out


@router.get("/tasks/{task_id}", response_model=ScrapeTaskResponse)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    task = await get_scrape_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Scrape task not found")
    # display_number = count of tasks with id ≤ self.id, hits the
    # primary-key index so it's O(log n).
    count_stmt = select(func.count()).select_from(ScrapeTask).where(ScrapeTask.id <= task.id)
    display_number = (await db.execute(count_stmt)).scalar_one()
    resp = ScrapeTaskResponse.model_validate(task)
    resp.display_number = display_number
    return resp


@router.get("/tasks/{task_id}/results", response_model=list[ScrapeInfluencerResult])
async def get_task_results(
    task_id: int,
    sort: str = "followers",
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    task = await get_scrape_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Scrape task not found")
    sort_by_followers = sort == "followers"
    influencers = await get_task_influencers(db, task_id, sort_by_followers=sort_by_followers)
    return influencers


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Delete a terminal-state scrape task (completed / failed / cancelled).
    Running / pending tasks cannot be deleted — cancel them first."""
    try:
        ok = await delete_scrape_task(db, task_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Scrape task not found")
    return None
