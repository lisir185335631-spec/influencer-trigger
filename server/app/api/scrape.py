import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.scrape import ScrapeTaskCreate, ScrapeTaskResponse
from app.services.scrape_service import (
    create_scrape_task,
    get_scrape_task,
    list_scrape_tasks,
)
from app.agents.scraper import run_scraper_agent

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

    user_id = int(current_user.sub) if current_user.sub else None
    task = await create_scrape_task(db, body, user_id)

    # Fire scraper in background
    background_tasks.add_task(_launch_scraper, task.id)

    return task


async def _launch_scraper(task_id: int) -> None:
    """Wrapper to run the scraper coroutine in the background."""
    try:
        await run_scraper_agent(task_id)
    except Exception:
        logger.exception("Background scraper for task %d raised unexpectedly", task_id)


@router.get("/tasks", response_model=list[ScrapeTaskResponse])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    return await list_scrape_tasks(db)


@router.get("/tasks/{task_id}", response_model=ScrapeTaskResponse)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    task = await get_scrape_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Scrape task not found")
    return task
