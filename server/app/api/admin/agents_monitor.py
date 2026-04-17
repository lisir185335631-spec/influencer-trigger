import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.agent_run import AgentRun
from app.schemas.auth import TokenData

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["admin-agents"])

ALL_AGENTS = ["scraper", "sender", "monitor", "classifier", "responder", "holiday"]
RECENT_WINDOW = 50  # last N runs for stats


@router.get("/status")
async def get_agents_status(_: TokenData = Depends(require_admin)) -> dict:
    """Return summary stats for each of the 6 agents."""
    result = {}
    async with AsyncSessionLocal() as db:
        for agent_name in ALL_AGENTS:
            # Recent N runs for rate/duration stats
            rows = (
                await db.execute(
                    select(AgentRun)
                    .where(AgentRun.agent_name == agent_name)
                    .order_by(AgentRun.started_at.desc())
                    .limit(RECENT_WINDOW)
                )
            ).scalars().all()

            running_count = (
                await db.execute(
                    select(func.count()).where(
                        AgentRun.agent_name == agent_name,
                        AgentRun.state == "running",
                    )
                )
            ).scalar() or 0

            total = len(rows)
            success = sum(1 for r in rows if r.state == "success")
            success_rate = round(success / total, 3) if total else None
            durations = [r.duration_ms for r in rows if r.duration_ms is not None]
            avg_duration_ms = round(sum(durations) / len(durations)) if durations else None
            last_run = rows[0].started_at.isoformat() if rows else None

            result[agent_name] = {
                "agent_name": agent_name,
                "running_count": running_count,
                "recent_total": total,
                "recent_success": success,
                "success_rate": success_rate,
                "avg_duration_ms": avg_duration_ms,
                "last_run_at": last_run,
            }
    return {"agents": result}


@router.get("/runs")
async def list_runs(
    agent: Optional[str] = None,
    state: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    _: TokenData = Depends(require_admin),
) -> dict:
    """List agent run history with optional filters."""
    page_size = min(page_size, 100)
    offset = (page - 1) * page_size

    async with AsyncSessionLocal() as db:
        q = select(AgentRun)
        if agent:
            q = q.where(AgentRun.agent_name == agent)
        if state:
            q = q.where(AgentRun.state == state)
        if from_date:
            try:
                q = q.where(AgentRun.started_at >= datetime.fromisoformat(from_date))
            except ValueError:
                pass
        if to_date:
            try:
                q = q.where(AgentRun.started_at <= datetime.fromisoformat(to_date))
            except ValueError:
                pass

        total_q = select(func.count()).select_from(q.subquery())
        total = (await db.execute(total_q)).scalar() or 0

        runs = (
            await db.execute(q.order_by(AgentRun.started_at.desc()).offset(offset).limit(page_size))
        ).scalars().all()

        items = [_serialize_run(r, brief=True) for r in runs]

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/runs/{run_id}")
async def get_run(run_id: int, _: TokenData = Depends(require_admin)) -> dict:
    """Get full detail of a single agent run including input/output/error."""
    async with AsyncSessionLocal() as db:
        run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _serialize_run(run, brief=False)


@router.post("/runs/{run_id}/retry")
async def retry_run(
    run_id: int,
    background_tasks: BackgroundTasks,
    _: TokenData = Depends(require_admin),
) -> dict:
    """Manually retry a failed agent run using its stored input_snapshot."""
    async with AsyncSessionLocal() as db:
        run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.state not in ("failed", "success"):
        raise HTTPException(status_code=409, detail="Only failed or completed runs can be retried")

    try:
        input_data: dict = json.loads(run.input_snapshot or "{}")
    except Exception:
        input_data = {}

    agent = run.agent_name
    if agent == "scraper":
        task_id = input_data.get("task_id")
        if not task_id:
            raise HTTPException(status_code=400, detail="Missing task_id in input snapshot")
        from app.agents.supervisor import run_scraper_with_tracking
        background_tasks.add_task(run_scraper_with_tracking, int(task_id))
    elif agent == "sender":
        campaign_id = input_data.get("campaign_id")
        influencer_ids = input_data.get("influencer_ids", [])
        template_id = input_data.get("template_id")
        if not campaign_id or not template_id:
            raise HTTPException(status_code=400, detail="Missing required fields in input snapshot")
        from app.agents.supervisor import run_sender_with_tracking
        background_tasks.add_task(run_sender_with_tracking, int(campaign_id), influencer_ids, int(template_id))
    elif agent == "holiday":
        from app.agents.supervisor import run_holiday_with_tracking
        background_tasks.add_task(run_holiday_with_tracking)
    else:
        raise HTTPException(status_code=400, detail=f"Retry not supported for agent: {agent}")

    return {"ok": True, "agent": agent, "retried_from": run_id}


def _serialize_run(run: AgentRun, brief: bool) -> dict:
    d: dict = {
        "id": run.id,
        "agent_name": run.agent_name,
        "task_id": run.task_id,
        "state": run.state,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "error_message": run.error_message if not brief else (run.error_message[:120] if run.error_message else None),
    }
    if not brief:
        d["input_snapshot"] = run.input_snapshot
        d["output_snapshot"] = run.output_snapshot
        d["error_stack"] = run.error_stack
        d["token_cost_usd"] = run.token_cost_usd
        d["llm_calls_count"] = run.llm_calls_count
    return d
