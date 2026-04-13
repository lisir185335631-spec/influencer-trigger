from datetime import datetime, timezone
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignStatus
from app.models.email import Email, EmailStatus
from app.models.influencer import Influencer
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


async def get_email_stats(db: AsyncSession) -> dict:
    result = await db.execute(
        select(
            func.count(case((Email.sent_at.isnot(None), 1))).label("total_sent"),
            func.count(case((
                Email.status.in_([EmailStatus.delivered, EmailStatus.opened, EmailStatus.clicked, EmailStatus.replied]),
                1,
            ))).label("delivered"),
            func.count(case((
                Email.status.in_([EmailStatus.opened, EmailStatus.clicked, EmailStatus.replied]),
                1,
            ))).label("opened"),
            func.count(case((Email.status == EmailStatus.replied, 1))).label("replied"),
            func.count(case((Email.status == EmailStatus.bounced, 1))).label("bounced"),
            func.count(case((
                (Email.sent_at.isnot(None))
                & (~Email.status.in_([EmailStatus.replied, EmailStatus.bounced, EmailStatus.failed])),
                1,
            ))).label("no_reply"),
        )
    )
    row = result.one()
    return {
        "total_sent": row.total_sent or 0,
        "delivered": row.delivered or 0,
        "opened": row.opened or 0,
        "replied": row.replied or 0,
        "no_reply": row.no_reply or 0,
        "bounced": row.bounced or 0,
    }


async def list_emails(
    db: AsyncSession,
    campaign_id: int | None = None,
    platform: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    base_q = (
        select(
            Email.id,
            Email.influencer_id,
            Email.campaign_id,
            Email.status,
            Email.subject,
            Email.sent_at,
            Email.updated_at,
            Influencer.nickname.label("influencer_name"),
            Influencer.email.label("influencer_email"),
            Influencer.platform.label("influencer_platform"),
            Campaign.name.label("campaign_name"),
        )
        .join(Influencer, Email.influencer_id == Influencer.id)
        .outerjoin(Campaign, Email.campaign_id == Campaign.id)
    )

    if campaign_id is not None:
        base_q = base_q.where(Email.campaign_id == campaign_id)
    if platform is not None:
        base_q = base_q.where(Influencer.platform == platform)
    if status is not None:
        base_q = base_q.where(Email.status == status)

    count_q = select(func.count()).select_from(base_q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    items_q = base_q.order_by(Email.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(items_q)).mappings().all()

    return [dict(r) for r in rows], total
