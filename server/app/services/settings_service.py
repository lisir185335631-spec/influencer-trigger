"""System settings service — singleton CRUD for SystemSettings table."""
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_settings import SystemSettings

logger = logging.getLogger(__name__)


async def get_or_create_system_settings(db: AsyncSession) -> SystemSettings:
    """Return the singleton system settings row, creating it with defaults if absent."""
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.id == 1)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = SystemSettings(id=1)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def update_system_settings(
    db: AsyncSession,
    scrape_concurrency: Optional[int] = None,
    webhook_feishu: Optional[str] = None,
    webhook_slack: Optional[str] = None,
    webhook_serverchan: Optional[str] = None,
    apify_tiktok_token: Optional[str] = None,
    apify_tiktok_actor: Optional[str] = None,
    apify_ig_token: Optional[str] = None,
    apify_ig_actor: Optional[str] = None,
    apify_twitter_token: Optional[str] = None,
    apify_twitter_actor: Optional[str] = None,
    apify_facebook_token: Optional[str] = None,
    apify_facebook_actor: Optional[str] = None,
) -> SystemSettings:
    """Partial update of system settings.

    For Apify fields: passing `None` leaves the field unchanged; passing `""`
    clears it (scraper then falls back to env var).
    """
    settings = await get_or_create_system_settings(db)

    if scrape_concurrency is not None:
        settings.scrape_concurrency = scrape_concurrency
    if webhook_feishu is not None:
        settings.webhook_feishu = webhook_feishu
    if webhook_slack is not None:
        settings.webhook_slack = webhook_slack
    if webhook_serverchan is not None:
        settings.webhook_serverchan = webhook_serverchan.strip()
    if apify_tiktok_token is not None:
        settings.apify_tiktok_token = apify_tiktok_token.strip()
    if apify_tiktok_actor is not None:
        # Normalize on write so DB never holds the `/` form again, even
        # if the user pastes from console URL bar. Defined below.
        settings.apify_tiktok_actor = _normalize_actor_id(apify_tiktok_actor)
    if apify_ig_token is not None:
        settings.apify_ig_token = apify_ig_token.strip()
    if apify_ig_actor is not None:
        settings.apify_ig_actor = _normalize_actor_id(apify_ig_actor)
    if apify_twitter_token is not None:
        settings.apify_twitter_token = apify_twitter_token.strip()
    if apify_twitter_actor is not None:
        settings.apify_twitter_actor = _normalize_actor_id(apify_twitter_actor)
    if apify_facebook_token is not None:
        settings.apify_facebook_token = apify_facebook_token.strip()
    if apify_facebook_actor is not None:
        settings.apify_facebook_actor = _normalize_actor_id(apify_facebook_actor)

    await db.commit()
    await db.refresh(settings)
    return settings


def _normalize_actor_id(actor: str) -> str:
    """Normalize Apify actor IDs so both `/` and `~` separators work.

    Apify's REST API treats `username~actor-name` as a single path segment
    in URLs like `/v2/acts/{actor}`. If users paste `username/actor-name`
    (which is what the Apify console URL shows in the address bar), the
    raw `/` makes the URL look like 3 path segments and Apify returns
    404 "no API endpoint at this URL". This is a recurring footgun —
    transparently rewrite at every read.

    Trims whitespace too. Empty input returns empty (let caller decide
    what to fall back to).
    """
    s = (actor or "").strip()
    if not s:
        return ""
    # Single `/` between username and actor-name is the canonical "wrong"
    # form people paste from the Apify console. Replace ALL `/` with `~`
    # — actor names never legitimately contain `/`.
    return s.replace("/", "~")


def mask_token(token: str) -> str:
    """Mask a secret for safe display. Empty -> empty; <=8 chars -> all stars;
    longer -> "****" + last 4 chars."""
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return "****" + token[-4:]


async def resolve_apify_credentials(
    db: AsyncSession,
    platform: str,
) -> tuple[str, str]:
    """Return (token, actor) for the given platform, preferring DB-configured
    values and falling back to env vars in config.py.

    `platform` ∈ {"tiktok", "instagram"}. Other platforms are not Apify-driven
    today and will return ("", "").
    """
    from app.config import get_settings as get_env_settings

    settings = await get_or_create_system_settings(db)
    env = get_env_settings()

    if platform == "tiktok":
        token = (settings.apify_tiktok_token or "").strip() or (env.apify_api_token or "").strip()
        # Default actor switched to clockworks (v2 list+local-extract pipeline)
        # on 2026-04-26 — 8x cheaper than the old jurassic_jove email actor
        # and avoids the third-party email leakage that scrapeEmails=true
        # introduced. The DB / env override fields are still honoured so
        # operators can plug in a different cheap actor without code change.
        # Actor IDs get normalized (`/` → `~`) so paste-from-console URLs
        # don't 404 — see _normalize_actor_id.
        actor = (
            _normalize_actor_id(settings.apify_tiktok_actor)
            or _normalize_actor_id(env.apify_tiktok_actor)
            or "clockworks~tiktok-scraper"
        )
        return token, actor

    if platform in ("instagram", "ig"):
        token = (settings.apify_ig_token or "").strip() or (env.apify_api_token or "").strip()
        actor = (
            _normalize_actor_id(settings.apify_ig_actor)
            or _normalize_actor_id(env.apify_ig_actor)
            or "apify~instagram-profile-scraper"
        )
        return token, actor

    if platform in ("twitter", "x"):
        token = (settings.apify_twitter_token or "").strip() or (env.apify_api_token or "").strip()
        actor = (
            _normalize_actor_id(settings.apify_twitter_actor)
            or "kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest"
        )
        return token, actor

    if platform == "facebook":
        token = (settings.apify_facebook_token or "").strip() or (env.apify_api_token or "").strip()
        actor = (
            _normalize_actor_id(settings.apify_facebook_actor)
            or "apify~facebook-pages-scraper"
        )
        return token, actor

    return "", ""
