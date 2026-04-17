import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.email import (
    CampaignOut,
    EmailListItem,
    EmailListResponse,
    EmailStats,
    SendBatchRequest,
    SendBatchResponse,
)
from app.services.email_service import (
    create_campaign,
    get_campaign,
    get_email_stats,
    list_campaigns,
    list_emails,
)
from app.agents.supervisor import run_sender_with_tracking

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emails", tags=["emails"])


@router.post(
    "/send-batch",
    response_model=SendBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_batch(
    body: SendBatchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
) -> SendBatchResponse:
    if not body.influencer_ids:
        raise HTTPException(status_code=400, detail="influencer_ids cannot be empty")

    user_id = int(current_user.sub) if current_user.sub else None
    campaign = await create_campaign(db, body, user_id)

    background_tasks.add_task(
        _launch_sender,
        campaign.id,
        body.influencer_ids,
        body.template_id,
    )

    return SendBatchResponse(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        total_count=campaign.total_count,
        message=f"Batch send started for {campaign.total_count} influencer(s)",
    )


async def _launch_sender(campaign_id: int, influencer_ids: list[int], template_id: int) -> None:
    try:
        await run_sender_with_tracking(campaign_id, influencer_ids, template_id)
    except Exception:
        logger.exception("Sender agent for campaign %d raised unexpectedly", campaign_id)


@router.get("/stats", response_model=EmailStats)
async def get_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> EmailStats:
    stats = await get_email_stats(db)
    return EmailStats(**stats)


@router.get("", response_model=EmailListResponse)
async def list_emails_endpoint(
    campaign_id: Optional[int] = Query(None),
    platform: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> EmailListResponse:
    items_dicts, total = await list_emails(db, campaign_id, platform, status_filter, page, page_size)
    total_pages = max(1, (total + page_size - 1) // page_size)
    return EmailListResponse(
        items=[EmailListItem(**item) for item in items_dicts],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns_endpoint(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> list[CampaignOut]:
    return await list_campaigns(db)  # type: ignore[return-value]


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign_endpoint(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> CampaignOut:
    campaign = await get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign  # type: ignore[return-value]
