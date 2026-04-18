"""
Integration tests: non-admin (operator) role must be forbidden from every
/api/admin/* endpoint, and unauthenticated requests must yield 401/403.
"""
import pytest


@pytest.mark.parametrize("method,path,body", [
    ("GET",  "/api/admin/overview/metrics", None),
    ("GET",  "/api/admin/overview/health",  None),
    ("GET",  "/api/admin/users",            None),
    ("POST", "/api/admin/users",            {"username": "x", "email": "x@example.com", "password": "pwpwpw", "role": "operator"}),
    ("GET",  "/api/admin/audit/logs",       None),
    ("GET",  "/api/admin/mailboxes",        None),
    ("GET",  "/api/admin/agents/status",    None),
    ("POST", "/api/admin/security/rotate-keys", {"admin_password": "anything"}),
])
@pytest.mark.asyncio
async def test_operator_forbidden_from_admin_endpoints(async_client, operator_headers, method, path, body):
    """Non-admin users must get 403 on every /api/admin/* endpoint."""
    kwargs = {"headers": operator_headers}
    if body is not None:
        kwargs["json"] = body
    resp = await async_client.request(method, path, **kwargs)
    assert resp.status_code == 403, f"{method} {path} expected 403, got {resp.status_code}: {resp.text[:200]}"


@pytest.mark.asyncio
async def test_unauthenticated_request_is_401_not_403(async_client):
    """No token at all should yield 401 or 403 (FastAPI HTTPBearer defaults to 403 when missing)."""
    resp = await async_client.get("/api/admin/overview/metrics")
    assert resp.status_code in (401, 403), f"expected 401/403, got {resp.status_code}"
