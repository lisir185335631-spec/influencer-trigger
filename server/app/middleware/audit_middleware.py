import json
import random
import time
from typing import Callable, Optional

from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.database import AsyncSessionLocal
from app.models.audit_log import AuditLog

_SENSITIVE_KEYS = {"password", "token", "api_key", "access_token", "refresh_token", "secret"}

_METHOD_ACTION = {
    "POST": "CREATE",
    "PUT": "UPDATE",
    "PATCH": "UPDATE",
    "DELETE": "DELETE",
    "GET": "READ",
}


def _redact_dict(data: dict) -> dict:
    result = {}
    for k, v in data.items():
        if k.lower() in _SENSITIVE_KEYS:
            result[k] = "***"
        elif isinstance(v, dict):
            result[k] = _redact_dict(v)
        else:
            result[k] = v
    return result


def _redact_body(raw: str) -> str:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = _redact_dict(data)
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return raw


async def _write_audit_log(
    *,
    user_id: Optional[int],
    username: Optional[str],
    role: Optional[str],
    action: Optional[str],
    resource_type: Optional[str],
    resource_id: Optional[str],
    request_method: Optional[str],
    request_path: Optional[str],
    ip: Optional[str],
    user_agent: Optional[str],
    status_code: Optional[int],
    request_body_snippet: Optional[str],
    response_snippet: Optional[str],
    duration_ms: Optional[int],
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            log = AuditLog(
                user_id=user_id,
                username=username,
                role=role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_method=request_method,
                request_path=request_path,
                ip=ip,
                user_agent=user_agent,
                status_code=status_code,
                request_body_snippet=request_body_snippet,
                response_snippet=response_snippet,
                duration_ms=duration_ms,
            )
            db.add(log)
            await db.commit()
    except Exception:
        pass


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            method = request.method.upper()
            is_write = method in ("POST", "PUT", "PATCH", "DELETE")
            is_read = method == "GET"

            if not (is_write or (is_read and random.random() < 0.1)):
                return await call_next(request)

            start = time.monotonic()

            body_snippet: Optional[str] = None
            if is_write:
                try:
                    raw = await request.body()
                    raw_str = raw.decode("utf-8", errors="replace")[:4096]
                    body_snippet = _redact_body(raw_str)[:2048]
                except Exception:
                    pass

            response = await call_next(request)
            duration_ms = int((time.monotonic() - start) * 1000)

            user_id: Optional[int] = None
            username: Optional[str] = None
            role: Optional[str] = None
            try:
                from app.services.auth_service import decode_token
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    td = decode_token(auth[7:])
                    if td:
                        user_id = td.user_id
                        username = td.username
                        role = td.role
            except Exception:
                pass

            action = _METHOD_ACTION.get(method, method)

            path = request.url.path
            clean = path.lstrip("/")
            if clean.startswith("api/"):
                clean = clean[4:]
            if clean.startswith("admin/"):
                clean = clean[6:]
            parts = [p for p in clean.split("/") if p]
            resource_type = parts[0] if parts else None
            resource_id = parts[1] if len(parts) > 1 else None

            ip = request.client.host if request.client else None
            user_agent = (request.headers.get("user-agent") or "")[:512]

            audit_task = BackgroundTask(
                _write_audit_log,
                user_id=user_id,
                username=username,
                role=role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_method=method,
                request_path=path,
                ip=ip,
                user_agent=user_agent,
                status_code=response.status_code,
                request_body_snippet=body_snippet,
                response_snippet=None,
                duration_ms=duration_ms,
            )

            # Defensive: if response already has a background task (rare), chain instead of overwrite
            if response.background is None:
                response.background = audit_task
            else:
                existing = response.background

                async def _chained() -> None:
                    try:
                        await existing()
                    finally:
                        await _write_audit_log(
                            user_id=user_id,
                            username=username,
                            role=role,
                            action=action,
                            resource_type=resource_type,
                            resource_id=resource_id,
                            request_method=method,
                            request_path=path,
                            ip=ip,
                            user_agent=user_agent,
                            status_code=response.status_code,
                            request_body_snippet=body_snippet,
                            response_snippet=None,
                            duration_ms=duration_ms,
                        )

                response.background = BackgroundTask(_chained)

            return response
        except Exception:
            return await call_next(request)
