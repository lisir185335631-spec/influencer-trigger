"""
Follow-up service — monthly automatic follow-up logic.

monthly_follow_up_check() is called by APScheduler daily at the configured
UTC hour. It queries influencers that meet ALL of:
  1. status = 'contacted'  (have been emailed but not replied)
  2. last_email_sent_at < now() - interval_days
  3. follow_up_count < max_count
  4. No follow_up email already sent this calendar month

For each qualifying influencer:
  - Generate differentiated content via Responder Agent
  - Send via SMTP (re-using sender helpers)
  - Increment follow_up_count; archive when max reached
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.email import Email, EmailStatus, EmailType
from app.models.follow_up_settings import FollowUpSettings
from app.models.influencer import Influencer, InfluencerStatus
from app.models.mailbox import Mailbox, MailboxStatus
from app.agents.responder import get_follow_up_email
from app.agents.sender import MailboxRotator, _send_one
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

async def get_or_create_settings(db: AsyncSession) -> FollowUpSettings:
    """Return the singleton settings row, creating it with defaults if absent."""
    result = await db.execute(select(FollowUpSettings).where(FollowUpSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = FollowUpSettings(id=1)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def update_settings(
    db: AsyncSession,
    enabled: bool | None = None,
    interval_days: int | None = None,
    max_count: int | None = None,
    hour_utc: int | None = None,
) -> FollowUpSettings:
    """Update follow-up settings (partial update)."""
    values: dict = {}
    if enabled is not None:
        values["enabled"] = enabled
    if interval_days is not None:
        values["interval_days"] = interval_days
    if max_count is not None:
        values["max_count"] = max_count
    if hour_utc is not None:
        values["hour_utc"] = hour_utc

    if values:
        await db.execute(
            update(FollowUpSettings)
            .where(FollowUpSettings.id == 1)
            .values(**values)
        )
        await db.commit()

    return await get_or_create_settings(db)


# ---------------------------------------------------------------------------
# Follow-up log queries
# ---------------------------------------------------------------------------

async def list_follow_up_logs(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """
    Return (rows, total) of follow-up emails sent, newest first.
    Each row is a dict with email + influencer fields.
    """
    base_q = (
        select(Email, Influencer)
        .join(Influencer, Email.influencer_id == Influencer.id)
        .where(Email.email_type == EmailType.follow_up)
        .order_by(Email.created_at.desc())
    )
    count_q = select(Email.id).where(Email.email_type == EmailType.follow_up)

    from sqlalchemy import func as sa_func
    total_result = await db.execute(
        select(sa_func.count()).select_from(count_q.subquery())
    )
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(base_q.offset(offset).limit(page_size))
    rows = []
    for email, inf in result.all():
        rows.append({
            "id": email.id,
            "influencer_id": inf.id,
            "influencer_name": inf.nickname,
            "influencer_email": inf.email,
            "influencer_platform": inf.platform.value if inf.platform else None,
            "follow_up_count": inf.follow_up_count,
            "subject": email.subject,
            "status": email.status.value,
            "sent_at": email.sent_at.isoformat() if email.sent_at else None,
            "created_at": email.created_at.isoformat(),
        })
    return rows, total


# ---------------------------------------------------------------------------
# Core scheduler job
# ---------------------------------------------------------------------------

async def monthly_follow_up_check() -> None:
    """
    Daily scheduler job (runs at configured UTC hour).
    Sends follow-up emails to qualifying influencers.
    """
    logger.info("monthly_follow_up_check: starting run")
    async with AsyncSessionLocal() as db:
        settings = await get_or_create_settings(db)
        if not settings.enabled:
            logger.info("monthly_follow_up_check: disabled, skipping")
            return

        now = datetime.now(timezone.utc)
        cutoff_dt = now - timedelta(days=settings.interval_days)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Subquery: influencer already has a follow_up email this month
        follow_up_this_month_sub = (
            select(Email.id)
            .where(
                Email.influencer_id == Influencer.id,
                Email.email_type == EmailType.follow_up,
                Email.sent_at >= month_start,
            )
            .correlate(Influencer)
        )

        qualifying_q = (
            select(Influencer)
            .where(
                Influencer.status == InfluencerStatus.contacted,
                Influencer.last_email_sent_at < cutoff_dt,
                Influencer.follow_up_count < settings.max_count,
                ~exists(follow_up_this_month_sub),
            )
        )
        result = await db.execute(qualifying_q)
        influencers = list(result.scalars().all())
        logger.info("monthly_follow_up_check: %d influencers qualify", len(influencers))

        if not influencers:
            return

        # Load active mailboxes for sending
        mb_result = await db.execute(
            select(Mailbox)
            .where(Mailbox.status == MailboxStatus.active)
            .order_by(Mailbox.today_sent.asc())
        )
        mailboxes = list(mb_result.scalars().all())
        if not mailboxes:
            logger.warning("monthly_follow_up_check: no active mailboxes, aborting")
            return

        rotator = MailboxRotator(mailboxes)

        sent_count = 0
        for inf in influencers:
            # Re-check: if status changed (e.g. replied during this run) skip
            await db.refresh(inf)
            if inf.status != InfluencerStatus.contacted:
                logger.info(
                    "monthly_follow_up_check: skipping %s (status now %s)",
                    inf.email, inf.status.value,
                )
                continue

            mailbox = rotator.next()
            if mailbox is None:
                logger.warning(
                    "monthly_follow_up_check: all mailboxes at limit, stopping at %d/%d",
                    sent_count, len(influencers),
                )
                break

            # Generate differentiated content
            subject, body_html = await get_follow_up_email(inf, inf.follow_up_count)

            # Build message-id
            domain = mailbox.email.split("@")[-1]
            msg_id = f"<{uuid.uuid4()}@{domain}>"

            ok, err, actual_msg_id = await _send_one(mailbox, inf.email, subject, body_html)
            used_msg_id = actual_msg_id or msg_id

            email_record = Email(
                influencer_id=inf.id,
                campaign_id=None,
                mailbox_id=mailbox.id,
                template_id=None,
                email_type=EmailType.follow_up,
                subject=subject,
                body_html=body_html,
                message_id=used_msg_id if ok else None,
                status=EmailStatus.sent if ok else EmailStatus.failed,
                sent_at=now if ok else None,
            )
            db.add(email_record)

            if ok:
                sent_count += 1
                # Update mailbox counters
                await db.execute(
                    update(Mailbox)
                    .where(Mailbox.id == mailbox.id)
                    .values(
                        today_sent=Mailbox.today_sent + 1,
                        this_hour_sent=Mailbox.this_hour_sent + 1,
                        total_sent=Mailbox.total_sent + 1,
                    )
                )
                mailbox.today_sent += 1
                mailbox.this_hour_sent += 1

                # Increment follow_up_count; archive if max reached
                new_count = inf.follow_up_count + 1
                new_status = (
                    InfluencerStatus.archived
                    if new_count >= settings.max_count
                    else inf.status
                )
                await db.execute(
                    update(Influencer)
                    .where(Influencer.id == inf.id)
                    .values(
                        follow_up_count=new_count,
                        last_email_sent_at=now,
                        status=new_status,
                    )
                )
                logger.info(
                    "monthly_follow_up_check: sent follow-up #%d to %s (status→%s)",
                    new_count, inf.email, new_status.value,
                )

                # Push realtime event
                await manager.broadcast("follow_up:sent", {
                    "influencer_id": inf.id,
                    "influencer_email": inf.email,
                    "follow_up_count": new_count,
                    "archived": new_status == InfluencerStatus.archived,
                })
            else:
                logger.error(
                    "monthly_follow_up_check: failed to send follow-up to %s: %s",
                    inf.email, err,
                )

            await db.commit()

        logger.info("monthly_follow_up_check: completed, sent=%d", sent_count)
