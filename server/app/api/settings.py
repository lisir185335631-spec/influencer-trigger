"""
System settings API — GET/PUT /api/settings
Aggregates SystemSettings (scrape, webhooks) + FollowUpSettings (follow-up strategy).
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.deps import get_current_user, require_manager_or_above
from app.schemas.auth import TokenData
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services.settings_service import (
    get_or_create_system_settings,
    update_system_settings,
)
from app.services.follow_up_service import get_or_create_settings, update_settings as update_follow_up
from app.services.webhook_service import test_webhook_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])

# Cookies file location must match _load_youtube_cookies() in scraper.py:
# server/data/youtube-cookies.json. Resolve once at import time so we don't
# recompute the path on every request.
_YT_COOKIES_PATH = Path(__file__).resolve().parents[2] / "data" / "youtube-cookies.json"

# Auth-critical YouTube cookies. At least one of these must be present in
# the saved payload, otherwise the cookie set is anonymous and the
# scraper's "View email address" button stays hidden — same outcome as no
# cookies at all. Surfacing this as a validation error early prevents the
# operator from saving an incomplete copy and wondering why hit-rate
# didn't move. SAPISID + the SID variants are present on every live
# YouTube login session; LOGIN_INFO is present after sign-in via
# accounts.google.com.
_AUTH_CRITICAL_COOKIE_NAMES = {
    "SAPISID",
    "__Secure-1PSAPISID",
    "__Secure-3PSAPISID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "LOGIN_INFO",
    "SID",
}


async def get_db():  # type: ignore[return]
    async with AsyncSessionLocal() as db:
        yield db


@router.get("", response_model=SettingsOut)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
) -> SettingsOut:
    """Return merged system settings."""
    sys = await get_or_create_system_settings(db)
    fu = await get_or_create_settings(db)
    return SettingsOut(
        follow_up_enabled=fu.enabled,
        interval_days=fu.interval_days,
        max_count=fu.max_count,
        hour_utc=fu.hour_utc,
        scrape_concurrency=sys.scrape_concurrency,
        webhook_feishu=sys.webhook_feishu,
        webhook_slack=sys.webhook_slack,
    )


@router.put("", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_manager_or_above),
) -> SettingsOut:
    """Update system settings (manager/admin only)."""
    # Update SystemSettings
    sys = await update_system_settings(
        db,
        scrape_concurrency=body.scrape_concurrency,
        webhook_feishu=body.webhook_feishu,
        webhook_slack=body.webhook_slack,
    )

    # Update FollowUpSettings
    fu = await update_follow_up(
        db,
        enabled=body.follow_up_enabled,
        interval_days=body.interval_days,
        max_count=body.max_count,
        hour_utc=body.hour_utc,
    )

    # Reschedule follow-up job if hour changed
    if body.hour_utc is not None:
        try:
            from app.scheduler import scheduler
            from apscheduler.triggers.cron import CronTrigger
            scheduler.reschedule_job(
                "monthly_follow_up",
                trigger=CronTrigger(hour=fu.hour_utc, minute=0, timezone="UTC"),
            )
        except Exception as exc:
            logger.warning("Failed to reschedule follow-up job: %s", exc)

    return SettingsOut(
        follow_up_enabled=fu.enabled,
        interval_days=fu.interval_days,
        max_count=fu.max_count,
        hour_utc=fu.hour_utc,
        scrape_concurrency=sys.scrape_concurrency,
        webhook_feishu=sys.webhook_feishu,
        webhook_slack=sys.webhook_slack,
    )


@router.post("/test-webhook")
async def test_webhook(
    body: dict,
    current_user: TokenData = Depends(require_manager_or_above),
) -> dict:
    """Test a webhook URL by sending a test message."""
    platform = body.get("platform", "")
    url = body.get("url", "")
    if platform not in ("feishu", "slack"):
        raise HTTPException(status_code=400, detail="platform must be 'feishu' or 'slack'")
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    ok = await test_webhook_url(platform, url)
    return {"success": ok, "platform": platform}


# ── YouTube cookies management ────────────────────────────────────────────
# Operators paste their YouTube cookie string (or JSON) here so the
# scraper can run authenticated and unlock the "View email address"
# button on creator About pages. See README-youtube-cookies.md for the
# F12 recipe the UI walks them through.


class YouTubeCookiesStatus(BaseModel):
    configured: bool
    count: int
    auth_complete: bool
    updated_at: str | None
    file_size: int


class YouTubeCookiesPayload(BaseModel):
    raw: str


def _parse_cookie_string(raw: str) -> list[dict]:
    """Parse `name1=value1; name2=value2; ...` into Playwright cookie dicts.

    Network-tab Request Headers `cookie:` value has no domain/path info;
    we default everything to `.youtube.com / /` because the scraper only
    visits youtube.com. Whitespace inside values is preserved (some YT
    cookies legitimately carry `=` and spaces).
    """
    cookies: list[dict] = []
    seen_names: set[str] = set()
    # Cookie pairs are separated by `; `. Use split on `;` then strip so
    # we tolerate `;` without trailing space too.
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        name = name.strip()
        value = value.strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        cookies.append({
            "name": name,
            "value": value,
            "domain": ".youtube.com",
            "path": "/",
        })
    return cookies


def _normalize_cookies_input(raw: str) -> list[dict]:
    """Accept either Playwright JSON (array or {cookies: [...]}) or a
    Network-tab cookie string. Return Playwright cookie array.

    Raises HTTPException(400) on unrecognised / empty input.
    """
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="cookie 内容不能为空")

    # JSON path: fastest exit. We accept the two formats `_load_youtube_cookies`
    # already supports.
    first_char = raw[0]
    if first_char in "[{":
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"JSON 解析失败：{e.msg} (line {e.lineno}, col {e.colno})",
            )
        if isinstance(parsed, dict) and isinstance(parsed.get("cookies"), list):
            cookies = parsed["cookies"]
        elif isinstance(parsed, list):
            cookies = parsed
        else:
            raise HTTPException(
                status_code=400,
                detail="JSON 格式不识别：需要数组或含 cookies 字段的对象",
            )
        # Light schema check on each entry.
        valid: list[dict] = []
        for c in cookies:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            value = c.get("value")
            if not name or value is None:
                continue
            valid.append({
                "name": name,
                "value": value,
                "domain": c.get("domain") or ".youtube.com",
                "path": c.get("path") or "/",
                **({k: v for k, v in c.items() if k in ("expires", "httpOnly", "secure", "sameSite")}),
            })
        return valid

    # Cookie string path.
    return _parse_cookie_string(raw)


def _read_status() -> YouTubeCookiesStatus:
    if not _YT_COOKIES_PATH.exists():
        return YouTubeCookiesStatus(
            configured=False, count=0, auth_complete=False,
            updated_at=None, file_size=0,
        )
    try:
        size = _YT_COOKIES_PATH.stat().st_size
        mtime = datetime.fromtimestamp(
            _YT_COOKIES_PATH.stat().st_mtime, tz=timezone.utc,
        ).isoformat()
        data = json.loads(_YT_COOKIES_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("cookies"), list):
            cookie_list = data["cookies"]
        elif isinstance(data, list):
            cookie_list = data
        else:
            cookie_list = []
        names = {c.get("name") for c in cookie_list if isinstance(c, dict)}
        auth_complete = bool(_AUTH_CRITICAL_COOKIE_NAMES & names)
        return YouTubeCookiesStatus(
            configured=True,
            count=len(cookie_list),
            auth_complete=auth_complete,
            updated_at=mtime,
            file_size=size,
        )
    except Exception as e:
        logger.warning("Reading youtube-cookies.json failed: %s", e)
        return YouTubeCookiesStatus(
            configured=True, count=0, auth_complete=False,
            updated_at=None, file_size=0,
        )


@router.get("/youtube-cookies/status", response_model=YouTubeCookiesStatus)
async def get_youtube_cookies_status(
    current_user: TokenData = Depends(get_current_user),
) -> YouTubeCookiesStatus:
    return _read_status()


@router.post("/youtube-cookies", response_model=YouTubeCookiesStatus)
async def save_youtube_cookies(
    body: YouTubeCookiesPayload,
    current_user: TokenData = Depends(require_manager_or_above),
) -> YouTubeCookiesStatus:
    cookies = _normalize_cookies_input(body.raw)
    if not cookies:
        raise HTTPException(
            status_code=400,
            detail="未解析到任何 cookie。请确认从 Network 面板 Request Headers 的 cookie 字段复制全部内容",
        )
    names = {c["name"] for c in cookies}
    if not (_AUTH_CRITICAL_COOKIE_NAMES & names):
        raise HTTPException(
            status_code=400,
            detail=(
                "未检测到登录态关键 cookie（如 SAPISID / __Secure-3PSID / LOGIN_INFO）。"
                "通常因为 cookie 字符串不完整或来自未登录会话，请重新复制。"
            ),
        )
    _YT_COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _YT_COOKIES_PATH.write_text(
        json.dumps(cookies, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "[settings] saved %d YouTube cookies (auth_complete=%s, user=%s)",
        len(cookies), bool(_AUTH_CRITICAL_COOKIE_NAMES & names),
        current_user.user_id,
    )
    return _read_status()


@router.delete("/youtube-cookies", response_model=YouTubeCookiesStatus)
async def delete_youtube_cookies(
    current_user: TokenData = Depends(require_manager_or_above),
) -> YouTubeCookiesStatus:
    if _YT_COOKIES_PATH.exists():
        _YT_COOKIES_PATH.unlink()
        logger.info("[settings] deleted youtube-cookies.json (user=%s)", current_user.user_id)
    return _read_status()
