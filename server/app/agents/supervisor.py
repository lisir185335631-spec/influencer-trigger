"""
Supervisor — tracked entry points for all Executor Agents.

Each function wraps an agent call with track_agent_run so every execution
is persisted to the agent_runs table. The 5 Executor Agent files are
untouched; only this file coordinates their invocation.
"""
import logging
from typing import Any

from app.agents._tracking import track_agent_run

logger = logging.getLogger(__name__)


async def run_scraper_with_tracking(task_id: int) -> None:
    from app.agents.scraper import run_scraper_agent
    async with track_agent_run(
        "scraper",
        f"task:{task_id}",
        {"task_id": task_id},
    ):
        await run_scraper_agent(task_id)


async def run_sender_with_tracking(
    campaign_id: int,
    influencer_ids: list[int],
    template_id: int,
) -> None:
    from app.agents.sender import run_sender_agent
    async with track_agent_run(
        "sender",
        f"campaign:{campaign_id}",
        {
            "campaign_id": campaign_id,
            "influencer_ids": influencer_ids[:100],  # cap to avoid huge snapshot
            "template_id": template_id,
        },
    ):
        await run_sender_agent(campaign_id, influencer_ids, template_id)


async def run_monitor_with_tracking() -> None:
    """Long-running monitor task — tracked as a single run for its entire lifetime."""
    from app.agents.monitor import run_monitor_agent
    async with track_agent_run("monitor", "lifespan", {}):
        await run_monitor_agent()


async def run_holiday_with_tracking() -> None:
    """Tracked holiday greeting check called by APScheduler."""
    from app.services.holiday_service import holiday_greeting_check
    async with track_agent_run("holiday", "scheduled", {}):
        await holiday_greeting_check()
