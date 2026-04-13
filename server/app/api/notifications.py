from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.deps import get_current_user
from app.models.user import User
from app.schemas.notification import (
    NotificationCreate,
    NotificationListResponse,
    NotificationOut,
)
from app.services.notification_service import (
    create_notification,
    list_notifications,
    mark_all_read,
    mark_read,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def get_db():
    async with AsyncSessionLocal() as db:
        yield db


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    is_read: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return await list_notifications(db, is_read=is_read, limit=limit, offset=offset)


@router.post("", response_model=NotificationOut, status_code=201)
async def post_notification(
    data: NotificationCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return await create_notification(db, data)


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def patch_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await mark_read(db, notification_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return result


@router.post("/read-all")
async def post_read_all(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    count = await mark_all_read(db)
    return {"marked_read": count}
