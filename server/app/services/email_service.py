from datetime import datetime, timezone
from sqlalchemy import select, func, case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignStatus
from app.models.email import Email, EmailStatus
from app.models.email_draft import EmailDraft, EmailDraftStatus
from app.models.influencer import Influencer, InfluencerPlatform
from app.schemas.email import SendBatchRequest


async def find_or_create_manual_influencer(
    db: AsyncSession,
    email: str,
    nickname: str | None,
) -> Influencer:
    """Look up an influencer by email; create a manual one if missing.

    Manual records use platform=other (the existing enum bucket for "not
    one of our 5 platforms") so no schema migration is required and the
    UI's existing platform filter naturally picks them up. The unique
    index on `email` is the source of truth — if two send-direct calls
    race on the same address, the loser falls back to the winner's row.
    """
    email_lower = email.strip().lower()
    existing = (
        await db.execute(select(Influencer).where(Influencer.email == email_lower))
    ).scalar_one_or_none()
    if existing:
        return existing

    # Use email prefix as a sane fallback nickname so monitor / list
    # views show *something* meaningful even when the user didn't type
    # a name on the send-direct form.
    fallback_nick = (nickname or email_lower.split("@", 1)[0])[:256]
    influencer = Influencer(
        email=email_lower,
        nickname=fallback_nick,
        platform=InfluencerPlatform.other,
    )
    db.add(influencer)
    try:
        await db.commit()
    except IntegrityError:
        # Another concurrent send-direct beat us to the unique index;
        # roll back and re-fetch the winner so the caller still gets a
        # valid row to attach the campaign/draft to.
        await db.rollback()
        existing = (
            await db.execute(
                select(Influencer).where(Influencer.email == email_lower)
            )
        ).scalar_one_or_none()
        if not existing:
            # Truly unexpected — raise so the endpoint returns 500
            # rather than silently dropping the send.
            raise
        return existing
    await db.refresh(influencer)
    return influencer


async def create_direct_send_campaign(
    db: AsyncSession,
    *,
    name: str,
    subject: str,
    body_html: str,
    influencer_id: int,
    user_id: int | None,
) -> tuple[Campaign, EmailDraft]:
    """Build a single-recipient campaign + a ready-to-send draft so the
    standard Sender Agent draft branch can pick it up unchanged. We
    deliberately route through the draft pipeline (rather than adding a
    third sender mode) — every cross-cutting feature added to drafts
    later (tracking pixel, retry counters, etc.) automatically applies
    to direct sends without re-implementation.
    """
    campaign = Campaign(
        name=name,
        template_id=None,
        status=CampaignStatus.pending,
        use_drafts=True,
        total_count=1,
        created_by=user_id,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    draft = EmailDraft(
        campaign_id=campaign.id,
        influencer_id=influencer_id,
        template_id=None,
        subject=subject,
        body_html=body_html,
        status=EmailDraftStatus.ready,
        edited_by_user=True,  # treat user-typed body as already-edited
        generated_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return campaign, draft


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
            # "Delivered" semantics for SMTP-direct mode: anything that left
            # the outbox and didn't bounce/fail counts as delivered. SMTP 250
            # OK is the only delivery signal we get without a webhook
            # provider (SendGrid/Mailgun); a separate `delivered` event only
            # ever fires if such a provider is wired up later. Including
            # `sent` here lets the dashboard reflect reality instead of
            # showing a permanent 0.
            func.count(case((
                Email.status.in_([
                    EmailStatus.sent,
                    EmailStatus.delivered,
                    EmailStatus.opened,
                    EmailStatus.clicked,
                    EmailStatus.replied,
                ]),
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
    email_type: str | None = None,
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
            Email.email_type,
            Influencer.follow_up_count.label("follow_up_count"),
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
    if email_type is not None:
        # initial / follow_up / holiday — UI can filter to "show only follow-ups"
        base_q = base_q.where(Email.email_type == email_type)

    count_q = select(func.count()).select_from(base_q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    items_q = base_q.order_by(Email.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(items_q)).mappings().all()

    # EmailType / EmailStatus are str-mixin enums (`class X(str, enum.Enum)`),
    # so Pydantic v2 accepts the instances directly into `str` schema fields
    # without coercion. No manual enum.value extraction needed.
    return [dict(r) for r in rows], total
