import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.database import AsyncSessionLocal, create_tables
from app.limiter import limiter
from app.scheduler import scheduler
from app.websocket.manager import manager
from app.api.health import router as health_router
# noqa: F401 — import models so create_all sees them
import app.models.scrape_task_influencer  # noqa: F401
import app.models.system_settings  # noqa: F401
from app.api.auth import router as auth_router
from app.api.mailboxes import router as mailboxes_router
from app.api.templates import router as templates_router
from app.api.scrape import router as scrape_router
from app.api.import_ import router as import_router
from app.api.emails import router as emails_router
from app.api.notifications import router as notifications_router
from app.api.influencers import router as influencers_router
from app.api.follow_up import router as follow_up_router
from app.api.holidays import router as holidays_router
from app.api.dashboard import router as dashboard_router
from app.api.users import router as users_router
from app.api.settings import router as settings_router
from app.api.admin.overview import router as admin_overview_router
from app.api.admin.users_admin import router as admin_users_router
from app.api.admin.audit import router as admin_audit_router
from app.api.admin.emails_admin import router as admin_emails_router
from app.api.admin.mailboxes_admin import router as admin_mailboxes_router
from app.middleware.audit_middleware import AuditMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()


async def _reset_today_sent_job() -> None:
    """APScheduler job: reset today_sent / this_hour_sent at 00:00 UTC."""
    from app.services.mailbox_service import reset_today_sent
    async with AsyncSessionLocal() as db:
        count = await reset_today_sent(db)
        logger.info("Daily reset: cleared today_sent for %d mailboxes", count)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting up Influencer Trigger service...")
    await create_tables()
    logger.info("Database tables created/verified.")

    # Migrate: add new columns to existing tables (SQLite)
    from sqlalchemy import text as sa_text
    async with AsyncSessionLocal() as _mig_db:
        for stmt in [
            "ALTER TABLE scrape_tasks ADD COLUMN target_market VARCHAR(64)",
            "ALTER TABLE scrape_tasks ADD COLUMN search_keywords TEXT",
            "ALTER TABLE scrape_tasks ADD COLUMN competitor_brands VARCHAR(256)",
            "ALTER TABLE influencers ADD COLUMN relevance_score FLOAT",
            "ALTER TABLE influencers ADD COLUMN match_reason TEXT",
            "ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0",
        ]:
            try:
                await _mig_db.execute(sa_text(stmt))
                await _mig_db.commit()
            except Exception:
                await _mig_db.rollback()

    scheduler.add_job(
        _reset_today_sent_job,
        CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="reset_today_sent",
        replace_existing=True,
    )

    # Load follow-up settings and schedule monthly follow-up job
    from app.services.follow_up_service import get_or_create_settings, monthly_follow_up_check
    async with AsyncSessionLocal() as db:
        fu_settings = await get_or_create_settings(db)

    scheduler.add_job(
        monthly_follow_up_check,
        CronTrigger(hour=fu_settings.hour_utc, minute=0, timezone="UTC"),
        id="monthly_follow_up",
        replace_existing=True,
    )
    logger.info("Follow-up scheduler job registered at %02d:00 UTC", fu_settings.hour_utc)

    # Seed default holidays and schedule daily holiday greeting job
    from app.services.holiday_service import seed_default_holidays, holiday_greeting_check
    async with AsyncSessionLocal() as db:
        await seed_default_holidays(db)

    scheduler.add_job(
        holiday_greeting_check,
        CronTrigger(hour=8, minute=0, timezone="UTC"),
        id="holiday_greeting",
        replace_existing=True,
    )
    logger.info("Holiday greeting scheduler job registered at 08:00 UTC")

    scheduler.start()
    logger.info("Scheduler started.")

    # Start IMAP monitor background task
    from app.agents.monitor import run_monitor_agent
    monitor_task: asyncio.Task = asyncio.create_task(
        run_monitor_agent(), name="monitor_agent"
    )
    logger.info("Monitor Agent background task started.")

    yield

    # Cancel monitor task on shutdown
    monitor_task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(monitor_task), timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    logger.info("Monitor Agent stopped.")

    scheduler.shutdown(wait=False)
    logger.info("Shutting down Influencer Trigger service...")


app = FastAPI(
    title="Influencer Trigger API",
    description="国外社交媒体网红自动触发系统",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

# Register routers
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(mailboxes_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(scrape_router, prefix="/api")
app.include_router(import_router, prefix="/api")
app.include_router(emails_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(influencers_router, prefix="/api")
app.include_router(follow_up_router, prefix="/api")
app.include_router(holidays_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(admin_overview_router, prefix="/api/admin")
app.include_router(admin_users_router, prefix="/api/admin")
app.include_router(admin_audit_router, prefix="/api/admin")
app.include_router(admin_emails_router, prefix="/api/admin")
app.include_router(admin_mailboxes_router, prefix="/api/admin")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.send_personal(websocket, "pong", {"echo": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
