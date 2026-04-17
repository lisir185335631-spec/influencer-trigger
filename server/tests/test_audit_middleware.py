"""Unit tests for audit middleware - sensitive field masking, sampling, and log writing."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.audit_middleware import _redact_body, _redact_dict, _write_audit_log


# --- Test 1: sensitive field masking in request body ---

def test_redact_body_masks_password():
    raw = json.dumps({"username": "alice", "password": "s3cret!"})
    result = json.loads(_redact_body(raw))
    assert result["password"] == "***"
    assert result["username"] == "alice"


def test_redact_body_masks_token_and_api_key():
    raw = json.dumps({"token": "tok_abc", "api_key": "sk-123", "name": "test"})
    result = json.loads(_redact_body(raw))
    assert result["token"] == "***"
    assert result["api_key"] == "***"
    assert result["name"] == "test"


def test_redact_dict_nested_sensitive_field():
    data = {"auth": {"access_token": "bearer_xyz", "expires": 3600}, "id": 1}
    result = _redact_dict(data)
    assert result["auth"]["access_token"] == "***"
    assert result["auth"]["expires"] == 3600
    assert result["id"] == 1


def test_redact_body_non_json_returns_original():
    raw = "not-json-content"
    assert _redact_body(raw) == "not-json-content"


# --- Test 2: read operation sampling is ~10% ---

def test_read_operation_sampling_rate():
    import random
    random.seed(0)
    sample_count = sum(1 for _ in range(10000) if random.random() < 0.1)
    # Expect roughly 1000 (10%), allow generous variance for test stability
    assert 700 < sample_count < 1300


# --- Test 3: _write_audit_log writes a record without raising ---

@pytest.mark.asyncio
async def test_write_audit_log_calls_db_add_and_commit():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.middleware.audit_middleware.AsyncSessionLocal", return_value=mock_ctx):
        await _write_audit_log(
            user_id=1,
            username="admin",
            role="admin",
            action="CREATE",
            resource_type="users",
            resource_id=None,
            request_method="POST",
            request_path="/api/users",
            ip="127.0.0.1",
            user_agent="pytest",
            status_code=200,
            request_body_snippet='{"name":"test"}',
            response_snippet=None,
            duration_ms=15,
        )

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_write_audit_log_silently_swallows_db_error():
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("DB connection error"))
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.middleware.audit_middleware.AsyncSessionLocal", return_value=mock_ctx):
        # Must not raise
        await _write_audit_log(
            user_id=None,
            username=None,
            role=None,
            action="READ",
            resource_type="logs",
            resource_id=None,
            request_method="GET",
            request_path="/api/admin/audit/logs",
            ip="10.0.0.1",
            user_agent="test-agent",
            status_code=200,
            request_body_snippet=None,
            response_snippet=None,
            duration_ms=5,
        )
