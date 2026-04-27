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
from app.schemas.settings import (
    SettingsOut,
    SettingsUpdate,
    TestApifyActorRequest,
    TestApifyActorResponse,
)
from app.services.settings_service import (
    get_or_create_system_settings,
    mask_token,
    resolve_apify_credentials,
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


def _build_settings_out(sys, fu) -> SettingsOut:
    """Shared serializer — masks Apify tokens before sending to client."""
    return SettingsOut(
        follow_up_enabled=fu.enabled,
        interval_days=fu.interval_days,
        max_count=fu.max_count,
        hour_utc=fu.hour_utc,
        scrape_concurrency=sys.scrape_concurrency,
        webhook_feishu=sys.webhook_feishu,
        webhook_slack=sys.webhook_slack,
        # Mask the SendKey before sending to the client — same defence as
        # apify_*_token. Client uses webhook_serverchan_set to know if a
        # value exists in DB.
        webhook_serverchan=mask_token(sys.webhook_serverchan or ""),
        webhook_serverchan_set=bool(sys.webhook_serverchan),
        apify_tiktok_token=mask_token(sys.apify_tiktok_token or ""),
        apify_tiktok_token_set=bool(sys.apify_tiktok_token),
        apify_tiktok_actor=sys.apify_tiktok_actor or "",
        apify_ig_token=mask_token(sys.apify_ig_token or ""),
        apify_ig_token_set=bool(sys.apify_ig_token),
        apify_ig_actor=sys.apify_ig_actor or "",
        apify_twitter_token=mask_token(sys.apify_twitter_token or ""),
        apify_twitter_token_set=bool(sys.apify_twitter_token),
        apify_twitter_actor=sys.apify_twitter_actor or "",
        apify_facebook_token=mask_token(sys.apify_facebook_token or ""),
        apify_facebook_token_set=bool(sys.apify_facebook_token),
        apify_facebook_actor=sys.apify_facebook_actor or "",
    )


@router.get("", response_model=SettingsOut)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
) -> SettingsOut:
    """Return merged system settings."""
    sys = await get_or_create_system_settings(db)
    fu = await get_or_create_settings(db)
    return _build_settings_out(sys, fu)


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
        webhook_serverchan=body.webhook_serverchan,
        apify_tiktok_token=body.apify_tiktok_token,
        apify_tiktok_actor=body.apify_tiktok_actor,
        apify_ig_token=body.apify_ig_token,
        apify_ig_actor=body.apify_ig_actor,
        apify_twitter_token=body.apify_twitter_token,
        apify_twitter_actor=body.apify_twitter_actor,
        apify_facebook_token=body.apify_facebook_token,
        apify_facebook_actor=body.apify_facebook_actor,
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
                "daily_follow_up",
                trigger=CronTrigger(hour=fu.hour_utc, minute=0, timezone="UTC"),
            )
        except Exception as exc:
            logger.warning("Failed to reschedule follow-up job: %s", exc)

    return _build_settings_out(sys, fu)


@router.post("/test-apify-actor", response_model=TestApifyActorResponse)
async def test_apify_actor(
    body: TestApifyActorRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_manager_or_above),
) -> TestApifyActorResponse:
    """Verify an Apify token+actor combo by hitting Apify's metadata endpoint.

    Doesn't run the actor (which would cost money) — just calls the
    `/v2/acts/{actor}` lookup with the token. Returns 200 OK if Apify accepts
    the token and the actor exists.
    """
    import httpx

    platform = (body.platform or "").strip().lower()
    logger.info(
        "[settings] test_apify_actor: platform=%s actor=%r token_provided=%s user=%s",
        platform, body.actor, bool(body.token), current_user.user_id,
    )
    if platform not in ("tiktok", "instagram", "ig", "twitter", "x", "facebook"):
        raise HTTPException(
            status_code=400,
            detail="platform 必须是 tiktok / instagram / twitter / facebook",
        )

    # Resolve effective credentials. If body provides token/actor, use those;
    # otherwise fall back to currently saved DB values (with env-var fallback).
    # Normalize the body's actor field too — user might be testing a freshly-
    # pasted `username/actor-name` before saving, the test should green-flag
    # it instead of 404'ing on the same `/`-vs-`~` URL bug.
    from app.services.settings_service import _normalize_actor_id
    token = (body.token or "").strip()
    actor = _normalize_actor_id(body.actor or "")
    if not token or not actor:
        db_token, db_actor = await resolve_apify_credentials(db, platform)
        token = token or db_token
        actor = actor or db_actor

    if not token:
        return TestApifyActorResponse(
            success=False,
            platform=platform,
            actor=actor,
            message="未填写 Apify Token，且 DB 与环境变量均无可用 token。",
        )
    if not actor:
        return TestApifyActorResponse(
            success=False,
            platform=platform,
            actor="",
            message="未填写 Actor ID。",
        )

    # Apify's actor lookup: GET /v2/acts/{actorId} with ?token=...
    # Use ~ as separator for username~actor-name (Apify accepts both ~ and /
    # but ~ is what config.py uses everywhere).
    url = f"https://api.apify.com/v2/acts/{actor}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params={"token": token})
    except httpx.RequestError as e:
        logger.warning("[settings] apify test request failed: %s", e)
        return TestApifyActorResponse(
            success=False,
            platform=platform,
            actor=actor,
            message=f"网络请求失败：{e}",
        )

    if resp.status_code == 401:
        return TestApifyActorResponse(
            success=False, platform=platform, actor=actor,
            message="Token 无效（HTTP 401）。请到 https://console.apify.com/account/integrations 重新签发。",
        )
    if resp.status_code == 403:
        return TestApifyActorResponse(
            success=False, platform=platform, actor=actor,
            message="Token 权限不足或账号被限制（HTTP 403）。",
        )
    if resp.status_code == 404:
        return TestApifyActorResponse(
            success=False, platform=platform, actor=actor,
            message=f"Actor 不存在：{actor!r}（HTTP 404）。",
        )
    if resp.status_code != 200:
        return TestApifyActorResponse(
            success=False, platform=platform, actor=actor,
            message=f"Apify 返回 HTTP {resp.status_code}：{resp.text[:200]}",
        )

    try:
        data = resp.json().get("data", {})
    except Exception:
        data = {}
    return TestApifyActorResponse(
        success=True,
        platform=platform,
        actor=actor,
        actor_title=data.get("title") or data.get("name"),
        actor_username=data.get("username"),
        message="Token 与 Actor 校验通过。",
    )


@router.post("/test-webhook")
async def test_webhook(
    body: dict,
    current_user: TokenData = Depends(require_manager_or_above),
) -> dict:
    """Test a webhook URL by sending a test message."""
    platform = body.get("platform", "")
    url = body.get("url", "")
    if platform not in ("feishu", "slack", "serverchan"):
        raise HTTPException(status_code=400, detail="platform must be 'feishu', 'slack', or 'serverchan'")
    if not url:
        # 'url' is the SendKey when platform == 'serverchan'
        raise HTTPException(status_code=400, detail="url (or SendKey for serverchan) is required")
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
