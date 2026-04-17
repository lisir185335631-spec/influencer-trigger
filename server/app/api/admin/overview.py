from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.email import Email, EmailStatus
from app.models.influencer import Influencer
from app.models.mailbox import Mailbox, MailboxStatus
from app.models.notification import Notification, NotificationLevel
from app.models.scrape_task import ScrapeTask
from app.models.user import User
from app.scheduler import scheduler
from app.schemas.auth import TokenData
from app.websocket.manager import manager

router = APIRouter(prefix="/overview", tags=["admin-overview"])


async def _get_db() -> AsyncSession:
    async with AsyncSessionLocal() as db:
        return db


def _today() -> date:
    return date.today()


def _week_start() -> datetime:
    today = date.today()
    return datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())


def _month_start() -> datetime:
    today = date.today()
    return datetime.combine(today.replace(day=1), datetime.min.time())


def _day_start(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time())


def _day_end(d: date) -> datetime:
    return datetime.combine(d, datetime.max.time())


@router.get("/metrics")
async def get_metrics(current_user: TokenData = Depends(require_admin)) -> dict:
    today = _today()
    week_start = _week_start()
    month_start = _month_start()
    today_start = _day_start(today)
    today_end = _day_end(today)

    async with AsyncSessionLocal() as db:
        # ── Users ──────────────────────────────────────────────────────────
        total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
        active_users = (await db.execute(
            select(func.count(User.id)).where(User.is_active == True)  # noqa: E712
        )).scalar_one()

        # ── Emails sent ────────────────────────────────────────────────────
        sent_statuses = [EmailStatus.sent, EmailStatus.delivered, EmailStatus.opened, EmailStatus.replied]

        def _sent_where(col):
            return Email.status.in_(sent_statuses) if col is None else True

        emails_sent_today = (await db.execute(
            select(func.count(Email.id)).where(
                Email.status.in_(sent_statuses),
                Email.sent_at >= today_start,
                Email.sent_at <= today_end,
            )
        )).scalar_one()
        emails_sent_week = (await db.execute(
            select(func.count(Email.id)).where(
                Email.status.in_(sent_statuses),
                Email.sent_at >= week_start,
            )
        )).scalar_one()
        emails_sent_month = (await db.execute(
            select(func.count(Email.id)).where(
                Email.status.in_(sent_statuses),
                Email.sent_at >= month_start,
            )
        )).scalar_one()

        # ── Emails replied ─────────────────────────────────────────────────
        emails_replied_today = (await db.execute(
            select(func.count(Email.id)).where(
                Email.status == EmailStatus.replied,
                Email.replied_at >= today_start,
                Email.replied_at <= today_end,
            )
        )).scalar_one()
        emails_replied_week = (await db.execute(
            select(func.count(Email.id)).where(
                Email.status == EmailStatus.replied,
                Email.replied_at >= week_start,
            )
        )).scalar_one()
        emails_replied_month = (await db.execute(
            select(func.count(Email.id)).where(
                Email.status == EmailStatus.replied,
                Email.replied_at >= month_start,
            )
        )).scalar_one()

        # ── Influencers ────────────────────────────────────────────────────
        influencers_total = (await db.execute(select(func.count(Influencer.id)))).scalar_one()
        influencers_today = (await db.execute(
            select(func.count(Influencer.id)).where(
                Influencer.created_at >= today_start,
                Influencer.created_at <= today_end,
            )
        )).scalar_one()
        influencers_week = (await db.execute(
            select(func.count(Influencer.id)).where(Influencer.created_at >= week_start)
        )).scalar_one()
        influencers_month = (await db.execute(
            select(func.count(Influencer.id)).where(Influencer.created_at >= month_start)
        )).scalar_one()

        # ── Scrape tasks ───────────────────────────────────────────────────
        scrape_today = (await db.execute(
            select(func.count(ScrapeTask.id)).where(
                ScrapeTask.created_at >= today_start,
                ScrapeTask.created_at <= today_end,
            )
        )).scalar_one()
        scrape_week = (await db.execute(
            select(func.count(ScrapeTask.id)).where(ScrapeTask.created_at >= week_start)
        )).scalar_one()
        scrape_month = (await db.execute(
            select(func.count(ScrapeTask.id)).where(ScrapeTask.created_at >= month_start)
        )).scalar_one()

        # ── Errors (notifications level=error) ────────────────────────────
        errors_today = (await db.execute(
            select(func.count(Notification.id)).where(
                Notification.level == NotificationLevel.urgent,
                Notification.created_at >= today_start,
                Notification.created_at <= today_end,
            )
        )).scalar_one()

        # ── 7-day email trend ──────────────────────────────────────────────
        email_trend = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            ds = _day_start(d)
            de = _day_end(d)
            sent = (await db.execute(
                select(func.count(Email.id)).where(
                    Email.status.in_(sent_statuses),
                    Email.sent_at >= ds,
                    Email.sent_at <= de,
                )
            )).scalar_one()
            replied = (await db.execute(
                select(func.count(Email.id)).where(
                    Email.status == EmailStatus.replied,
                    Email.replied_at >= ds,
                    Email.replied_at <= de,
                )
            )).scalar_one()
            email_trend.append({
                "date": d.strftime("%m/%d"),
                "sent": sent,
                "replied": replied,
            })

        # ── 7-day scrape task trend ────────────────────────────────────────
        scrape_trend = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            ds = _day_start(d)
            de = _day_end(d)
            count = (await db.execute(
                select(func.count(ScrapeTask.id)).where(
                    ScrapeTask.created_at >= ds,
                    ScrapeTask.created_at <= de,
                )
            )).scalar_one()
            scrape_trend.append({"date": d.strftime("%m/%d"), "tasks": count})

        # ── Platform distribution ──────────────────────────────────────────
        rows = (await db.execute(
            select(Influencer.platform, func.count(Influencer.id))
            .group_by(Influencer.platform)
        )).all()
        platform_dist = [{"platform": r[0].value if r[0] else "other", "count": r[1]} for r in rows]

    return {
        "users": {"total": total_users, "active": active_users},
        "emails_sent": {"today": emails_sent_today, "this_week": emails_sent_week, "this_month": emails_sent_month},
        "emails_replied": {"today": emails_replied_today, "this_week": emails_replied_week, "this_month": emails_replied_month},
        "influencers": {"total": influencers_total, "today": influencers_today, "this_week": influencers_week, "this_month": influencers_month},
        "scrape_tasks": {"today": scrape_today, "this_week": scrape_week, "this_month": scrape_month},
        "agent_tasks": {"today": 0},
        "errors": {"today": errors_today},
        "charts": {
            "email_trend": email_trend,
            "scrape_trend": scrape_trend,
            "platform_dist": platform_dist,
        },
    }


@router.get("/health")
async def get_health(current_user: TokenData = Depends(require_admin)) -> dict:
    # DB health
    db_ok = False
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(select(func.now()))
            db_ok = True
    except Exception:
        pass

    # Scheduler
    scheduler_ok = scheduler.running

    # Monitor agent task
    import asyncio
    monitor_ok = False
    for task in asyncio.all_tasks():
        if task.get_name() == "monitor_agent" and not task.done():
            monitor_ok = True
            break

    # WebSocket connections
    ws_count = len(manager.active_connections)

    # Mailbox pool health
    mailbox_status = "red"
    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(Mailbox.status, Mailbox.bounce_rate)
            )).all()
        if rows:
            scores = []
            for status, bounce_rate in rows:
                if status == MailboxStatus.active:
                    score = max(0.0, 100.0 - (bounce_rate or 0.0) * 100.0)
                elif status == MailboxStatus.inactive:
                    score = 30.0
                else:  # error
                    score = 0.0
                scores.append(score)

            if any(s > 70 for s in scores):
                mailbox_status = "green"
            elif any(s > 30 for s in scores):
                mailbox_status = "yellow"
            else:
                mailbox_status = "red"
    except Exception:
        pass

    return {
        "db": {"ok": db_ok, "label": "Database"},
        "scheduler": {"ok": scheduler_ok, "label": "Scheduler"},
        "monitor": {"ok": monitor_ok, "label": "Monitor Agent"},
        "websocket": {"count": ws_count, "label": "WebSocket", "ok": True},
        "mailbox_pool": {"status": mailbox_status, "label": "Mailbox Pool"},
    }


@router.get("/recent-events")
async def get_recent_events(current_user: TokenData = Depends(require_admin)) -> list:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Notification)
            .order_by(Notification.created_at.desc())
            .limit(20)
        )).scalars().all()

    return [
        {
            "id": n.id,
            "title": n.title,
            "content": n.content,
            "level": n.level.value,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat(),
        }
        for n in rows
    ]
