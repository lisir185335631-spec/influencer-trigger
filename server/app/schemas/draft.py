"""Pydantic schemas for the per-recipient email draft workflow.

Phase 1 of the personalization pipeline: drafts hold LLM-generated content
between campaign creation and batch send. Schemas here cover:
- Listing angles available to users (UI dropdown)
- Creating a draft campaign + triggering generation
- Reading drafts (single + list)
- Editing / regenerating / cancelling drafts
- Triggering the final batch send from drafts
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Angle catalog (for UI) ───────────────────────────────────────────────────

class AngleOption(BaseModel):
    """One option in the angle dropdown."""
    key: str
    description: str


# ── Generate ─────────────────────────────────────────────────────────────────

class GenerateDraftsRequest(BaseModel):
    """Create a Campaign in draft mode and kick off batch LLM generation
    for all selected influencers."""
    influencer_ids: list[int] = Field(..., min_length=1)
    template_id: int
    campaign_name: Optional[str] = None
    angle: str = "friendly"
    extra_notes: Optional[str] = Field(None, max_length=500)
    # premium model only on user-explicit request — gpt-4o-mini default
    use_premium_model: bool = False


class GenerateDraftsResponse(BaseModel):
    campaign_id: int
    campaign_name: str
    total_count: int
    message: str


# ── Read ─────────────────────────────────────────────────────────────────────

class DraftOut(BaseModel):
    """Full single-draft view (for editor modal)."""
    id: int
    campaign_id: int
    influencer_id: int
    template_id: Optional[int]
    subject: str
    body_html: str
    angle_used: Optional[str]
    generation_model: Optional[str]
    status: str
    edited_by_user: bool
    error_message: Optional[str]
    email_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    generated_at: Optional[datetime]
    sent_at: Optional[datetime]

    model_config = {"from_attributes": True}


class DraftListItem(BaseModel):
    """List view — joins influencer info for the table view."""
    id: int
    campaign_id: int
    influencer_id: int
    influencer_name: Optional[str]
    influencer_email: str
    influencer_platform: Optional[str]
    influencer_followers: Optional[int]
    subject: str
    body_html_preview: str  # first ~200 chars stripped
    angle_used: Optional[str]
    status: str
    edited_by_user: bool
    error_message: Optional[str]
    updated_at: datetime


class DraftListResponse(BaseModel):
    items: list[DraftListItem]
    total: int
    # Aggregated counts so the UI can show progress without re-counting client-side
    counts_by_status: dict[str, int]


# ── Update / Regenerate / Delete ─────────────────────────────────────────────

class UpdateDraftRequest(BaseModel):
    """User edits a draft — sets edited_by_user=True so subsequent bulk
    regenerate operations skip this row."""
    subject: str = Field(..., max_length=512)
    body_html: str


class RegenerateDraftRequest(BaseModel):
    """Force regeneration of a single draft. Optional `angle` overrides the
    campaign default; otherwise reuses the angle this draft was originally
    generated with."""
    angle: Optional[str] = None
    use_premium_model: bool = False
    extra_notes: Optional[str] = Field(None, max_length=500)


class BulkRegenerateRequest(BaseModel):
    """Bulk regenerate by status filter. By default skips edited_by_user
    drafts to preserve user customisations — pass include_edited=True to
    override."""
    angle: Optional[str] = None
    statuses: list[str] = Field(default_factory=lambda: ["ready", "failed"])
    include_edited: bool = False
    use_premium_model: bool = False
    extra_notes: Optional[str] = Field(None, max_length=500)


# ── Send (campaign-level trigger after review) ───────────────────────────────

class SendCampaignFromDraftsResponse(BaseModel):
    campaign_id: int
    total_drafts: int
    sendable_drafts: int  # status in {ready, edited}, excludes failed/cancelled
    message: str
