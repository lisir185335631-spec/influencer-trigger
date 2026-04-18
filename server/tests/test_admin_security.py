"""
Integration tests for POST /api/admin/security/rotate-keys.

Patches _update_env_key to avoid writing to the real .env file.
Uses fresh_admin_headers fixture so the token_version is always current
(rotate-keys increments ALL users including admin, which would invalidate
the session-scoped admin_token for subsequent tests).
"""
import pytest


@pytest.mark.asyncio
async def test_rotate_keys_wrong_password(async_client, fresh_admin_headers, monkeypatch):
    """Wrong admin password must return 403."""
    monkeypatch.setattr(
        "app.api.admin.security._update_env_key",
        lambda *args, **kwargs: None,
    )
    resp = await async_client.post(
        "/api/admin/security/rotate-keys",
        json={"admin_password": "totally_wrong_password"},
        headers=fresh_admin_headers,
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_rotate_keys_correct_password_returns_ok(async_client, admin_user, monkeypatch):
    """
    Correct admin password → 200 + {"ok": true}.

    We regenerate the admin token inside this test after the call because
    rotate-keys bumps token_version for all users, invalidating the
    session-scoped token.  This test must be the LAST to use rotate-keys.
    """
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.auth_service import create_access_token

    monkeypatch.setattr(
        "app.api.admin.security._update_env_key",
        lambda *args, **kwargs: None,
    )

    # Get current token_version for admin
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.id == admin_user.id))).scalar_one()
    headers = {"Authorization": f"Bearer {create_access_token(u.id, u.username, u.role.value, u.token_version)}"}

    resp = await async_client.post(
        "/api/admin/security/rotate-keys",
        json={"admin_password": "admin_pw_2026"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("ok") is True


@pytest.mark.asyncio
async def test_rotate_keys_increments_all_token_versions(async_client, admin_user, operator_user, monkeypatch):
    """
    After rotate-keys, old token_version tokens for any user must be rejected.
    Reads token_version before and after, verifies bump.
    """
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.auth_service import create_access_token

    monkeypatch.setattr(
        "app.api.admin.security._update_env_key",
        lambda *args, **kwargs: None,
    )

    # Snapshot token_version for operator before rotation
    async with AsyncSessionLocal() as db:
        op_before = (await db.execute(select(User).where(User.id == operator_user.id))).scalar_one()
        op_tv_before = op_before.token_version
        # Build a stale token using the current version
        stale_token = create_access_token(
            op_before.id, op_before.username, op_before.role.value, op_tv_before
        )
        # Admin token with current version
        adm = (await db.execute(select(User).where(User.id == admin_user.id))).scalar_one()
        admin_headers = {"Authorization": f"Bearer {create_access_token(adm.id, adm.username, adm.role.value, adm.token_version)}"}

    # Perform rotation
    resp = await async_client.post(
        "/api/admin/security/rotate-keys",
        json={"admin_password": "admin_pw_2026"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    # Verify operator token_version was bumped
    async with AsyncSessionLocal() as db:
        op_after = (await db.execute(select(User).where(User.id == operator_user.id))).scalar_one()
        assert op_after.token_version > op_tv_before, (
            f"Expected token_version > {op_tv_before}, got {op_after.token_version}"
        )

    # Stale token must now be rejected on any authenticated endpoint
    r = await async_client.get(
        "/api/dashboard/stats",
        headers={"Authorization": f"Bearer {stale_token}"},
    )
    assert r.status_code == 401, f"Expected 401 for stale token, got {r.status_code}: {r.text}"
