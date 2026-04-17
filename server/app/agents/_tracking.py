"""
Agent run tracking — async context manager that persists AgentRun records.
"""
import json
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from app.database import AsyncSessionLocal
from app.models.agent_run import AgentRun

logger = logging.getLogger(__name__)


@asynccontextmanager
async def track_agent_run(
    agent_name: str,
    task_id: str,
    input_data: dict[str, Any],
) -> AsyncGenerator[None, None]:
    """
    Async context manager: creates an AgentRun row (state=running) on enter,
    updates to success/failed on exit. Exceptions are re-raised transparently.
    """
    started_at = datetime.now(timezone.utc)
    run_id: int | None = None

    try:
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                agent_name=agent_name,
                task_id=task_id,
                state="running",
                input_snapshot=json.dumps(input_data, default=str)[:4096],
                started_at=started_at,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id
    except Exception:
        logger.exception("track_agent_run: failed to create run record for %s", agent_name)

    try:
        yield
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        if run_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    run = await db.get(AgentRun, run_id)
                    if run:
                        run.state = "failed"
                        run.finished_at = finished_at
                        run.duration_ms = duration_ms
                        run.error_message = str(exc)[:1024]
                        run.error_stack = traceback.format_exc()[:4096]
                        await db.commit()
            except Exception:
                logger.exception("track_agent_run: failed to save failure for run_id=%s", run_id)
        raise
    else:
        finished_at = datetime.now(timezone.utc)
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        if run_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    run = await db.get(AgentRun, run_id)
                    if run:
                        run.state = "success"
                        run.finished_at = finished_at
                        run.duration_ms = duration_ms
                        await db.commit()
            except Exception:
                logger.exception("track_agent_run: failed to save success for run_id=%s", run_id)
