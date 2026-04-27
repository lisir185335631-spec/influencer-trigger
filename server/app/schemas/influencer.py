from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Tag schemas ─────────────────────────────────────────────────────────────

class TagOut(BaseModel):
    id: int
    name: str
    color: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TagCreate(BaseModel):
    name: str
    color: str = "#6366f1"


# ── Note schemas ─────────────────────────────────────────────────────────────

class NoteOut(BaseModel):
    id: int
    influencer_id: int
    content: str
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NoteCreate(BaseModel):
    content: str


# ── Collaboration schemas ────────────────────────────────────────────────────

class CollaborationOut(BaseModel):
    id: int
    influencer_id: int
    title: str
    status: str
    description: Optional[str] = None
    budget: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Email timeline schemas ───────────────────────────────────────────────────

class EmailTimelineItem(BaseModel):
    id: int
    email_type: str
    subject: str
    status: str
    reply_content: Optional[str] = None
    reply_from: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    replied_at: Optional[datetime] = None
    bounced_at: Optional[datetime] = None
    created_at: datetime


# ── Influencer detail schemas ────────────────────────────────────────────────

class InfluencerDetail(BaseModel):
    id: int
    nickname: Optional[str] = None
    email: str
    platform: Optional[str] = None
    profile_url: Optional[str] = None
    followers: Optional[int] = None
    industry: Optional[str] = None
    bio: Optional[str] = None
    status: str
    priority: str
    reply_intent: Optional[str] = None
    follow_up_count: int
    last_email_sent_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    tags: list[TagOut] = []
    notes: list[NoteOut] = []
    collaborations: list[CollaborationOut] = []
    emails: list[EmailTimelineItem] = []


class InfluencerUpdate(BaseModel):
    nickname: Optional[str] = None
    platform: Optional[str] = None
    profile_url: Optional[str] = None
    followers: Optional[int] = None
    industry: Optional[str] = None
    bio: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    # Used by the InfluencerDetail "重启从头" button to reset cadence back
    # to follow-up #0 — combined with status='new' it puts the influencer
    # back into the picker as a fresh lead. Range-bounded so a malformed or
    # adversarial PATCH can't corrupt the counter:
    #   ge=0   — negative would make the cadence's "count < total_cap" SQL
    #            check permanently true, causing infinite follow-ups
    #   le=100 — well above any plausible spec (default total_cap=9); keeps
    #            the door open for custom cadences without permitting absurd
    #            values that would silently disable follow-ups (e.g. 9999999
    #            would always exceed any sane cap → influencer never re-fired)
    follow_up_count: Optional[int] = Field(None, ge=0, le=100)


class InfluencerListItem(BaseModel):
    id: int
    nickname: Optional[str] = None
    email: str
    platform: Optional[str] = None
    avatar_url: Optional[str] = None
    profile_url: Optional[str] = None
    followers: Optional[int] = None
    industry: Optional[str] = None
    bio: Optional[str] = None
    status: str
    priority: str
    reply_intent: Optional[str] = None
    reply_summary: Optional[str] = None
    relevance_score: Optional[float] = None
    match_reason: Optional[str] = None
    follow_up_count: int
    last_email_sent_at: Optional[datetime] = None
    created_at: datetime
    tags: list[TagOut] = []


class InfluencerListResponse(BaseModel):
    items: list[InfluencerListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── Tag assignment ───────────────────────────────────────────────────────────

class AssignTagsRequest(BaseModel):
    tag_ids: list[int]


# ── Batch operations ─────────────────────────────────────────────────────────

class BatchUpdateRequest(BaseModel):
    influencer_ids: list[int]
    action: str  # "archive" | "assign_tags"
    tag_ids: Optional[list[int]] = None


class BatchUpdateResponse(BaseModel):
    affected: int


# ── Export params ─────────────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    status: Optional[str] = None
    platform: Optional[str] = None
    priority: Optional[str] = None
    search: Optional[str] = None
    tag_ids: Optional[list[int]] = None
    followers_min: Optional[int] = None
    followers_max: Optional[int] = None
    industry: Optional[str] = None
    reply_intent: Optional[str] = None
