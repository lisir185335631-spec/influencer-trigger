"""HTTP routes for the webhook push audit log.

Powers the "Server酱 推送" stat card + modal on the email-monitor page.
Read-only: rows are written by webhook_service._send_with_log; this
module just exposes them to the dashboard.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.webhook_push_log import WebhookPushLog
from app.schemas.auth import TokenData
from app.schemas.webhook_log import (
    WebhookLogItem,
    WebhookLogList,
    WebhookLogStats,
)

router = APIRouter(prefix="/webhook-logs", tags=["webhook-logs"])


@router.get("/stats", response_model=WebhookLogStats)
async def get_stats(
    channel: str | None = Query(default="serverchan"),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> WebhookLogStats:
    """Aggregate counts for the dashboard card. Default channel filter
    is `serverchan` because that's what the card shows; pass channel="" or
    omit to count across all channels."""
    base_filter = []
    if channel:
        base_filter.append(WebhookPushLog.channel == channel)

    total_q = select(func.count(WebhookPushLog.id))
    success_q = select(func.count(WebhookPushLog.id)).where(
        WebhookPushLog.status == "success",
    )
    for f in base_filter:
        total_q = total_q.where(f)
        success_q = success_q.where(f)

    total = (await db.execute(total_q)).scalar_one()
    success = (await db.execute(success_q)).scalar_one()

    return WebhookLogStats(
        total=total,
        success=success,
        failed=max(0, total - success),
    )


@router.get("", response_model=WebhookLogList)
async def list_logs(
    channel: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> WebhookLogList:
    """Newest-first list. The modal opens with `channel=serverchan`,
    `limit=50` for snappy load — that's enough for ~daily ops and the
    real-time WebSocket prepend keeps it fresh while open."""
    base = select(WebhookPushLog)
    if channel:
        base = base.where(WebhookPushLog.channel == channel)

    count_subq = base.subquery()
    total = (
        await db.execute(select(func.count()).select_from(count_subq))
    ).scalar_one()

    rows = (
        await db.execute(
            base.order_by(WebhookPushLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    items = [WebhookLogItem.model_validate(r) for r in rows]
    return WebhookLogList(items=items, total=total)
