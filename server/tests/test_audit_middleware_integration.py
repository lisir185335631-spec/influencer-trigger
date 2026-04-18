"""
Integration test: AuditMiddleware writes to audit_log on write operations.

Verifies:
- POST /api/admin/users creates an audit_log record
- action == "CREATE", resource_type == "users"
- Sensitive field "password" is redacted to "***"

Note on timing: AuditMiddleware uses asyncio.create_task (fire-and-forget).
We sleep 2.0s to give the background task time to commit.
"""
import asyncio
import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_audit_log_written_on_create_user(async_client, admin_user):
    """POST /api/admin/users must produce an audit_log row with redacted password."""
    from app.database import AsyncSessionLocal
    from app.models.audit_log import AuditLog
    from app.models.user import User
    from app.services.auth_service import create_access_token

    # Unique username to isolate this test's audit record
    test_username = "audit_target_int_test"
    test_email = "audit_int@example.com"
    test_password = "secret_pw_for_audit_test_xyz"

    # Get fresh admin token
    async with AsyncSessionLocal() as db:
        adm = (await db.execute(select(User).where(User.id == admin_user.id))).scalar_one()
    headers = {"Authorization": f"Bearer {create_access_token(adm.id, adm.username, adm.role.value, adm.token_version)}"}

    # Clean up if this user already exists (test re-run safety)
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(User).where(User.username == test_username))).scalar_one_or_none()
        if existing:
            await db.delete(existing)
            await db.commit()

    resp = await async_client.post(
        "/api/admin/users",
        json={
            "username": test_username,
            "email": test_email,
            "password": test_password,
            "role": "operator",
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text

    # Give background task time to write the audit log
    await asyncio.sleep(2.0)

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.request_path == "/api/admin/users",
                    AuditLog.request_method == "POST",
                )
                .order_by(AuditLog.id.desc())
            )
        ).scalars().all()

    assert len(rows) >= 1, (
        f"Expected at least one audit_log row for POST /api/admin/users, found 0"
    )

    # Check the most recent matching row
    row = rows[0]
    assert row.action == "CREATE", f"Expected action=CREATE, got {row.action!r}"
    assert row.resource_type == "users", f"Expected resource_type=users, got {row.resource_type!r}"
    assert row.status_code in (200, 201), f"Expected status 200/201, got {row.status_code}"

    # Sensitive field must be redacted
    snippet = row.request_body_snippet or ""
    assert test_password not in snippet, (
        f"Raw password leaked in audit log snippet: {snippet!r}"
    )
    assert "***" in snippet, (
        f"Expected '***' redaction in audit log snippet, got: {snippet!r}"
    )
