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

# CJK = Chinese / Japanese (Hiragana/Katakana/Kanji) / Korean. The ranges below
# cover Hangul, Hiragana, Katakana, CJK Unified Ideographs (incl. Extension A),
# and CJK Compat. We don't differentiate sub-languages here — the only thing
# downstream cares about is "is this query CJK or Latin-script", because IG
# bios in different scripts need different dork limiters and Brave Search's
# index for CJK profiles is much smaller than English.
_CJK_RE = re.compile(
    r"[぀-ヿ"     # Hiragana + Katakana
    r"가-힣"      # Hangul Syllables
    r"㐀-䶿"      # CJK Extension A
    r"一-鿿"      # CJK Unified Ideographs (covers most CN/JP kanji/TW)
    r"豈-﫿"      # CJK Compatibility Ideographs
    r"]"
)


def _is_cjk_text(text: str) -> bool:
    """Returns True if text contains any CJK character.

    Used to decide query-language alignment: if `expected_lang == 'en'` and a
    query contains CJK, the query is dropped (the August 2026 IG bug — LLM
    returned 8 Chinese queries while target_market='us', resulting in 32
    dorks × 0 hits each)."""
    if not text:
        return False
    return _CJK_RE.search(text) is not None


# target_market → expected query language. The mapping is intentionally coarse;
# we only care about the script bucket (en / cn / tw / jp / kr) since that's
# what dork limiters and Brave's index respect.
_MARKET_TO_LANG: dict[str, str] = {
    # English-speaking
    "us": "en", "uk": "en", "au": "en", "ca": "en", "nz": "en",
    "global": "en", "intl": "en", "in": "en",
    # Mandarin (mainland)
    "cn": "cn", "china": "cn", "mainland": "cn",
    # Mandarin (traditional)
    "tw": "tw", "taiwan": "tw", "hk": "tw", "hongkong": "tw", "mo": "tw",
    # Other CJK
    "jp": "jp", "japan": "jp",
    "kr": "kr", "korea": "kr",
}


def _expected_query_lang(industry: str, target_market: str | None) -> str:
    """Decide what language outgoing search queries should be in.

    Priority: target_market wins (it's the explicit user choice for *where*
    we're hunting). If target_market is unset, fall back to the industry
    keyword's script — Chinese industry → Chinese queries, English → English."""
    market = (target_market or "").lower().strip()
    if market in _MARKET_TO_LANG:
        return _MARKET_TO_LANG[market]
    # Unknown / empty market: read from industry script
    if _is_cjk_text(industry or ""):
        return "cn"
    return "en"


def _query_matches_lang(query: str, expected_lang: str) -> bool:
    """Returns True if `query` is in the expected script bucket.

    Rule of thumb:
      - expected 'en' → query must NOT contain CJK (English brand words like
        'GPT', 'Canva' are fine because they're Latin script)
      - expected 'cn'/'tw'/'jp'/'kr' → query MUST contain at least one CJK
        character... EXCEPT when the query is a short proper noun (1-3 words,
        all Latin script). The search-strategy prompt explicitly asks the
        LLM to mix in real KOL handles (`MKBHD`, `Linus Tech Tips`,
        `Marques Brownlee`) and brand names (`ChatGPT`, `Anker`) — these
        are Latin-script proper nouns that work across all languages on
        Brave/YouTube. Pre-fix task #44 (lang=tw) dropped 8/12 valid
        queries because they were KOL names; this short-Latin allowlist
        restores them.
        Long English sentences (4+ words) ARE still rejected — those are
        actual mis-translations the LLM produced when it should have used
        the local language.
    """
    has_cjk = _is_cjk_text(query)
    if expected_lang == "en":
        return not has_cjk
    if has_cjk:
        return True
    # CJK expected, query has no CJK — allow if it looks like a proper noun
    # (1-3 whitespace-separated tokens). 4+ tokens means the LLM tried to
    # write a description in English and forgot to translate.
    return len(query.split()) <= 3


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
    excluded_channels: set[str] | None = None,
    on_progress: "Callable[[str], Awaitable[None]] | None" = None,
) -> None:
    """
    Search YouTube for '{industry} influencer', extract channel About pages for emails.

    `excluded_channels` is a set of full channel URLs (e.g.
    "https://www.youtube.com/@J3M_AI") that the scraper has previously
    successfully extracted emails from. Visiting them again yields no new
    contacts, so they're filtered out of the candidate pool BEFORE visit —
    saving the per-channel budget (~10s) for genuinely new candidates.
    """
    ctx = await _new_context(browser, use_yt_cookies=True)
    page = await ctx.new_page()
    await stealth_async(page)
    excluded = excluded_channels or set()

    try:
        search_queries = queries or [f"{industry} creator contact email"]
        all_channel_links: list[str] = []

        # YouTube is an SPA: search results live inside the `ytInitialData`
        # JS blob, NOT in rendered <a> tags. DOM selectors always returned 0.
        # We regex the canonicalBaseUrl / url occurrences of /@<handle> from
        # the raw HTML — this is resilient to YouTube's DOM schema changes.
        _YT_CHANNEL_PATH_RE = re.compile(r'"(?:canonicalBaseUrl|url)":"(/@[A-Za-z0-9_.\-]+)"')

        # Per-query scroll cap. With early-exit on consecutive zero-growth
        # scrolls, we rarely hit 8 — but the cap is the safety net.
        _MAX_SCROLLS = 8
        # Stop scrolling a single query once 2 consecutive scrolls find no new
        # channels. YouTube's ytInitialData lazy-load typically saturates after
        # 1-2 scrolls; spending the remaining 6 on a query that's already dry
        # is the bug observed in task #23 (8 scrolls all returned 0 new).
        _SCROLL_STALL_THRESHOLD = 2

        for q_idx, query in enumerate(search_queries):
            search_url = f"https://www.youtube.com/results?search_query={query}"
            logger.info("[YouTube] query %d/%d: %r", q_idx + 1, len(search_queries), query)
            if on_progress:
                await on_progress(f"搜索 query {q_idx + 1}/{len(search_queries)}: {query[:50]}")
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning("[YouTube] goto failed for %r: %s — skipping query", query, e)
                continue
            await _random_delay()

            found_this_query: set[str] = set()
            stall_count = 0
            for scroll_i in range(_MAX_SCROLLS):
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
                    "[YouTube] q%d scroll #%d: html_len=%d regex_hits=%d new_channels=%d total_this_query=%d",
                    q_idx + 1, scroll_i + 1, len(html), len(matches), new_count, len(found_this_query),
                )
                if new_count == 0:
                    stall_count += 1
                    if stall_count >= _SCROLL_STALL_THRESHOLD:
                        logger.info(
                            "[YouTube] q%d early-exit scroll: %d consecutive 0-new scrolls",
                            q_idx + 1, stall_count,
                        )
                        break
                else:
                    stall_count = 0
                await page.evaluate("window.scrollBy(0, 1800)")
                await asyncio.sleep(2)

            # Merge into global pool (preserve order = first occurrence wins).
            # No early-break across queries — each query gets a chance to
            # contribute distinct channels even when earlier queries already
            # filled the per-task `target_count * 15` quota.
            for link in found_this_query:
                if link not in all_channel_links:
                    all_channel_links.append(link)

        # ── Cross-task DB dedup ─────────────────────────────────────────
        # Filter out channels we've already extracted emails from in prior
        # tasks. Without this, the candidate pool's first 5-10 entries are
        # always the "old reliables" (J3M_AI, lichangzhanglaile, ...) — the
        # scraper visits them, hits the existing influencer row, and exits
        # via the link-existing path with reused_count++. Net new finds: 0.
        before_filter = len(all_channel_links)
        if excluded:
            all_channel_links = [u for u in all_channel_links if u not in excluded]
        # Shuffle so candidate visit order isn't biased by YouTube's ranking
        # (which puts the same first 5 channels every time for a given query).
        # Without shuffle, the first 5 channel-budget slots burn through the
        # most "front-page" candidates regardless of email hit rate; with
        # shuffle, hit rate evens out across the pool.
        random.shuffle(all_channel_links)

        logger.info(
            "[YouTube] collected %d channels (raw=%d, excluded=%d/%d) across %d queries — shuffled",
            len(all_channel_links), before_filter, before_filter - len(all_channel_links),
            len(excluded), len(search_queries),
        )
        if on_progress:
            await on_progress(
                f"候选池建好: {len(all_channel_links)} 个 channel "
                f"(已过滤 {before_filter - len(all_channel_links)} 个老熟人)"
            )

        # Visit up to 15× the target count. Empirical hit rate:
        #   商业化关键词 (Canva / ChatGPT review): ~35%
        #   AI tools / Notion productivity:          ~20-27%
        # 15× buffer means even a 20% hit rate still delivers target_count.
        # Visit budget hard cap = 200 (was target_count * 15). When stop
        # condition counts only NEW influencers (not duplicates), some
        # tasks need to walk further than the old 15× cap allowed —
        # task #52 hit target with 4 new + 6 reused under the old cap;
        # the new cap gives ~5× more room to find genuine new contacts
        # in industries where the same KOL/MCN reuses one email across
        # multiple channels (cross-channel email collision).
        _MAX_VISIT_CAP = 200
        max_to_visit = min(len(all_channel_links), _MAX_VISIT_CAP)

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

        # NOTE: counter tracks NEW influencers only (target=10 → 10 fresh
        # contacts), not the older "any email" semantics. Reused emails
        # (existing DB rows hit via email-collision) no longer consume
        # the target budget. Backed by on_found's bool return value.
        new_counter = 0
        found_lock = asyncio.Lock()
        stop_event = asyncio.Event()
        sem = asyncio.Semaphore(_CHANNEL_CONCURRENCY)

        async def _process_channel(ch_idx: int, ch_url: str) -> None:
            nonlocal new_counter
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
                        # Broadcast a phase_detail every visit attempt so
                        # the user sees the channel-level work happening.
                        # This is the big "stuck at 15%" fix — without it,
                        # the UI sat on "正在抓取频道并提取邮箱…" for
                        # multiple minutes with no signal anything was alive.
                        if on_progress:
                            handle = ch_url.rsplit("/", 1)[-1]
                            await on_progress(
                                f"访问 channel {ch_idx + 1}/{max_to_visit}: {handle}"
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
                                # on_found returns True only when the
                                # influencer was actually inserted (genuinely
                                # new). Reused / collision emails return False
                                # and don't count toward target — visit
                                # budget keeps walking past the cross-channel
                                # email collisions until target real new
                                # contacts are found OR _MAX_VISIT_CAP hits.
                                is_new = await on_found(
                                    email, name, ch_url,
                                    followers=followers, bio=bio, avatar_url=avatar_url,
                                )
                                if is_new:
                                    async with found_lock:
                                        new_counter += 1
                                        if new_counter >= target_count:
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
            "[YouTube] channel phase done: new=%d / target=%d (visited up to %d)",
            new_counter, target_count, max_to_visit,
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

# Dork templates per script. The "limiter" half (after `"{q}"`) needs to match
# the script of the IG bio we're looking for: an English-language IG creator's
# bio writes "business inquiries" / "for collab"; a Chinese creator writes
# "商务合作" / "合作邮箱"; a Japanese creator writes "お仕事". The pre-fix
# implementation hardcoded the English limiters and produced 0 hits whenever
# the LLM returned non-English queries.
#
# All variants keep `gmail.com` and `email "@"` as universal dorks — those
# strings are language-agnostic and present in any creator's contact info.
# Dork templates per script. The 2026-04-25 5-expert review found that 3 of
# the original 4 templates produced ~0 hits each (e.g. `"Power Bank"
# "business inquiries"` returned 0 across the entire candidate pool while
# `"Power Bank" email "@"` returned 13). Net effect: 75% of Brave quota
# burned for nothing. The slimmer set below keeps:
#   1) email + @ — strong filter that the page actually contains a contact
#   2) bare site limiter — broadest recall, lets `_ig_profile_url_from_href`
#      do the post-filter to keep profile URLs only (drops /p/, /reel/, etc.)
# Local-language `business inquiries` analogues are kept ONLY for non-en
# markets where they actually have a chance of matching CN/JP/KR bios — and
# even there they're gravy on top of `email "@"`.
_IG_DORK_TEMPLATES_EN = (
    'site:instagram.com "{q}" email "@"',
    'site:instagram.com "{q}"',
)
_IG_DORK_TEMPLATES_CN = (
    'site:instagram.com "{q}" email "@"',
    'site:instagram.com "{q}"',
    'site:instagram.com "{q}" "合作"',
)
_IG_DORK_TEMPLATES_TW = (
    'site:instagram.com "{q}" email "@"',
    'site:instagram.com "{q}"',
    'site:instagram.com "{q}" "合作"',
)
_IG_DORK_TEMPLATES_JP = (
    'site:instagram.com "{q}" email "@"',
    'site:instagram.com "{q}"',
    'site:instagram.com "{q}" "お仕事"',
)
_IG_DORK_TEMPLATES_KR = (
    'site:instagram.com "{q}" email "@"',
    'site:instagram.com "{q}"',
    'site:instagram.com "{q}" "협업"',
)


def _ig_dork_templates(lang: str) -> tuple[str, ...]:
    """Pick dork limiters for the script of the queries we're about to run."""
    return {
        "en": _IG_DORK_TEMPLATES_EN,
        "cn": _IG_DORK_TEMPLATES_CN,
        "tw": _IG_DORK_TEMPLATES_TW,
        "jp": _IG_DORK_TEMPLATES_JP,
        "kr": _IG_DORK_TEMPLATES_KR,
    }.get(lang, _IG_DORK_TEMPLATES_EN)

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
    r'https?://(?:www\.)?('
    r'linktr\.ee|beacons\.ai|linkin\.bio|campsite\.bio|bio\.link|'
    r'carrd\.co|lnk\.bio|allmylinks\.com|many\.link|flowcode\.com|'
    # link.me — used by Unbox Therapy and other major KOLs (added 2026-04-25
    # after Apify revealed it's the top aggregator we were missing)
    r'link\.me|'
    # Other aggregators frequently in IG bios
    r'linkpop\.com|snipfeed\.co|contactin\.bio|direct\.me|magic\.ly|'
    r'milkshake\.app|stan\.store|komi\.io|withkoji\.com|tap\.bio|'
    r'pop\.bio|popl\.co|toneden\.io|hypeauditor\.com'
    r')/[A-Za-z0-9._\-]+',
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


async def _search_brave(
    query: str,
    limit: int = 20,
    quota_errors_out: list[dict] | None = None,
) -> list[str]:
    """Brave Search Web API → dedup Instagram profile URL list.

    Requires BRAVE_SEARCH_API_KEY in env. Returns [] when key absent or API
    returns non-200 — the task completes with 0 results rather than
    crashing so ops can diagnose from the log.

    quota_errors_out: when provided, classified errors (auth/quota/rate
    limit) are appended as dicts so the task-level coordinator can surface
    them to the UI as a quota-exhaustion banner. Each entry shape:
      {"service": "brave", "http_code": int, "message": str, "remaining": str | None}
    Non-quota errors (timeout / 5xx / JSON decode) are NOT appended — those
    are transient network issues, not actionable for the user.
    """
    settings = get_settings()
    api_key = (settings.brave_search_api_key or "").strip()
    if not api_key:
        logger.warning(
            "[Instagram] BRAVE_SEARCH_API_KEY not configured — IG scraper cannot "
            "discover profiles. Add the key to server/.env and restart."
        )
        if quota_errors_out is not None:
            # Treat missing key as a config-level "quota" issue too — same UX
            # signal: user has to do something before scraping works again.
            quota_errors_out.append({
                "service": "brave",
                "http_code": 0,
                "message": "BRAVE_SEARCH_API_KEY 未配置，IG 抓取无法发现 profile。请到 https://api.search.brave.com 注册并把 token 配到 server/.env",
                "remaining": None,
            })
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
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        reset = resp.headers.get("X-RateLimit-Reset", "?")
        logger.warning(
            "[Instagram] Brave rate limit hit (monthly quota or QPS). "
            "Remaining=%s Reset=%s",
            remaining, reset,
        )
        if quota_errors_out is not None:
            quota_errors_out.append({
                "service": "brave",
                "http_code": 429,
                "message": (
                    f"Brave Search 配额或速率限制触发（remaining={remaining}, reset={reset}）。"
                    f"如果 remaining=0 → 月配额（2000 query/月）耗尽，到 "
                    f"https://api.search.brave.com 升级套餐；否则等几分钟自动恢复。"
                ),
                "remaining": remaining,
            })
        return profiles
    if resp.status_code in (401, 403):
        logger.warning(
            "[Instagram] Brave auth failed (HTTP %d): %s",
            resp.status_code, resp.text[:200],
        )
        if quota_errors_out is not None:
            quota_errors_out.append({
                "service": "brave",
                "http_code": resp.status_code,
                "message": (
                    f"Brave Search API 鉴权失败（HTTP {resp.status_code}）。"
                    f"BRAVE_SEARCH_API_KEY 可能已失效或被吊销，到 "
                    f"https://api.search.brave.com 重新签发 token 后更新 .env。"
                ),
                "remaining": None,
            })
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
    target_market: str | None = None,
    quota_errors_out: list[dict] | None = None,
) -> list[str]:
    """Generate Google-Dork queries from LLM-suggested seeds (or the raw
    industry keyword as fallback), run them through Brave Search, return
    a dedup profile URL list capped at target_urls.

    Picks dork limiters by language inferred from `target_market` so an EN-only
    creator's "business inquiries" doesn't get searched against a CN keyword's
    page (which is how task #27 produced 32 dorks × 0 hits).

    quota_errors_out: shared list passed down from the task coordinator so
    Brave 429/401/403 errors bubble up to the UI instead of being silently
    swallowed."""
    seeds = [q.strip() for q in (queries or [industry]) if q and q.strip()]
    if not seeds:
        seeds = [industry]

    expected_lang = _expected_query_lang(industry, target_market)
    templates = _ig_dork_templates(expected_lang)

    dorks: list[str] = []
    for q in seeds:
        for tpl in templates:
            dorks.append(tpl.format(q=q))

    all_profiles: list[str] = []
    seen: set[str] = set()

    for i, dork in enumerate(dorks):
        if len(all_profiles) >= target_urls:
            break
        logger.info("[Instagram] search #%d/%d dork=%r", i + 1, len(dorks), dork)

        urls = await _search_brave(dork, limit=20, quota_errors_out=quota_errors_out)
        logger.info(
            "[Instagram] dork #%d: brave=%d total_so_far=%d",
            i + 1, len(urls), len(all_profiles) + sum(1 for u in urls if u not in seen),
        )
        # Early-exit on quota exhaustion: every subsequent dork will hit
        # the same wall, so don't burn the per-task time budget OR get
        # the user another 24 redundant warning entries.
        if quota_errors_out:
            logger.warning(
                "[Instagram] quota error detected (%s) — aborting remaining %d dorks",
                quota_errors_out[-1].get("service"), len(dorks) - i - 1,
            )
            break

        for u in urls:
            if u not in seen:
                seen.add(u)
                all_profiles.append(u)
                if len(all_profiles) >= target_urls:
                    break

        # Brave free tier caps at 1 QPS — stay polite (and under limit).
        await asyncio.sleep(random.uniform(1.1, 1.6))

    logger.info(
        "[Instagram] discovery done: %d unique profile URLs from %d dorks (lang=%s)",
        len(all_profiles), len(dorks), expected_lang,
    )

    # ── Low-hit fallback ───────────────────────────────────────────
    # If LLM-generated queries collectively produced too few IG profiles
    # (because the queries were over-specific niche phrases / had a
    # script mismatch / Brave's IG index just doesn't have the long-tail
    # / etc.), retry with the raw industry keyword and the two universal
    # dorks (`gmail.com` / `email "@"`). Universal dorks don't depend on
    # the page containing language-specific phrases like "business
    # inquiries", so they recover the broad signal even when the
    # targeted dorks miss.
    #
    # Threshold = max(target_urls // 3, 5). Rationale: cross-task
    # dedup downstream typically eliminates 30-60% of the candidate
    # pool when the same industry has been mined before; if discovery
    # collected fewer than ~1/3 of `target_urls`, the post-dedup pool
    # will be tiny. Always trigger when total < 5 even if target_urls
    # itself is small (e.g. target_count=2 → target_urls=30 → threshold
    # 10, but we still want retry on a 4-hit run).
    threshold = max(target_urls // 3, 5)
    if len(all_profiles) < threshold:
        logger.warning(
            "[Instagram] only %d hits across %d dorks (threshold=%d) — "
            "retrying with bare industry %r + universal dorks",
            len(all_profiles), len(dorks), threshold, industry,
        )
        retry_dorks = [
            f'site:instagram.com "{industry}" "gmail.com"',
            f'site:instagram.com "{industry}" email "@"',
        ]
        for retry_dork in retry_dorks:
            if len(all_profiles) >= target_urls:
                break
            if quota_errors_out:
                # Already hit quota on initial dorks — no point retrying.
                break
            logger.info("[Instagram] retry dork: %r", retry_dork)
            urls = await _search_brave(retry_dork, limit=20, quota_errors_out=quota_errors_out)
            logger.info("[Instagram] retry: brave=%d", len(urls))
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    all_profiles.append(u)
                    if len(all_profiles) >= target_urls:
                        break
            await asyncio.sleep(random.uniform(1.1, 1.6))
        logger.info(
            "[Instagram] post-retry total: %d profiles",
            len(all_profiles),
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
    timeout_sec: float = 18.0,
) -> list[str]:
    """Open a Linktree/bio.link/beacons page (public, no login wall) and
    extract emails from its rendered HTML.

    Many aggregators (especially beacons.ai, link.me, stan.store) ship a
    React/Next.js shell where the SSR HTML is ~5KB of bootstrapping code
    and the actual link list — including any contact email — only paints
    after JS hydration. Pre-fix `wait_until=domcontentloaded` + 1.2s
    sleep was too eager: task #40 audit found beacons.ai/ijustine had
    SSR HTML of just 5.9KB and no emails, while linktr.ee/linustech had
    187KB SSR with the email already inline. We now:

      1. wait for `networkidle` (gives React/Next time to fetch the
         link list and inject DOM nodes), with a fallback wait if
         networkidle never fires (some pages keep websockets open)
      2. wait an extra 2s after networkidle for any deferred mailto
         rendering
      3. AS A LAST RESORT, also harvest from a fresh `agg_page.content()`
         AFTER scrolling — some aggregators lazy-render contact cards
         only when they enter the viewport

    timeout_sec defaults to 18s (was 8s) — the budget is per-Linktree-
    visit, dominated by JS hydration cost. Caller can tighten it.
    """
    agg_page: Page | None = None
    try:
        async with asyncio.timeout(timeout_sec):
            agg_page = await ctx.new_page()
            try:
                # Stage 1: navigate. networkidle blocks until 500ms with no
                # in-flight requests; on heavy aggregators that means the
                # initial fetch + React hydration + first link list render
                # all completed. If the page keeps pinging analytics
                # forever, networkidle never fires and we'd hang — the
                # outer asyncio.timeout protects us, plus we lower the
                # navigation timeout itself to ~12s.
                await agg_page.goto(
                    aggregator_url,
                    wait_until="networkidle",
                    timeout=12000,
                )
            except Exception:
                # Fallback: some pages (analytics-heavy) never reach
                # networkidle. Settle for domcontentloaded + sleep.
                try:
                    await agg_page.goto(
                        aggregator_url,
                        wait_until="domcontentloaded",
                        timeout=10000,
                    )
                except Exception as e:
                    logger.debug("[Instagram] aggregator goto failed: %s", e)
                    return []

            # Stage 2: extra settle time for deferred mailto / contact-card
            # rendering. 2s empirically catches ~all React aggregators
            # without bloating per-profile budget.
            await asyncio.sleep(2.0)

            # Stage 3: harvest emails from rendered DOM.
            content = await agg_page.content()
            emails = await asyncio.to_thread(_extract_emails, content)

            # Also check `mailto:` links explicitly — some aggregators put
            # the email only in href="mailto:..." not as visible text, so
            # the text-regex would miss it.
            try:
                mailto_hrefs = await agg_page.eval_on_selector_all(
                    "a[href^='mailto:']",
                    "els => els.map(e => e.href)",
                )
                for href in mailto_hrefs or []:
                    addr = href.split("mailto:", 1)[-1].split("?", 1)[0].strip()
                    if addr and "@" in addr and addr.lower() not in {e.lower() for e in emails}:
                        emails.append(addr)
            except Exception:
                pass

            # Stage 4 (last resort): if still no emails, scroll to trigger
            # lazy-rendering of contact cards lower on the page, then
            # re-harvest. Many beacons.ai / stan.store layouts only render
            # the contact button when it enters viewport.
            if not emails:
                try:
                    await agg_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(1.5)
                    content2 = await agg_page.content()
                    emails = await asyncio.to_thread(_extract_emails, content2)
                except Exception:
                    pass

            return emails
    except Exception as e:
        logger.debug("[Instagram] aggregator %s failed: %s", aggregator_url, e)
        return []
    finally:
        if agg_page is not None:
            try:
                await agg_page.close()
            except Exception:
                pass


async def _scrape_via_apify(
    profile_urls: list[str],
    token: str,
    actor: str,
    quota_errors_out: list[dict] | None = None,
) -> dict[str, dict]:
    """Call Apify's Instagram Profile Scraper to extract bio/email/external_url
    for a batch of profile URLs. Returns a {username: profile_data} dict.

    The 2026-04-25 audit found that IG's SSR HTML hides the contact_email,
    business_email and external_url fields behind a login wall — even
    headlining KOLs like Dave2D (248k followers) and Unbox Therapy (3M)
    return emails=0 from a Playwright SSR scrape. Apify's actor uses a
    different access path (private API / mobile endpoint emulation) and
    returns the full contact set including business_email which is what
    PremLogin actually needs for outreach.

    Each profile data dict has keys (Apify schema):
      - username, fullName, biography, followersCount, profilePicUrl,
        externalUrl, businessEmail, businessPhoneNumber,
        businessCategoryName, isBusinessAccount, ...
    """
    if not profile_urls:
        return {}
    # Apify's instagram-profile-scraper expects `usernames` (plain handles),
    # NOT `directUrls`. Extracting username from each URL.
    usernames: list[str] = []
    for url in profile_urls:
        m = _IG_PROFILE_URL_RE.match(url)
        if m:
            usernames.append(m.group(1).lower())
    if not usernames:
        return {}
    api_url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    payload = {"usernames": usernames}
    # Apify run-sync-get-dataset-items takes 60-180s for 50 profiles, longer
    # under IG anti-bot heat. read=300 gives a comfortable margin. The connect
    # timeout stays short (15s) because Apify is on global Cloudflare —
    # connection itself is fast, all the time is on the actor running.
    timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                api_url,
                params={"token": token},
                json=payload,
            )
    except Exception as e:
        # Use `%r` instead of `%s` because some httpx errors (ReadTimeout,
        # ConnectError) stringify to empty — task #41 was diagnosed by the
        # empty fallback log; we now expose the exception type+repr so
        # the next time it happens we know if it's timeout vs DNS vs auth.
        logger.warning(
            "[Instagram/Apify] request failed: %s: %r",
            type(e).__name__, e,
            exc_info=True,
        )
        return {}

    if resp.status_code >= 400:
        logger.warning(
            "[Instagram/Apify] HTTP %d — %s",
            resp.status_code, resp.text[:300],
        )
        # Classify quota / auth errors so the task coordinator can surface
        # them to the UI. Apify error codes (per official docs):
        #   401: token-not-found / invalid signature
        #   402: payment-required (FREE plan $5 monthly credit exhausted,
        #        or paid plan card declined)
        #   403: forbidden (token lacks scope for this actor)
        #   429: rate-limit (concurrent run cap or QPS)
        # Anything else is a transient network / actor-internal error,
        # not user-actionable — those get logged but not bubbled up.
        if quota_errors_out is not None and resp.status_code in (401, 402, 403, 429):
            messages = {
                401: (
                    f"Apify API token 无效或未找到（HTTP 401）。"
                    f"到 https://console.apify.com/account/integrations 重新签发 token，"
                    f"更新 server/.env 的 APIFY_API_TOKEN 后重启 backend。"
                ),
                402: (
                    f"Apify 月度配额已耗尽（HTTP 402）。"
                    f"FREE plan 是 $5/月，约 100 次 IG 任务的额度。"
                    f"到 https://console.apify.com/billing 查看用量并升级套餐，"
                    f"或者等下个月 1 号自动重置。"
                ),
                403: (
                    f"Apify token 权限不足（HTTP 403），无法调用 actor {actor!r}。"
                    f"检查 token 的 scope，或换一个 actor。"
                ),
                429: (
                    f"Apify 并发或速率限制触发（HTTP 429）。"
                    f"FREE plan 最多 25 个并发 actor run，等几分钟后重试。"
                ),
            }
            quota_errors_out.append({
                "service": "apify",
                "http_code": resp.status_code,
                "message": messages.get(resp.status_code, f"Apify HTTP {resp.status_code}: {resp.text[:200]}"),
                "remaining": None,
            })
        return {}

    try:
        data = resp.json()
    except Exception as e:
        logger.warning("[Instagram/Apify] JSON decode failed: %s", e)
        return {}

    # Apify returns a list of profile data dicts (one per requested URL).
    # Index by username (lowercase) for easy lookup against profile_urls.
    out: dict[str, dict] = {}
    for item in data or []:
        if not isinstance(item, dict):
            continue
        username = (item.get("username") or "").lower()
        if username:
            out[username] = item
    logger.info(
        "[Instagram/Apify] scraped %d/%d profiles",
        len(out), len(profile_urls),
    )
    return out


async def _scrape_instagram_via_apify(
    profile_urls: list[str],
    target_count: int,
    on_found: "Callable[[str, str, str], Awaitable[None]]",
    apify_token: str,
    apify_actor: str,
    browser: Browser,
    quota_errors_out: list[dict] | None = None,
    on_progress: "Callable[[str], Awaitable[None]] | None" = None,
) -> None:
    """Apify-driven IG profile extraction. Replaces Playwright per-profile
    SSR visits with a single Apify batch call that returns full contact
    metadata (incl. businessEmail/externalUrl which IG hides behind login)."""
    # Visit budget cap = 200 (was target_count * 5). The bigger cap matches
    # the YouTube path's _MAX_VISIT_CAP — important now that target counts
    # only NEW influencers (not collisions). Apify still charges per
    # profile but a 200-cap batch on FREE plan is ~$0.10, well within
    # budget for one task.
    max_to_scrape = min(len(profile_urls), 200)
    batch = profile_urls[:max_to_scrape]
    logger.info(
        "[Instagram/Apify] scraping batch of %d profiles (target=%d)",
        len(batch), target_count,
    )
    by_username = await _scrape_via_apify(batch, apify_token, apify_actor, quota_errors_out=quota_errors_out)

    if not by_username:
        logger.warning(
            "[Instagram/Apify] returned 0 profile data items. "
            "Check APIFY_API_TOKEN validity / actor availability / quota."
        )
        return

    # Build a Linktree fallback browser context lazily, only if at least one
    # profile needs it (saves browser launch cost on tasks where every
    # profile already has a businessEmail).
    fallback_ctx: BrowserContext | None = None

    new_counter = 0  # NEW influencers only — see comment in _scrape_youtube
    try:
        for profile_url in batch:
            if new_counter >= target_count:
                break
            m = _IG_PROFILE_URL_RE.match(profile_url)
            if not m:
                continue
            username = m.group(1).lower()
            data = by_username.get(username)
            if not data:
                logger.debug("[Instagram/Apify] no data for %s", username)
                continue

            full_name = (data.get("fullName") or "").strip()
            biography = (data.get("biography") or "").strip()
            followers = data.get("followersCount")
            avatar_url = (data.get("profilePicUrlHD") or data.get("profilePicUrl") or "").strip() or None
            external_url = (data.get("externalUrl") or "").strip()
            business_email = (data.get("businessEmail") or "").strip()
            public_email = (data.get("publicEmail") or "").strip()

            # Email candidates, in priority order:
            #   1) businessEmail field (Apify exposes it directly — IG's
            #      "Email" contact button value)
            #   2) publicEmail field (set on personal accounts that opt in)
            #   3) plain-text emails inside biography
            #   4) Linktree/beacons.ai/etc. aggregator at externalUrl
            emails: list[str] = []
            for direct in (business_email, public_email):
                if direct:
                    emails.extend(_extract_emails(direct))
            if not emails and biography:
                emails = await asyncio.to_thread(_extract_emails, biography)

            # Linktree fallback (only when bio + business_email both empty
            # and externalUrl points to a known aggregator). Saves Playwright
            # cost on profiles that already gave us email via Apify.
            if not emails and external_url and _LINK_AGGREGATOR_RE.match(external_url):
                if fallback_ctx is None:
                    fallback_ctx = await _new_context(browser)
                logger.info(
                    "[Instagram/Apify] %s: no direct email, trying aggregator %s",
                    username, external_url,
                )
                emails = await _scrape_aggregator_emails(fallback_ctx, external_url)

            logger.info(
                "[Instagram/Apify] @%s: followers=%s biz_email=%r emails=%d ext_url=%s",
                username, followers, business_email, len(emails),
                external_url[:80] if external_url else "—",
            )
            if on_progress:
                fol = f"{followers/1000:.0f}K" if isinstance(followers, int) and followers >= 1000 else str(followers or "?")
                await on_progress(
                    f"处理 IG @{username} ({fol} 粉, {len(emails)} 邮箱)"
                )

            for email in emails:
                if "@" not in email:
                    continue
                domain = email.split("@", 1)[1]
                if not await _mx_valid(domain):
                    continue
                display_name = full_name or f"@{username}"
                is_new = await on_found(
                    email,
                    display_name,
                    profile_url,
                    followers=followers if isinstance(followers, int) else None,
                    bio=biography or None,
                    avatar_url=avatar_url,
                )
                if is_new:
                    new_counter += 1
                    if new_counter >= target_count:
                        break
    finally:
        if fallback_ctx is not None:
            try:
                await fallback_ctx.close()
            except Exception:
                pass

    logger.info(
        "[Instagram/Apify] phase done: new=%d / target=%d (scraped %d profiles)",
        new_counter, target_count, len(batch),
    )


async def _scrape_instagram(
    browser: Browser,
    industry: str,
    target_count: int,
    on_found: "Callable[[str, str, str], Awaitable[None]]",
    queries: list[str] | None = None,
    target_market: str | None = None,
    excluded_profiles: set[str] | None = None,
    quota_errors_out: list[dict] | None = None,
    on_progress: "Callable[[str], Awaitable[None]] | None" = None,
) -> None:
    """
    Instagram scraper.

    Strategy (chooses based on settings.apify_api_token):

      Path A — Apify (preferred when token is set, ~40-60% email hit rate):
        1. Brave Search dorks → candidate IG profile URLs (unchanged)
        2. Cross-task DB dedup + shuffle (unchanged)
        3. Batch-call Apify's Instagram Profile Scraper for the candidates
           (one HTTP call per ~50 profiles), get businessEmail + bio +
           externalUrl + followersCount per profile
        4. For profiles where businessEmail is empty but externalUrl points
           to a link aggregator (Linktree/beacons.ai/etc.), Playwright-visit
           that aggregator and harvest emails from there

      Path B — Playwright SSR fallback (when token not set, ~5-10% hit rate):
        1-2 same as Path A
        3. Per profile: Playwright visit → SSR HTML → og:description bio +
           any plain-text email
        4. Linktree fallback if bio has no email

    target_market drives dork limiters (en/cn/tw/jp/kr).
    excluded_profiles cross-task DB dedup filter.
    """
    target_urls = target_count * 15
    excluded = excluded_profiles or set()
    profile_urls = await _discover_ig_profiles(
        industry, queries, target_urls,
        target_market=target_market,
        quota_errors_out=quota_errors_out,
    )
    # Cross-task dedup: filter out profiles whose emails we've already
    # mined.
    before_filter = len(profile_urls)
    if excluded:
        profile_urls = [u for u in profile_urls if u not in excluded]
    random.shuffle(profile_urls)
    logger.info(
        "[Instagram] candidate pool after dedup+shuffle: %d (raw=%d, excluded=%d/%d)",
        len(profile_urls), before_filter, before_filter - len(profile_urls), len(excluded),
    )
    if on_progress:
        await on_progress(
            f"IG 候选池建好: {len(profile_urls)} 个 profile "
            f"(过滤 {before_filter - len(profile_urls)} 个老熟人)"
        )

    if not profile_urls:
        logger.warning(
            "[Instagram] no profile URLs found — search engines returned 0 hits. "
            "Check network / retry with different industry keyword."
        )
        return

    settings = get_settings()
    apify_token = (settings.apify_api_token or "").strip()
    apify_actor = (settings.apify_ig_actor or "apify~instagram-profile-scraper").strip()

    if apify_token:
        logger.info(
            "[Instagram] using Apify path (token configured, actor=%s)",
            apify_actor,
        )
        if on_progress:
            await on_progress(f"调用 Apify 批量抓 {min(len(profile_urls), max(target_count*5, 20))} 个 IG profile…")
        await _scrape_instagram_via_apify(
            profile_urls, target_count, on_found,
            apify_token, apify_actor, browser,
            quota_errors_out=quota_errors_out,
            on_progress=on_progress,
        )
        return

    logger.info(
        "[Instagram] APIFY_API_TOKEN not set — falling back to Playwright SSR "
        "(typical hit rate 5-10%%, vs 40-60%% with Apify). "
        "Configure APIFY_API_TOKEN in .env to enable the high-hit-rate path."
    )
    ctx = await _new_context(browser)
    try:
        # Visit budget cap = 200 (was target_urls = target_count*15). See
        # _scrape_youtube for the rationale — target now counts only NEW
        # influencers so we need more headroom to walk past collisions.
        max_to_visit = min(len(profile_urls), 200)

        # Slightly longer than YouTube's 15s because IG SSR occasionally stalls
        # under heavier reverse-proxy layers (Meta's edge); still short enough
        # that a single slow profile can't starve the task.
        _IG_PROFILE_BUDGET = 18.0
        _IG_CONCURRENCY = 3

        new_counter = 0
        found_lock = asyncio.Lock()
        stop_event = asyncio.Event()
        sem = asyncio.Semaphore(_IG_CONCURRENCY)

        async def _process_profile(idx: int, profile_url: str) -> None:
            nonlocal new_counter
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
                                is_new = await on_found(
                                    email,
                                    meta["name"] or f"@{username}",
                                    profile_url,
                                    followers=meta["followers"],
                                    bio=meta["bio"],
                                    avatar_url=meta["avatar_url"],
                                )
                                if is_new:
                                    async with found_lock:
                                        new_counter += 1
                                        if new_counter >= target_count:
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
            "[Instagram] profile phase done: new=%d / target=%d (visited up to %d)",
            new_counter, target_count, max_to_visit,
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

# ── LLM search-strategy cache ───────────────────────────────────────────
# In-memory cache for `_generate_search_strategy` results, keyed by the
# inputs that actually shape the LLM output. Hits skip the 5-15s LLM call
# entirely — useful during iterative development / debugging when the
# operator runs the same task multiple times. Misses fall through to a
# real LLM call.
#
# We deliberately do NOT include `excluded_channels` in the key — that
# field changes after every successful task as new channels get mined,
# which would invalidate the cache on every run. The LLM uses excluded
# only as a soft hint anyway (the real dedup is downstream).
#
# TTL = 5 minutes: long enough to absorb burst-debug retries, short
# enough that a real "let me try a different approach" run still gets
# a fresh LLM response within the first refill.
import time as _time

_LLM_CACHE_TTL = 300.0
_llm_strategy_cache: dict[tuple, tuple[float, dict[str, list[str]], str | None]] = {}


def _llm_cache_key(industry: str, target_market: str | None, competitor_brands: str | None, platforms: list[str]) -> tuple:
    return (
        (industry or "").strip(),
        (target_market or "").strip().lower(),
        (competitor_brands or "").strip(),
        tuple(sorted(platforms)),
    )


async def _generate_search_strategy(
    industry: str,
    platforms: list[str],
    target_market: str | None = None,
    competitor_brands: str | None = None,
    excluded_channels: list[str] | None = None,
) -> tuple[dict[str, list[str]], str | None]:
    """LLM pre-processing: expand industry keyword into platform-specific search queries.

    Returns `(queries, fallback_reason)`. `fallback_reason` is None on LLM
    success WITH all queries language-aligned. On LLM failure OR script
    mismatch (e.g. LLM returned Chinese queries for target_market='us'),
    the offending queries are dropped and fallback fills in if remaining
    count drops below 3.
    """
    settings = get_settings()
    expected_lang = _expected_query_lang(industry, target_market)

    # ── Cache hit fast path ─────────────────────────────────────────
    # Skip the 5-15s LLM call when the same (industry, market, competitors,
    # platforms) tuple was queried within the TTL window. The fallback_reason
    # is replayed from cache too so the UI's "LLM unreachable" / "drops
    # X/12 queries" warnings stay consistent across cached invocations.
    cache_key = _llm_cache_key(industry, target_market, competitor_brands, platforms)
    cached = _llm_strategy_cache.get(cache_key)
    now = _time.time()
    if cached and now - cached[0] < _LLM_CACHE_TTL:
        # Deep-copy the queries so caller modifications don't pollute
        # the cache. Lightweight: usually 12-16 short strings per platform.
        cached_queries = {k: list(v) for k, v in cached[1].items()}
        logger.info(
            "[scraper] LLM cache HIT (age %.1fs) for industry=%r market=%r — skipped LLM call",
            now - cached[0], industry, target_market,
        )
        return cached_queries, cached[2]

    if not settings.openai_api_key:
        return _fallback_queries(industry, platforms, target_market), "OPENAI_API_KEY 未配置，使用 fallback 多 query 变体"

    from app.prompts import load_prompt
    try:
        business_ctx = load_prompt(f"scraper/_shared/{settings.active_business}.business")
        system = load_prompt("scraper/search_strategy.system", business_context=business_ctx)
    except FileNotFoundError as e:
        logger.warning("Prompt template not found, using fallback: %s", e)
        return _fallback_queries(industry, platforms, target_market), f"Prompt 模板缺失: {e}"

    user_lines = [
        f"Industry keyword: {industry}",
        f"Platforms: {', '.join(platforms)}",
    ]
    if target_market:
        user_lines.append(f"Target market: {target_market}")
    if competitor_brands:
        user_lines.append(f"Competitor brands: {competitor_brands}")
    # CRITICAL hint to the LLM: tell it the expected output language. Without
    # this the LLM tends to follow the Chinese business_context's own language
    # rather than respecting the (industry, target_market) pair — which is how
    # task #27 produced 8 Chinese queries for an English `ai tools` / market=us
    # setup, blowing out the entire IG run.
    user_lines.append(
        f"Expected query language: {expected_lang} "
        f"(en=English-only Latin script; cn=Simplified Chinese; "
        f"tw=Traditional Chinese; jp=Japanese; kr=Korean). "
        f"ALL queries MUST be in this language. Brand names like 'GPT', "
        f"'Canva' may stay in Latin script regardless of language."
    )
    if excluded_channels:
        sample = excluded_channels[:30]
        user_lines.append(
            "Already-mined channels (AVOID generating queries that surface these; "
            "prefer angles, brand variants, languages, or use-cases that would "
            "find different creators): "
            + ", ".join(sample)
            + (f" ... (+{len(excluded_channels) - 30} more)" if len(excluded_channels) > 30 else "")
        )
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
    except Exception as e:
        # Log the FULL exception (type + repr). Empty `str(e)` was the bug
        # behind tasks 14-23: httpx.ConnectError('') showed `fallback: ` with
        # no detail, so nobody noticed the LLM was permanently unreachable.
        reason = f"{type(e).__name__}: {e!r}"
        logger.warning(
            "LLM search strategy failed, using fallback: %s",
            reason,
            exc_info=True,
        )
        return _fallback_queries(industry, platforms, target_market), reason

    # ── Post-validate LLM output: language alignment ─────────────────
    # Even when the API call succeeds, the LLM can return queries in the
    # wrong script. Drop those, and if a platform ends up with <3 valid
    # queries, fill in from fallback (which is now language-aware).
    drop_notes: list[str] = []
    for p in platforms:
        platform_queries = result.get(p, [])
        if not isinstance(platform_queries, list):
            platform_queries = []
        valid = [q for q in platform_queries if isinstance(q, str) and q.strip() and _query_matches_lang(q, expected_lang)]
        dropped = len(platform_queries) - len(valid)
        if dropped > 0:
            drop_notes.append(f"{p}: 丢弃 {dropped}/{len(platform_queries)} 条语言不符 query (期望 lang={expected_lang})")
        if len(valid) < 3:
            fb = _fallback_queries(industry, [p], target_market).get(p, [])
            # Merge: keep LLM's language-aligned queries first, then fill
            # from fallback up to 8 total. dict.fromkeys preserves order.
            merged = list(dict.fromkeys(valid + fb))[:8]
            result[p] = merged
            drop_notes.append(f"{p}: LLM 有效 query 仅 {len(valid)} 条，回退 fallback 补齐到 {len(merged)} 条")
        else:
            result[p] = valid

    fallback_reason = "; ".join(drop_notes) if drop_notes else None
    logger.info(
        "LLM search strategy generated (business=%s, expected_lang=%s, drops=%s): %s",
        settings.active_business, expected_lang, drop_notes or "none", result,
    )
    # Cache the LLM-derived result for 5 minutes — only the hot path
    # gets cached. fallback_reason from drops is preserved so cached
    # replays surface the same drop-count warning.
    _llm_strategy_cache[cache_key] = (now, {k: list(v) for k, v in result.items()}, fallback_reason)
    return result, fallback_reason


# Suffix vocabularies for fallback YouTube queries, per script. The same
# industry word generates structurally distinct queries so the candidate
# pool isn't dominated by a single ranking. Mixing languages was the bug
# behind task #27 — fallback gave the YouTube scraper Chinese suffixes
# while the user wanted US/English IG creators.
_YT_FALLBACK_SUFFIXES_EN = (
    "creator contact email",
    "review",
    "tutorial",
    "best 2026",
    "guide",
    "tips",
    "comparison",
    "for creators",
)
_YT_FALLBACK_SUFFIXES_CN = (
    "创作者 邮箱",
    "评测",
    "教程",
    "推荐",
    "商务合作",
    "懒人包",
    "排行 2026",
    "使用指南",
)
_YT_FALLBACK_SUFFIXES_TW = (
    "創作者 信箱",
    "評測",
    "教學",
    "推薦",
    "商務合作",
    "懶人包",
    "排行 2026",
    "使用指南",
)
_YT_FALLBACK_SUFFIXES_JP = (
    "クリエイター メール",
    "レビュー",
    "使い方",
    "おすすめ",
    "お仕事",
    "ガイド",
    "比較",
    "2026 ランキング",
)
_YT_FALLBACK_SUFFIXES_KR = (
    "크리에이터 이메일",
    "리뷰",
    "사용법",
    "추천",
    "협업 문의",
    "가이드",
    "비교",
    "2026 순위",
)

_YT_FALLBACK_SUFFIXES_BY_LANG = {
    "en": _YT_FALLBACK_SUFFIXES_EN,
    "cn": _YT_FALLBACK_SUFFIXES_CN,
    "tw": _YT_FALLBACK_SUFFIXES_TW,
    "jp": _YT_FALLBACK_SUFFIXES_JP,
    "kr": _YT_FALLBACK_SUFFIXES_KR,
}

_IG_FALLBACK_SUFFIXES_EN = ("creator", "influencer", "review", "tips", "for creators")
_IG_FALLBACK_SUFFIXES_CN = ("创作者", "推荐", "评测", "商务合作", "测评")
_IG_FALLBACK_SUFFIXES_TW = ("創作者", "推薦", "評測", "商務合作", "測評")
_IG_FALLBACK_SUFFIXES_JP = ("クリエイター", "おすすめ", "レビュー", "お仕事", "比較")
_IG_FALLBACK_SUFFIXES_KR = ("크리에이터", "추천", "리뷰", "협업", "비교")

_IG_FALLBACK_SUFFIXES_BY_LANG = {
    "en": _IG_FALLBACK_SUFFIXES_EN,
    "cn": _IG_FALLBACK_SUFFIXES_CN,
    "tw": _IG_FALLBACK_SUFFIXES_TW,
    "jp": _IG_FALLBACK_SUFFIXES_JP,
    "kr": _IG_FALLBACK_SUFFIXES_KR,
}


def _fallback_queries(
    industry: str,
    platforms: list[str],
    target_market: str | None = None,
) -> dict[str, list[str]]:
    """Fallback search queries when the LLM is unavailable OR returns
    language-mismatched output.

    Generates 5-8 diverse variants per platform. Suffixes are picked based
    on the script inferred from `target_market` (or `industry` if market
    isn't set), so an English `ai tools` + market=`us` combo never produces
    Chinese fallback queries — the bug behind task #27.
    """
    result: dict[str, list[str]] = {}
    base = industry.strip()
    expected_lang = _expected_query_lang(industry, target_market)
    for p in platforms:
        if p == "youtube":
            suffixes = _YT_FALLBACK_SUFFIXES_BY_LANG.get(expected_lang, _YT_FALLBACK_SUFFIXES_EN)
            variants = [f"{base} {suffix}" for suffix in suffixes]
            random.shuffle(variants)
            result[p] = variants
        elif p == "instagram":
            # Brave Search is a natural-language engine — preserve spaces.
            # Always include the bare industry as the first variant; it's
            # the most-recall form when later dorks add language-specific
            # limiters.
            suffixes = _IG_FALLBACK_SUFFIXES_BY_LANG.get(expected_lang, _IG_FALLBACK_SUFFIXES_EN)
            variants = [base] + [f"{base} {suffix}" for suffix in suffixes]
            result[p] = variants
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

            # Pass the task-level `industry` explicitly so the LLM treats it
            # as the scoring axis (per enrich_results.system.md), NOT each
            # row's stored `industry` field which can be empty / mismatched
            # for influencers re-discovered across tasks. Without this the
            # LLM falls back to scoring against PremLogin business context
            # and gives non-PremLogin categories (Power Bank etc.) flat 0%.
            user_lines = [f"Industry (scoring axis): {industry}"]
            if target_market:
                user_lines.append(f"Target market: {target_market}")
            user_lines.append("")
            user_lines.append(f"Please score these {len(batch)} influencers:")
            user_lines.append("")
            user_lines.append(json.dumps(profiles, ensure_ascii=False))
            user = "\n".join(user_lines)

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
                            try:
                                score_f = float(score)
                            except (ValueError, TypeError):
                                break
                            # Floor at 0.05 — the prompt explicitly forbids
                            # 0% but some LLMs ignore that. We also clamp
                            # the upper bound to 1.0 in case the model
                            # returns 1.2 / 100 / etc. The heuristic floor
                            # was the intent of the original code; making
                            # it explicit here means a misbehaving LLM
                            # can't sneak a 0% past us (the bug that made
                            # task #35 show 4 zeros for valid contacts).
                            inf.relevance_score = max(0.05, min(1.0, score_f))
                            # Strip negative phrasing the prompt also
                            # forbids — defence in depth in case the LLM
                            # outputs "内容与 PremLogin 无关" anyway.
                            reason_str = str(reason)[:100]
                            if any(bad in reason_str for bad in ("PremLogin 无关", "PremLogin无关", "行业不匹配")):
                                # Substitute a neutral, KOL-quality oriented
                                # reason derived from heuristic data so the
                                # UI doesn't show "PremLogin 无关" anymore.
                                # (Heuristic ran first so inf.match_reason
                                # already has a positive baseline; reuse it.)
                                pass  # keep prior heuristic match_reason
                            else:
                                inf.match_reason = reason_str
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

        # ── Helper: progress broadcast with full counter set ────────────
        # All early-phase events share these zero counters. Centralising
        # avoids the field-drift between phases that bit us during the
        # quota-error rollout (tasks #28-#31 silently dropped fields).
        async def _ph(progress: int, phase: str) -> None:
            await update_task_status(db, task, ScrapeTaskStatus.running, progress=progress)
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "running",
                "progress": progress,
                "phase": phase,
                "found_count": 0,
                "valid_count": 0,
                "new_count": 0,
                "reused_count": 0,
            })

        # Phase 1/9: starting (0%)
        await _ph(0, "starting")

        # ── Background: kick off Playwright launch in parallel with the
        # LLM call below. Browser launch takes 2-3s on a warm machine;
        # running it concurrently with the 5-15s LLM call hides that cost
        # entirely. We hand-roll the lifecycle (start() / stop()) instead
        # of `async with async_playwright()` because that context manager
        # forces the launch into the synchronous code path. The pw + browser
        # tuple is awaited just before we need them (right before the
        # crawl phase).
        async def _start_browser() -> tuple[object, Browser]:
            pw_ctx = await async_playwright().start()
            br = await pw_ctx.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            return pw_ctx, br

        playwright_task = asyncio.create_task(_start_browser())
        # Track the started Playwright pieces so the outer finally below
        # can close them even if the body raises before the inner
        # try/finally would do it.
        pw_for_cleanup: object | None = None
        browser_for_cleanup: Browser | None = None

        # Phase 2/9: querying_history (1%) — DB excluded_channels lookup
        await _ph(1, "querying_history")

        # Phase 3/9: build "excluded channels" — channels we've successfully
        # extracted emails from in prior tasks of the same industry within
        # the last 30 days. Passing these to the LLM (negative context) +
        # the YouTube scraper (hard filter) is the only way to keep new
        # tasks from re-mining the same 18 "old reliables" (the pre-fix
        # behaviour observed in tasks #14-#23).
        #
        # The DB query (~100-500ms on a warm DB) used to run synchronously
        # before the LLM call. With O2 it's a background task that overlaps
        # with the next 50ms of broadcast / LLM-prep work — small win but
        # composes cleanly with O1 cache hits (DB still finishes first).
        from datetime import timedelta

        async def _query_excluded_urls() -> list[str]:
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                stmt = (
                    sa.select(Influencer.profile_url)
                    .where(
                        Influencer.platform.in_([InfluencerPlatform.youtube, InfluencerPlatform.instagram]),
                        Influencer.industry == task.industry,
                        Influencer.created_at >= cutoff,
                        Influencer.profile_url.isnot(None),
                        Influencer.profile_url != "",
                    )
                    .distinct()
                )
                r = await db.execute(stmt)
                return [u for (u,) in r.all() if u]
            except Exception as e:
                logger.warning("[scraper] excluded-channels lookup failed (non-fatal): %s", e)
                return []

        excluded_db_task = asyncio.create_task(_query_excluded_urls())

        # Phase 4/9: llm_thinking (3%) — LLM is about to generate queries.
        # The phase broadcast itself happens *while* the DB excluded query
        # is in flight, hiding its 100-500ms cost.
        await _ph(3, "llm_thinking")

        # Now block on the DB result — usually it's already done because
        # the broadcast above took longer than the SELECT.
        excluded_profile_urls = await excluded_db_task
        logger.info(
            "[scraper] task %d: %d excluded channels (industry=%r, last 30d)",
            task_id, len(excluded_profile_urls), task.industry,
        )

        search_queries, fallback_reason = await _generate_search_strategy(
            task.industry, platforms, task.target_market, task.competitor_brands,
            excluded_channels=excluded_profile_urls,
        )
        task.search_keywords = json.dumps(search_queries, ensure_ascii=False)
        if fallback_reason:
            # Surface the fallback reason on the task. The UI shows
            # error_message in a yellow/red banner — better to admit
            # "LLM unreachable, ran with fallback queries" than to silently
            # produce shallow results.
            task.error_message = f"LLM 搜索策略不可用，使用 fallback 关键词。原因: {fallback_reason}"
        await db.commit()

        # Phase 5/9: strategy_ready (5%)
        await _ph(5, "strategy_ready")

        found_total = 0
        valid_total = 0
        new_total = 0
        reused_total = 0
        # cross-platform dedup by email
        seen_emails: set[str] = set()
        # Pre-load excluded channel URL set (same data we passed to the LLM)
        # for the in-process candidate-pool filter. Stored as a `set` for O(1)
        # membership test inside `_scrape_youtube`.
        excluded_url_set = set(excluded_profile_urls)
        # Quota / auth errors from Brave + Apify get appended here by the
        # platform scrapers. We surface them to the UI at task completion
        # so the user knows whether 0 results = "industry exhausted" or
        # "quota ran out, need to refill credit". An empty list means
        # everything ran with no quota issues.
        quota_errors: list[dict] = []

        platform_map = {
            "instagram": InfluencerPlatform.instagram,
            "youtube": InfluencerPlatform.youtube,
            "tiktok": InfluencerPlatform.tiktok,
            "twitter": InfluencerPlatform.twitter,
            "facebook": InfluencerPlatform.facebook,
        }

        # ── on_progress: phase_detail without changing progress % ───────
        # Inner scrapers (_scrape_youtube / _scrape_instagram) call this
        # at structural milestones — start of each query, candidate-pool
        # ready, per-channel visit. The progress bar's % is driven only
        # by valid emails (on_found increments new_total → progress jumps
        # 21%, 28%, 34%...), but a long stretch with no valid email used
        # to look frozen at 15%. Now `phase_detail` is a free-text status
        # line that updates every 5-15 seconds during the stuck window:
        # "搜索 query 5/12: ChatGPT" / "访问 channel 12/100: @MKBHD".
        async def on_progress(phase_detail: str) -> None:
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "running",
                # Don't bump the progress integer — let on_found drive it.
                "progress": task.progress,
                "phase": "crawling",
                "phase_detail": phase_detail,
                "found_count": found_total,
                "valid_count": valid_total,
                "new_count": new_total,
                "reused_count": reused_total,
            })

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
            ) -> bool:
                """Returns True iff this email was a NEW influencer
                (inserted into DB). False for already-seen-this-task
                emails, or for emails that hit a pre-existing DB row
                (cross-channel email collision → fresh-only skip).

                The return value is what platform scrapers use to
                decide stop-on-target: only NEW finds count against
                the target budget so that target=10 → 10 real new
                contacts, not 4 new + 6 reused (the task #52 problem).
                """
                nonlocal found_total, valid_total, new_total, reused_total

                async with db_lock:
                    if email in seen_emails:
                        return False
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
                        new_total += 1
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
                        # Strict fresh-only mode (default since 2026-04-25):
                        # we no longer link existing influencers to the new
                        # task. The candidate-pool DB filter already excludes
                        # most known channels; this branch only fires on edge
                        # cases (cross-platform email collision, or a channel
                        # that was added between the filter SELECT and the
                        # visit). Counting these as "valid" used to inflate
                        # task results with zero new contacts — task #23
                        # showed valid_count=6 with new_count=0 implicitly.
                        #
                        # Avatar back-fill is still useful (the row is in DB
                        # with stale data), but we no longer create a
                        # scrape_task_influencer link. The task results page
                        # then accurately reflects only fresh discoveries.
                        if avatar_url:
                            old_avatar = existing.avatar_url
                            if not old_avatar or "&amp;" in old_avatar:
                                existing.avatar_url = avatar_url
                                await db.commit()
                        reused_total += 1
                        logger.info(
                            "[scraper] task %d: skipping existing influencer "
                            "(id=%d, email=%s, profile=%s) — fresh-only mode",
                            task_id, existing.id, email, profile_url,
                        )

                    # Progress ramps 15-79% based on `new_total` (NOT
                    # valid_total) so re-discovered influencers don't bump
                    # the bar — the bar reflects genuine new finds toward
                    # target_count.
                    progress = min(79, 15 + int((new_total / task.target_count) * 65))
                    await update_task_status(
                        db, task, ScrapeTaskStatus.running,
                        progress=progress,
                        found_count=found_total,
                        valid_count=valid_total,
                        new_count=new_total,
                        reused_count=reused_total,
                    )
                    await manager.broadcast("scrape:progress", {
                        "task_id": task_id,
                        "status": "running",
                        "progress": progress,
                        "phase": "crawling",
                        "found_count": found_total,
                        "valid_count": valid_total,
                        "new_count": new_total,
                        "reused_count": reused_total,
                        "latest_email": email,
                    })

                # Tell the caller whether this was a fresh insert (existing
                # was None inside the lock) or a fresh-only skip (existing
                # had a row). The scraper uses this to advance the
                # stop-on-target counter only on real new contacts.
                return existing is None

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
                    await _scrape_youtube(
                        browser, industry, target_per_platform, on_found,
                        queries=search_queries.get("youtube"),
                        excluded_channels=excluded_url_set,
                        on_progress=on_progress,
                    )
                elif platform == "instagram":
                    await _scrape_instagram(
                        browser, industry, target_per_platform, on_found,
                        queries=search_queries.get("instagram"),
                        target_market=task.target_market,
                        excluded_profiles=excluded_url_set,
                        quota_errors_out=quota_errors,
                        on_progress=on_progress,
                    )
                else:
                    await _scrape_stub(platform)

        try:
            # Phase 6/9: browser_starting (7%) — wait for the parallel
            # Playwright launch we kicked off above. By now the LLM call
            # finished, so the browser launch (started ~10s earlier in
            # the background) is usually already complete and this `await`
            # returns immediately. Worst case we still need to wait the
            # remaining ~1-2s of browser startup, but that's overlapped
            # with the LLM cost we already paid.
            await _ph(7, "browser_starting")
            try:
                pw, browser = await playwright_task
                pw_for_cleanup = pw
                browser_for_cleanup = browser
            except Exception as exc:
                logger.exception("Playwright launch failed: %s", exc)
                # If the parallel launch crashed, the task can't proceed.
                # Re-raise into the outer except: clause so the task is
                # marked failed with a clear error.
                raise

            try:
                # Phase 7/9: searching (10%) — scrapers are about to make
                # their first HTTP call (YouTube search / Brave dork).
                await _ph(10, "searching")

                # Phase 8/9: crawling (15%) — channel/profile visits start
                await manager.broadcast("scrape:progress", {
                    "task_id": task_id,
                    "status": "running",
                    "progress": 15,
                    "phase": "crawling",
                    "found_count": 0,
                    "valid_count": 0,
                    "new_count": 0,
                    "reused_count": 0,
                })
                await update_task_status(db, task, ScrapeTaskStatus.running, progress=15)

                # Run all platforms concurrently, limited by scrape_concurrency semaphore.
                await asyncio.gather(
                    *[run_platform(browser, p) for p in platforms],
                    return_exceptions=True,
                )
            finally:
                # Tear down browser + pw in reverse-construction order.
                # Wrap each in its own try so a browser-close failure
                # doesn't prevent pw.stop() from running.
                try:
                    await browser.close()
                except Exception as e:
                    logger.warning("[scraper] browser.close() failed: %s", e)
                try:
                    await pw.stop()
                except Exception as e:
                    logger.warning("[scraper] pw.stop() failed: %s", e)
                # Mark as already-cleaned so the outer finally below
                # doesn't try to close them a second time.
                pw_for_cleanup = None
                browser_for_cleanup = None

            # Phase 4/5: LLM enrichment (relevance scoring)
            await update_task_status(db, task, ScrapeTaskStatus.running, progress=85)
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "running",
                "progress": 85,
                "phase": "enriching",
                "found_count": found_total,
                "valid_count": valid_total,
                "new_count": new_total,
                "reused_count": reused_total,
            })

            await _enrich_results(task.id, task.industry, task.target_market)

            # Phase 5/5: completed.
            # If the run hit the LLM fallback path or produced 0 new finds
            # while still being asked for ≥1, append a warning to
            # error_message so the UI can flag "completed but suspicious".
            # We deliberately don't add a new ScrapeTaskStatus value — the
            # existing 4 (pending/running/completed/failed/cancelled) are
            # already wired through the entire stack; surfacing the warning
            # via error_message keeps the change surface small.
            warnings: list[str] = []
            # Quota errors come first because they're the most actionable —
            # the user can't do anything about "industry exhausted" except
            # try a new keyword, but they CAN top up Brave/Apify credit.
            # Dedup by service so we don't emit 24 entries when 24 dorks
            # all hit the same 429.
            seen_services: set[str] = set()
            for qe in quota_errors:
                key = f"{qe.get('service')}:{qe.get('http_code')}"
                if key in seen_services:
                    continue
                seen_services.add(key)
                warnings.append(qe.get("message") or f"{qe.get('service')} 配额异常")
            if fallback_reason:
                warnings.append(f"LLM 搜索策略不可用: {fallback_reason}")
            if new_total == 0 and task.target_count > 0 and not quota_errors:
                warnings.append(
                    "本次未抓到任何新网红("
                    f"复链接 {reused_total} 人，候选池可能已被历史任务穷尽)。"
                    "建议换 industry 关键词或扩大 target_market。"
                )
            elif (
                0 < new_total < task.target_count
                and not quota_errors
            ):
                # Partial completion — visit budget (max 200 candidates)
                # exhausted before hitting target. With the 2026-04-25
                # target-semantics change (target counts only NEW
                # influencers), this surfaces when the candidate pool's
                # email-collision rate is too high to find `target`
                # genuinely new contacts within the visit cap.
                warnings.append(
                    f"目标 {task.target_count} 个新网红，仅找到 {new_total} 个真新人"
                    f" + {reused_total} 个复链接（已遍历候选池上限 200 个 channel）。"
                    "建议换 industry 关键词或扩大 target_market 拓展候选池。"
                )
            warning_message = " | ".join(warnings) if warnings else None

            # Quota-exceeded flag drives the frontend modal popup. Only
            # set when quota_errors is non-empty so a normal-completion
            # task with 0 new finds doesn't trigger the modal — that
            # case uses the existing yellow warning banner.
            quota_exceeded = bool(quota_errors)
            quota_payload = [
                {"service": qe.get("service"),
                 "http_code": qe.get("http_code"),
                 "message": qe.get("message")}
                for qe in quota_errors
                if f"{qe.get('service')}:{qe.get('http_code')}" in seen_services
            ] if quota_exceeded else None

            await update_task_status(
                db, task, ScrapeTaskStatus.completed,
                progress=100,
                found_count=found_total,
                valid_count=valid_total,
                new_count=new_total,
                reused_count=reused_total,
                error_message=warning_message,
            )
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "completed",
                "progress": 100,
                "phase": "completed",
                "found_count": found_total,
                "valid_count": valid_total,
                "new_count": new_total,
                "reused_count": reused_total,
                "warning": warning_message,
                "quota_exceeded": quota_exceeded,
                "quota_errors": quota_payload,
            })
            logger.info(
                "ScrapeTask %d completed: found=%d valid=%d new=%d reused=%d quota_errors=%d warning=%r",
                task_id, found_total, valid_total, new_total, reused_total,
                len(quota_errors), warning_message,
            )

        except Exception as exc:
            logger.exception("ScrapeTask %d failed: %s", task_id, exc)
            # Even on hard failure, surface any quota errors that
            # accumulated before the crash — they're often the actual
            # root cause (e.g. Apify auth failure → empty result →
            # downstream code crashes on missing data). Frontend then
            # shows the modal even on failed tasks.
            failed_seen: set[str] = set()
            failed_quota_payload: list[dict] | None = None
            if quota_errors:
                failed_quota_payload = []
                for qe in quota_errors:
                    key = f"{qe.get('service')}:{qe.get('http_code')}"
                    if key in failed_seen:
                        continue
                    failed_seen.add(key)
                    failed_quota_payload.append({
                        "service": qe.get("service"),
                        "http_code": qe.get("http_code"),
                        "message": qe.get("message"),
                    })
            # error_message: prepend quota messages so the most
            # actionable info is at the top, then the actual exception.
            error_lines: list[str] = []
            if failed_quota_payload:
                for qe in failed_quota_payload:
                    error_lines.append(qe.get("message") or "")
            error_lines.append(str(exc))
            error_message = " | ".join(filter(None, error_lines))[:1000]

            await update_task_status(
                db, task, ScrapeTaskStatus.failed,
                error_message=error_message,
                found_count=found_total,
                valid_count=valid_total,
                new_count=new_total,
                reused_count=reused_total,
            )
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "failed",
                "error": str(exc),
                "found_count": found_total,
                "valid_count": valid_total,
                "new_count": new_total,
                "reused_count": reused_total,
                "quota_exceeded": bool(failed_quota_payload),
                "quota_errors": failed_quota_payload,
            })
        finally:
            # ── Outer Playwright cleanup ─────────────────────────────
            # Three exit paths converge here, in order of likelihood:
            #
            # 1) Inner crawl finally already ran (pw_for_cleanup =
            #    browser_for_cleanup = None) — happy path. Nothing to do.
            #
            # 2) Phase 6 await playwright_task succeeded but the inner
            #    try block raised before the inner finally fired (rare).
            #    pw_for_cleanup / browser_for_cleanup are non-None.
            #    Close them.
            #
            # 3) Phase 6 await playwright_task hadn't returned yet, but
            #    the body raised somewhere else — the parallel launch
            #    might still be in flight. Cancel it; if it already
            #    succeeded into a stray (pw, browser) tuple, salvage
            #    and close.
            if browser_for_cleanup is not None:
                try:
                    await browser_for_cleanup.close()
                except Exception as e:
                    logger.warning("[scraper] outer browser.close() failed: %s", e)
            if pw_for_cleanup is not None:
                try:
                    await pw_for_cleanup.stop()
                except Exception as e:
                    logger.warning("[scraper] outer pw.stop() failed: %s", e)
            elif playwright_task is not None:
                if not playwright_task.done():
                    playwright_task.cancel()
                    try:
                        await playwright_task
                    except (asyncio.CancelledError, Exception):
                        pass
                else:
                    # Done but neither awaited successfully into
                    # *_for_cleanup nor errored before that — i.e. the
                    # body raised between the await and the assignment.
                    # Salvage and clean.
                    if playwright_task.exception() is None:
                        try:
                            stray_pw, stray_browser = playwright_task.result()
                            try:
                                await stray_browser.close()
                            except Exception:
                                pass
                            try:
                                await stray_pw.stop()
                            except Exception:
                                pass
                        except Exception:
                            pass
