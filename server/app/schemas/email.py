import math
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


class SendDirectRequest(BaseModel):
    """One-off "send to this email" form. The recipient may not be in the
    influencer table yet — backend creates a manual record on demand so
    the row still flows through the standard sender → email_drafts →
    emails pipeline (and inherits tracking pixel + IMAP reply detection)
    instead of bypassing them."""
    to_email: str
    to_name: Optional[str] = None
    subject: str
    body_html: str
    campaign_name: Optional[str] = None


class SendDirectResponse(BaseModel):
    campaign_id: int
    influencer_id: int
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


class EmailListItem(BaseModel):
    id: int
    influencer_id: int
    influencer_name: Optional[str] = None
    influencer_email: str
    influencer_platform: Optional[str] = None
    # email_type tells the UI whether this is the initial outreach, an
    # automated follow-up, or a holiday greeting — so operators viewing the
    # monitor list can distinguish "first contact" from "follow-up #N".
    email_type: str
    # Snapshot of the influencer's follow_up_count at list-time. Combined
    # with email_type it lets the UI render "follow-up #2/9" inline.
    follow_up_count: int
    campaign_id: Optional[int] = None
    campaign_name: Optional[str] = None
    status: str
    subject: str
    sent_at: Optional[datetime] = None
    updated_at: datetime


class EmailStats(BaseModel):
    total_sent: int
    delivered: int
    opened: int
    replied: int
    no_reply: int
    bounced: int


class EmailListResponse(BaseModel):
    items: list[EmailListItem]
    total: int
    page: int
    page_size: int
    total_pages: int
