"""Apify monthly usage tracker — pre-flight budget guard for Apify-driven
scrapes (TikTok / Instagram).

Why a pre-flight (not just post-mortem):
  Apify charges per-event before returning data, so by the time a run
  finishes we've already spent the credit. The only point at which we
  can refuse a $30 task is BEFORE making the API call. This module gives
  the scraper a cheap (~50ms) check against the user's running monthly
  total and returns a verdict.

Soft + hard caps:
  - SOFT cap (warn): UI banner / quota_errors entry that the user is
    approaching their budget. Scrape proceeds.
  - HARD cap (abort): refuse the scrape with a clear quota_errors
    message. Operator must either raise the cap or wait for monthly
    reset on the 1st.

Caching: 60-second TTL so a burst of tasks doesn't hammer the usage
endpoint. The endpoint itself is fast but rate-limited.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_USAGE_CACHE: dict[str, tuple[float, float]] = {}  # token -> (fetched_at, total_usd)
_USAGE_CACHE_TTL_S = 60.0


@dataclass(frozen=True)
class BudgetVerdict:
    ok: bool          # True ⇒ scrape may proceed
    spent_usd: float  # Current month-to-date spend (best known)
    soft_cap: float   # Soft warn threshold
    hard_cap: float   # Hard abort threshold
    message: str | None = None


async def get_monthly_usage_usd(token: str) -> float | None:
    """Return current month-to-date Apify spend in USD, or None on error.

    Caches successful fetches for 60s to avoid hammering the API in
    multi-task bursts. The "after volume discount" total is the figure
    Apify uses for billing on the user's plan.
    """
    if not token:
        return None
    now = time.time()
    cached = _USAGE_CACHE.get(token)
    if cached and (now - cached[0]) < _USAGE_CACHE_TTL_S:
        return cached[1]

    url = "https://api.apify.com/v2/users/me/usage/monthly"
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(url, params={"token": token})
    except httpx.HTTPError as e:
        logger.warning("[apify_usage] fetch failed: %s: %r", type(e).__name__, e)
        return None
    if r.status_code != 200:
        logger.warning("[apify_usage] HTTP %d: %s", r.status_code, r.text[:200])
        return None
    try:
        d = r.json().get("data", {})
        # `totalUsageCreditsUsdAfterVolumeDiscount` is the canonical figure;
        # falls back to summing per-service entries on older API versions.
        total = d.get("totalUsageCreditsUsdAfterVolumeDiscount")
        if total is None:
            msu = d.get("monthlyServiceUsage", {}) or {}
            total = sum(
                (svc or {}).get("amountAfterVolumeDiscountUsd", 0) or 0
                for svc in msu.values()
                if isinstance(svc, dict)
            )
    except Exception as e:
        logger.warning("[apify_usage] parse failed: %s", e)
        return None

    total_f = float(total or 0)
    _USAGE_CACHE[token] = (now, total_f)
    return total_f


async def check_budget(
    token: str,
    soft_cap: float = 20.0,
    hard_cap: float = 30.0,
) -> BudgetVerdict:
    """Pre-flight budget check.

    Defaults soft=$20 / hard=$30 match the user-confirmed monthly cap
    (see PR notes 2026-04-26). When usage can't be fetched (network /
    auth issue) we fail OPEN — assume budget is fine — to avoid blocking
    legitimate scrapes on a transient API outage.
    """
    spent = await get_monthly_usage_usd(token)
    if spent is None:
        # Fail open — return ok with a soft warning so the operator can
        # see in logs that we couldn't verify, but the scrape still runs.
        return BudgetVerdict(
            ok=True,
            spent_usd=0.0,
            soft_cap=soft_cap,
            hard_cap=hard_cap,
            message="无法读取 Apify 月度用量（网络/权限问题），跳过预算检查",
        )

    if spent >= hard_cap:
        return BudgetVerdict(
            ok=False,
            spent_usd=spent,
            soft_cap=soft_cap,
            hard_cap=hard_cap,
            message=(
                f"已达到 Apify 月度硬性预算上限：当前已用 "
                f"${spent:.2f} ≥ ${hard_cap:.2f}。任务被拒以防超支。"
                f"解决：① 等下月 1 号自动重置；② 到系统设置抬高 hard_cap；"
                f"③ 到 console.apify.com 充值后调高上限。"
            ),
        )
    if spent >= soft_cap:
        return BudgetVerdict(
            ok=True,
            spent_usd=spent,
            soft_cap=soft_cap,
            hard_cap=hard_cap,
            message=(
                f"接近 Apify 月度预算软上限：当前 ${spent:.2f} ≥ ${soft_cap:.2f}。"
                f"剩余至硬上限 ${hard_cap - spent:.2f}。"
            ),
        )
    return BudgetVerdict(ok=True, spent_usd=spent, soft_cap=soft_cap, hard_cap=hard_cap)
