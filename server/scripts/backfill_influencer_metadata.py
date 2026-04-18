"""
Backfill Influencer metadata (followers / bio / avatar_url) for existing DB rows.

Re-visits each influencer's profile_url with Playwright and extracts the three
metadata fields from og:description / og:image meta tags. Only fills NULL
fields by default (use --force to overwrite).

Usage:
    cd server
    .venv/Scripts/python scripts/backfill_influencer_metadata.py --all
    .venv/Scripts/python scripts/backfill_influencer_metadata.py --task-id 3
    .venv/Scripts/python scripts/backfill_influencer_metadata.py --platform youtube --limit 10
    .venv/Scripts/python scripts/backfill_influencer_metadata.py --dry-run
"""
import argparse
import asyncio
import html as html_module
import logging
import random
import re
import sys
from pathlib import Path

# Make sibling packages importable when run from server/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from sqlalchemy import select, update, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.influencer import Influencer, InfluencerPlatform
from app.models.scrape_task_influencer import ScrapeTaskInfluencer
# Reuse the exact same parser already used in scraper.py for consistency
from app.agents.scraper import _parse_subscriber_count

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Suppress SQLAlchemy's verbose SQL echo on Windows GBK terminals — the engine
# is configured with echo=settings.debug which may be True; silence it here so
# bio text containing emojis doesn't crash the terminal stream handler.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def _extract_metadata_from_html(html: str) -> dict:
    """Extract bio, followers, avatar_url from page HTML via og: meta tags."""
    out: dict = {"bio": None, "followers": None, "avatar_url": None}

    # og:description -> bio + embedded follower count
    try:
        m = re.search(
            r'<meta\s+(?:property|name)="(?:og:description|description)"\s+content="([^"]*)"',
            html,
        )
        if m and m.group(1):
            desc = html_module.unescape(m.group(1))
            out["bio"] = desc[:2000]
            # YouTube: "1.2M subscribers", Instagram: "1,234 Followers"
            fm = re.search(
                r'([\d.,]+\s*[KMB]?)\s*(?:subscribers?|Followers?)',
                desc,
                re.IGNORECASE,
            )
            if not fm:
                # Fall back to scanning the full page body
                fm = re.search(
                    r'([\d.,]+\s*[KMB]?)\s*(?:subscribers?|Followers?)',
                    html,
                    re.IGNORECASE,
                )
            if fm:
                out["followers"] = _parse_subscriber_count(fm.group(1))
    except Exception:
        pass

    # og:image -> avatar_url
    try:
        m = re.search(
            r'<meta\s+(?:property|name)="og:image"\s+content="([^"]+)"',
            html,
        )
        if m and m.group(1):
            out["avatar_url"] = m.group(1)[:512]
    except Exception:
        pass

    return out


async def _fetch_one(page, url: str) -> dict:
    """Navigate to profile URL, wait for DOM, then extract metadata from HTML."""
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    # Small pause to let any SSR hydration settle
    await asyncio.sleep(2)
    html = await page.content()
    return _extract_metadata_from_html(html)


async def _query_candidates(args: argparse.Namespace) -> list[Influencer]:
    """Query the DB for influencers that need backfilling."""
    async with AsyncSessionLocal() as db:
        stmt = select(Influencer).where(Influencer.profile_url.isnot(None))

        if not args.force:
            stmt = stmt.where(
                or_(
                    Influencer.followers.is_(None),
                    Influencer.bio.is_(None),
                    Influencer.avatar_url.is_(None),
                )
            )

        if args.platform:
            try:
                plat_enum = InfluencerPlatform(args.platform)
                stmt = stmt.where(Influencer.platform == plat_enum)
            except ValueError:
                logger.error("Unknown platform: %s", args.platform)
                sys.exit(2)

        if args.task_id is not None:
            sub = select(ScrapeTaskInfluencer.influencer_id).where(
                ScrapeTaskInfluencer.scrape_task_id == args.task_id
            )
            stmt = stmt.where(Influencer.id.in_(sub))

        stmt = stmt.limit(args.limit)
        rows = (await db.execute(stmt)).scalars().all()
        return list(rows)


async def main(args: argparse.Namespace) -> int:
    rows = await _query_candidates(args)
    total = len(rows)

    logger.info(
        "Found %d candidate(s) to process  (limit=%d  force=%s  dry-run=%s)",
        total, args.limit, args.force, args.dry_run,
    )
    if total == 0:
        logger.info("Nothing to do.")
        return 0

    stats = {"processed": 0, "updated": 0, "skipped": 0, "failed": 0}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=args.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(
            user_agent=random.choice(_USER_AGENTS),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = await ctx.new_page()
        await stealth_async(page)

        for i, inf in enumerate(rows, 1):
            stats["processed"] += 1
            platform_label = inf.platform.value if inf.platform else "-"

            try:
                meta = await _fetch_one(page, inf.profile_url)
            except Exception as exc:
                logger.info(
                    "[%d/%d] id=%d (%s) -> %s\n       FAILED: %s",
                    i, total, inf.id, platform_label, inf.profile_url, exc,
                )
                stats["failed"] += 1
                if i < total:
                    await asyncio.sleep(random.uniform(args.delay_min, args.delay_max))
                continue

            # Build update dict, respecting --force and NULL-only rules
            updates: dict = {}
            parts: list[str] = []

            for field in ("bio", "followers", "avatar_url"):
                new_val = meta[field]
                existing = getattr(inf, field)

                if new_val is None:
                    parts.append(f"{field}=--")
                    continue

                if existing is not None and not args.force:
                    parts.append(f"{field}=skip(existing)")
                    continue

                updates[field] = new_val
                if field == "followers":
                    parts.append(f"followers={new_val}")
                else:
                    parts.append(f"{field}=filled")

            status_tag = "[UPDATED]" if updates else "[NO CHANGE]"
            if args.dry_run and updates:
                status_tag = "[DRY-RUN]"

            logger.info(
                "[%d/%d] id=%d (%s) -> %s",
                i, total, inf.id, platform_label, inf.profile_url,
            )
            logger.info("       %s  %s", "  ".join(parts), status_tag)

            if updates and not args.dry_run:
                async with AsyncSessionLocal() as wdb:
                    await wdb.execute(
                        update(Influencer)
                        .where(Influencer.id == inf.id)
                        .values(**updates)
                    )
                    await wdb.commit()
                stats["updated"] += 1
            elif not updates:
                stats["skipped"] += 1
            # dry-run with updates: count as "updated" for reporting purposes but note (DRY RUN)
            elif args.dry_run and updates:
                stats["updated"] += 1

            if i < total:
                delay = random.uniform(args.delay_min, args.delay_max)
                logger.info("       sleeping %.1fs before next...", delay)
                await asyncio.sleep(delay)

        await browser.close()

    logger.info("")
    logger.info("=== Summary ===")
    logger.info("Processed: %d", stats["processed"])
    dry_note = "  (DRY RUN - nothing persisted)" if args.dry_run else ""
    logger.info("Updated:   %d%s", stats["updated"], dry_note)
    logger.info("Skipped:   %d  (nothing to fill)", stats["skipped"])
    logger.info("Failed:    %d  (see errors above)", stats["failed"])

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill Influencer metadata (followers/bio/avatar_url) from profile URLs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  .venv/Scripts/python scripts/backfill_influencer_metadata.py --all
  .venv/Scripts/python scripts/backfill_influencer_metadata.py --task-id 3
  .venv/Scripts/python scripts/backfill_influencer_metadata.py --platform youtube --limit 10
  .venv/Scripts/python scripts/backfill_influencer_metadata.py --dry-run --limit 3
        """,
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="process all candidates with missing metadata (default behaviour)",
    )
    parser.add_argument(
        "--task-id",
        type=int,
        default=None,
        metavar="N",
        help="only process influencers linked to scrape task #N",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="max rows to process in one run (default: 50)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing non-null values (default: only fill NULL fields)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be updated without writing to DB",
    )
    parser.add_argument(
        "--platform",
        choices=["youtube", "instagram", "tiktok", "twitter", "facebook"],
        default=None,
        help="restrict to a single platform",
    )
    parser.add_argument(
        "--delay-min",
        type=float,
        default=5.0,
        metavar="N",
        help="minimum seconds between requests (default: 5)",
    )
    parser.add_argument(
        "--delay-max",
        type=float,
        default=15.0,
        metavar="N",
        help="maximum seconds between requests (default: 15)",
    )

    # --headless is the default; --headed disables headless
    headless_group = parser.add_mutually_exclusive_group()
    headless_group.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        default=True,
        help="run browser in headless mode (default)",
    )
    headless_group.add_argument(
        "--headed",
        dest="headless",
        action="store_false",
        help="run browser in headed (visible) mode",
    )

    args = parser.parse_args()

    # Validate delay ordering
    if args.delay_min > args.delay_max:
        parser.error(f"--delay-min ({args.delay_min}) must be <= --delay-max ({args.delay_max})")

    sys.exit(asyncio.run(main(args)))
