"""
Integration tests for POST /api/admin/users/{id}/force-logout.

Verifies:
- Correct admin password → 200
- Operator's token_version is incremented by 1
- Old operator JWT is rejected on subsequent authenticated requests
"""
import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_force_logout_correct_password(async_client, admin_user, operator_user, monkeypatch):
    """Admin force-logout with correct password returns 200."""
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.auth_service import create_access_token

    # Build a fresh admin token (token_version may have shifted from security tests)
    async with AsyncSessionLocal() as db:
        adm = (await db.execute(select(User).where(User.id == admin_user.id))).scalar_one()
    headers = {"Authorization": f"Bearer {create_access_token(adm.id, adm.username, adm.role.value, adm.token_version)}"}

    resp = await async_client.post(
        f"/api/admin/users/{operator_user.id}/force-logout",
        json={"admin_password": "admin_pw_2026"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json().get("ok") is True


@pytest.mark.asyncio
async def test_force_logout_increments_token_version(async_client, admin_user, operator_user):
    """force-logout should increment operator's token_version by exactly 1."""
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.auth_service import create_access_token

    async with AsyncSessionLocal() as db:
        op_before = (await db.execute(select(User).where(User.id == operator_user.id))).scalar_one()
        tv_before = op_before.token_version
        adm = (await db.execute(select(User).where(User.id == admin_user.id))).scalar_one()

    headers = {"Authorization": f"Bearer {create_access_token(adm.id, adm.username, adm.role.value, adm.token_version)}"}

    resp = await async_client.post(
        f"/api/admin/users/{operator_user.id}/force-logout",
        json={"admin_password": "admin_pw_2026"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        op_after = (await db.execute(select(User).where(User.id == operator_user.id))).scalar_one()

    assert op_after.token_version == tv_before + 1, (
        f"Expected token_version {tv_before + 1}, got {op_after.token_version}"
    )


@pytest.mark.asyncio
async def test_force_logout_invalidates_old_token(async_client, admin_user, operator_user):
    """
    Old operator JWT (with stale token_version) must be rejected with 401
    after force-logout is called.
    Uses /api/dashboard/stats which calls get_current_user (not require_admin),
    so an operator token is valid there before logout.
    """
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.auth_service import create_access_token

    # Capture operator's current token_version and build token before logout
    async with AsyncSessionLocal() as db:
        op = (await db.execute(select(User).where(User.id == operator_user.id))).scalar_one()
        stale_token = create_access_token(op.id, op.username, op.role.value, op.token_version)
        adm = (await db.execute(select(User).where(User.id == admin_user.id))).scalar_one()

    admin_headers = {"Authorization": f"Bearer {create_access_token(adm.id, adm.username, adm.role.value, adm.token_version)}"}

    # Confirm stale_token works BEFORE logout
    r1 = await async_client.get(
        "/api/dashboard/stats",
        headers={"Authorization": f"Bearer {stale_token}"},
    )
    assert r1.status_code == 200, f"Pre-logout should be 200, got {r1.status_code}: {r1.text}"

    # Force logout
    resp = await async_client.post(
        f"/api/admin/users/{operator_user.id}/force-logout",
        json={"admin_password": "admin_pw_2026"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    # Now stale_token must be rejected
    r2 = await async_client.get(
        "/api/dashboard/stats",
        headers={"Authorization": f"Bearer {stale_token}"},
    )
    assert r2.status_code == 401, (
        f"Post-logout stale token should be 401, got {r2.status_code}: {r2.text}"
    )


@pytest.mark.asyncio
async def test_force_logout_wrong_password(async_client, admin_user, operator_user):
    """Wrong admin password must return 403."""
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.auth_service import create_access_token

    async with AsyncSessionLocal() as db:
        adm = (await db.execute(select(User).where(User.id == admin_user.id))).scalar_one()

    headers = {"Authorization": f"Bearer {create_access_token(adm.id, adm.username, adm.role.value, adm.token_version)}"}

    resp = await async_client.post(
        f"/api/admin/users/{operator_user.id}/force-logout",
        json={"admin_password": "wrong_password"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
