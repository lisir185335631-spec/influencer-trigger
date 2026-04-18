"""
Scraper Agent — Playwright-based influencer email extractor.

Supports: Instagram, YouTube (full Playwright scraping)
Degrades:  TikTok, Twitter, Facebook (stub — shows manual-input prompt)

Concurrency: controlled by `scrape_concurrency` system setting (default 1), random 5-15 second delay between page visits.
"""

import asyncio
import html as html_module
import json
import logging
import random
import re
from datetime import datetime, timezone

import dns.resolver
import sqlalchemy as sa
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import stealth_async
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.influencer import Influencer, InfluencerPlatform
from app.models.scrape_task import ScrapeTask, ScrapeTaskStatus
from app.models.scrape_task_influencer import ScrapeTaskInfluencer
from app.services.scrape_service import update_task_status
from app.services.settings_service import get_or_create_system_settings
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────

_SUB_COUNT_RE = re.compile(r"([\d.,]+)\s*([KMB]?)", re.IGNORECASE)


def _parse_subscriber_count(text: str) -> int | None:
    """Parse '1.2M subscribers' / '123K' / '456' into an int."""
    if not text:
        return None
    m = _SUB_COUNT_RE.search(text.strip())
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(m.group(2).upper(), 1)
    return int(num * mult)


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
    await asyncio.sleep(random.uniform(5.0, 15.0))


# ── platform scrapers ────────────────────────────────────────────────────────

async def _scrape_youtube(
    browser: Browser,
    industry: str,
    target_count: int,
    on_found: "Callable[[str, str, str], Awaitable[None]]",
    queries: list[str] | None = None,
) -> None:
    """
    Search YouTube for '{industry} influencer', extract channel About pages for emails.
    """
    ctx = await _new_context(browser)
    page = await ctx.new_page()
    await stealth_async(page)

    try:
        search_queries = queries or [f"{industry} creator contact email"]
        all_channel_links: list[str] = []

        for query in search_queries:
            search_url = f"https://www.youtube.com/results?search_query={query}"
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

            for link in channel_links:
                if link not in all_channel_links:
                    all_channel_links.append(link)

            if len(all_channel_links) >= target_count * 2:
                break

        logger.info("[YouTube] Found %d channel links (across %d queries)", len(all_channel_links), len(search_queries))

        found = 0
        for ch_url in all_channel_links[:target_count * 2]:
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

                # Extract channel bio (og:description) + subscriber count
                # (from SSR'd JSON inside the page HTML)
                bio: str | None = None
                followers: int | None = None
                try:
                    m = re.search(
                        r'<meta\s+(?:property|name)="(?:og:description|description)"\s+content="([^"]*)"',
                        content,
                    )
                    if m and m.group(1):
                        bio = html_module.unescape(m.group(1))[:2000]
                except Exception:
                    pass
                try:
                    # YouTube renders "1.2M subscribers" / "123K subscribers" / "456 subscribers"
                    # in multiple places (page body, JSON metadata, aria labels).
                    # A direct text regex is resilient to their SSR schema changes.
                    sm = re.search(
                        r'([\d.,]+\s*[KMB]?)\s*subscribers?',
                        content,
                        re.IGNORECASE,
                    )
                    if sm:
                        followers = _parse_subscriber_count(sm.group(1))
                except Exception:
                    pass

                avatar_url: str | None = None
                try:
                    # og:image is typically the channel avatar
                    m = re.search(
                        r'<meta\s+(?:property|name)="og:image"\s+content="([^"]+)"',
                        content,
                    )
                    if m and m.group(1):
                        avatar_url = m.group(1)[:512]
                except Exception:
                    pass

                for email in emails:
                    domain = email.split("@")[1]
                    if await _mx_valid(domain):
                        await on_found(email, name, ch_url, followers=followers, bio=bio, avatar_url=avatar_url)
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
    queries: list[str] | None = None,
) -> None:
    """
    Search Instagram hashtag explore page for influencer profiles, extract bio emails.
    Note: Instagram requires login for most content; this extracts from public meta tags.
    """
    ctx = await _new_context(browser)
    page = await ctx.new_page()
    await stealth_async(page)

    try:
        hashtags = queries or [industry.lower().replace(" ", "")]
        all_post_hrefs: list[str] = []

        for hashtag in hashtags:
            explore_url = f"https://www.instagram.com/explore/tags/{hashtag}/"
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

            for link in post_links:
                if link not in all_post_hrefs:
                    all_post_hrefs.append(link)

            if len(all_post_hrefs) >= target_count * 3:
                break

        logger.info("[Instagram] Found %d post links (across %d hashtags)", len(all_post_hrefs), len(hashtags))

        visited_profiles: set[str] = set()
        found = 0

        for post_url in all_post_hrefs[:target_count * 3]:
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

                # Extract Instagram metadata from SSR meta tags
                bio: str | None = None
                followers: int | None = None
                avatar_url: str | None = None

                try:
                    desc_m = re.search(
                        r'<meta\s+(?:property|name)="og:description"\s+content="([^"]+)"',
                        content,
                    )
                    if desc_m:
                        desc = html_module.unescape(desc_m.group(1))
                        # followers from "1,234 Followers" embedded in description
                        fm = re.search(r'([\d.,]+\s*[KMB]?)\s*Followers?', desc, re.IGNORECASE)
                        if fm:
                            followers = _parse_subscriber_count(fm.group(1))
                        bio = desc[:2000]
                except Exception:
                    pass

                try:
                    img_m = re.search(
                        r'<meta\s+(?:property|name)="og:image"\s+content="([^"]+)"',
                        content,
                    )
                    if img_m and img_m.group(1):
                        avatar_url = img_m.group(1)[:512]
                except Exception:
                    pass

                for email in emails:
                    domain = email.split("@")[1]
                    if await _mx_valid(domain):
                        await on_found(email, username, profile_url, followers=followers, bio=bio, avatar_url=avatar_url)
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


# ── LLM pre/post processing ──────────────────────────────────────────────────

async def _generate_search_strategy(
    industry: str,
    platforms: list[str],
    target_market: str | None = None,
    competitor_brands: str | None = None,
) -> dict[str, list[str]]:
    """LLM pre-processing: expand industry keyword into platform-specific search queries."""
    settings = get_settings()
    if not settings.openai_api_key:
        return _fallback_queries(industry, platforms)

    from app.prompts import load_prompt
    try:
        business_ctx = load_prompt(f"scraper/_shared/{settings.active_business}.business")
        system = load_prompt("scraper/search_strategy.system", business_context=business_ctx)
    except FileNotFoundError as e:
        logger.warning("Prompt template not found, using fallback: %s", e)
        return _fallback_queries(industry, platforms)

    user_lines = [
        f"Industry keyword: {industry}",
        f"Platforms: {', '.join(platforms)}",
    ]
    if target_market:
        user_lines.append(f"Target market: {target_market}")
    if competitor_brands:
        user_lines.append(f"Competitor brands: {competitor_brands}")
    user = "\n".join(user_lines)

    try:
        from app.tools.llm_client import chat as llm_chat
        content = await llm_chat(
            model=settings.openai_classifier_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.7,
            max_tokens=500,
            response_format={"type": "json_object"},
            agent_name="scraper.search_strategy",
        )
        result = json.loads(content.strip())
        for p in platforms:
            if p not in result:
                result[p] = _fallback_queries(industry, [p])[p]
        logger.info("LLM search strategy generated (business=%s): %s", settings.active_business, result)
        return result
    except Exception as e:
        logger.warning("LLM search strategy failed, using fallback: %s", e)
        return _fallback_queries(industry, platforms)


def _fallback_queries(industry: str, platforms: list[str]) -> dict[str, list[str]]:
    """Fallback search queries when LLM is unavailable."""
    result: dict[str, list[str]] = {}
    for p in platforms:
        if p == "youtube":
            result[p] = [f"{industry} creator contact email"]
        elif p == "instagram":
            result[p] = [industry.lower().replace(" ", "")]
        else:
            result[p] = [industry]
    return result


async def _enrich_results(
    task_id: int,
    industry: str,
    target_market: str | None = None,
) -> None:
    """LLM post-processing: score each influencer's relevance and generate match reason."""
    settings = get_settings()
    if not settings.openai_api_key:
        logger.info("No OpenAI API key, skipping result enrichment")
        return

    from app.prompts import load_prompt
    try:
        business_ctx = load_prompt(f"scraper/_shared/{settings.active_business}.business")
        system = load_prompt("scraper/enrich_results.system", business_context=business_ctx)
    except FileNotFoundError as e:
        logger.warning("Prompt template not found, skipping result enrichment: %s", e)
        return

    async with AsyncSessionLocal() as db:
        from app.models.scrape_task_influencer import ScrapeTaskInfluencer
        stmt = (
            sa.select(Influencer)
            .join(ScrapeTaskInfluencer, ScrapeTaskInfluencer.influencer_id == Influencer.id)
            .where(ScrapeTaskInfluencer.scrape_task_id == task_id)
        )
        rows = await db.execute(stmt)
        influencers = list(rows.scalars().all())

        if not influencers:
            return

        from app.tools.llm_client import chat as llm_chat

        batch_size = 10
        for i in range(0, len(influencers), batch_size):
            batch = influencers[i:i + batch_size]
            profiles = [
                {
                    "id": inf.id,
                    "nickname": inf.nickname or "Unknown",
                    "platform": inf.platform.value if inf.platform else "unknown",
                    "bio": (inf.bio or "")[:200],
                    "industry": inf.industry or "",
                }
                for inf in batch
            ]

            user = (
                f"Please score these {len(batch)} influencers:\n\n"
                f"{json.dumps(profiles, ensure_ascii=False)}"
            )
            if target_market:
                user = f"Target market: {target_market}\n\n" + user

            try:
                content = await llm_chat(
                    model=settings.openai_classifier_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.3,
                    max_tokens=1000,
                    response_format={"type": "json_object"},
                    agent_name="scraper.enrich_results",
                )
                data = json.loads(content.strip())
                enrichments = data.get("results", [])

                for item in enrichments:
                    inf_id = item.get("id")
                    if inf_id is not None:
                        for inf in batch:
                            if inf.id == inf_id:
                                score = item.get("relevance_score")
                                inf.relevance_score = float(score) if score is not None else None
                                inf.match_reason = item.get("match_reason")
                                break
                await db.commit()
            except Exception as e:
                logger.warning("LLM enrichment batch failed: %s", e)
                await db.rollback()

    logger.info("Result enrichment completed for task %d", task_id)


# ── main agent entry point ───────────────────────────────────────────────────

async def run_scraper_agent(task_id: int) -> None:
    """
    Background coroutine executed after the API creates a ScrapeTask record.
    Manages its own DB session and pushes WebSocket progress.

    Concurrency is controlled by the `scrape_concurrency` system setting: up to
    that many platform scrapers run simultaneously via asyncio.Semaphore.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScrapeTask).where(ScrapeTask.id == task_id)
        )
        task: ScrapeTask | None = result.scalar_one_or_none()
        if not task:
            logger.error("ScrapeTask %d not found", task_id)
            return

        # Read scrape_concurrency from system settings so the UI value takes effect.
        sys_settings = await get_or_create_system_settings(db)
        concurrency = max(1, sys_settings.scrape_concurrency)
        semaphore = asyncio.Semaphore(concurrency)
        # Serialise DB writes so concurrent platform tasks don't interleave flush/commit.
        db_lock = asyncio.Lock()

        logger.info(
            "ScrapeTask %d: scrape_concurrency=%d (from system settings)",
            task_id, concurrency,
        )

        platforms: list[str] = json.loads(task.platforms)
        industry = task.industry
        target_per_platform = max(1, task.target_count // max(1, len(platforms)))

        # LLM: generate expanded search queries
        search_queries = await _generate_search_strategy(
            task.industry, platforms, task.target_market, task.competitor_brands
        )
        task.search_keywords = json.dumps(search_queries, ensure_ascii=False)
        await db.commit()

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

        platform_map = {
            "instagram": InfluencerPlatform.instagram,
            "youtube": InfluencerPlatform.youtube,
            "tiktok": InfluencerPlatform.tiktok,
            "twitter": InfluencerPlatform.twitter,
            "facebook": InfluencerPlatform.facebook,
        }

        def make_on_found(platform: str):
            """Return a platform-specific on_found callback (avoids shared mutable closure)."""
            plat = platform_map.get(platform, InfluencerPlatform.other)

            async def on_found(
                email: str,
                name: str,
                profile_url: str,
                followers: int | None = None,
                bio: str | None = None,
                avatar_url: str | None = None,
            ) -> None:
                nonlocal found_total, valid_total

                async with db_lock:
                    if email in seen_emails:
                        return
                    seen_emails.add(email)
                    found_total += 1

                    existing_result = await db.execute(
                        select(Influencer).where(Influencer.email == email)
                    )
                    existing = existing_result.scalar_one_or_none()

                    if existing is None:
                        inf = Influencer(
                            email=email,
                            nickname=name or None,
                            platform=plat,
                            profile_url=profile_url or None,
                            industry=industry,
                            followers=followers,
                            bio=bio,
                            avatar_url=avatar_url,
                        )
                        db.add(inf)
                        await db.flush()  # get inf.id without full commit
                        db.add(ScrapeTaskInfluencer(scrape_task_id=task_id, influencer_id=inf.id))
                        await db.commit()
                        valid_total += 1
                    else:
                        # already exists — link to this task if not already linked
                        link_result = await db.execute(
                            select(ScrapeTaskInfluencer).where(
                                ScrapeTaskInfluencer.scrape_task_id == task_id,
                                ScrapeTaskInfluencer.influencer_id == existing.id,
                            )
                        )
                        if link_result.scalar_one_or_none() is None:
                            db.add(ScrapeTaskInfluencer(
                                scrape_task_id=task_id, influencer_id=existing.id
                            ))
                            await db.commit()
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

            return on_found

        async def run_platform(browser: Browser, platform: str) -> None:
            """Run one platform scraper, gated by the concurrency semaphore."""
            async with semaphore:
                logger.info(
                    "ScrapeTask %d: starting %s scrape (target=%d, concurrency=%d)",
                    task_id, platform, target_per_platform, concurrency,
                )
                on_found = make_on_found(platform)
                if platform == "youtube":
                    await _scrape_youtube(browser, industry, target_per_platform, on_found, queries=search_queries.get("youtube"))
                elif platform == "instagram":
                    await _scrape_instagram(browser, industry, target_per_platform, on_found, queries=search_queries.get("instagram"))
                else:
                    await _scrape_stub(platform)

        try:
            async with async_playwright() as pw:
                browser: Browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                try:
                    # Run all platforms concurrently, limited by scrape_concurrency semaphore.
                    await asyncio.gather(
                        *[run_platform(browser, p) for p in platforms],
                        return_exceptions=True,
                    )
                finally:
                    await browser.close()

            # LLM: enrich scraped results
            await _enrich_results(task.id, task.industry, task.target_market)

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
