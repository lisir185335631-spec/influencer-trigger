from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: int
    influencer_id: Optional[int] = None
    email_id: Optional[int] = None
    title: str
    content: str
    level: str
    intent: Optional[str] = None
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime
    influencer_name: Optional[str] = None

    model_config = {"from_attributes": True}


class NotificationCreate(BaseModel):
    influencer_id: Optional[int] = None
    email_id: Optional[int] = None
    title: str
    content: str
    level: str = "info"
    intent: Optional[str] = None


class NotificationListResponse(BaseModel):
    items: list[NotificationOut]
    total: int
    unread_count: int
