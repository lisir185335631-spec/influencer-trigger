"""
Scraper Agent — Playwright-based influencer email extractor.

Supports: Instagram, YouTube (full Playwright scraping)
Degrades:  TikTok, Twitter, Facebook (stub — shows manual-input prompt)

Per-platform: max 1 browser concurrent, random 2-5 second delay between page visits.
"""

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone

import dns.resolver
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.database import AsyncSessionLocal
from app.models.influencer import Influencer, InfluencerPlatform
from app.models.scrape_task import ScrapeTask, ScrapeTaskStatus
from app.services.scrape_service import update_task_status
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

# ── email extraction ─────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+\s*(?:\[at\]|\(at\)|@|＠)\s*"
    r"[a-zA-Z0-9.\-]+\s*(?:\[dot\]|\(dot\)|\.)\s*[a-zA-Z]{2,}",
    re.IGNORECASE,
)

_PLAIN_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

_BLOCKLIST_DOMAINS = {
    "example.com", "sentry.io", "wixpress.com", "squarespace.com",
    "wordpress.com", "shopify.com", "amazonaws.com", "cloudfront.net",
}


def _deobfuscate(raw: str) -> str:
    """Normalize obfuscated email representations to standard form."""
    s = raw.strip()
    s = re.sub(r"\s*\[at\]\s*|\s*\(at\)\s*", "@", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\[dot\]\s*|\s*\(dot\)\s*", ".", s, flags=re.IGNORECASE)
    s = re.sub(r"＠", "@", s)
    s = re.sub(r"\s+", "", s)
    return s.lower()


def _extract_emails(text: str) -> list[str]:
    """Extract and de-obfuscate all email-like strings from text."""
    found: set[str] = set()

    for match in _EMAIL_RE.finditer(text):
        email = _deobfuscate(match.group())
        if _PLAIN_EMAIL_RE.fullmatch(email):
            found.add(email)

    for match in _PLAIN_EMAIL_RE.finditer(text):
        email = match.group().lower()
        found.add(email)

    return [e for e in found if _is_valid_email_format(e)]


def _is_valid_email_format(email: str) -> bool:
    parts = email.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    if not local or not domain:
        return False
    if domain in _BLOCKLIST_DOMAINS:
        return False
    if "." not in domain:
        return False
    tld = domain.rsplit(".", 1)[-1]
    return len(tld) >= 2


# ── MX record validation ─────────────────────────────────────────────────────

_mx_cache: dict[str, bool] = {}


async def _mx_valid(domain: str) -> bool:
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        loop = asyncio.get_event_loop()
        records = await loop.run_in_executor(
            None, lambda: dns.resolver.resolve(domain, "MX", lifetime=5)
        )
        result = len(records) > 0
    except Exception:
        result = False
    _mx_cache[domain] = result
    return result


# ── Playwright helpers ───────────────────────────────────────────────────────

_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
"""

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


async def _new_context(browser: Browser) -> BrowserContext:
    ctx = await browser.new_context(
        user_agent=random.choice(_USER_AGENTS),
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="America/New_York",
    )
    await ctx.add_init_script(_STEALTH_INIT_SCRIPT)
    return ctx


async def _random_delay() -> None:
    await asyncio.sleep(random.uniform(2.0, 5.0))


# ── platform scrapers ────────────────────────────────────────────────────────

async def _scrape_youtube(
    browser: Browser,
    industry: str,
    target_count: int,
    on_found: "Callable[[str, str, str], Awaitable[None]]",
) -> None:
    """
    Search YouTube for '{industry} influencer', extract channel About pages for emails.
    """
    ctx = await _new_context(browser)
    page = await ctx.new_page()

    try:
        search_url = f"https://www.youtube.com/results?search_query={industry}+creator+contact+email"
        logger.info("[YouTube] Navigating to search: %s", search_url)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await _random_delay()

        # Collect channel links from search results
        channel_links: list[str] = []
        for _ in range(3):  # scroll up to 3 times to load more
            links = await page.eval_on_selector_all(
                "a#channel-name, a.yt-simple-endpoint[href*='/@'], a.yt-simple-endpoint[href*='/channel/']",
                "els => els.map(e => e.href)",
            )
            for link in links:
                if link not in channel_links:
                    channel_links.append(link)
            if len(channel_links) >= target_count * 2:
                break
            await page.evaluate("window.scrollBy(0, 1200)")
            await asyncio.sleep(1.5)

        logger.info("[YouTube] Found %d channel links", len(channel_links))

        found = 0
        for ch_url in channel_links[:target_count * 2]:
            if found >= target_count:
                break
            try:
                # Normalize to /about tab
                about_url = ch_url.rstrip("/") + "/about"
                await page.goto(about_url, wait_until="domcontentloaded", timeout=20000)
                await _random_delay()

                # Try clicking "View email address" button if present
                try:
                    btn = page.locator("button:has-text('View email address')")
                    if await btn.count() > 0:
                        await btn.first.click(timeout=3000)
                        await asyncio.sleep(1)
                except Exception:
                    pass

                content = await page.content()
                emails = _extract_emails(content)

                # Also grab channel name
                name = ""
                try:
                    name = await page.title()
                    name = name.replace(" - YouTube", "").strip()
                except Exception:
                    pass

                for email in emails:
                    domain = email.split("@")[1]
                    if await _mx_valid(domain):
                        await on_found(email, name, ch_url)
                        found += 1
                        break

            except Exception as e:
                logger.debug("[YouTube] Error on %s: %s", ch_url, e)

            await _random_delay()

    finally:
        await ctx.close()


async def _scrape_instagram(
    browser: Browser,
    industry: str,
    target_count: int,
    on_found: "Callable[[str, str, str], Awaitable[None]]",
) -> None:
    """
    Search Instagram hashtag explore page for influencer profiles, extract bio emails.
    Note: Instagram requires login for most content; this extracts from public meta tags.
    """
    ctx = await _new_context(browser)
    page = await ctx.new_page()

    try:
        tag = industry.replace(" ", "").lower()
        explore_url = f"https://www.instagram.com/explore/tags/{tag}/"
        logger.info("[Instagram] Navigating to: %s", explore_url)
        await page.goto(explore_url, wait_until="domcontentloaded", timeout=30000)
        await _random_delay()

        # Collect post links
        post_links: list[str] = []
        for _ in range(3):
            links = await page.eval_on_selector_all(
                "a[href*='/p/']",
                "els => [...new Set(els.map(e => e.href))]",
            )
            post_links.extend(l for l in links if l not in post_links)
            if len(post_links) >= target_count * 3:
                break
            await page.evaluate("window.scrollBy(0, 1200)")
            await asyncio.sleep(1.5)

        logger.info("[Instagram] Found %d post links", len(post_links))

        visited_profiles: set[str] = set()
        found = 0

        for post_url in post_links[:target_count * 3]:
            if found >= target_count:
                break
            try:
                await page.goto(post_url, wait_until="domcontentloaded", timeout=20000)
                await _random_delay()

                # Extract username from the post
                username = ""
                try:
                    username_el = await page.query_selector("a[href*='/']:not([href*='/p/'])")
                    if username_el:
                        href = await username_el.get_attribute("href")
                        if href:
                            username = href.strip("/").split("/")[-1]
                except Exception:
                    pass

                if not username or username in visited_profiles:
                    continue
                visited_profiles.add(username)

                profile_url = f"https://www.instagram.com/{username}/"
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=20000)
                await _random_delay()

                content = await page.content()
                emails = _extract_emails(content)

                for email in emails:
                    domain = email.split("@")[1]
                    if await _mx_valid(domain):
                        await on_found(email, username, profile_url)
                        found += 1
                        break

            except Exception as e:
                logger.debug("[Instagram] Error: %s", e)

            await _random_delay()

    finally:
        await ctx.close()


async def _scrape_stub(platform: str) -> list[dict]:
    """Platforms not yet fully implemented return empty list with a log notice."""
    logger.info(
        "[%s] Full Playwright scraping not yet implemented. "
        "Use CSV import or manual entry for this platform.",
        platform.upper(),
    )
    return []


# ── main agent entry point ───────────────────────────────────────────────────

async def run_scraper_agent(task_id: int) -> None:
    """
    Background coroutine executed after the API creates a ScrapeTask record.
    Manages its own DB session and pushes WebSocket progress.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(ScrapeTask).where(ScrapeTask.id == task_id)
        )
        task: ScrapeTask | None = result.scalar_one_or_none()
        if not task:
            logger.error("ScrapeTask %d not found", task_id)
            return

        platforms: list[str] = json.loads(task.platforms)
        industry = task.industry
        target_per_platform = max(1, task.target_count // max(1, len(platforms)))

        await update_task_status(db, task, ScrapeTaskStatus.running, progress=0)
        await manager.broadcast("scrape:progress", {
            "task_id": task_id,
            "status": "running",
            "progress": 0,
            "found_count": 0,
            "valid_count": 0,
        })

        found_total = 0
        valid_total = 0
        # cross-platform dedup by email
        seen_emails: set[str] = set()

        async def on_found(email: str, name: str, profile_url: str) -> None:
            nonlocal found_total, valid_total
            if email in seen_emails:
                return
            seen_emails.add(email)
            found_total += 1

            # Write to influencers table (upsert by email)
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            from app.models.influencer import InfluencerPlatform as IP

            platform_map = {
                "instagram": IP.instagram,
                "youtube": IP.youtube,
                "tiktok": IP.tiktok,
                "twitter": IP.twitter,
                "facebook": IP.facebook,
            }
            plat = platform_map.get(current_platform, IP.other)

            existing_result = await db.execute(
                __import__("sqlalchemy", fromlist=["select"]).select(Influencer).where(Influencer.email == email)
            )
            existing = existing_result.scalar_one_or_none()

            if existing is None:
                inf = Influencer(
                    email=email,
                    nickname=name or None,
                    platform=plat,
                    profile_url=profile_url or None,
                    industry=industry,
                )
                db.add(inf)
                await db.commit()
                valid_total += 1
            else:
                # already exists — count as valid but don't duplicate
                valid_total += 1

            progress = min(99, int((valid_total / task.target_count) * 100))
            await update_task_status(
                db, task, ScrapeTaskStatus.running,
                progress=progress,
                found_count=found_total,
                valid_count=valid_total,
            )
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "running",
                "progress": progress,
                "found_count": found_total,
                "valid_count": valid_total,
                "latest_email": email,
            })

        try:
            async with async_playwright() as pw:
                browser: Browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                try:
                    for platform in platforms:
                        current_platform = platform  # noqa: F841 — captured by closure
                        logger.info(
                            "ScrapeTask %d: starting %s scrape (target=%d)",
                            task_id, platform, target_per_platform,
                        )
                        if platform == "youtube":
                            await _scrape_youtube(browser, industry, target_per_platform, on_found)
                        elif platform == "instagram":
                            await _scrape_instagram(browser, industry, target_per_platform, on_found)
                        else:
                            await _scrape_stub(platform)

                        if valid_total >= task.target_count:
                            break

                finally:
                    await browser.close()

            await update_task_status(
                db, task, ScrapeTaskStatus.completed,
                progress=100,
                found_count=found_total,
                valid_count=valid_total,
            )
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "completed",
                "progress": 100,
                "found_count": found_total,
                "valid_count": valid_total,
            })
            logger.info(
                "ScrapeTask %d completed: found=%d valid=%d",
                task_id, found_total, valid_total,
            )

        except Exception as exc:
            logger.exception("ScrapeTask %d failed: %s", task_id, exc)
            await update_task_status(
                db, task, ScrapeTaskStatus.failed,
                error_message=str(exc),
                found_count=found_total,
                valid_count=valid_total,
            )
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "failed",
                "error": str(exc),
                "found_count": found_total,
                "valid_count": valid_total,
            })
