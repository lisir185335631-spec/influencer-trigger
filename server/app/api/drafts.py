"""HTTP routes for the per-recipient email draft workflow.

Phase 1 endpoints:
- GET  /personalizer/angles                 — list available angle options
- POST /campaigns/drafts/generate           — create campaign + start LLM batch
- GET  /campaigns/{id}/drafts               — list all drafts for a campaign
- GET  /drafts/{id}                         — read one draft (for editor modal)
- PUT  /drafts/{id}                         — user edit (subject + body)
- POST /drafts/{id}/regenerate              — single regenerate (LLM)
- DELETE /drafts/{id}                       — cancel a draft
- POST /campaigns/{id}/drafts/send          — kick off batch send (uses sender)
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.personalizer import list_angles
from app.agents.supervisor import run_sender_with_tracking
from app.database import get_db
from app.deps import get_current_user
from app.models.campaign import Campaign, CampaignStatus
from app.models.email_draft import EmailDraft, EmailDraftStatus
from app.schemas.auth import TokenData
from app.schemas.draft import (
    AngleOption,
    DraftListItem,
    DraftListResponse,
    DraftOut,
    GenerateDraftsRequest,
    GenerateDraftsResponse,
    RegenerateDraftRequest,
    SendCampaignFromDraftsResponse,
    UpdateDraftRequest,
)
from app.services.draft_service import (
    cancel_draft,
    count_sendable,
    create_draft_campaign,
    generate_drafts_for_campaign,
    list_drafts_for_campaign,
    regenerate_single_draft,
    update_draft,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["email-drafts"])


@router.get("/personalizer/angles", response_model=list[AngleOption])
async def get_angles(
    _: TokenData = Depends(get_current_user),
) -> list[AngleOption]:
    return [AngleOption(**a) for a in list_angles()]


# ── Generate ─────────────────────────────────────────────────────────────────

@router.post(
    "/campaigns/drafts/generate",
    response_model=GenerateDraftsResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_drafts(
    body: GenerateDraftsRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
) -> GenerateDraftsResponse:
    name = body.campaign_name or f"Campaign {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    campaign = await create_draft_campaign(
        db=db,
        name=name,
        template_id=body.template_id,
        influencer_ids=body.influencer_ids,
        user_id=current_user.user_id,
    )
    background_tasks.add_task(
        _launch_draft_generation,
        campaign.id,
        body.angle,
        body.extra_notes,
        body.use_premium_model,
    )
    return GenerateDraftsResponse(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        total_count=campaign.total_count,
        message=f"Started generating {campaign.total_count} draft(s)",
    )


async def _launch_draft_generation(
    campaign_id: int,
    angle: str,
    extra_notes: Optional[str],
    use_premium_model: bool,
) -> None:
    try:
        await generate_drafts_for_campaign(
            campaign_id, angle, extra_notes, use_premium_model,
        )
    except Exception:
        logger.exception(
            "Draft generation for campaign %d raised unexpectedly",
            campaign_id,
        )


# ── Read ─────────────────────────────────────────────────────────────────────

@router.get(
    "/campaigns/{campaign_id}/drafts",
    response_model=DraftListResponse,
)
async def list_drafts(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> DraftListResponse:
    items, total, counts = await list_drafts_for_campaign(db, campaign_id)
    return DraftListResponse(
        items=[DraftListItem(**i) for i in items],
        total=total,
        counts_by_status=counts,
    )


@router.get("/drafts/{draft_id}", response_model=DraftOut)
async def get_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> DraftOut:
    draft = await db.get(EmailDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return DraftOut.model_validate(draft)


# ── Update / Regenerate / Cancel ─────────────────────────────────────────────

@router.put("/drafts/{draft_id}", response_model=DraftOut)
async def edit_draft(
    draft_id: int,
    body: UpdateDraftRequest,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> DraftOut:
    draft = await update_draft(db, draft_id, body.subject, body.body_html)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status in {EmailDraftStatus.sending, EmailDraftStatus.sent}:
        raise HTTPException(
            status_code=409,
            detail="Cannot edit a draft that is already sending or sent",
        )
    return DraftOut.model_validate(draft)


@router.post("/drafts/{draft_id}/regenerate", response_model=DraftOut)
async def regenerate_draft(
    draft_id: int,
    body: RegenerateDraftRequest,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> DraftOut:
    draft = await regenerate_single_draft(
        db,
        draft_id,
        angle=body.angle,
        extra_notes=body.extra_notes,
        use_premium_model=body.use_premium_model,
    )
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return DraftOut.model_validate(draft)


@router.delete("/drafts/{draft_id}", response_model=DraftOut)
async def remove_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> DraftOut:
    draft = await cancel_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return DraftOut.model_validate(draft)


# ── Send ─────────────────────────────────────────────────────────────────────

@router.post(
    "/campaigns/{campaign_id}/drafts/send",
    response_model=SendCampaignFromDraftsResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_campaign_from_drafts(
    campaign_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> SendCampaignFromDraftsResponse:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not campaign.use_drafts:
        raise HTTPException(
            status_code=400,
            detail="Campaign was not created in draft mode",
        )

    # Collect sendable drafts (status: ready/edited)
    result = await db.execute(
        select(EmailDraft.influencer_id, EmailDraft.id)
        .where(
            EmailDraft.campaign_id == campaign_id,
            EmailDraft.status.in_([
                EmailDraftStatus.ready, EmailDraftStatus.edited,
            ]),
        )
    )
    pairs = result.all()
    influencer_ids = [int(p[0]) for p in pairs]
    sendable = await count_sendable(db, campaign_id)
    total_q = await db.execute(
        select(EmailDraft.id).where(EmailDraft.campaign_id == campaign_id)
    )
    total = len(total_q.all())

    if not influencer_ids:
        raise HTTPException(
            status_code=400,
            detail="No drafts in 'ready' or 'edited' state to send",
        )

    # Hand off to the existing sender pipeline. Sender's draft branch
    # (Task #4) reads (subject, body_html) from the draft directly so it
    # bypasses Jinja2 rendering.
    template_id = campaign.template_id or 0
    background_tasks.add_task(
        _launch_sender_from_drafts,
        campaign_id,
        influencer_ids,
        template_id,
    )

    return SendCampaignFromDraftsResponse(
        campaign_id=campaign_id,
        total_drafts=total,
        sendable_drafts=sendable,
        message=f"Sending {sendable} of {total} drafts",
    )


async def _launch_sender_from_drafts(
    campaign_id: int, influencer_ids: list[int], template_id: int,
) -> None:
    try:
        await run_sender_with_tracking(
            campaign_id, influencer_ids, template_id,
        )
    except Exception:
        logger.exception(
            "Sender (from drafts) for campaign %d raised unexpectedly",
            campaign_id,
        )
