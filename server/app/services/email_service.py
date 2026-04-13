from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignStatus
from app.schemas.email import SendBatchRequest


async def create_campaign(db: AsyncSession, data: SendBatchRequest, user_id: int | None) -> Campaign:
    name = data.campaign_name or f"Campaign {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    campaign = Campaign(
        name=name,
        template_id=data.template_id,
        status=CampaignStatus.pending,
        total_count=len(data.influencer_ids),
        created_by=user_id,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def list_campaigns(db: AsyncSession) -> list[Campaign]:
    result = await db.execute(select(Campaign).order_by(Campaign.created_at.desc()))
    return list(result.scalars().all())


async def get_campaign(db: AsyncSession, campaign_id: int) -> Campaign | None:
    return await db.get(Campaign, campaign_id)
