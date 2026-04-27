"""
Follow-up service — two-phase automatic follow-up logic.

daily_follow_up_check() is called by APScheduler daily at the configured
UTC hour. Cadence is two-phase:
  Phase 1 (intensive): first `phase1_count` follow-ups, `phase1_interval_days` apart
                       (default 3 × 2 days → days 3/5/7).
  Phase 2 (cold)     : next `max_count` follow-ups, `interval_days` apart
                       (default 6 × 30 days → ~6 months).

Per influencer, the next required interval is decided by current
follow_up_count: phase 1 while count < phase1_count, phase 2 otherwise.
Total cap = phase1_count + max_count (default 9). When reached, the
influencer is auto-archived.

For each qualifying influencer:
  - Generate differentiated content via Responder Agent
  - Send via SMTP (re-using sender helpers)
  - Increment follow_up_count; archive when total cap reached
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update
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


def _required_interval_days(
    follow_up_count: int,
    phase1_count: int,
    phase1_interval_days: int,
    phase2_interval_days: int,
) -> int:
    """Decide the next-due interval for one influencer based on how many
    follow-ups they've already received. Phase-1 cadence applies until the
    influencer has consumed all phase-1 slots; after that, switch to the
    cold (phase-2) interval.
    """
    if follow_up_count < phase1_count:
        return phase1_interval_days
    return phase2_interval_days


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
    phase1_count: int | None = None,
    phase1_interval_days: int | None = None,
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
    if phase1_count is not None:
        values["phase1_count"] = phase1_count
    if phase1_interval_days is not None:
        values["phase1_interval_days"] = phase1_interval_days

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

async def daily_follow_up_check() -> None:
    """
    Daily scheduler job (runs at configured UTC hour).
    Sends follow-up emails to qualifying influencers using two-phase cadence.

    Selection: status='contacted' AND follow_up_count < (phase1_count +
    max_count) AND distance(last_email_sent_at, now) >= phase-aware
    required-interval. The "one follow-up per calendar month" guard is
    intentionally removed — phase-1 cadence requires multiple sends per
    month early on; the per-influencer interval check is what spaces sends
    correctly across both phases.
    """
    logger.info("daily_follow_up_check: starting run")
    async with AsyncSessionLocal() as db:
        settings = await get_or_create_settings(db)
        if not settings.enabled:
            logger.info("daily_follow_up_check: disabled, skipping")
            return

        now = datetime.now(timezone.utc)
        total_cap = settings.phase1_count + settings.max_count

        # Cheap pre-filter at the SQL layer; the per-row interval check
        # (which depends on each influencer's follow_up_count) happens in
        # Python below — small scan size, no need to express the CASE WHEN
        # in SQL.
        qualifying_q = (
            select(Influencer)
            .where(
                Influencer.status == InfluencerStatus.contacted,
                Influencer.last_email_sent_at.isnot(None),
                Influencer.follow_up_count < total_cap,
            )
        )
        result = await db.execute(qualifying_q)
        candidates = list(result.scalars().all())

        # Per-row interval gate using the phase-aware helper.
        influencers: list[Influencer] = []
        for inf in candidates:
            interval = _required_interval_days(
                inf.follow_up_count,
                settings.phase1_count,
                settings.phase1_interval_days,
                settings.interval_days,
            )
            if inf.last_email_sent_at is None:
                continue
            # Naive datetimes from SQLite default to UTC; coerce so the
            # subtraction below doesn't blow up with tz-naive vs tz-aware.
            last_sent = inf.last_email_sent_at
            if last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            if (now - last_sent) >= timedelta(days=interval):
                influencers.append(inf)

        logger.info(
            "daily_follow_up_check: %d/%d candidates due (cap=%d)",
            len(influencers), len(candidates), total_cap,
        )

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
            logger.warning("daily_follow_up_check: no active mailboxes, aborting")
            return

        rotator = MailboxRotator(mailboxes)

        sent_count = 0
        for inf in influencers:
            # Re-check: if status changed (e.g. replied during this run) skip
            await db.refresh(inf)
            if inf.status != InfluencerStatus.contacted:
                logger.info(
                    "daily_follow_up_check: skipping %s (status now %s)",
                    inf.email, inf.status.value,
                )
                continue

            mailbox = rotator.next()
            if mailbox is None:
                logger.warning(
                    "daily_follow_up_check: all mailboxes at limit, stopping at %d/%d",
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

                # Increment follow_up_count; archive if total cap reached
                # (phase 1 + phase 2 combined).
                new_count = inf.follow_up_count + 1
                new_status = (
                    InfluencerStatus.archived
                    if new_count >= total_cap
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
                    "daily_follow_up_check: sent follow-up #%d to %s (status→%s)",
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
                    "daily_follow_up_check: failed to send follow-up to %s: %s",
                    inf.email, err,
                )

            await db.commit()

        logger.info("daily_follow_up_check: completed, sent=%d", sent_count)
