from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class SendBatchRequest(BaseModel):
    influencer_ids: list[int]
    template_id: int
    campaign_name: Optional[str] = None


class SendBatchResponse(BaseModel):
    campaign_id: int
    campaign_name: str
    total_count: int
    message: str


class CampaignOut(BaseModel):
    id: int
    name: str
    status: str
    total_count: int
    sent_count: int
    success_count: int
    failed_count: int
    replied_count: int
    bounced_count: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EmailOut(BaseModel):
    id: int
    influencer_id: int
    campaign_id: Optional[int] = None
    mailbox_id: Optional[int] = None
    template_id: Optional[int] = None
    status: str
    subject: str
    message_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}
