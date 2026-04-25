"""Re-enrich all completed scrape tasks using the current enrich_results
prompt + 4-axis scoring rubric.

Why: tasks #28-#37 ran with the old PremLogin-locked prompt that gave
non-PremLogin industries (Power Bank, Notion, etc.) a flat 0% with reason
"内容与 PremLogin 无关". The 2026-04-25 enrich rewrite scores
industry-internal KOL quality with a 0.05 floor and forbids that phrasing.
This script clears stored scores on every influencer linked to a completed
task and re-runs the new prompt so historical task detail pages match what
the user sees on tasks running under the fix.

Usage:
    cd server
    .venv/Scripts/python scripts/reenrich_completed_tasks.py

Optional flags:
    --task <id>    Re-enrich a single task instead of all
    --dry-run      Print what would happen, don't modify DB
    --only-zero    Only re-enrich influencers whose current score is 0
                   (skips ones that already have a healthy non-zero score)

Cost: each batch of 10 influencers triggers one LLM call. With ~150
historical influencers across all tasks, expect ~15 LLM calls (~$0.01-0.05
on the configured proxy).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make `app.*` importable when run from server/scripts/
_SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVER_ROOT))

from sqlalchemy import select  # noqa: E402

from app.agents.scraper import _enrich_results  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models.influencer import Influencer  # noqa: E402
from app.models.scrape_task import ScrapeTask, ScrapeTaskStatus  # noqa: E402
from app.models.scrape_task_influencer import ScrapeTaskInfluencer  # noqa: E402


async def reenrich_one(task: ScrapeTask, only_zero: bool, dry_run: bool) -> tuple[int, int]:
    """Re-enrich a single task. Returns (influencers_reset, influencers_total)."""
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Influencer)
            .join(ScrapeTaskInfluencer, ScrapeTaskInfluencer.influencer_id == Influencer.id)
            .where(ScrapeTaskInfluencer.scrape_task_id == task.id)
        )
        rows = await db.execute(stmt)
        influencers = list(rows.scalars().all())

        if not influencers:
            return (0, 0)

        # Clear scores so _enrich_results re-runs the full heuristic +
        # LLM pipeline. Without this the function would skip the heuristic
        # phase (because relevance_score is not None), and the LLM-overwrite
        # logic would still fire — but defence-in-depth on negative reason
        # phrasing in the new code path silently keeps the old reason text.
        # Resetting both fields gives a clean slate.
        targets = []
        for inf in influencers:
            if only_zero and inf.relevance_score and inf.relevance_score > 0:
                continue
            targets.append(inf)
            if not dry_run:
                inf.relevance_score = None
                inf.match_reason = None

        if not dry_run:
            await db.commit()

    if dry_run:
        return (len(targets), len(influencers))

    # Now run the new enrich prompt. This re-applies heuristic baseline
    # then upgrades via LLM for every influencer linked to this task.
    await _enrich_results(task.id, task.industry, task.target_market)

    return (len(targets), len(influencers))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=int, help="Re-enrich a single task by ID (default: all completed tasks)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, don't modify DB")
    parser.add_argument("--only-zero", action="store_true", help="Skip influencers with non-zero score (cheaper, partial fix)")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        if args.task is not None:
            r = await db.execute(select(ScrapeTask).where(ScrapeTask.id == args.task))
            tasks = list(r.scalars().all())
        else:
            r = await db.execute(
                select(ScrapeTask)
                .where(ScrapeTask.status == ScrapeTaskStatus.completed)
                .order_by(ScrapeTask.id)
            )
            tasks = list(r.scalars().all())

    if not tasks:
        print("No tasks found.")
        return

    print(f"Re-enriching {len(tasks)} task(s){' (DRY RUN)' if args.dry_run else ''}")
    print(f"Mode: {'only-zero' if args.only_zero else 'all influencers per task'}")
    print()

    total_reset = 0
    total_seen = 0
    for task in tasks:
        try:
            reset, seen = await reenrich_one(task, args.only_zero, args.dry_run)
            total_reset += reset
            total_seen += seen
            print(
                f"  task #{task.id:3d} ({task.industry!r:20s} {task.target_market or '—':>6s}): "
                f"reset {reset}/{seen} influencers"
            )
        except Exception as e:
            print(f"  task #{task.id}: ERROR {type(e).__name__}: {e}")

    print()
    print(f"Done. Total: reset {total_reset}/{total_seen} influencers across {len(tasks)} tasks")
    if args.dry_run:
        print("(dry-run mode — no DB changes were made)")


if __name__ == "__main__":
    asyncio.run(main())
