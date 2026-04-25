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


# Cheap relevance gate that runs at visit time, before on_found writes
# to DB. Catches the most common failure mode the LLM-based enrichment
# already flags: SERP returned a creator whose channel is unrelated to
# the requested industry (travel / lifestyle / news outlet / gaming
# bio with no AI / Notion / Power Bank signal). Without this gate
# those channels enter the DB at relevance_score 5-15% and clutter
# the operator's outreach list.
#
# 2026-04-25 relaxed (task #65 root-cause work): of the 7 channels in
# task #65 that had emails, 5 were rejected (71% kill rate) — most were
# real Chinese AI-tool creators whose bio used adjacent vocabulary
# ('联系合作', '商务', '硬核知识') instead of the literal industry
# tokens ('ai', '工具'). Fix:
#   - lower follower bypass 50K → 5K (niche creators with verified
#     contact intent shouldn't need 50K subs to qualify)
#   - bypass when bio carries any business-intent signal (collab /
#     business / contact / 合作 / 商务 / email / inquiry / 邮箱 / 联系)
#     — these are explicit "I want to be contacted" markers and the
#     creator has self-selected as outreach-receptive regardless of
#     whether their bio happens to contain the literal industry word
# Result on the #65 sample: 黑魔法 (bio: '联系方式...') would now
# pass; only truly off-topic English vlog channels still get rejected.
#
# Conservative by design — `False` (reject) only fires when ALL of:
#   - industry is non-empty AND has at least one usable token
#   - bio + nickname together produce a non-empty searchable string
#   - followers is below `follower_bypass` (default 5K)
#   - bio carries no business-intent signal
#   - none of the industry tokens appear in bio/nickname
# When the data is incomplete (no bio, no industry, all tokens too
# short) the gate passes, deferring the decision to LLM enrichment.
_RELEVANCE_TOKEN_SPLIT_RE = re.compile(r"[\s　_\-/、，,/]+")
_RELEVANCE_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")
_BUSINESS_INTENT_RE = re.compile(
    r"collab|business|sponsor|partner|contact|inquir|brand deal|"
    r"合作|商务|商業|聯絡|联系|邮箱|信箱|郵箱|協作|协作|お仕事|협업|문의",
    re.IGNORECASE,
)


def _industry_relevance_prefilter(
    industry: str | None,
    bio: str | None,
    nickname: str | None,
    followers: int | None,
    *,
    follower_bypass: int = 5_000,
) -> bool:
    """Return True (keep) iff this channel plausibly matches `industry`."""
    if not industry or not industry.strip():
        return True
    if followers and followers >= follower_bypass:
        return True

    text = f"{bio or ''} {nickname or ''}".lower()
    if not text.strip():
        return True

    # Business-intent bypass: a creator who explicitly invites
    # collaboration / lists a contact email is a viable outreach target
    # even when the bio uses adjacent vocabulary instead of the literal
    # industry tokens. LLM enrichment downstream will score the actual
    # topic match.
    if _BUSINESS_INTENT_RE.search(text):
        return True

    raw_tokens = _RELEVANCE_TOKEN_SPLIT_RE.split(industry.lower())
    has_meaningful_token = False
    for tok in raw_tokens:
        tok = tok.strip()
        if not tok:
            continue
        if _RELEVANCE_CJK_RE.search(tok):
            has_meaningful_token = True
            if tok in text:
                return True
        elif len(tok) >= 2:
            has_meaningful_token = True
            if re.search(rf"\b{re.escape(tok)}\b", text):
                return True

    if not has_meaningful_token:
        # industry tokenises to nothing usable (single-char Latin etc.) —
        # we have no signal to filter on, so let it through.
        return True
    return False


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
        # Stop scrolling a single query once N consecutive scrolls find no
        # new channels. YouTube's ytInitialData lazy-load is bursty —
        # sometimes scroll #2 returns 0 new but scroll #3 picks up another
        # batch (especially on date-desc / saturated industries where
        # YouTube interleaves promoted+relevant blocks). Threshold raised
        # 2 → 3 (2026-04-25) to give each query one more chance before
        # bailing; the per-query cost grows by ~3s when the threshold
        # actually kicks in but candidate-pool size grows ~10-15% on
        # already-saturated industries (where every extra channel
        # matters most).
        _SCROLL_STALL_THRESHOLD = 3

        # YouTube `sp=` filter codes (URL-encoded). When DB already has many
        # known channels for this industry, the default-sort SERP keeps
        # returning the same head-of-tail. Adding "upload-date desc" gives
        # us a different slice (recent uploads → smaller / newer channels)
        # without doubling the LLM cost. We only run the date variant on
        # the first 4 queries (brand category) to cap added latency at
        # ~4 × (goto + scroll + delay) ≈ 30s extra.
        _SP_DEFAULT = ""
        _SP_UPLOAD_DATE_DESC = "&sp=CAI%253D"
        _DATE_VARIANT_QUERY_COUNT = 4

        # Saturation-aware variant gate: only fan out to date-desc when this
        # industry has already saturated the default SERP (i.e. we know
        # about ≥ 20 channels for it from prior tasks). For first-time /
        # rare-industry runs, the candidate pool from the default sort is
        # already plenty, and the date variant adds ~1 min of search time
        # for marginal new channels. This makes the multi-keyword usage
        # path (every task is a new industry) ~25% faster without hurting
        # the saturated-industry path.
        _SERP_SATURATION_THRESHOLD = 20
        _serp_saturated = len(excluded) >= _SERP_SATURATION_THRESHOLD
        logger.info(
            "[YouTube] SERP variant mode: %s (excluded=%d, threshold=%d)",
            "saturated → +date-desc" if _serp_saturated else "fresh → default-only",
            len(excluded), _SERP_SATURATION_THRESHOLD,
        )

        # Estimated total SERP scrolls for the search phase. Search owns
        # progress 0-30%, mapped to cumulative scroll count linearly.
        # We use 3 scrolls/query (the empirical average — stall threshold
        # cuts most queries off after the 3rd scroll) so the bar can
        # actually reach 30 by the end of search. If a run completes
        # fewer scrolls than estimated, the candidate-pool-ready push
        # (smooth-walk to 30 below) fills any remaining gap.
        _AVG_SCROLLS_PER_QUERY = 3
        n_search_passes = len(search_queries)
        if _serp_saturated:
            n_search_passes += min(_DATE_VARIANT_QUERY_COUNT, len(search_queries))
        estimated_total_scrolls = max(1, n_search_passes * _AVG_SCROLLS_PER_QUERY)
        cumulative_scrolls = 0
        last_pushed_search_progress = 0

        for q_idx, query in enumerate(search_queries):
            # Two passes for the first 4 queries when SERP is saturated:
            # default sort + upload-date. The rest run default-only. Both
            # passes contribute to the cross-query global pool, so duplicate
            # channels (same channel appears in both passes) get naturally
            # deduped on insert.
            if q_idx < _DATE_VARIANT_QUERY_COUNT and _serp_saturated:
                sp_variants = [(_SP_DEFAULT, "default"), (_SP_UPLOAD_DATE_DESC, "date-desc")]
            else:
                sp_variants = [(_SP_DEFAULT, "default")]

            for sp_param, sp_label in sp_variants:
                search_url = f"https://www.youtube.com/results?search_query={query}{sp_param}"
                logger.info(
                    "[YouTube] query %d/%d (%s): %r",
                    q_idx + 1, len(search_queries), sp_label, query,
                )
                if on_progress:
                    # Phase_detail tag for the UI's status line. Progress
                    # is pushed per-scroll below (not per-query) so the
                    # bar advances continuously through the SERP loop.
                    await on_progress(
                        f"搜索 query {q_idx + 1}/{len(search_queries)} ({sp_label}): {query[:50]}"
                    )
                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    logger.warning("[YouTube] goto failed for %r (%s): %s — skipping variant", query, sp_label, e)
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
                        "[YouTube] q%d/%s scroll #%d: html_len=%d regex_hits=%d new_channels=%d total_this_query=%d",
                        q_idx + 1, sp_label, scroll_i + 1, len(html), len(matches), new_count, len(found_this_query),
                    )

                    # Per-scroll progress push (search phase 0→30%). Each
                    # completed scroll is a real unit of work — that's
                    # what the user considers "actual execution" — so
                    # progress advances strictly by completed scroll
                    # count. Push only when the integer progress
                    # actually changes — avoids spamming WebSocket with
                    # redundant same-value events.
                    cumulative_scrolls += 1
                    target_search_progress = min(
                        29,
                        int(cumulative_scrolls / estimated_total_scrolls * 30),
                    )
                    if on_progress and target_search_progress > last_pushed_search_progress:
                        last_pushed_search_progress = target_search_progress
                        await on_progress(
                            f"搜索 query {q_idx + 1}/{len(search_queries)} ({sp_label}): {query[:50]} · scroll {scroll_i + 1}",
                            target_search_progress,
                        )

                    if new_count == 0:
                        stall_count += 1
                        if stall_count >= _SCROLL_STALL_THRESHOLD:
                            logger.info(
                                "[YouTube] q%d/%s early-exit scroll: %d consecutive 0-new scrolls",
                                q_idx + 1, sp_label, stall_count,
                            )
                            break
                    else:
                        stall_count = 0
                    await page.evaluate("window.scrollBy(0, 1800)")
                    await asyncio.sleep(2)

                # Merge into global pool (preserve order = first occurrence wins).
                # No early-break across queries — each query/variant gets a
                # chance to contribute distinct channels even when earlier
                # ones already filled the per-task quota.
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
            # Smooth catch-up from wherever the scroll loop got us to up
            # to 30. Stall-driven early exits often leave us at e.g. 22
            # (cumulative=36 / estimated=48 = 22%); jumping straight to
            # 30 would skip 7 numbers. Walk 23,24,...,30 at 50ms/digit
            # so every number is visible. Keep `last_pushed_search_progress`
            # as the lower bound so we don't double-emit numbers we
            # already broadcast during the scroll loop.
            for _walk_p in range(last_pushed_search_progress + 1, 30):
                await on_progress(
                    f"搜索完成，整理候选池 ({_walk_p}%)",
                    _walk_p,
                )
                await asyncio.sleep(0.05)
            # Final commit at 30 with the real candidate-pool message.
            await on_progress(
                f"候选池建好: {len(all_channel_links)} 个 channel "
                f"(已过滤 {before_filter - len(all_channel_links)} 个老熟人)",
                30,
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
        visited_counter = 0
        found_lock = asyncio.Lock()
        stop_event = asyncio.Event()
        sem = asyncio.Semaphore(_CHANNEL_CONCURRENCY)

        # Hit-rate-aware early stop. When the candidate pool is mostly
        # weak-relevance channels (LLM gave fictional KOL names → SERP
        # returned random non-business creators), continuing to visit is
        # marginal-return. Threshold: 8× target visits with < target/2
        # genuine hits → bail out. For target=10, that's "after 80
        # visits if we still have <5 new, stop and surface partial
        # result". Beats waiting another 80 visits to maybe find one
        # more contact.
        _LOW_HIT_VISITS_THRESHOLD = max(80, target_count * 8)
        _LOW_HIT_NEW_THRESHOLD = max(1, target_count // 2)

        async def _process_channel(ch_idx: int, ch_url: str) -> None:
            nonlocal new_counter, visited_counter
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
                        # Note: the per-visit phase_detail push moved to
                        # the finally block (uses visited_counter, which
                        # is monotonic). Pushing on entry used ch_idx+1
                        # (candidate-pool position), which doesn't agree
                        # with finally's visited_counter under
                        # concurrency=3 — users saw "channel 14" then
                        # "channel 13" because two coroutines were
                        # racing on different counters.
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

                        # Visit-time relevance gate. If the channel's bio +
                        # nickname don't carry any industry token (and
                        # followers < 50K so the size bypass doesn't apply),
                        # skip on_found entirely so the channel never lands
                        # in DB with a 5-15% relevance score that the user
                        # has to clean up manually. The gate is conservative
                        # — small-size channels with NO industry signal at
                        # all are the only thing it rejects. LLM enrichment
                        # still grades everything that passes.
                        if emails and not _industry_relevance_prefilter(
                            industry, bio, name, followers,
                        ):
                            logger.info(
                                "[YouTube] [%d] prefilter REJECT (industry=%r, "
                                "followers=%s, bio_excerpt=%r) — skip on_found",
                                ch_idx + 1, industry, followers, (bio or "")[:80],
                            )
                            emails = []  # nothing to insert; visited_counter still bumps below

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
                # Hit-rate gate: every visit (success or failure) bumps
                # visited_counter. After a low-hit-rate threshold, bail
                # rather than keep grinding through a candidate pool the
                # LLM filled with fictional KOL names. Task #55 walked
                # 166/176 visits to find 10 new — a 6% hit rate. With the
                # gate, we'd stop at ~80 visits if we still had < 5 new,
                # surfacing the partial result fast.
                async with found_lock:
                    visited_counter += 1
                    # Per-visit progress push so the bar advances even when
                    # this channel had no email / was a reused-skip / was
                    # prefilter-rejected. Visit phase owns 30-79% — visit
                    # ratio fills the band roughly linearly, with new-finds
                    # in on_found doing the same; on_progress's monotonic
                    # gate ensures whichever is higher wins.
                    visit_ratio = visited_counter / max(1, max_to_visit)
                    new_ratio = new_counter / max(1, target_count)
                    visit_progress = min(79, 30 + int(max(visit_ratio, new_ratio) * 49))
                    if on_progress:
                        # Include the handle so the user sees which
                        # channel just finished. visited_counter is the
                        # monotonic completed-count (1, 2, 3, ...) — the
                        # handle is the channel that just produced this
                        # completion, not the channel at slot
                        # visited_counter in the candidate pool. Under
                        # concurrency=3 those don't 1:1 map, but the
                        # visual contract the user wants is "see a
                        # number that goes up + see what just got
                        # visited" — both satisfied here.
                        handle = ch_url.rsplit("/", 1)[-1]
                        await on_progress(
                            f"访问 channel {visited_counter}/{max_to_visit}: {handle}",
                            visit_progress,
                        )
                    if (
                        not stop_event.is_set()
                        and visited_counter >= _LOW_HIT_VISITS_THRESHOLD
                        and new_counter < _LOW_HIT_NEW_THRESHOLD
                    ):
                        logger.warning(
                            "[YouTube] hit-rate gate: visited=%d new=%d (<%d) — early-stop",
                            visited_counter, new_counter, _LOW_HIT_NEW_THRESHOLD,
                        )
                        if on_progress:
                            await on_progress(
                                f"候选池命中率低（已查 {visited_counter} 个频道仅 {new_counter} 新人），提前结束"
                            )
                        stop_event.set()
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
        # IG search-phase done. Bump the bar to 30% to mirror YouTube's
        # search→visit handover, so phase=searching ends and the visit
        # band (30-79%) takes over.
        await on_progress(
            f"IG 候选池建好: {len(profile_urls)} 个 profile "
            f"(过滤 {before_filter - len(profile_urls)} 个老熟人)",
            30,
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
# 2026-04-25: `excluded_count` IS in the key now. The hard-blacklist
# rule in the system prompt means cached query sets become invalid
# the moment the blacklist grows (e.g. after a successful task adds
# 9 channels to DB, the next task's blacklist is +9 longer). Replaying
# the old query set would silently violate the blacklist and re-surface
# just-mined KOLs. Trade-off: cache hit rate drops to "burst-retry only"
# (same task fired twice within TTL before any new channels saved).
#
# TTL = 5 minutes: long enough to absorb burst-debug retries, short
# enough that a real "let me try a different approach" run still gets
# a fresh LLM response within the first refill.
import time as _time

_LLM_CACHE_TTL = 300.0
_llm_strategy_cache: dict[tuple, tuple[float, dict[str, list[str]], str | None]] = {}


def _llm_cache_key(
    industry: str,
    target_market: str | None,
    competitor_brands: str | None,
    platforms: list[str],
    excluded_count: int = 0,
) -> tuple:
    # `excluded_count` enters the key so a task that adds new mined
    # channels invalidates cached query sets generated under the old
    # blacklist. Without this, the LLM's hard-blacklist rule (#8 in the
    # system prompt) would be silently bypassed by replaying a cached
    # set that pre-dates the latest mined channels.
    return (
        (industry or "").strip(),
        (target_market or "").strip().lower(),
        (competitor_brands or "").strip(),
        tuple(sorted(platforms)),
        excluded_count,
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
    cache_key = _llm_cache_key(
        industry, target_market, competitor_brands, platforms,
        excluded_count=len(excluded_channels) if excluded_channels else 0,
    )
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
            "Already-mined channels (HARD BLACKLIST — see system prompt rule #8; "
            "any query that would surface these is invalid): "
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

    # ── Post-validate LLM output: language alignment + blacklist match ─
    # Even when the API call succeeds, the LLM can return:
    #   - queries in the wrong script (drop)
    #   - bare KOL/brand names that exactly match an already-mined channel
    #     name (drop — task #65 saw 4/15 queries fall into this trap;
    #     each wasted SERP slot returned 1-6 unique channels, mostly
    #     the same KOL we already had)
    # Build a normalized blacklist set from the `Already-mined channels`
    # the caller passed via `excluded_channels` (entries are formatted as
    # `"<nickname> (<url>)"` or just `"<url>"` when nickname is missing).
    excluded_nick_norms: set[str] = set()
    if excluded_channels:
        nick_extract_re = re.compile(r"^(.+?)\s*\(https?://")
        for entry in excluded_channels:
            m = nick_extract_re.match(entry)
            if m:
                # normalize: lower + strip ascii/full-width whitespace +
                # collapse all internal whitespace. Matches the same
                # normalization rule used elsewhere in this module so a
                # KOL nickname `Matt Wolfe` blocks queries `matt wolfe`,
                # `MattWolfe`, `Matt  Wolfe`, etc.
                norm = re.sub(r"[\s　]+", "", m.group(1).strip().lower())
                if norm:
                    excluded_nick_norms.add(norm)

    def _is_blacklisted_query(q: str) -> bool:
        norm = re.sub(r"[\s　]+", "", q.strip().lower())
        return norm in excluded_nick_norms

    drop_notes: list[str] = []
    for p in platforms:
        platform_queries = result.get(p, [])
        if not isinstance(platform_queries, list):
            platform_queries = []
        valid: list[str] = []
        blacklist_hits: list[str] = []
        for q in platform_queries:
            if not isinstance(q, str) or not q.strip():
                continue
            if not _query_matches_lang(q, expected_lang):
                continue
            if _is_blacklisted_query(q):
                blacklist_hits.append(q)
                continue
            valid.append(q)
        if blacklist_hits:
            drop_notes.append(
                f"{p}: 丢弃 {len(blacklist_hits)} 条命中黑名单 KOL 的 query "
                f"({', '.join(blacklist_hits[:3])}{'...' if len(blacklist_hits) > 3 else ''})"
            )
        dropped = len(platform_queries) - len(valid) - len(blacklist_hits)
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
    on_progress: "Callable[[str, int | None], Awaitable[None]] | None" = None,
) -> list[str]:
    """Two-phase scoring: always assign a heuristic score first so every
    influencer has a relevance_score / match_reason. Then, if OpenAI is
    configured, upgrade each batch with an LLM score.

    Returns a list of human-readable failure reasons (one per failed LLM
    batch / blocked stage). Empty list = clean run. Caller appends these
    to task.error_message so the UI can show "completed but X batches
    used heuristic scoring instead of LLM" — previously these failures
    were swallowed and only visible in server logs.

    `on_progress` is the same callback used by platform scrapers; we
    drive enrichment progress 80→85% as influencers are scored, so the
    bar continues to advance during the LLM-grade phase rather than
    sitting at 79 while the user waits 5-15 seconds for batch responses.
    """
    failures: list[str] = []
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
            return failures

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
            failures.append("评分降级：未配置 OPENAI_API_KEY，使用启发式评分")
            return failures

        from app.prompts import load_prompt
        try:
            business_ctx = load_prompt(f"scraper/_shared/{settings.active_business}.business")
            system = load_prompt("scraper/enrich_results.system", business_context=business_ctx)
        except FileNotFoundError as e:
            logger.warning("Prompt template not found, keeping heuristic scores: %s", e)
            failures.append(f"评分降级：评分 prompt 模板缺失 ({e})")
            return failures

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
                    # 600 chars covers the partnership / business inquiry
                    # block that mid-tier KOLs put at the END of their bio
                    # (after intro / weekly schedule / etc.). The previous
                    # 200-char cut frequently lopped that off, leaving the
                    # LLM blind to the strongest collaboration signal and
                    # producing softer scores for genuinely-business-ready
                    # creators. 600 is still well under classifier model
                    # context limits even with batch=10.
                    "bio": (inf.bio or "")[:600],
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
                failures.append(f"评分批次 {i // batch_size + 1} 调用 LLM 失败 ({type(e).__name__}: {e})，已使用启发式分数兜底")
                await db.rollback()

            # Per-batch progress push: enrichment owns 80→85%. Each
            # completed batch (success or failed-but-still-counts) bumps
            # the bar one notch closer to 85, so the user sees the LLM
            # grading is alive instead of staring at a stuck 79%.
            if on_progress:
                batch_idx = i // batch_size + 1
                total_batches = max(1, (len(influencers) + batch_size - 1) // batch_size)
                ench_progress = min(85, 80 + int((batch_idx / total_batches) * 5))
                await on_progress(
                    f"评分批次 {batch_idx}/{total_batches}",
                    ench_progress,
                )

        logger.info(
            "Enrichment done for task %d: %d heuristic / %d LLM-upgraded out of %d",
            task_id, heuristic_applied, llm_upgraded, len(influencers),
        )
        return failures


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
        # Pre-flight phases all push progress=0 — the user considers
        # querying_history / llm_thinking / strategy_ready / browser_starting
        # as "preparation" not "task execution". Real progress only starts
        # when the search SERP loop produces its first scroll worth of
        # candidates (see _scrape_youtube). Phase_detail still updates so
        # the UI shows what's happening behind the 0%.
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
        await _ph(0, "querying_history")

        # Phase 3/9: build "excluded channels" — channels whose emails we've
        # already mined in prior tasks of the SAME industry within the last
        # 30 days. Passing this to the LLM (negative context) + the scraper
        # (hard filter on the candidate pool) keeps new tasks from re-visiting
        # the same "old reliables".
        #
        # 2026-04-25 reverted from "all-time + all-industry" back to this
        # narrow window. The wider filter was reactive over-correction for
        # task #53's reused=30: by excluding every known channel across all
        # industries, the candidate pool shrank to the URL-fresh tail of
        # SERP — which on saturated industry/market combos (AI 工具/tw after
        # 13 runs) is mostly non-business channels with 0 emails. Net effect
        # was new=0 + reused=39 (when the SQLAlchemy race below let the
        # filter run no-op anyway). Narrow filter accepts some reused as
        # the price for keeping cross-industry rescans + a wider candidate
        # pool that still surfaces fresh contacts on the long tail.
        #
        # Race fix (paired): _query_excluded_urls runs in a *separate*
        # AsyncSession (AsyncSessionLocal()), not the main `db` session.
        # The previous code shared `db` between this background task and
        # the concurrent _ph(...) → update_task_status → db.commit() path,
        # which SQLAlchemy AsyncSession rejects as
        # "concurrent operations are not permitted". The except branch
        # silently returned [], so URL filtering became a no-op. With
        # a private side session there's no contention.
        # Normalize industry name: lower + strip whitespace.
        # Without this, 'AI 工具' / 'AI工具' / 'ai工具' / 'AI TOOLS' / 'AI tools'
        # are treated as 4 different industries by SQL `=`, so a user
        # running 'AI 工具' would not see channels mined under 'ai工具'
        # in the excluded set — and re-visit them on every task.
        # Task #55 produced 7 such "false-fresh" reused channels purely
        # from this string-mismatch.
        def _norm_industry(s: str | None) -> str:
            return (s or "").lower().replace(" ", "").replace("　", "")

        normalized_target_industry = _norm_industry(task.industry)

        async def _query_excluded_urls() -> list[tuple[str, str | None]]:
            from datetime import timedelta
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                # SQLite's lower() handles ASCII case fold; non-ASCII
                # (CJK) compares byte-equal anyway. Strip only ASCII
                # spaces here — full-width whitespace handled in Python
                # post-filter below.
                stmt = (
                    sa.select(Influencer.profile_url, Influencer.nickname, Influencer.industry)
                    .where(
                        Influencer.platform.in_([InfluencerPlatform.youtube, InfluencerPlatform.instagram]),
                        Influencer.created_at >= cutoff,
                        Influencer.profile_url.isnot(None),
                        Influencer.profile_url != "",
                    )
                    .distinct()
                )
                async with AsyncSessionLocal() as side_db:
                    r = await side_db.execute(stmt)
                    rows = r.all()
                # Apply normalized industry filter in Python so the same
                # rule (lower + strip) covers all the unicode whitespace
                # variants we've seen in user input ('AI 工具' with space,
                # 'AI　工具' with full-width, 'AI工具' no space, 'ai工具'
                # all-lower, 'AI TOOLS' all-upper).
                return [
                    (u, n) for (u, n, ind) in rows
                    if u and _norm_industry(ind) == normalized_target_industry
                ]
            except Exception as e:
                logger.warning("[scraper] excluded-channels lookup failed (non-fatal): %s", e)
                return []

        excluded_db_task = asyncio.create_task(_query_excluded_urls())

        # Phase 4/9: llm_thinking (3%) — LLM is about to generate queries.
        # The phase broadcast itself happens *while* the DB excluded query
        # is in flight, hiding its 100-500ms cost.
        await _ph(0, "llm_thinking")

        # Now block on the DB result — usually it's already done because
        # the broadcast above took longer than the SELECT.
        excluded_pairs: list[tuple[str, str | None]] = await excluded_db_task
        excluded_profile_urls = [u for (u, _) in excluded_pairs]
        # Pass (nickname, url) pairs to the LLM so it can recognise and
        # avoid known KOLs by name (the URL alone is harder to map back
        # to the creator the LLM is being asked to skip).
        excluded_for_llm = [
            f"{n} ({u})" if n else u
            for (u, n) in excluded_pairs
        ]
        logger.info(
            "[scraper] task %d: %d excluded channels (industry=%r, last 30d)",
            task_id, len(excluded_profile_urls), task.industry,
        )

        # Saturation early warning: when the in-DB exclusion set has grown
        # to >= 100 distinct profile_urls for this industry within 30 days,
        # the candidate pool YouTube SERP can produce is largely already
        # mined. The task will still complete but is statistically likely
        # to return < target new contacts (task #65 root cause: 144
        # excluded → only 2/10 new found). Push a `scrape:saturation`
        # event NOW (before the 6-7 minute crawl) so the operator can
        # cancel and switch keywords instead of waiting for the
        # post-completion warning. The warning is also persisted to
        # error_message so it survives page reload.
        _SATURATION_THRESHOLD = 100
        saturation_warning: str | None = None
        if len(excluded_profile_urls) >= _SATURATION_THRESHOLD:
            saturation_warning = (
                f"⚠ industry={task.industry!r} 已饱和: 30 天内已抓过 "
                f"{len(excluded_profile_urls)} 个频道，候选池命中率会显著下降 "
                f"(实测 ≥100 时 new/target 可能 < 30%)。"
                "建议:换 industry 关键词 / 切换 target_market / 取消任务。"
            )
            task.error_message = saturation_warning
            await db.commit()
            await manager.broadcast("scrape:saturation", {
                "task_id": task_id,
                "industry": task.industry,
                "excluded_count": len(excluded_profile_urls),
                "threshold": _SATURATION_THRESHOLD,
                "message": saturation_warning,
            })
            logger.warning(
                "[scraper] task %d: SATURATION warning broadcast (excluded=%d, threshold=%d)",
                task_id, len(excluded_profile_urls), _SATURATION_THRESHOLD,
            )

        search_queries, fallback_reason = await _generate_search_strategy(
            task.industry, platforms, task.target_market, task.competitor_brands,
            excluded_channels=excluded_for_llm,
        )
        task.search_keywords = json.dumps(search_queries, ensure_ascii=False)
        if fallback_reason:
            # Surface the fallback reason on the task. The UI shows
            # error_message in a yellow/red banner — better to admit
            # "LLM unreachable, ran with fallback queries" than to silently
            # produce shallow results. Append (don't overwrite) so the
            # earlier saturation warning survives.
            llm_msg = f"LLM 搜索策略不可用，使用 fallback 关键词。原因: {fallback_reason}"
            task.error_message = (
                f"{task.error_message} | {llm_msg}" if task.error_message else llm_msg
            )
        await db.commit()

        # Phase 5/9: strategy_ready (5%)
        await _ph(0, "strategy_ready")

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

        # ── on_progress: phase_detail + optional progress override ──────
        # Inner scrapers (_scrape_youtube / _scrape_instagram) call this at
        # structural milestones — per query, candidate pool ready, per
        # channel visit. Two responsibilities:
        #
        # 1. Push a free-text `phase_detail` so the UI shows "搜索 query
        #    5/12: ChatGPT" / "访问 channel 12/100: @MKBHD" instead of
        #    sitting silent.
        # 2. Optionally override the progress %. Search-phase calls pass
        #    the SERP-walk percentage (15-30%); visit-phase calls leave
        #    it None and let on_found drive the bar via new-finds.
        #
        # The previous implementation always used task.progress, which
        # froze the bar at 15% during the entire search SERP loop (3-4
        # min on a 12-query run) — users saw 15% / phase=crawling and
        # thought the task was stuck.
        async def on_progress(phase_detail: str, progress: int | None = None) -> None:
            # Monotonic: never let the bar go backward. visit-phase pushes
            # come from two sources (per-visit count + per-new-found),
            # whichever is higher wins. We update DB inside db_lock so
            # concurrent on_found writes don't race.
            if progress is not None and progress > (task.progress or 0):
                async with db_lock:
                    if progress > (task.progress or 0):
                        await update_task_status(
                            db, task, ScrapeTaskStatus.running, progress=progress,
                        )
            phase_label = "searching" if (task.progress < 30) else "crawling"
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "running",
                "progress": task.progress,
                "phase": phase_label,
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
                    # Visit phase owns 30-79%. Each NEW influencer bumps
                    # the bar by 49 / target_count percentage points so a
                    # 10-target task fills 30→79 in 10 hits.
                    #
                    # Monotonic guard: take max with task.progress so this
                    # call site never regresses the bar even if visited
                    # counter has already pushed progress past the
                    # new-based estimate. Without this max(), a task with
                    # visited=50/108 (progress=52 from finally) would
                    # see progress jump back to 34 here on the first
                    # email find (30 + 1/10*49 = 34) — the task #64
                    # "猛地倒退" symptom. update_task_status also
                    # enforces monotonic at the function level as a
                    # second line of defense.
                    new_based_progress = min(79, 30 + int((new_total / task.target_count) * 49))
                    progress = max(task.progress or 0, new_based_progress)
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
                        "progress": task.progress,
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
            await _ph(0, "browser_starting")
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
                # Phase searching: still 0% — the actual progress 1→30
                # comes from inner _scrape_youtube, which pushes
                # progress as each SERP scroll completes (real work).
                await _ph(0, "searching")

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

            # Smooth catch-up from wherever per-visit pushes left us to
            # 79 (visit phase ceiling). If new=target hit early or hit-rate
            # gate fired, task.progress can be anywhere from 30 to 79.
            # Walk one digit per 50ms so the visit band finishes cleanly
            # before enrichment takes over at 80.
            for _walk_p in range(int(task.progress or 0) + 1, 80):
                await manager.broadcast("scrape:progress", {
                    "task_id": task_id,
                    "status": "running",
                    "progress": _walk_p,
                    "phase": "crawling",
                    "found_count": found_total,
                    "valid_count": valid_total,
                    "new_count": new_total,
                    "reused_count": reused_total,
                })
                await asyncio.sleep(0.05)
            await update_task_status(db, task, ScrapeTaskStatus.running, progress=79)

            # Phase 4/5: LLM enrichment (relevance scoring) — owns 80→85%.
            # Visit phase tops out at 79; this 80 bump signals "we're done
            # finding contacts, now grading them". _enrich_results pushes
            # one progress notch per LLM batch.
            await update_task_status(db, task, ScrapeTaskStatus.running, progress=80)
            await manager.broadcast("scrape:progress", {
                "task_id": task_id,
                "status": "running",
                "progress": 80,
                "phase": "enriching",
                "found_count": found_total,
                "valid_count": valid_total,
                "new_count": new_total,
                "reused_count": reused_total,
            })

            enrich_failures = await _enrich_results(
                task.id, task.industry, task.target_market,
                on_progress=on_progress,
            )

            # Smooth catch-up from wherever enrichment batches left us to
            # 85. With 1-3 batches and integer rounding, the last batch
            # often lands at 83 or 84, leaving a 1-2 digit gap to 85.
            for _walk_p in range(int(task.progress or 0) + 1, 86):
                await manager.broadcast("scrape:progress", {
                    "task_id": task_id,
                    "status": "running",
                    "progress": _walk_p,
                    "phase": "enriching",
                    "found_count": found_total,
                    "valid_count": valid_total,
                    "new_count": new_total,
                    "reused_count": reused_total,
                })
                await asyncio.sleep(0.05)
            await update_task_status(db, task, ScrapeTaskStatus.running, progress=85)

            # Phase 5/5: completed.
            # If the run hit the LLM fallback path or produced 0 new finds
            # while still being asked for ≥1, append a warning to
            # error_message so the UI can flag "completed but suspicious".
            # We deliberately don't add a new ScrapeTaskStatus value — the
            # existing 4 (pending/running/completed/failed/cancelled) are
            # already wired through the entire stack; surfacing the warning
            # via error_message keeps the change surface small.
            warnings: list[str] = []
            # Saturation warning surfaced at startup is preserved across
            # the run — it explains the most likely reason why a low
            # new_count happened, and the operator may not see the
            # transient WebSocket toast if they navigated away.
            if saturation_warning:
                warnings.append(saturation_warning)
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
            # Surface LLM enrichment failures (one per failed batch / blocked
            # stage) so the user can tell why scores look heuristic instead
            # of LLM-graded. Dedup duplicates so 5 batches all hitting the
            # same 429 only show once.
            if enrich_failures:
                seen_enrich: set[str] = set()
                for ef in enrich_failures:
                    key = ef[:80]
                    if key in seen_enrich:
                        continue
                    seen_enrich.add(key)
                    warnings.append(ef)
            if new_total == 0 and task.target_count > 0 and not quota_errors:
                msg = (
                    "本次未抓到任何新网红("
                    f"复链接 {reused_total} 人，候选池可能已被历史任务穷尽)。"
                    "建议换 industry 关键词或扩大 target_market。"
                )
                # Cookies hint: anonymous YouTube scraping misses the
                # "View email" captcha-gated emails. If the task ran
                # YouTube without cookies AND found 0, configuring
                # youtube-cookies.json is the cheapest 30-50% recovery.
                if "youtube" in platforms and _load_youtube_cookies() is None:
                    msg += (
                        " 另外：未检测到 youtube-cookies.json，YouTube 命中率"
                        "受限（约 35%，配置后可达 70-85%）。"
                        "参考 server/data/README-youtube-cookies.md。"
                    )
                warnings.append(msg)
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

            # Walk the final 86→99 numbers so the bar fills smoothly to
            # 100 instead of jumping from 85 (post-enrichment) straight
            # to terminal. The actual wrap-up work (warning_message
            # build, quota_payload compute, final DB write) takes ~50ms,
            # but the user-visible bar gets paced ~80ms per number so
            # all 14 numbers are visible — total ~1.1s, fast enough not
            # to feel like a stall, slow enough each digit registers.
            for _walk_p in range(86, 100):
                await manager.broadcast("scrape:progress", {
                    "task_id": task_id,
                    "status": "running",
                    "progress": _walk_p,
                    "phase": "completing",
                    "found_count": found_total,
                    "valid_count": valid_total,
                    "new_count": new_total,
                    "reused_count": reused_total,
                })
                await asyncio.sleep(0.08)

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
            # Always prefix with the exception's type name. `str(exc)` is
            # empty for several real-world exception types — most notably
            # `NotImplementedError()` raised by `asyncio.create_subprocess_exec`
            # when Playwright is launched on a Windows SelectorEventLoop
            # (the original symptom of failed tasks #66/#67/#68 — UI showed
            # "失败" with no detail because str(exc)="" was filtered out by
            # filter(None, ...) below). Using the type name guarantees the
            # operator always sees something actionable.
            error_lines: list[str] = []
            if failed_quota_payload:
                for qe in failed_quota_payload:
                    error_lines.append(qe.get("message") or "")
            exc_str = str(exc).strip()
            error_lines.append(
                f"{type(exc).__name__}: {exc_str}" if exc_str else type(exc).__name__
            )
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
                "error": error_message,
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
