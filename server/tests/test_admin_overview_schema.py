"""
Integration test: GET /api/admin/overview/metrics response schema completeness.

Verifies that all expected keys exist in the response so any future
structural regressions in overview.py are caught immediately.
"""
import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_overview_metrics_schema(async_client, admin_user):
    """GET /api/admin/overview/metrics must return 200 with complete schema."""
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.auth_service import create_access_token

    async with AsyncSessionLocal() as db:
        adm = (await db.execute(select(User).where(User.id == admin_user.id))).scalar_one()
    headers = {"Authorization": f"Bearer {create_access_token(adm.id, adm.username, adm.role.value, adm.token_version)}"}

    resp = await async_client.get("/api/admin/overview/metrics", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # ── Top-level keys ─────────────────────────────────────────────────────────
    required_top_keys = [
        "users", "emails_sent", "emails_replied", "influencers",
        "scrape_tasks", "agent_tasks", "errors", "charts",
    ]
    for k in required_top_keys:
        assert k in data, f"Missing top-level key: {k!r}"

    # ── users ──────────────────────────────────────────────────────────────────
    assert {"total", "active"} <= set(data["users"].keys()), (
        f"users missing keys, got: {set(data['users'].keys())}"
    )

    # ── emails_sent ────────────────────────────────────────────────────────────
    assert {"today", "this_week", "this_month"} <= set(data["emails_sent"].keys()), (
        f"emails_sent missing keys, got: {set(data['emails_sent'].keys())}"
    )

    # ── emails_replied ─────────────────────────────────────────────────────────
    assert {"today", "this_week", "this_month"} <= set(data["emails_replied"].keys()), (
        f"emails_replied missing keys, got: {set(data['emails_replied'].keys())}"
    )

    # ── influencers ────────────────────────────────────────────────────────────
    assert {"total", "today", "this_week", "this_month"} <= set(data["influencers"].keys()), (
        f"influencers missing keys, got: {set(data['influencers'].keys())}"
    )

    # ── scrape_tasks ───────────────────────────────────────────────────────────
    assert {"today", "this_week", "this_month"} <= set(data["scrape_tasks"].keys()), (
        f"scrape_tasks missing keys, got: {set(data['scrape_tasks'].keys())}"
    )

    # ── agent_tasks ────────────────────────────────────────────────────────────
    assert "today" in data["agent_tasks"], (
        f"agent_tasks missing 'today', got: {set(data['agent_tasks'].keys())}"
    )

    # ── errors ─────────────────────────────────────────────────────────────────
    assert "today" in data["errors"], (
        f"errors missing 'today', got: {set(data['errors'].keys())}"
    )

    # ── charts ─────────────────────────────────────────────────────────────────
    assert {"email_trend", "scrape_trend", "platform_dist"} <= set(data["charts"].keys()), (
        f"charts missing keys, got: {set(data['charts'].keys())}"
    )

    email_trend = data["charts"]["email_trend"]
    scrape_trend = data["charts"]["scrape_trend"]

    assert len(email_trend) == 7, (
        f"email_trend should have 7 entries, got {len(email_trend)}"
    )
    assert len(scrape_trend) == 7, (
        f"scrape_trend should have 7 entries, got {len(scrape_trend)}"
    )

    # ── Verify row structure in trend arrays ───────────────────────────────────
    for i, row in enumerate(email_trend):
        assert {"date", "sent", "replied"} <= set(row.keys()), (
            f"email_trend[{i}] missing keys, got: {set(row.keys())}"
        )

    for i, row in enumerate(scrape_trend):
        assert {"date", "tasks"} <= set(row.keys()), (
            f"scrape_trend[{i}] missing keys, got: {set(row.keys())}"
        )
