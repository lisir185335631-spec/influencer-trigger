import asyncio
import sys

# Windows requires ProactorEventLoop for asyncio subprocess support;
# Playwright launches Chromium via `asyncio.create_subprocess_exec` and
# fails with `NotImplementedError` on the Selector loop. uvicorn's
# `--reload` mode picks Selector by default on Windows (uvicorn ≤ 0.30
# behaviour) — task #66 2026-04-25 was killed at Playwright launch with
# that exact stack. Setting the policy *before* uvicorn boots its loop
# (i.e. at module import time, which runs before lifespan) guarantees
# every subsequent `asyncio.new_event_loop()` returns a Proactor
# instance. No-op on non-Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

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
from app.api.image_proxy import router as image_proxy_router
from app.api.track import router as track_router
from app.api.webhook_logs import router as webhook_logs_router
# noqa: F401 — import models so create_all sees them
import app.models.scrape_task_influencer  # noqa: F401
import app.models.system_settings  # noqa: F401
import app.models.platform_quota  # noqa: F401
import app.models.compliance_keywords  # noqa: F401
import app.models.agent_run  # noqa: F401
import app.models.usage_metric  # noqa: F401
import app.models.usage_budget  # noqa: F401
import app.models.feature_flag  # noqa: F401
import app.models.security_alert  # noqa: F401
import app.models.webhook_push_log  # noqa: F401
from app.api.auth import router as auth_router
from app.api.mailboxes import router as mailboxes_router
from app.api.templates import router as templates_router
from app.api.scrape import router as scrape_router
from app.api.import_ import router as import_router
from app.api.emails import router as emails_router
from app.api.drafts import router as drafts_router
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
from app.api.admin.influencers_admin import router as admin_influencers_router
from app.api.admin.scrape_admin import router as admin_scrape_router
from app.api.admin.templates_admin import router as admin_templates_router
from app.api.admin.agents_monitor import router as admin_agents_router
from app.api.admin.usage import router as admin_usage_router
from app.api.admin.followup_admin import router as admin_followup_router
from app.api.admin.holidays_admin import router as admin_holidays_router
from app.api.admin.settings_admin import router as admin_settings_router
from app.api.admin.security import router as admin_security_router
from app.api.admin.diagnostics import router as admin_diagnostics_router
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


async def _reset_this_hour_sent_job() -> None:
    """APScheduler job: reset this_hour_sent at minute=0 of every hour."""
    from app.services.mailbox_service import reset_this_hour_sent
    async with AsyncSessionLocal() as db:
        count = await reset_this_hour_sent(db)
        logger.info("Hourly reset: cleared this_hour_sent for %d mailboxes", count)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting up Influencer Trigger service...")
    await create_tables()
    logger.info("Database tables created/verified.")

    # Schema changes are managed by Alembic migrations.
    # To add a column:  cd server && alembic revision --autogenerate -m "desc"
    #                   cd server && alembic upgrade head
    # See server/alembic/README.md

    # Zombie ScrapeTask cleanup. When uvicorn is killed mid-task (Ctrl+C,
    # crash, OS reboot), any task that was running at the time stays
    # status='running' in DB forever — there's no agent left to update it.
    # The UI then shows the task as "still running" with no progress.
    # On every startup we promote any orphaned 'running' task to 'failed'
    # with a clear error_message so the UI recovers automatically.
    from datetime import datetime, timezone
    from sqlalchemy import update, select
    from app.models.scrape_task import ScrapeTask, ScrapeTaskStatus
    async with AsyncSessionLocal() as db:
        try:
            count_stmt = select(ScrapeTask.id).where(ScrapeTask.status == ScrapeTaskStatus.running)
            result = await db.execute(count_stmt)
            zombie_ids = [r[0] for r in result.all()]
            if zombie_ids:
                stmt = (
                    update(ScrapeTask)
                    .where(ScrapeTask.status == ScrapeTaskStatus.running)
                    .values(
                        status=ScrapeTaskStatus.failed,
                        error_message="服务重启中断，请重新发起任务",
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await db.execute(stmt)
                await db.commit()
                logger.warning(
                    "Startup cleanup: marked %d zombie running task(s) as failed: %s",
                    len(zombie_ids), zombie_ids,
                )
        except Exception as e:
            logger.warning("Zombie cleanup failed (non-fatal): %s", e)

        # Same recovery for orphaned EmailDraft rows. If uvicorn was killed
        # while the Sender Agent was mid-flight on a draft, the draft is
        # left at status='sending' / 'generating' with no agent to clear it.
        # Without this, the user can neither resend nor regenerate that
        # row (both refuse those statuses). Demote orphans back to a
        # reviewable / regeneratable state.
        from app.models.email_draft import EmailDraft, EmailDraftStatus
        try:
            draft_stmt = (
                update(EmailDraft)
                .where(EmailDraft.status == EmailDraftStatus.sending)
                .values(
                    status=EmailDraftStatus.ready,
                    error_message="服务重启中断；草稿已重置为可发送状态",
                )
            )
            res = await db.execute(draft_stmt)
            if res.rowcount:
                logger.warning(
                    "Startup cleanup: reset %d zombie 'sending' draft(s) → ready",
                    res.rowcount,
                )
            draft_gen_stmt = (
                update(EmailDraft)
                .where(EmailDraft.status == EmailDraftStatus.generating)
                .values(
                    status=EmailDraftStatus.failed,
                    error_message="服务重启中断；请重新生成此草稿",
                )
            )
            res = await db.execute(draft_gen_stmt)
            if res.rowcount:
                logger.warning(
                    "Startup cleanup: marked %d zombie 'generating' draft(s) → failed",
                    res.rowcount,
                )
            await db.commit()
        except Exception as e:
            logger.warning("Draft zombie cleanup failed (non-fatal): %s", e)

    scheduler.add_job(
        _reset_today_sent_job,
        CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="reset_today_sent",
        replace_existing=True,
    )

    scheduler.add_job(
        _reset_this_hour_sent_job,
        CronTrigger(minute=0, timezone="UTC"),
        id="reset_this_hour_sent",
        replace_existing=True,
    )
    logger.info("Hourly reset job registered (minute=0 every hour UTC)")

    # Load follow-up settings and schedule monthly follow-up job
    from app.services.follow_up_service import get_or_create_settings, daily_follow_up_check
    async with AsyncSessionLocal() as db:
        fu_settings = await get_or_create_settings(db)

    scheduler.add_job(
        daily_follow_up_check,
        CronTrigger(hour=fu_settings.hour_utc, minute=0, timezone="UTC"),
        id="daily_follow_up",
        replace_existing=True,
    )
    logger.info("Follow-up scheduler job registered at %02d:00 UTC", fu_settings.hour_utc)

    # Seed default holidays and schedule daily holiday greeting job
    from app.services.holiday_service import seed_default_holidays, holiday_greeting_check
    async with AsyncSessionLocal() as db:
        await seed_default_holidays(db)

    from app.agents.supervisor import run_holiday_with_tracking
    scheduler.add_job(
        run_holiday_with_tracking,
        CronTrigger(hour=8, minute=0, timezone="UTC"),
        id="holiday_greeting",
        replace_existing=True,
    )
    logger.info("Holiday greeting scheduler job registered at 08:00 UTC")

    scheduler.start()
    logger.info("Scheduler started.")

    # Start IMAP monitor background task (wrapped with tracking)
    from app.agents.supervisor import run_monitor_with_tracking
    monitor_task: asyncio.Task = asyncio.create_task(
        run_monitor_with_tracking(), name="monitor_agent"
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
app.include_router(image_proxy_router, prefix="/api")
app.include_router(track_router, prefix="/api")
app.include_router(webhook_logs_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(mailboxes_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(scrape_router, prefix="/api")
app.include_router(import_router, prefix="/api")
app.include_router(emails_router, prefix="/api")
app.include_router(drafts_router, prefix="/api")
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
app.include_router(admin_influencers_router, prefix="/api/admin")
app.include_router(admin_scrape_router, prefix="/api/admin")
app.include_router(admin_templates_router, prefix="/api/admin")
app.include_router(admin_agents_router, prefix="/api/admin")
app.include_router(admin_usage_router, prefix="/api/admin")
app.include_router(admin_followup_router, prefix="/api/admin")
app.include_router(admin_holidays_router, prefix="/api/admin")
app.include_router(admin_settings_router, prefix="/api/admin")
app.include_router(admin_security_router, prefix="/api/admin")
app.include_router(admin_diagnostics_router, prefix="/api/admin")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.send_personal(websocket, "pong", {"echo": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
