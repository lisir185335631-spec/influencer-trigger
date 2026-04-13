from datetime import datetime, timedelta, timezone

from sqlalchemy import func, case, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import Email, EmailStatus
from app.models.influencer import Influencer, ReplyIntent
from app.models.mailbox import Mailbox
from app.models.collaboration import Collaboration


async def get_stats(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)

    # Influencer counts
    inf_result = await db.execute(
        select(
            func.count().label("total"),
            func.count(
                case((Influencer.created_at >= week_start, 1))
            ).label("new_this_week"),
        )
    )
    inf_row = inf_result.one()

    # Email counts
    email_result = await db.execute(
        select(
            func.count(case((Email.sent_at.isnot(None), 1))).label("total_sent"),
            func.count(
                case((
                    (Email.sent_at.isnot(None)) & (Email.sent_at >= week_start),
                    1,
                ))
            ).label("sent_this_week"),
            func.count(case((Email.status == EmailStatus.replied, 1))).label("total_replied"),
            func.count(
                case((
                    (Email.status == EmailStatus.replied)
                    & (Influencer.reply_intent.in_([ReplyIntent.interested, ReplyIntent.pricing])),
                    1,
                ))
            ).label("effective_replies"),
        ).join(Influencer, Email.influencer_id == Influencer.id, isouter=True)
    )
    email_row = email_result.one()

    total_sent = email_row.total_sent or 0
    total_replied = email_row.total_replied or 0
    effective_replies = email_row.effective_replies or 0
    total_influencers = inf_row.total or 0

    # Collaboration count
    collab_result = await db.execute(select(func.count()).select_from(Collaboration))
    collab_count = collab_result.scalar() or 0

    reply_rate = round(total_replied / total_sent, 4) if total_sent > 0 else 0.0
    effective_reply_rate = round(effective_replies / total_sent, 4) if total_sent > 0 else 0.0
    conversion_rate = round(collab_count / total_influencers, 4) if total_influencers > 0 else 0.0

    return {
        "total_influencers": total_influencers,
        "new_this_week": inf_row.new_this_week or 0,
        "total_sent": total_sent,
        "sent_this_week": email_row.sent_this_week or 0,
        "reply_rate": reply_rate,
        "effective_reply_rate": effective_reply_rate,
        "conversion_rate": conversion_rate,
    }


async def get_trends(db: AsyncSession) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=29)

    # Use SQLite date() function to group by day
    sent_result = await db.execute(
        select(
            func.date(Email.sent_at).label("day"),
            func.count().label("cnt"),
        )
        .where(
            Email.sent_at.isnot(None),
            Email.sent_at >= start,
        )
        .group_by(func.date(Email.sent_at))
        .order_by(func.date(Email.sent_at))
    )
    sent_map: dict[str, int] = {row.day: row.cnt for row in sent_result}

    replied_result = await db.execute(
        select(
            func.date(Email.replied_at).label("day"),
            func.count().label("cnt"),
        )
        .where(
            Email.replied_at.isnot(None),
            Email.replied_at >= start,
        )
        .group_by(func.date(Email.replied_at))
        .order_by(func.date(Email.replied_at))
    )
    replied_map: dict[str, int] = {row.day: row.cnt for row in replied_result}

    # Build complete 30-day series
    result = []
    for i in range(30):
        day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        result.append({
            "date": day,
            "sent": sent_map.get(day, 0),
            "replied": replied_map.get(day, 0),
        })
    return result


async def get_platform_distribution(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(
            Influencer.platform.label("platform"),
            func.count().label("count"),
        )
        .where(Influencer.platform.isnot(None))
        .group_by(Influencer.platform)
        .order_by(func.count().desc())
    )
    rows = result.all()
    return [
        {"platform": row.platform.value if hasattr(row.platform, "value") else str(row.platform), "count": row.count}
        for row in rows
    ]


async def get_mailbox_health(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Mailbox).order_by(Mailbox.email)
    )
    mailboxes = result.scalars().all()
    return [
        {
            "id": m.id,
            "email": m.email,
            "today_sent": m.today_sent,
            "daily_limit": m.daily_limit,
            "total_sent": m.total_sent,
            "bounce_rate": m.bounce_rate,
            "status": m.status.value,
        }
        for m in mailboxes
    ]
