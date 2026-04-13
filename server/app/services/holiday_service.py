"""
Holiday service — CRUD and holiday greeting email scheduler job.

holiday_greeting_check() is called by APScheduler daily at 08:00 UTC.
For each active holiday that matches today's date:
  - Find all non-archived influencers
  - Exclude those who already received a follow_up or holiday email this month
  - Generate personalized greeting via GPT-4o (or static fallback)
  - Send via SMTP (does NOT increment follow_up_count)
  - Log as EmailType.holiday
"""
import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select, update, exists, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.email import Email, EmailStatus, EmailType
from app.models.holiday import Holiday
from app.models.influencer import Influencer, InfluencerStatus
from app.models.mailbox import Mailbox, MailboxStatus
from app.agents.sender import MailboxRotator, _send_one
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default holidays to seed on first startup
# ---------------------------------------------------------------------------

DEFAULT_HOLIDAYS = [
    {"name": "Christmas", "date": date(2025, 12, 25), "is_recurring": True},
    {"name": "New Year", "date": date(2025, 1, 1), "is_recurring": True},
    {"name": "Thanksgiving", "date": date(2025, 11, 27), "is_recurring": True},
    {"name": "Valentine's Day", "date": date(2025, 2, 14), "is_recurring": True},
    {"name": "Halloween", "date": date(2025, 10, 31), "is_recurring": True},
    {"name": "Easter", "date": date(2025, 4, 20), "is_recurring": True},
]


async def seed_default_holidays(db: AsyncSession) -> None:
    """Insert the 6 default holidays if the holidays table is empty."""
    result = await db.execute(select(sa_func.count()).select_from(Holiday))
    count = result.scalar_one()
    if count > 0:
        return
    for h in DEFAULT_HOLIDAYS:
        db.add(Holiday(
            name=h["name"],
            date=h["date"],
            is_recurring=h["is_recurring"],
            is_active=True,
        ))
    await db.commit()
    logger.info("Seeded %d default holidays", len(DEFAULT_HOLIDAYS))


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

async def list_holidays(db: AsyncSession) -> list[Holiday]:
    result = await db.execute(select(Holiday).order_by(Holiday.date.asc()))
    return list(result.scalars().all())


async def get_holiday(db: AsyncSession, holiday_id: int) -> Holiday | None:
    result = await db.execute(select(Holiday).where(Holiday.id == holiday_id))
    return result.scalar_one_or_none()


async def create_holiday(
    db: AsyncSession,
    name: str,
    holiday_date: date,
    is_recurring: bool = True,
    is_active: bool = True,
    greeting_template: str | None = None,
) -> Holiday:
    holiday = Holiday(
        name=name,
        date=holiday_date,
        is_recurring=is_recurring,
        is_active=is_active,
        greeting_template=greeting_template,
    )
    db.add(holiday)
    await db.commit()
    await db.refresh(holiday)
    return holiday


async def update_holiday(
    db: AsyncSession,
    holiday_id: int,
    **kwargs,
) -> Holiday | None:
    holiday = await get_holiday(db, holiday_id)
    if holiday is None:
        return None
    for key, value in kwargs.items():
        if value is not None or key in ("greeting_template",):
            setattr(holiday, key, value)
    await db.commit()
    await db.refresh(holiday)
    return holiday


async def delete_holiday(db: AsyncSession, holiday_id: int) -> bool:
    holiday = await get_holiday(db, holiday_id)
    if holiday is None:
        return False
    await db.delete(holiday)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Greeting log queries
# ---------------------------------------------------------------------------

async def list_greeting_logs(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """Return (rows, total) of holiday greeting emails, newest first."""
    base_q = (
        select(Email, Influencer)
        .join(Influencer, Email.influencer_id == Influencer.id)
        .where(Email.email_type == EmailType.holiday)
        .order_by(Email.created_at.desc())
    )
    total_result = await db.execute(
        select(sa_func.count()).select_from(
            select(Email.id).where(Email.email_type == EmailType.holiday).subquery()
        )
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
            "subject": email.subject,
            "status": email.status.value,
            "sent_at": email.sent_at.isoformat() if email.sent_at else None,
            "created_at": email.created_at.isoformat(),
        })
    return rows, total


# ---------------------------------------------------------------------------
# GPT greeting generation
# ---------------------------------------------------------------------------

_GREETING_SYSTEM_PROMPT = """You are a brand partnership manager writing warm holiday greeting emails to influencers.
Write a short, genuine, personalized holiday greeting (max 100 words) that:
1. References the specific holiday
2. Is warm and human — not promotional
3. Does NOT ask for anything — it is purely a greeting
4. Has a short, friendly subject line

Return ONLY valid JSON:
{
  "subject": "subject line here",
  "body_html": "<p>email body in HTML here (only p tags)</p>"
}"""


async def generate_greeting(
    influencer: Influencer,
    holiday_name: str,
    greeting_template: str | None = None,
) -> tuple[str, str]:
    """
    Generate a holiday greeting (subject, body_html).
    Uses custom greeting_template if set, otherwise tries GPT-4o, falls back to static.
    """
    from app.config import get_settings
    settings = get_settings()

    influencer_name = influencer.nickname or influencer.email.split("@")[0]
    industry = influencer.industry or "your niche"

    # Use custom template if provided
    if greeting_template:
        subject = f"Happy {holiday_name}! 🎉"
        body_html = greeting_template.replace("{name}", influencer_name).replace("{holiday}", holiday_name)
        return subject, body_html

    # Try GPT-4o
    if settings.openai_api_key:
        user_prompt = (
            f"Influencer details:\n"
            f"  Name: {influencer_name}\n"
            f"  Industry: {industry}\n\n"
            f"Holiday: {holiday_name}\n\n"
            f"Write a personalized holiday greeting email for this influencer."
        )
        try:
            import json
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": _GREETING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.8,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            subject = data.get("subject", "").strip()
            body_html = data.get("body_html", "").strip()
            if subject and body_html:
                return subject, body_html
        except Exception as exc:
            logger.error("Holiday greeting GPT call failed: %s", exc)

    # Static fallback
    subject = f"Happy {holiday_name} from us! 🎉"
    body_html = (
        f"<p>Hi {influencer_name},</p>"
        f"<p>Wishing you a wonderful {holiday_name}! "
        f"We hope this season brings you joy and inspiration in everything you do.</p>"
        f"<p>Warm regards</p>"
    )
    return subject, body_html


# ---------------------------------------------------------------------------
# Core scheduler job
# ---------------------------------------------------------------------------

def _is_today(holiday: Holiday, today: date) -> bool:
    """Check if a holiday falls on today (considering is_recurring)."""
    if not holiday.is_active:
        return False
    if holiday.is_recurring:
        return holiday.date.month == today.month and holiday.date.day == today.day
    return holiday.date == today


async def holiday_greeting_check() -> None:
    """
    Daily scheduler job (08:00 UTC): send greeting emails for today's holidays.
    Does NOT increment follow_up_count.
    """
    logger.info("holiday_greeting_check: starting run")
    async with AsyncSessionLocal() as db:
        today = datetime.now(timezone.utc).date()
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Find active holidays matching today
        all_holidays_result = await db.execute(select(Holiday).where(Holiday.is_active == True))
        all_holidays = list(all_holidays_result.scalars().all())
        todays_holidays = [h for h in all_holidays if _is_today(h, today)]

        if not todays_holidays:
            logger.info("holiday_greeting_check: no holidays today (%s), skipping", today)
            return

        logger.info(
            "holiday_greeting_check: %d holiday(s) today: %s",
            len(todays_holidays),
            [h.name for h in todays_holidays],
        )

        # Subquery: influencer already received follow_up or holiday email this month
        contacted_this_month_sub = (
            select(Email.id)
            .where(
                Email.influencer_id == Influencer.id,
                Email.email_type.in_([EmailType.follow_up, EmailType.holiday]),
                Email.sent_at >= month_start,
            )
            .correlate(Influencer)
        )

        # Find all non-archived influencers not yet contacted this month
        qualifying_q = (
            select(Influencer)
            .where(
                Influencer.status != InfluencerStatus.archived,
                ~exists(contacted_this_month_sub),
            )
        )
        result = await db.execute(qualifying_q)
        influencers = list(result.scalars().all())
        logger.info("holiday_greeting_check: %d influencers qualify for greetings", len(influencers))

        if not influencers:
            return

        # Load active mailboxes
        mb_result = await db.execute(
            select(Mailbox)
            .where(Mailbox.status == MailboxStatus.active)
            .order_by(Mailbox.today_sent.asc())
        )
        mailboxes = list(mb_result.scalars().all())
        if not mailboxes:
            logger.warning("holiday_greeting_check: no active mailboxes, aborting")
            return

        rotator = MailboxRotator(mailboxes)

        # Use first matching holiday for greeting content
        holiday = todays_holidays[0]

        sent_count = 0
        for inf in influencers:
            mailbox = rotator.next()
            if mailbox is None:
                logger.warning(
                    "holiday_greeting_check: all mailboxes at limit, stopping at %d/%d",
                    sent_count, len(influencers),
                )
                break

            subject, body_html = await generate_greeting(inf, holiday.name, holiday.greeting_template)

            domain = mailbox.email.split("@")[-1]
            msg_id = f"<{uuid.uuid4()}@{domain}>"

            ok, err, actual_msg_id = await _send_one(mailbox, inf.email, subject, body_html)
            used_msg_id = actual_msg_id or msg_id

            email_record = Email(
                influencer_id=inf.id,
                campaign_id=None,
                mailbox_id=mailbox.id,
                template_id=None,
                email_type=EmailType.holiday,
                subject=subject,
                body_html=body_html,
                message_id=used_msg_id if ok else None,
                status=EmailStatus.sent if ok else EmailStatus.failed,
                sent_at=now if ok else None,
            )
            db.add(email_record)

            if ok:
                sent_count += 1
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

                # NOTE: follow_up_count is NOT incremented for holiday greetings
                logger.info(
                    "holiday_greeting_check: sent '%s' greeting to %s",
                    holiday.name, inf.email,
                )

                await manager.broadcast("holiday:greeting_sent", {
                    "influencer_id": inf.id,
                    "influencer_email": inf.email,
                    "holiday_name": holiday.name,
                })
            else:
                logger.error(
                    "holiday_greeting_check: failed to send greeting to %s: %s",
                    inf.email, err,
                )

            await db.commit()

        logger.info("holiday_greeting_check: completed, sent=%d", sent_count)
