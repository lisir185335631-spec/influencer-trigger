import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.email import CampaignOut, SendBatchRequest, SendBatchResponse
from app.services.email_service import create_campaign, get_campaign, list_campaigns
from app.agents.sender import run_sender_agent

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
        await run_sender_agent(campaign_id, influencer_ids, template_id)
    except Exception:
        logger.exception("Sender agent for campaign %d raised unexpectedly", campaign_id)


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
