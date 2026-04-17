import csv
import io
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.schemas.auth import TokenData

router = APIRouter(prefix="/audit", tags=["admin-audit"])


def _day_start(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time())


def _day_end(d: date) -> datetime:
    return datetime.combine(d, datetime.max.time())


@router.get("/logs")
async def list_audit_logs(
    user_id: Optional[int] = Query(None),
    username: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    method: Optional[str] = Query(None),
    status_code: Optional[int] = Query(None),
    created_at_start: Optional[datetime] = Query(None),
    created_at_end: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: TokenData = Depends(require_admin),
) -> dict:
    offset = (page - 1) * page_size

    async with AsyncSessionLocal() as db:
        q = select(AuditLog)
        count_q = select(func.count(AuditLog.id))

        if user_id is not None:
            q = q.where(AuditLog.user_id == user_id)
            count_q = count_q.where(AuditLog.user_id == user_id)
        if username:
            q = q.where(AuditLog.username.ilike(f"%{username}%"))
            count_q = count_q.where(AuditLog.username.ilike(f"%{username}%"))
        if action:
            q = q.where(AuditLog.action == action.upper())
            count_q = count_q.where(AuditLog.action == action.upper())
        if resource_type:
            q = q.where(AuditLog.resource_type == resource_type)
            count_q = count_q.where(AuditLog.resource_type == resource_type)
        if method:
            q = q.where(AuditLog.request_method == method.upper())
            count_q = count_q.where(AuditLog.request_method == method.upper())
        if status_code is not None:
            q = q.where(AuditLog.status_code == status_code)
            count_q = count_q.where(AuditLog.status_code == status_code)
        if created_at_start:
            q = q.where(AuditLog.created_at >= created_at_start)
            count_q = count_q.where(AuditLog.created_at >= created_at_start)
        if created_at_end:
            q = q.where(AuditLog.created_at <= created_at_end)
            count_q = count_q.where(AuditLog.created_at <= created_at_end)

        total = (await db.execute(count_q)).scalar_one()
        rows = (
            await db.execute(q.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size))
        ).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_log_to_dict(r) for r in rows],
    }


@router.get("/export")
async def export_audit_logs(
    user_id: Optional[int] = Query(None),
    username: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    method: Optional[str] = Query(None),
    status_code: Optional[int] = Query(None),
    created_at_start: Optional[datetime] = Query(None),
    created_at_end: Optional[datetime] = Query(None),
    current_user: TokenData = Depends(require_admin),
) -> StreamingResponse:
    async with AsyncSessionLocal() as db:
        q = select(AuditLog)

        if user_id is not None:
            q = q.where(AuditLog.user_id == user_id)
        if username:
            q = q.where(AuditLog.username.ilike(f"%{username}%"))
        if action:
            q = q.where(AuditLog.action == action.upper())
        if resource_type:
            q = q.where(AuditLog.resource_type == resource_type)
        if method:
            q = q.where(AuditLog.request_method == method.upper())
        if status_code is not None:
            q = q.where(AuditLog.status_code == status_code)
        if created_at_start:
            q = q.where(AuditLog.created_at >= created_at_start)
        if created_at_end:
            q = q.where(AuditLog.created_at <= created_at_end)

        rows = (
            await db.execute(q.order_by(AuditLog.created_at.desc()).limit(10000))
        ).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "user_id", "username", "role", "action", "resource_type", "resource_id",
        "request_method", "request_path", "ip", "user_agent", "status_code",
        "request_body_snippet", "response_snippet", "duration_ms", "created_at",
    ])
    for r in rows:
        writer.writerow([
            r.id, r.user_id, r.username, r.role, r.action, r.resource_type, r.resource_id,
            r.request_method, r.request_path, r.ip, r.user_agent, r.status_code,
            r.request_body_snippet, r.response_snippet, r.duration_ms,
            r.created_at.isoformat() if r.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )


@router.get("/stats")
async def get_audit_stats(
    current_user: TokenData = Depends(require_admin),
) -> dict:
    today = date.today()
    since = _day_start(today - timedelta(days=6))

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(
                func.strftime("%Y-%m-%d", AuditLog.created_at).label("day"),
                AuditLog.action,
                func.count(AuditLog.id).label("cnt"),
            )
            .where(AuditLog.created_at >= since)
            .group_by("day", AuditLog.action)
            .order_by("day")
        )).all()

    # Build a day-keyed dict
    trend: dict[str, dict[str, int]] = {}
    for i in range(7):
        d = (today - timedelta(days=6 - i)).strftime("%Y-%m-%d")
        trend[d] = {}

    for row in rows:
        day, action, cnt = row
        if day in trend:
            trend[day][action or "UNKNOWN"] = cnt

    return {
        "trend": [
            {"date": day, "actions": actions}
            for day, actions in sorted(trend.items())
        ]
    }


def _log_to_dict(r: AuditLog) -> dict:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "username": r.username,
        "role": r.role,
        "action": r.action,
        "resource_type": r.resource_type,
        "resource_id": r.resource_id,
        "request_method": r.request_method,
        "request_path": r.request_path,
        "ip": r.ip,
        "user_agent": r.user_agent,
        "status_code": r.status_code,
        "request_body_snippet": r.request_body_snippet,
        "response_snippet": r.response_snippet,
        "duration_ms": r.duration_ms,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
