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
import httpx
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


def _load_youtube_cookies() -> list[dict] | None:
    """Load cookies.json for authenticated YouTube scraping (unlocks 'View email
    address' button that only shows for signed-in viewers).

    Expected path: server/data/youtube-cookies.json
    Format: Playwright storage_state format OR array of cookie dicts.
    Returns None if file missing or unparseable (scraper still works, just
    misses creators who hide email behind the sign-in wall).
    """
    from pathlib import Path
    cookie_path = Path(__file__).resolve().parents[3] / "data" / "youtube-cookies.json"
    if not cookie_path.exists():
        return None
    try:
        data = json.loads(cookie_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "cookies" in data:
            return data["cookies"]
        if isinstance(data, list):
            return data
    except Exception as e:
        logger.warning("Failed to parse youtube-cookies.json: %s", e)
    return None


# Resource types we never need for email/bio/follower scraping. Blocking these
# dramatically reduces Playwright CDP event volume (a single YouTube page
# normally fetches 100+ sub-resources), which in turn frees up the Windows
# ProactorEventLoop to serve HTTP requests while the scraper is running.
# `ytInitialData` (our data source) is inline in the main HTML, so skipping
# images/CSS/fonts/media/trackers doesn't lose any extractable field.
_BLOCK_RESOURCE_TYPES = frozenset({"image", "stylesheet", "font", "media"})


async def _block_non_essential(route) -> None:
    try:
        if route.request.resource_type in _BLOCK_RESOURCE_TYPES:
            await route.abort()
        else:
            await route.continue_()
    except Exception:
        # If routing fails mid-request (context closed, page gone), swallow —
        # the request either succeeded already or will raise upstream.
        pass


async def _new_context(browser: Browser, use_yt_cookies: bool = False) -> BrowserContext:
    ctx = await browser.new_context(
        user_agent=random.choice(_USER_AGENTS),
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="America/New_York",
    )
    await ctx.add_init_script(_STEALTH_INIT_SCRIPT)
    # Block images/CSS/fonts/media/tracking BEFORE any navigation happens.
    await ctx.route("**/*", _block_non_essential)
    if use_yt_cookies:
        cookies = _load_youtube_cookies()
        if cookies:
            try:
                await ctx.add_cookies(cookies)
                logger.info("[YouTube] loaded %d cookies for authenticated scraping", len(cookies))
            except Exception as e:
                logger.warning("[YouTube] add_cookies failed: %s", e)
        else:
            logger.info("[YouTube] no cookies.json — running anonymous (some emails hidden)")
    return ctx


async def _random_delay() -> None:
    # 2-5s: short enough to not bottleneck throughput, long enough to look
    # human-ish. YouTube does not ban an IP for opening several channel pages
    # within 30s when each uses its own UA + stealth. If reCAPTCHA/detection
    # ever triggers, widen this back to 5-15.
    await asyncio.sleep(random.uniform(2.0, 5.0))


# ── YouTube channel metadata extraction ──────────────────────────────────────
# These regexes operate on the raw HTML of a channel /about page. They must NOT
# be applied to video-page HTML, because e.g. og:title on a video page is the
# video title, not the channel name — the earlier bug where nickname showed up
# as "12 productivity apps that got me through college" happened because
# page.title() was called after fallback navigated to a video.

_OG_TITLE_RE = re.compile(
    r'<meta\s+(?:property|name)="og:title"\s+content="([^"]*)"',
    re.IGNORECASE,
)
_OG_DESC_RE = re.compile(
    r'<meta\s+(?:property|name)="(?:og:description|description)"\s+content="([^"]*)"',
    re.IGNORECASE,
)
_OG_IMAGE_RE = re.compile(
    r'<meta\s+(?:property|name)="og:image"\s+content="([^"]+)"',
    re.IGNORECASE,
)
# ytInitialData subscriberCountText — two SSR variants
_YT_SUB_SIMPLE_RE = re.compile(
    r'"subscriberCountText":\s*\{\s*"(?:simpleText|content)":\s*"([^"]+)"'
)
_YT_SUB_ACCESS_RE = re.compile(
    r'"subscriberCountText":[^}]*?"label":"([^"]*subscribers?[^"]*)"',
)
# ytInitialData channel avatar: look inside the c4TabbedHeaderRenderer block,
# then pick the highest-resolution thumbnail URL (yt3.ggpht.com / yt4.ggpht.com).
_YT_AVATAR_BLOCK_RE = re.compile(
    r'"c4TabbedHeaderRenderer":\s*\{.*?"avatar":\s*\{\s*"thumbnails":\s*\[([^\]]*)\]',
    re.DOTALL,
)
_YT_THUMB_URL_RE = re.compile(r'"url":"(https?://[^"]+)"')
# YouTube's "no avatar" placeholders we should skip when choosing avatar
_AVATAR_PLACEHOLDER_MARKERS = ("no-channel-avatar", "yts/img/no-av", "default_profile")


def _extract_youtube_channel_metadata(html: str) -> dict:
    """Extract channel-level fields (nickname/bio/followers/avatar_url) from an
    /about page HTML. ONLY call on about page HTML — video pages would give
    video-scoped values (wrong nickname, wrong follower count).
    All fields are independent — any can be None on failure."""
    name: str | None = None
    m = _OG_TITLE_RE.search(html)
    if m:
        raw = html_module.unescape(m.group(1)).strip()
        # Some pages still include " - YouTube" suffix even in og:title
        raw = re.sub(r"\s*[\-–]\s*YouTube\s*$", "", raw).strip()
        if raw:
            name = raw[:256]

    bio: str | None = None
    m = _OG_DESC_RE.search(html)
    if m and m.group(1):
        raw = html_module.unescape(m.group(1))
        # Collapse 3+ consecutive newlines to 2 for downstream readability
        raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
        if raw:
            bio = raw[:4000]

    followers: int | None = None
    # Prefer structured ytInitialData sources over generic text regex, because the
    # text regex can match "1.2K subscribers" that appears anywhere on the page
    # (e.g. a related channel in sidebar).
    m = _YT_SUB_SIMPLE_RE.search(html)
    if not m:
        m = _YT_SUB_ACCESS_RE.search(html)
    if m:
        followers = _parse_subscriber_count(m.group(1))
    if followers is None:
        m = re.search(r'([\d.,]+\s*[KMB]?)\s*subscribers?', html, re.IGNORECASE)
        if m:
            followers = _parse_subscriber_count(m.group(1))

    avatar_url: str | None = None
    # 1) og:image — usually the channel avatar; skip if it's a known placeholder
    m = _OG_IMAGE_RE.search(html)
    if m and m.group(1):
        candidate = m.group(1)
        if not any(marker in candidate for marker in _AVATAR_PLACEHOLDER_MARKERS):
            avatar_url = candidate[:512]
    # 2) ytInitialData c4TabbedHeaderRenderer avatar — pick the last (highest-res)
    if not avatar_url:
        block_m = _YT_AVATAR_BLOCK_RE.search(html)
        if block_m:
            urls = _YT_THUMB_URL_RE.findall(block_m.group(1))
            urls = [u for u in urls if not any(marker in u for marker in _AVATAR_PLACEHOLDER_MARKERS)]
            if urls:
                avatar_url = urls[-1][:512]

    return {
        "name": name,
        "bio": bio,
        "followers": followers,
        "avatar_url": avatar_url,
    }


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
    ctx = await _new_context(browser, use_yt_cookies=True)
    page = await ctx.new_page()
    await stealth_async(page)

    try:
        search_queries = queries or [f"{industry} creator contact email"]
        all_channel_links: list[str] = []

        # YouTube is an SPA: search results live inside the `ytInitialData`
        # JS blob, NOT in rendered <a> tags. DOM selectors always returned 0.
        # We regex the canonicalBaseUrl / url occurrences of /@<handle> from
        # the raw HTML — this is resilient to YouTube's DOM schema changes.
        _YT_CHANNEL_PATH_RE = re.compile(r'"(?:canonicalBaseUrl|url)":"(/@[A-Za-z0-9_.\-]+)"')

        for query in search_queries:
            search_url = f"https://www.youtube.com/results?search_query={query}"
            logger.info("[YouTube] search query: %r", query)
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await _random_delay()

            # Extract channels from this page. Scroll a few times to trigger
            # lazy-load appends to ytInitialData. A larger pool is needed when
            # the keyword's email-hit rate is low (e.g. ~20-30% for AI / Notion
            # type queries) — we aim for 5× target_count candidates so even
            # 20% hit rate still yields the target.
            found_this_query: set[str] = set()
            for scroll_i in range(8):
                html = await page.content()
                # Regex over 1–2 MB HTML on the event-loop thread freezes all
                # HTTP handlers. Offload to thread pool.
                matches = await asyncio.to_thread(_YT_CHANNEL_PATH_RE.findall, html)
                new_count = 0
                for path in matches:
                    full_url = f"https://www.youtube.com{path}"
                    if full_url not in found_this_query:
                        found_this_query.add(full_url)
                        new_count += 1
                logger.info(
                    "[YouTube] scroll #%d: html_len=%d regex_hits=%d new_channels=%d total_this_query=%d",
                    scroll_i + 1, len(html), len(matches), new_count, len(found_this_query),
                )
                if len(found_this_query) >= target_count * 15:
                    break
                await page.evaluate("window.scrollBy(0, 1800)")
                await asyncio.sleep(2)

            for link in found_this_query:
                if link not in all_channel_links:
                    all_channel_links.append(link)

            if len(all_channel_links) >= target_count * 15:
                break

        logger.info(
            "[YouTube] collected %d channel links across %d queries",
            len(all_channel_links), len(search_queries),
        )

        # Visit up to 5× the target count. Empirical hit rate:
        #   商业化关键词 (Canva / ChatGPT review): ~35%
        #   AI tools / Notion productivity:          ~20-27%
        # 5× buffer means even a 20% hit rate still delivers target_count.
        max_to_visit = min(len(all_channel_links), target_count * 15)

        # Per-channel hard watchdog: playwright's own op-level timeouts don't
        # always fire (e.g. `page.content()` has no internal timeout), so we
        # wrap each channel's work in asyncio.timeout.
        #
        # 90 → 30 → 15: once video fallback was removed, a successful
        # channel = about goto (≤8s) + hydration 1.2s + regex <1s +
        # _random_delay (2-5s) + overhead ≈ 10s. 15s gives 5s buffer for
        # slow YouTube responses. Dead channels (20s goto timeout) still
        # get shed within the budget.
        _CHANNEL_BUDGET = 15.0

        # Parallel channel processing. Each task creates its own page (shares
        # the same context — so cookies, stealth init script, and UA rotation
        # all carry over).
        #
        # History of this constant:
        #   3 → 2: Windows IOCP accept-socket errors cascaded under sustained
        #          Playwright×3 load, eventually killing uvicorn's accept loop.
        #   2 → 1: concurrency=2 still caused health-probe 3s timeouts and
        #          scraper progress stalled. Pre-subresource-block CDP event
        #          volume was ~thousands/page (every image/CSS/font/tracker
        #          hit the event loop via IOCP).
        #   1 → 3: after adding `ctx.route("**/*", _block_non_essential)` which
        #          aborts 80% of sub-resource requests at the browser side,
        #          CDP event volume dropped ~5×. Restoring concurrency=3
        #          (MEMORY's proven 1.6 min config) with the lighter CDP
        #          traffic should fit within Windows IOCP's headroom.
        #
        # The regex CPU fix (`asyncio.to_thread` on _extract_* calls) stays
        # in place — regex on 2MB HTML must not block the event loop or
        # /api/* endpoints lag.
        _CHANNEL_CONCURRENCY = 3

        found_counter = 0
        found_lock = asyncio.Lock()
        stop_event = asyncio.Event()
        sem = asyncio.Semaphore(_CHANNEL_CONCURRENCY)

        async def _process_channel(ch_idx: int, ch_url: str) -> None:
            nonlocal found_counter
            # Fast pre-check: if target already reached before we even queue
            # for the semaphore, skip cheaply (no new_page cost).
            if stop_event.is_set():
                return
            async with sem:
                if stop_event.is_set():
                    return
                ch_page = None
                try:
                    async with asyncio.timeout(_CHANNEL_BUDGET):
                        ch_page = await ctx.new_page()
                        await stealth_async(ch_page)

                        about_url = ch_url.rstrip("/") + "/about"
                        logger.info(
                            "[YouTube] [%d/%d] visiting %s",
                            ch_idx + 1, max_to_visit, about_url,
                        )
                        await ch_page.goto(about_url, wait_until="domcontentloaded", timeout=20000)
                        # Hydration wait: 1.2s lets client-side JS render the
                        # "View email address" button (only visible when
                        # logged in via cookies.json). Metadata extraction
                        # below is SSR-based so it doesn't need hydration,
                        # but the email-reveal button does.
                        await asyncio.sleep(1.2)

                        view_email_btn_count = 0
                        try:
                            btn = ch_page.locator("button:has-text('View email address')")
                            view_email_btn_count = await btn.count()
                            if view_email_btn_count > 0:
                                await btn.first.click(timeout=3000)
                                await asyncio.sleep(1)
                        except Exception:
                            pass

                        content = await ch_page.content()
                        # CPU-bound regex work goes to the default thread pool so
                        # it doesn't stall the event loop (otherwise all HTTP
                        # handlers block while the scraper is mid-channel).
                        emails = await asyncio.to_thread(_extract_emails, content)

                        # Lock channel metadata from the /about page BEFORE any
                        # fallback navigation.
                        meta = await asyncio.to_thread(_extract_youtube_channel_metadata, content)
                        name = meta["name"] or ""
                        bio = meta["bio"]
                        followers = meta["followers"]
                        avatar_url = meta["avatar_url"]
                        if not name:
                            try:
                                t = await ch_page.title()
                                name = re.sub(r"\s*[\-–]\s*YouTube\s*$", "", (t or "").strip())
                            except Exception:
                                pass

                        logger.info(
                            "[YouTube] [%d] html_len=%d view_email_btn=%d emails_found=%d "
                            "name=%r followers=%s avatar=%s",
                            ch_idx + 1, len(content), view_email_btn_count, len(emails),
                            name, followers, "yes" if avatar_url else "no",
                        )

                        # Video fallback intentionally removed. Rationale:
                        #   - Subresource block (image/stylesheet/font/media)
                        #     breaks YouTube video player hydration, so
                        #     `page.content()` on a video page rarely yields
                        #     useful HTML — hit rate approaches 0.
                        #   - Each dead fallback still eats ~20-30s of a
                        #     scarce concurrency slot, bloating total task
                        #     time from ~2min to 20min+.
                        #   - Pure about-page mode + wider candidate pool
                        #     (target_count * 15) compensates with more
                        #     first-hop lookups instead.
                        # If you reintroduce fallback later, also relax the
                        # subresource block for video URLs and bump
                        # _CHANNEL_BUDGET ≥ 60s.

                        for email in emails:
                            domain = email.split("@")[1]
                            if await _mx_valid(domain):
                                await on_found(email, name, ch_url, followers=followers, bio=bio, avatar_url=avatar_url)
                                async with found_lock:
                                    found_counter += 1
                                    if found_counter >= target_count:
                                        stop_event.set()
                                break
                except asyncio.TimeoutError:
                    logger.warning(
                        "[YouTube] [%d/%d] hard timeout %.0fs, skipping: %s",
                        ch_idx + 1, max_to_visit, _CHANNEL_BUDGET, ch_url,
                    )
                except Exception as e:
                    logger.debug("[YouTube] Error on %s: %s", ch_url, e)
                finally:
                    if ch_page is not None:
                        try:
                            await ch_page.close()
                        except Exception:
                            pass
                # Each task paces itself independently before releasing the
                # semaphore. With concurrency=3 and 2-5s delay, effective rate
                # ~1 new channel request per ~1s, which stays within normal
                # browsing patterns.
                await _random_delay()

        await asyncio.gather(
            *[_process_channel(i, url) for i, url in enumerate(all_channel_links[:max_to_visit])],
            return_exceptions=True,
        )
        logger.info(
            "[YouTube] channel phase done: valid=%d / target=%d (visited up to %d)",
            found_counter, target_count, max_to_visit,
        )

    finally:
        await ctx.close()


# ── Instagram helpers ────────────────────────────────────────────────────────
# Strategy: IG's explore page requires login since 2024 — DOM-based entry
# collapses to ~0 hits. Instead we Google-Dork via the Brave Search API to
# surface public IG profile URLs, then visit each profile with Playwright.
# When a profile's SSR bio has no email we follow its Linktree / bio.link /
# beacons outbound link (common IG creator pattern) and extract from there.
#
# Why Brave (not DDG/Bing)? DDG returns HTTP 418 and Bing serves a captcha
# wall to this machine's IP, so HTTP-scraped search engines yield 0 results.
# Brave gives us an authorized JSON API with 2000 free queries/month — 1–2
# orders of magnitude more than a typical scrape task needs.

_IG_DORK_TEMPLATES = (
    'site:instagram.com "{q}" "gmail.com"',
    'site:instagram.com "{q}" "business inquiries"',
    'site:instagram.com "{q}" creator collab',
    'site:instagram.com "{q}" email "@"',
)

# Paths under instagram.com/... that are NOT user profiles.
_IG_RESERVED_PATHS = frozenset({
    "", "p", "reel", "reels", "tv", "explore", "accounts", "about",
    "directory", "stories", "developer", "legal", "press", "api",
    "privacy", "safety", "hashtag", "web", "ar", "invites",
    "session", "direct", "emails", "static",
})

_IG_PROFILE_URL_RE = re.compile(
    r'https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]{2,30})/?',
    re.IGNORECASE,
)

_LINK_AGGREGATOR_RE = re.compile(
    r'https?://(?:www\.)?(?:linktr\.ee|beacons\.ai|linkin\.bio|campsite\.bio|'
    r'bio\.link|carrd\.co|lnk\.bio|allmylinks\.com|many\.link|flowcode\.com)'
    r'/[A-Za-z0-9._\-]+',
    re.IGNORECASE,
)

_IG_FOLLOWERS_RE = re.compile(
    r'([\d.,]+\s*[KMB]?)\s*Followers?',
    re.IGNORECASE,
)

_IG_OG_DESC_RE = re.compile(
    r'<meta\s+(?:property|name)="og:description"\s+content="([^"]*)"',
    re.IGNORECASE,
)
_IG_OG_TITLE_RE = re.compile(
    r'<meta\s+(?:property|name)="og:title"\s+content="([^"]*)"',
    re.IGNORECASE,
)
_IG_OG_IMAGE_RE = re.compile(
    r'<meta\s+(?:property|name)="og:image"\s+content="([^"]+)"',
    re.IGNORECASE,
)

def _ig_profile_url_from_href(href: str) -> str | None:
    """Return canonical `https://www.instagram.com/<username>/` if href matches
    an IG user profile (not a reserved path), else None."""
    m = _IG_PROFILE_URL_RE.match(href)
    if not m:
        return None
    username = m.group(1)
    if username.lower() in _IG_RESERVED_PATHS:
        return None
    return f"https://www.instagram.com/{username}/"


async def _search_brave(query: str, limit: int = 20) -> list[str]:
    """Brave Search Web API → dedup Instagram profile URL list.
    Requires BRAVE_SEARCH_API_KEY in env. Returns [] and logs a warning
    when the key is absent or the API returns non-200 — the task completes
    with 0 results rather than crashing so ops can diagnose from the log.
    """
    settings = get_settings()
    api_key = (settings.brave_search_api_key or "").strip()
    if not api_key:
        logger.warning(
            "[Instagram] BRAVE_SEARCH_API_KEY not configured — IG scraper cannot "
            "discover profiles. Add the key to server/.env and restart."
        )
        return []

    profiles: list[str] = []
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
        ) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={
                    "q": query,
                    "count": max(1, min(limit, 20)),
                    "country": "US",
                    "search_lang": "en",
                },
            )
    except Exception as e:
        logger.warning("[Instagram] Brave request failed for %r: %s", query, e)
        return profiles

    if resp.status_code == 429:
        logger.warning(
            "[Instagram] Brave rate limit hit (monthly quota or QPS). "
            "Remaining=%s Reset=%s",
            resp.headers.get("X-RateLimit-Remaining", "?"),
            resp.headers.get("X-RateLimit-Reset", "?"),
        )
        return profiles
    if resp.status_code != 200:
        logger.warning(
            "[Instagram] Brave status %d for %r: %s",
            resp.status_code, query, resp.text[:200],
        )
        return profiles

    try:
        data = resp.json()
    except Exception as e:
        logger.warning("[Instagram] Brave JSON decode failed: %s", e)
        return profiles

    for item in data.get("web", {}).get("results", []) or []:
        url = item.get("url") or ""
        canonical = _ig_profile_url_from_href(url)
        if canonical and canonical not in profiles:
            profiles.append(canonical)
            if len(profiles) >= limit:
                break
    return profiles


async def _discover_ig_profiles(
    industry: str,
    queries: list[str] | None,
    target_urls: int,
) -> list[str]:
    """Generate Google-Dork queries from LLM-suggested seeds (or the raw
    industry keyword as fallback), run them through Brave Search, return
    a dedup profile URL list capped at target_urls."""
    seeds = [q.strip() for q in (queries or [industry]) if q and q.strip()]
    if not seeds:
        seeds = [industry]

    dorks: list[str] = []
    for q in seeds:
        for tpl in _IG_DORK_TEMPLATES:
            dorks.append(tpl.format(q=q))

    all_profiles: list[str] = []
    seen: set[str] = set()

    for i, dork in enumerate(dorks):
        if len(all_profiles) >= target_urls:
            break
        logger.info("[Instagram] search #%d/%d dork=%r", i + 1, len(dorks), dork)

        urls = await _search_brave(dork, limit=20)
        logger.info(
            "[Instagram] dork #%d: brave=%d total_so_far=%d",
            i + 1, len(urls), len(all_profiles) + sum(1 for u in urls if u not in seen),
        )

        for u in urls:
            if u not in seen:
                seen.add(u)
                all_profiles.append(u)
                if len(all_profiles) >= target_urls:
                    break

        # Brave free tier caps at 1 QPS — stay polite (and under limit).
        await asyncio.sleep(random.uniform(1.1, 1.6))

    logger.info(
        "[Instagram] discovery done: %d unique profile URLs from %d dorks",
        len(all_profiles), len(dorks),
    )
    return all_profiles


def _extract_instagram_profile_metadata(html: str, username_fallback: str) -> dict:
    """Mirror of `_extract_youtube_channel_metadata` for IG profile SSR HTML.
    All fields independent — any can be None."""
    name: str | None = None
    m = _IG_OG_TITLE_RE.search(html)
    if m and m.group(1):
        raw = html_module.unescape(m.group(1)).strip()
        # og:title variants we've observed:
        #   "Username (@handle) • Instagram photos and videos"
        #   "Username on Instagram: \"bio...\""
        #   "@handle • Instagram photos and videos"
        cleaned = re.sub(r"\s*[•·]\s*Instagram.*$", "", raw, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+on Instagram.*$", "", cleaned, flags=re.IGNORECASE).strip()
        if cleaned:
            name = cleaned[:256]
    if not name:
        name = f"@{username_fallback}"[:256]

    bio: str | None = None
    followers: int | None = None
    m = _IG_OG_DESC_RE.search(html)
    if m and m.group(1):
        desc = html_module.unescape(m.group(1))
        fm = _IG_FOLLOWERS_RE.search(desc)
        if fm:
            followers = _parse_subscriber_count(fm.group(1))
        # Strip IG's boilerplate "<N> Followers, <N> Following, <N> Posts - "
        # prefix and "See Instagram photos and videos from @..." so `bio` holds
        # only the creator-authored part.
        bio_part = re.sub(
            r'^[\d.,]+\s*[KMB]?\s*Followers?,\s*[\d.,]+\s*[KMB]?\s*Following,\s*'
            r'[\d.,]+\s*[KMB]?\s*Posts\s*[-–—]\s*',
            '',
            desc,
            flags=re.IGNORECASE,
        )
        bio_part = re.sub(
            r'^See Instagram photos and videos from\s+@?[\w.]+',
            '',
            bio_part,
            flags=re.IGNORECASE,
        ).strip(' -–—"\'')
        if bio_part:
            bio = bio_part[:4000]

    avatar_url: str | None = None
    m = _IG_OG_IMAGE_RE.search(html)
    if m and m.group(1):
        # IG CDN signed URLs are ~600-900 chars and the og:image attribute
        # HTML-escapes '&' as '&amp;'. Skipping unescape or truncating below
        # the signature (oh=...&oe=...) guarantees a 403 from the CDN, so
        # both must be handled.
        avatar_url = html_module.unescape(m.group(1))[:1024]

    return {
        "name": name,
        "bio": bio,
        "followers": followers,
        "avatar_url": avatar_url,
    }


def _extract_linktree_url(html: str) -> str | None:
    m = _LINK_AGGREGATOR_RE.search(html)
    return m.group(0) if m else None


async def _scrape_aggregator_emails(
    ctx: BrowserContext,
    aggregator_url: str,
    timeout_sec: float = 8.0,
) -> list[str]:
    """Open a Linktree/bio.link/beacons page (public, no login wall) and
    extract emails from its rendered HTML. Uses a short-lived page in the
    caller's context to keep stealth + UA continuity."""
    agg_page: Page | None = None
    try:
        async with asyncio.timeout(timeout_sec):
            agg_page = await ctx.new_page()
            await agg_page.goto(
                aggregator_url,
                wait_until="domcontentloaded",
                timeout=int(timeout_sec * 1000),
            )
            content = await agg_page.content()
            return await asyncio.to_thread(_extract_emails, content)
    except Exception as e:
        logger.debug("[Instagram] linktree %s failed: %s", aggregator_url, e)
        return []
    finally:
        if agg_page is not None:
            try:
                await agg_page.close()
            except Exception:
                pass


async def _scrape_instagram(
    browser: Browser,
    industry: str,
    target_count: int,
    on_found: "Callable[[str, str, str], Awaitable[None]]",
    queries: list[str] | None = None,
) -> None:
    """
    Instagram scraper — Phase 1 rewrite:
      - Entry: Google-Dork via DuckDuckGo + Bing (HTTP, no Playwright).
        Replaces hashtag explore page which redirects to login since 2024.
      - Per candidate: open IG profile with Playwright, extract bio email +
        SSR metadata. If no bio email, follow outbound Linktree/bio.link link
        and extract from there.
      - Concurrency / hard per-profile timeout / candidate pool 15× /
        resource blocking / regex-to-thread / stop_event — all mirror
        `_scrape_youtube` so IG stops being the pipeline's bottleneck.
    """
    target_urls = target_count * 15
    profile_urls = await _discover_ig_profiles(industry, queries, target_urls)

    if not profile_urls:
        logger.warning(
            "[Instagram] no profile URLs found — search engines returned 0 hits. "
            "Check network / retry with different industry keyword."
        )
        return

    ctx = await _new_context(browser)
    try:
        max_to_visit = min(len(profile_urls), target_urls)

        # Slightly longer than YouTube's 15s because IG SSR occasionally stalls
        # under heavier reverse-proxy layers (Meta's edge); still short enough
        # that a single slow profile can't starve the task.
        _IG_PROFILE_BUDGET = 18.0
        _IG_CONCURRENCY = 3

        found_counter = 0
        found_lock = asyncio.Lock()
        stop_event = asyncio.Event()
        sem = asyncio.Semaphore(_IG_CONCURRENCY)

        async def _process_profile(idx: int, profile_url: str) -> None:
            nonlocal found_counter
            if stop_event.is_set():
                return
            async with sem:
                if stop_event.is_set():
                    return

                m = _IG_PROFILE_URL_RE.match(profile_url)
                username = m.group(1) if m else ""
                if not username:
                    return

                ig_page: Page | None = None
                try:
                    async with asyncio.timeout(_IG_PROFILE_BUDGET):
                        ig_page = await ctx.new_page()
                        await stealth_async(ig_page)

                        logger.info(
                            "[Instagram] [%d/%d] visiting %s",
                            idx + 1, max_to_visit, profile_url,
                        )
                        await ig_page.goto(
                            profile_url, wait_until="domcontentloaded", timeout=15000,
                        )

                        # If IG redirected us to /accounts/login/, skip fast —
                        # the SSR HTML will have no bio/email for us.
                        landed_url = ig_page.url or ""
                        if "/accounts/login" in landed_url:
                            logger.info(
                                "[Instagram] [%d] login wall, skipping %s",
                                idx + 1, profile_url,
                            )
                            return

                        content = await ig_page.content()
                        emails = await asyncio.to_thread(_extract_emails, content)
                        meta = await asyncio.to_thread(
                            _extract_instagram_profile_metadata, content, username,
                        )

                        # Linktree / bio.link fallback when bio has no email.
                        if not emails:
                            aggregator_url = _extract_linktree_url(content)
                            if aggregator_url:
                                logger.info(
                                    "[Instagram] [%d] no bio email, trying aggregator: %s",
                                    idx + 1, aggregator_url,
                                )
                                emails = await _scrape_aggregator_emails(ctx, aggregator_url)

                        logger.info(
                            "[Instagram] [%d] html_len=%d emails=%d name=%r "
                            "followers=%s avatar=%s",
                            idx + 1, len(content), len(emails), meta["name"],
                            meta["followers"], "yes" if meta["avatar_url"] else "no",
                        )

                        for email in emails:
                            domain = email.split("@")[1]
                            if await _mx_valid(domain):
                                await on_found(
                                    email,
                                    meta["name"] or f"@{username}",
                                    profile_url,
                                    followers=meta["followers"],
                                    bio=meta["bio"],
                                    avatar_url=meta["avatar_url"],
                                )
                                async with found_lock:
                                    found_counter += 1
                                    if found_counter >= target_count:
                                        stop_event.set()
                                break
                except asyncio.TimeoutError:
                    logger.warning(
                        "[Instagram] [%d/%d] hard timeout %.0fs, skipping: %s",
                        idx + 1, max_to_visit, _IG_PROFILE_BUDGET, profile_url,
                    )
                except Exception as e:
                    logger.debug("[Instagram] Error on %s: %s", profile_url, e)
                finally:
                    if ig_page is not None:
                        try:
                            await ig_page.close()
                        except Exception:
                            pass
                await _random_delay()

        await asyncio.gather(
            *[_process_profile(i, url) for i, url in enumerate(profile_urls[:max_to_visit])],
            return_exceptions=True,
        )
        logger.info(
            "[Instagram] profile phase done: valid=%d / target=%d (visited up to %d)",
            found_counter, target_count, max_to_visit,
        )

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
    base = industry.strip()
    for p in platforms:
        if p == "youtube":
            result[p] = [f"{base} creator contact email"]
        elif p == "instagram":
            # Brave Search is a natural-language engine — preserve spaces and
            # give a few seed variants so recall doesn't collapse when LLM is
            # unavailable. Historical "replace(' ', '')" compression was a
            # leftover from the old hashtag-explore entry (hashtags cannot
            # contain spaces); Brave needs the opposite.
            result[p] = [base, f"{base} creator", f"{base} influencer"]
        else:
            result[p] = [base]
    return result


# ── Heuristic relevance scoring (LLM enrichment fallback) ────────────────────

_BIZ_KEYWORDS_RE = re.compile(
    r"collab|business|sponsor|partner|contact|合作|商务|联系|赞助",
    re.IGNORECASE,
)
_PRODUCT_KEYWORDS_RE = re.compile(
    r"ai\b|tutorial|review|productivity|canva|chatgpt|\bgpt\b|netflix|notion|"
    r"subscription|tools|creator|learning|教程|评测|软件|订阅|工具",
    re.IGNORECASE,
)
_EMAIL_IN_BIO_RE = re.compile(
    r"[\w.+%\-]+@[\w.\-]+\.[a-z]{2,}",
    re.IGNORECASE,
)


def _heuristic_score(inf: Influencer) -> tuple[float, str]:
    """Compute a rough relevance score when LLM is unavailable or fails.
    Range 0.0–1.0, returns (score, match_reason)."""
    followers = inf.followers or 0
    bio = inf.bio or ""

    # Followers tier (base 0.05–0.35)
    if 10_000 <= followers < 1_000_000:
        base, tier_label = 0.35, "粉丝处于黄金区间"
    elif followers >= 1_000_000:
        base, tier_label = 0.30, "大号粉丝量"
    elif 1_000 <= followers < 10_000:
        base, tier_label = 0.25, "粉丝量适中"
    elif 100 <= followers < 1_000:
        base, tier_label = 0.15, "粉丝较少"
    else:
        base, tier_label = 0.05, "粉丝极少或未知"

    # Bio signal bonuses (capped at +0.30)
    signals: list[str] = []
    bonus = 0.0
    if _EMAIL_IN_BIO_RE.search(bio):
        bonus += 0.15
        signals.append("bio 含邮箱")
    if _BIZ_KEYWORDS_RE.search(bio):
        bonus += 0.10
        signals.append("有合作信号")
    if _PRODUCT_KEYWORDS_RE.search(bio):
        bonus += 0.10
        signals.append("品类相关")
    bonus = min(bonus, 0.30)

    score = round(min(1.0, base + bonus), 2)
    reason = (tier_label + ("，" + "，".join(signals) if signals else ""))[:30]
    return score, reason


async def _enrich_results(
    task_id: int,
    industry: str,
    target_market: str | None = None,
) -> None:
    """Two-phase scoring: always assign a heuristic score first so every
    influencer has a relevance_score / match_reason. Then, if OpenAI is
    configured, upgrade each batch with an LLM score. LLM batch failures
    fall through silently — the heuristic score stays."""
    settings = get_settings()

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

        # Phase 1: heuristic baseline for every influencer that still lacks a
        # score (e.g. freshly inserted from this task). Pre-existing scores
        # from prior tasks are left untouched.
        heuristic_applied = 0
        for inf in influencers:
            if inf.relevance_score is None:
                score, reason = _heuristic_score(inf)
                inf.relevance_score = score
                inf.match_reason = reason
                heuristic_applied += 1
        if heuristic_applied:
            await db.commit()
            logger.info(
                "Heuristic baseline applied to %d/%d influencers (task %d)",
                heuristic_applied, len(influencers), task_id,
            )

        # Phase 2: LLM upgrade. Skip if no API key or prompt templates missing.
        if not settings.openai_api_key:
            logger.info("No OpenAI API key, keeping heuristic scores for task %d", task_id)
            return

        from app.prompts import load_prompt
        try:
            business_ctx = load_prompt(f"scraper/_shared/{settings.active_business}.business")
            system = load_prompt("scraper/enrich_results.system", business_context=business_ctx)
        except FileNotFoundError as e:
            logger.warning("Prompt template not found, keeping heuristic scores: %s", e)
            return

        from app.tools.llm_client import chat as llm_chat

        batch_size = 10
        llm_upgraded = 0
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
                    if inf_id is None:
                        continue
                    for inf in batch:
                        if inf.id != inf_id:
                            continue
                        score = item.get("relevance_score")
                        reason = item.get("match_reason")
                        # Only overwrite when both fields look valid. Otherwise
                        # keep the heuristic baseline.
                        if score is not None and reason:
                            inf.relevance_score = float(score)
                            inf.match_reason = str(reason)[:100]
                            llm_upgraded += 1
                        break
                await db.commit()
            except Exception as e:
                logger.warning("LLM enrichment batch failed (heuristic stays): %s", e)
                await db.rollback()

        logger.info(
            "Enrichment done for task %d: %d heuristic / %d LLM-upgraded out of %d",
            task_id, heuristic_applied, llm_upgraded, len(influencers),
        )


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

        # Phase 1/5: starting (0%)
        await update_task_status(db, task, ScrapeTaskStatus.running, progress=0)
        await manager.broadcast("scrape:progress", {
            "task_id": task_id,
            "status": "running",
            "progress": 0,
            "phase": "starting",
            "found_count": 0,
            "valid_count": 0,
        })

        # Phase 2/5: LLM 生成搜索策略 (5%)
        search_queries = await _generate_search_strategy(
            task.industry, platforms, task.target_market, task.competitor_brands
        )
        task.search_keywords = json.dumps(search_queries, ensure_ascii=False)
        await db.commit()

        await update_task_status(db, task, ScrapeTaskStatus.running, progress=5)
        await manager.broadcast("scrape:progress", {
            "task_id": task_id,
            "status": "running",
            "progress": 5,
            "phase": "strategy_ready",
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

                    # Dedup by (platform, profile_url) first — one channel
                    # may expose several emails (business/info/creator), and
                    # we only want one Influencer row per channel. Fall back
                    # to email lookup for legacy rows with no profile_url.
                    existing: Influencer | None = None
                    if profile_url:
                        by_profile = await db.execute(
                            select(Influencer).where(
                                Influencer.platform == plat,
                                Influencer.profile_url == profile_url,
                            )
                        )
                        existing = by_profile.scalar_one_or_none()

                    if existing is None:
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
                        # Broadcast full influencer payload so the 网红数据
                        # page can prepend the row in real time. Only fires on
                        # first insert — re-linking an existing influencer
                        # doesn't broadcast (it's already in the page's list).
                        await manager.broadcast("influencer:created", {
                            "id": inf.id,
                            "nickname": inf.nickname,
                            "email": inf.email,
                            "platform": plat.value,
                            "avatar_url": inf.avatar_url,
                            "profile_url": inf.profile_url,
                            "followers": inf.followers,
                            "industry": inf.industry,
                            "bio": inf.bio,
                            "status": "new",
                            "priority": "medium",
                            "relevance_score": None,
                            "match_reason": None,
                            "reply_intent": None,
                            "reply_summary": None,
                            "follow_up_count": 0,
                            "last_email_sent_at": None,
                            "created_at": (inf.created_at or datetime.now(timezone.utc)).isoformat(),
                            "tags": [],
                        })
                    else:
                        # Back-fill avatar_url when it's missing or historically
                        # corrupted. Pre-fix IG URLs were HTML-escaped ('&amp;')
                        # and 512-truncated — the frontend image proxy rejects
                        # those as 403s. Overwriting only in these two cases
                        # preserves the general upsert policy (bio/followers/
                        # nickname stay untouched for already-known rows).
                        avatar_backfilled = False
                        if avatar_url:
                            old_avatar = existing.avatar_url
                            if not old_avatar or "&amp;" in old_avatar:
                                existing.avatar_url = avatar_url
                                avatar_backfilled = True

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
                        elif avatar_backfilled:
                            await db.commit()
                        valid_total += 1

                    # Phase 3/5: crawling — progress ramps 15% to 80% based on valid emails collected
                    progress = min(79, 15 + int((valid_total / task.target_count) * 65))
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
                        "phase": "crawling",
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
            # Phase 3/5 continues: actual channel crawling now
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "running",
                "progress": 15,
                "phase": "crawling",
                "found_count": 0,
                "valid_count": 0,
            })

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

            # Phase 4/5: LLM enrichment (relevance scoring)
            await update_task_status(db, task, ScrapeTaskStatus.running, progress=85)
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "running",
                "progress": 85,
                "phase": "enriching",
                "found_count": found_total,
                "valid_count": valid_total,
            })

            await _enrich_results(task.id, task.industry, task.target_market)

            # Phase 5/5: completed
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
                "phase": "completed",
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
