import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import AsyncSessionLocal, create_tables
from app.websocket.manager import manager
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.mailboxes import router as mailboxes_router
from app.api.templates import router as templates_router
from app.api.scrape import router as scrape_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
scheduler = AsyncIOScheduler()


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

    scheduler.add_job(
        _reset_today_sent_job,
        CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="reset_today_sent",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started.")

    yield

    scheduler.shutdown(wait=False)
    logger.info("Shutting down Influencer Trigger service...")


app = FastAPI(
    title="Influencer Trigger API",
    description="国外社交媒体网红自动触发系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(mailboxes_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(scrape_router, prefix="/api")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.send_personal(websocket, "pong", {"echo": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
