from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, select
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
    tomorrow_start = _day_start(today + timedelta(days=1))
    trend_start = _day_start(today - timedelta(days=6))

    sent_statuses = [EmailStatus.sent, EmailStatus.delivered, EmailStatus.opened, EmailStatus.replied]

    async with AsyncSessionLocal() as db:
        # ── Query 1: Users (total + active in one shot) ────────────────────
        user_row = (await db.execute(
            select(
                func.count(User.id).label("total"),
                func.sum(case((User.is_active == True, 1), else_=0)).label("active"),  # noqa: E712
            )
        )).one()
        total_users = user_row.total or 0
        active_users = user_row.active or 0

        # ── Query 2: Emails — 6 metrics in one shot ────────────────────────
        # Half-open windows [start, next_start) avoid max-time precision edge cases.
        email_row = (await db.execute(
            select(
                func.sum(case(
                    (and_(Email.status.in_(sent_statuses),
                           Email.sent_at >= today_start,
                           Email.sent_at < tomorrow_start), 1),
                    else_=0
                )).label("sent_today"),
                func.sum(case(
                    (and_(Email.status.in_(sent_statuses),
                           Email.sent_at >= week_start), 1),
                    else_=0
                )).label("sent_week"),
                func.sum(case(
                    (and_(Email.status.in_(sent_statuses),
                           Email.sent_at >= month_start), 1),
                    else_=0
                )).label("sent_month"),
                func.sum(case(
                    (and_(Email.status == EmailStatus.replied,
                           Email.replied_at >= today_start,
                           Email.replied_at < tomorrow_start), 1),
                    else_=0
                )).label("replied_today"),
                func.sum(case(
                    (and_(Email.status == EmailStatus.replied,
                           Email.replied_at >= week_start), 1),
                    else_=0
                )).label("replied_week"),
                func.sum(case(
                    (and_(Email.status == EmailStatus.replied,
                           Email.replied_at >= month_start), 1),
                    else_=0
                )).label("replied_month"),
            )
        )).one()
        emails_sent_today = email_row.sent_today or 0
        emails_sent_week = email_row.sent_week or 0
        emails_sent_month = email_row.sent_month or 0
        emails_replied_today = email_row.replied_today or 0
        emails_replied_week = email_row.replied_week or 0
        emails_replied_month = email_row.replied_month or 0

        # ── Query 3: Influencers — 4 metrics in one shot ───────────────────
        inf_row = (await db.execute(
            select(
                func.count(Influencer.id).label("total"),
                func.sum(case(
                    (and_(Influencer.created_at >= today_start,
                           Influencer.created_at < tomorrow_start), 1),
                    else_=0
                )).label("today"),
                func.sum(case(
                    (Influencer.created_at >= week_start, 1),
                    else_=0
                )).label("this_week"),
                func.sum(case(
                    (Influencer.created_at >= month_start, 1),
                    else_=0
                )).label("this_month"),
            )
        )).one()
        influencers_total = inf_row.total or 0
        influencers_today = inf_row.today or 0
        influencers_week = inf_row.this_week or 0
        influencers_month = inf_row.this_month or 0

        # ── Query 4: ScrapeTasks — 3 metrics in one shot ───────────────────
        scrape_row = (await db.execute(
            select(
                func.sum(case(
                    (and_(ScrapeTask.created_at >= today_start,
                           ScrapeTask.created_at < tomorrow_start), 1),
                    else_=0
                )).label("today"),
                func.sum(case(
                    (ScrapeTask.created_at >= week_start, 1),
                    else_=0
                )).label("this_week"),
                func.sum(case(
                    (ScrapeTask.created_at >= month_start, 1),
                    else_=0
                )).label("this_month"),
            )
        )).one()
        scrape_today = scrape_row.today or 0
        scrape_week = scrape_row.this_week or 0
        scrape_month = scrape_row.this_month or 0

        # ── Query 5: Errors (notifications level=urgent) ───────────────────
        errors_today = (await db.execute(
            select(func.count(Notification.id)).where(
                Notification.level == NotificationLevel.urgent,
                Notification.created_at >= today_start,
                Notification.created_at < tomorrow_start,
            )
        )).scalar_one()

        # ── Query 6a: email_trend sent — GROUP BY sent_at date ─────────────
        # Note: func.date(col) returns 'YYYY-MM-DD' string on SQLite; we avoid
        # cast(col, Date) because SQLAlchemy's Date type-converter passes a
        # datetime (not str) to fromisoformat via aiosqlite, which crashes.
        sent_date = func.date(Email.sent_at)
        sent_trend_rows = (await db.execute(
            select(
                sent_date.label("d"),
                func.count(Email.id).label("sent"),
            )
            .where(
                Email.status.in_(sent_statuses),
                Email.sent_at >= trend_start,
                Email.sent_at < tomorrow_start,
            )
            .group_by(sent_date)
        )).all()

        # ── Query 6b: email_trend replied — GROUP BY replied_at date ───────
        replied_date = func.date(Email.replied_at)
        replied_trend_rows = (await db.execute(
            select(
                replied_date.label("d"),
                func.count(Email.id).label("replied"),
            )
            .where(
                Email.status == EmailStatus.replied,
                Email.replied_at >= trend_start,
                Email.replied_at < tomorrow_start,
            )
            .group_by(replied_date)
        )).all()

        # Keys are 'YYYY-MM-DD' strings; Python-side date lookup uses isoformat.
        sent_map = {r.d: r.sent for r in sent_trend_rows}
        replied_map = {r.d: r.replied for r in replied_trend_rows}
        email_trend = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            d_iso = d.isoformat()
            email_trend.append({
                "date": d.strftime("%m/%d"),
                "sent": sent_map.get(d_iso, 0),
                "replied": replied_map.get(d_iso, 0),
            })

        # ── Query 7: scrape_trend 7 days — GROUP BY created_at date ───────
        scrape_date = func.date(ScrapeTask.created_at)
        scrape_trend_rows = (await db.execute(
            select(
                scrape_date.label("d"),
                func.count(ScrapeTask.id).label("tasks"),
            )
            .where(
                ScrapeTask.created_at >= trend_start,
                ScrapeTask.created_at < tomorrow_start,
            )
            .group_by(scrape_date)
        )).all()

        scrape_by_date = {r.d: r.tasks for r in scrape_trend_rows}
        scrape_trend = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            scrape_trend.append({"date": d.strftime("%m/%d"), "tasks": scrape_by_date.get(d.isoformat(), 0)})

        # ── Query 8: Platform distribution ────────────────────────────────
        platform_rows = (await db.execute(
            select(Influencer.platform, func.count(Influencer.id))
            .group_by(Influencer.platform)
        )).all()
        platform_dist = [{"platform": r[0].value if r[0] else "other", "count": r[1]} for r in platform_rows]

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
