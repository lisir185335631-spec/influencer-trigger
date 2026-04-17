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
import app.models.platform_quota  # noqa: F401
import app.models.compliance_keywords  # noqa: F401
import app.models.agent_run  # noqa: F401
import app.models.usage_metric  # noqa: F401
import app.models.usage_budget  # noqa: F401
import app.models.feature_flag  # noqa: F401
import app.models.security_alert  # noqa: F401
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
            "ALTER TABLE templates ADD COLUMN is_published BOOLEAN DEFAULT 1 NOT NULL",
            "ALTER TABLE templates ADD COLUMN compliance_flags VARCHAR(1024) DEFAULT '' NOT NULL",
            "CREATE TABLE IF NOT EXISTS agent_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_name VARCHAR(64) NOT NULL, task_id VARCHAR(128), state VARCHAR(16) NOT NULL DEFAULT 'pending', input_snapshot TEXT, output_snapshot TEXT, error_message TEXT, error_stack TEXT, started_at DATETIME, finished_at DATETIME, duration_ms INTEGER, token_cost_usd REAL, llm_calls_count INTEGER DEFAULT 0)",
            "CREATE INDEX IF NOT EXISTS ix_agent_runs_agent_started ON agent_runs (agent_name, started_at)",
            "CREATE INDEX IF NOT EXISTS ix_agent_runs_state_started ON agent_runs (state, started_at)",
            "CREATE TABLE IF NOT EXISTS usage_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, metric_date DATE NOT NULL, metric_type VARCHAR(32) NOT NULL, sub_key VARCHAR(128), value REAL NOT NULL DEFAULT 0, cost_usd REAL, created_at DATETIME, CONSTRAINT ix_usage_metric_date_type_key UNIQUE (metric_date, metric_type, sub_key))",
            "CREATE TABLE IF NOT EXISTS usage_budgets (id INTEGER PRIMARY KEY AUTOINCREMENT, month VARCHAR(7) NOT NULL UNIQUE, budget_usd REAL NOT NULL DEFAULT 0, alert_threshold_pct REAL NOT NULL DEFAULT 80, created_at DATETIME)",
            "ALTER TABLE holidays ADD COLUMN sensitive_regions VARCHAR(512) DEFAULT '' NOT NULL",
            "ALTER TABLE system_settings ADD COLUMN webhook_default_url VARCHAR(512) DEFAULT '' NOT NULL",
            "ALTER TABLE system_settings ADD COLUMN default_daily_quota INTEGER DEFAULT 100 NOT NULL",
            "CREATE TABLE IF NOT EXISTS feature_flags (id INTEGER PRIMARY KEY AUTOINCREMENT, flag_key VARCHAR(128) NOT NULL UNIQUE, enabled BOOLEAN NOT NULL DEFAULT 0, description VARCHAR(512) NOT NULL DEFAULT '', rollout_percentage INTEGER NOT NULL DEFAULT 100, target_roles VARCHAR(256) NOT NULL DEFAULT '', updated_by_user_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_feature_flags_key ON feature_flags (flag_key)",
            "CREATE TABLE IF NOT EXISTS security_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, alert_type VARCHAR(64) NOT NULL, user_id INTEGER, details_json TEXT, acknowledged BOOLEAN NOT NULL DEFAULT 0, acknowledged_by INTEGER, acknowledged_at DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
            "CREATE INDEX IF NOT EXISTS ix_security_alerts_user_id ON security_alerts (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_security_alerts_created_at ON security_alerts (created_at)",
            "CREATE TABLE IF NOT EXISTS key_rotation_history (id INTEGER PRIMARY KEY AUTOINCREMENT, rotated_by_user_id INTEGER NOT NULL, rotated_by_username VARCHAR(128) NOT NULL, note VARCHAR(512), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
            "CREATE INDEX IF NOT EXISTS ix_key_rotation_created_at ON key_rotation_history (created_at)",
            "ALTER TABLE system_settings ADD COLUMN security_config TEXT",
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
