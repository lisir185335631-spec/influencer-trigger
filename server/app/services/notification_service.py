from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.influencer import Influencer
from app.models.notification import Notification
from app.schemas.notification import (
    NotificationCreate,
    NotificationListResponse,
    NotificationOut,
)


async def list_notifications(
    db: AsyncSession,
    is_read: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> NotificationListResponse:
    base = select(Notification)
    if is_read is not None:
        base = base.where(Notification.is_read == is_read)

    total_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = total_result.scalar_one()

    unread_result = await db.execute(
        select(func.count()).where(Notification.is_read == False)  # noqa: E712
    )
    unread_count = unread_result.scalar_one()

    rows = await db.execute(
        base.order_by(Notification.is_read.asc(), Notification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    notifications = list(rows.scalars().all())

    influencer_ids = [n.influencer_id for n in notifications if n.influencer_id]
    name_map: dict[int, str] = {}
    if influencer_ids:
        inf_rows = await db.execute(
            select(Influencer.id, Influencer.nickname, Influencer.email).where(
                Influencer.id.in_(influencer_ids)
            )
        )
        for row in inf_rows:
            name_map[row.id] = row.nickname or row.email

    items: list[NotificationOut] = []
    for n in notifications:
        out = NotificationOut.model_validate(n)
        out.influencer_name = name_map.get(n.influencer_id) if n.influencer_id else None
        items.append(out)

    return NotificationListResponse(items=items, total=total, unread_count=unread_count)


async def create_notification(
    db: AsyncSession,
    data: NotificationCreate,
) -> NotificationOut:
    notification = Notification(
        influencer_id=data.influencer_id,
        email_id=data.email_id,
        title=data.title,
        content=data.content,
        level=data.level,
        intent=data.intent,
    )
    db.add(notification)
    await db.flush()
    await db.commit()
    await db.refresh(notification)
    return NotificationOut.model_validate(notification)


async def mark_read(
    db: AsyncSession, notification_id: int
) -> Optional[NotificationOut]:
    notification = await db.get(Notification, notification_id)
    if not notification:
        return None
    notification.is_read = True
    notification.read_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(notification)
    return NotificationOut.model_validate(notification)


async def mark_all_read(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(Notification)
        .where(Notification.is_read == False)  # noqa: E712
        .values(is_read=True, read_at=now)
    )
    await db.commit()
    return result.rowcount
