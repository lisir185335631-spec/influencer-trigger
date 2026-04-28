"""Pydantic schemas for /api/webhook-logs endpoints."""
from datetime import datetime

from pydantic import BaseModel


class WebhookLogItem(BaseModel):
    id: int
    channel: str
    email_id: int | None = None
    influencer_id: int | None = None
    title: str
    content_preview: str
    status: str  # "success" | "failed"
    http_code: int | None = None
    error_message: str | None = None
    duration_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookLogList(BaseModel):
    items: list[WebhookLogItem]
    total: int


class WebhookLogStats(BaseModel):
    total: int
    success: int
    failed: int
