from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.dashboard import (
    DashboardMailboxHealth,
    DashboardPlatformDistribution,
    DashboardStats,
    DashboardTrends,
    MailboxHealthItem,
    PlatformItem,
    TrendPoint,
)
from app.services.dashboard_service import (
    get_mailbox_health,
    get_platform_distribution,
    get_stats,
    get_trends,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def stats_endpoint(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> DashboardStats:
    data = await get_stats(db)
    return DashboardStats(**data)


@router.get("/trends", response_model=DashboardTrends)
async def trends_endpoint(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> DashboardTrends:
    rows = await get_trends(db)
    return DashboardTrends(data=[TrendPoint(**r) for r in rows])


@router.get("/platform-distribution", response_model=DashboardPlatformDistribution)
async def platform_distribution_endpoint(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> DashboardPlatformDistribution:
    rows = await get_platform_distribution(db)
    return DashboardPlatformDistribution(data=[PlatformItem(**r) for r in rows])


@router.get("/mailbox-health", response_model=DashboardMailboxHealth)
async def mailbox_health_endpoint(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> DashboardMailboxHealth:
    rows = await get_mailbox_health(db)
    return DashboardMailboxHealth(data=[MailboxHealthItem(**r) for r in rows])
