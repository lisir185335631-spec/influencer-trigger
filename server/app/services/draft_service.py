"""Service layer for the per-recipient email draft workflow.

Owns the heavy lifting that the API layer delegates to:
- Creating draft rows in bulk after Campaign creation
- Driving the LLM personalizer for batch generation
- Single + bulk regenerate
- Composing the list view (draft + influencer join)
- Computing per-status counts for the review UI
- Marshalling drafts → emails for the actual send phase

The router itself (api/drafts.py) stays thin — schema validation, auth,
and delegation only.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.personalizer import (
    ANGLE_DEFINITIONS,
    DEFAULT_ANGLE,
    compute_prompt_hash,
    generate_or_fallback,
)
from app.database import AsyncSessionLocal
from app.models.campaign import Campaign, CampaignStatus
from app.models.email_draft import EmailDraft, EmailDraftStatus
from app.models.influencer import Influencer
from app.models.template import Template
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


# Statuses that count as "sendable" — bulk send only consumes these.
_SENDABLE_STATUSES = {EmailDraftStatus.ready, EmailDraftStatus.edited}


async def create_draft_campaign(
    db: AsyncSession,
    name: str,
    template_id: int,
    influencer_ids: list[int],
    user_id: int | None,
) -> Campaign:
    """Create a Campaign row in draft_pending state plus one EmailDraft per
    influencer (status=pending). The actual LLM generation runs as a
    BackgroundTask via `generate_drafts_for_campaign`."""
    campaign = Campaign(
        name=name,
        template_id=template_id,
        status=CampaignStatus.draft_pending,
        total_count=len(influencer_ids),
        use_drafts=True,
        created_by=user_id,
    )
    db.add(campaign)
    await db.flush()  # need campaign.id for draft FKs

    for inf_id in influencer_ids:
        db.add(EmailDraft(
            campaign_id=campaign.id,
            influencer_id=inf_id,
            template_id=template_id,
            status=EmailDraftStatus.pending,
        ))
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def generate_drafts_for_campaign(
    campaign_id: int,
    angle: str,
    extra_notes: str | None,
    use_premium_model: bool,
) -> None:
    """Background task: walks every pending draft for a campaign, calls the
    LLM personalizer per draft, and updates the row + broadcasts WS progress.

    Runs sequentially (not concurrently) — LLM rate limits and local
    backend stability matter more than wall time, and batch sizes are
    typically <200. Failures on individual drafts don't break the batch.
    """
    angle = angle if angle in ANGLE_DEFINITIONS else DEFAULT_ANGLE
    model = "gpt-4o" if use_premium_model else "gpt-4o-mini"

    async with AsyncSessionLocal() as db:
        # Collect pending drafts + supporting Influencer + Template
        result = await db.execute(
            select(EmailDraft)
            .where(
                EmailDraft.campaign_id == campaign_id,
                EmailDraft.status == EmailDraftStatus.pending,
            )
            .order_by(EmailDraft.id)
        )
        drafts = list(result.scalars().all())
        if not drafts:
            logger.info("Campaign %d: no pending drafts to generate", campaign_id)
            await _finalize_campaign_drafts(db, campaign_id)
            return

        template_id = drafts[0].template_id
        template = await db.get(Template, template_id) if template_id else None

        total = len(drafts)
        completed = 0
        succeeded = 0
        failed = 0

        for draft in drafts:
            influencer = await db.get(Influencer, draft.influencer_id)
            if not influencer:
                draft.status = EmailDraftStatus.failed
                draft.error_message = "Influencer no longer exists"
                failed += 1
                completed += 1
                await db.commit()
                continue

            draft.status = EmailDraftStatus.generating
            await db.commit()

            subject, body_html, model_used, error_msg = await generate_or_fallback(
                influencer=influencer,
                angle_key=angle,
                base_template=template,
                extra_notes=extra_notes,
                model=model,
            )

            draft.subject = subject
            draft.body_html = body_html
            draft.angle_used = angle
            draft.generation_model = model_used  # None if static fallback
            draft.generation_prompt_hash = compute_prompt_hash(
                influencer.id, angle, template_id, model, extra_notes,
            )
            draft.generated_at = datetime.now(timezone.utc)
            draft.error_message = error_msg
            # Static fallback (LLM unavailable) is still "ready" — content
            # was produced and is reviewable. Only true exceptions go to failed.
            draft.status = EmailDraftStatus.ready
            await db.commit()

            if model_used:
                succeeded += 1
            else:
                # Counted as success for UX (something was produced) but
                # tagged with error_msg so the UI can surface a "fallback used"
                # badge.
                succeeded += 1

            completed += 1
            await manager.broadcast("draft:progress", {
                "campaign_id": campaign_id,
                "completed": completed,
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
                "current_influencer": influencer.email,
            })

        await _finalize_campaign_drafts(db, campaign_id)
        await manager.broadcast("draft:completed", {
            "campaign_id": campaign_id,
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
        })
        logger.info(
            "Campaign %d draft generation done: %d/%d ready (%d failed)",
            campaign_id, succeeded, total, failed,
        )


async def _finalize_campaign_drafts(db: AsyncSession, campaign_id: int) -> None:
    """Move campaign from draft_pending → draft_ready when all drafts have
    settled (no more `pending` / `generating` rows)."""
    result = await db.execute(
        select(func.count())
        .select_from(EmailDraft)
        .where(
            EmailDraft.campaign_id == campaign_id,
            EmailDraft.status.in_([
                EmailDraftStatus.pending,
                EmailDraftStatus.generating,
            ]),
        )
    )
    in_flight = result.scalar_one()
    if in_flight == 0:
        await db.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .values(status=CampaignStatus.draft_ready)
        )
        await db.commit()


async def list_drafts_for_campaign(
    db: AsyncSession, campaign_id: int,
) -> tuple[list[dict], int, dict[str, int]]:
    """Returns (rows, total, counts_by_status). Rows are influencer-joined
    dicts ready for DraftListItem."""
    base_q = (
        select(
            EmailDraft.id,
            EmailDraft.campaign_id,
            EmailDraft.influencer_id,
            EmailDraft.subject,
            EmailDraft.body_html,
            EmailDraft.angle_used,
            EmailDraft.status,
            EmailDraft.edited_by_user,
            EmailDraft.error_message,
            EmailDraft.updated_at,
            Influencer.nickname.label("influencer_name"),
            Influencer.email.label("influencer_email"),
            Influencer.platform.label("influencer_platform"),
            Influencer.followers.label("influencer_followers"),
        )
        .join(Influencer, EmailDraft.influencer_id == Influencer.id)
        .where(EmailDraft.campaign_id == campaign_id)
        .order_by(EmailDraft.id)
    )
    rows = (await db.execute(base_q)).mappings().all()

    items: list[dict] = []
    for r in rows:
        body = (r["body_html"] or "").strip()
        # Strip simple HTML tags for the list preview — keeps the API
        # output frontend-agnostic. Frontend renders the full HTML in modal.
        import re as _re
        plain = _re.sub(r"<[^>]+>", " ", body)
        plain = _re.sub(r"\s+", " ", plain).strip()
        items.append({
            "id": r["id"],
            "campaign_id": r["campaign_id"],
            "influencer_id": r["influencer_id"],
            "influencer_name": r["influencer_name"],
            "influencer_email": r["influencer_email"],
            "influencer_platform": (
                r["influencer_platform"].value
                if r["influencer_platform"] is not None
                else None
            ),
            "influencer_followers": r["influencer_followers"],
            "subject": r["subject"],
            "body_html_preview": plain[:200],
            "angle_used": r["angle_used"],
            "status": r["status"].value if r["status"] else "pending",
            "edited_by_user": r["edited_by_user"],
            "error_message": r["error_message"],
            "updated_at": r["updated_at"],
        })

    # Status histogram for the campaign
    histo_q = (
        select(EmailDraft.status, func.count())
        .where(EmailDraft.campaign_id == campaign_id)
        .group_by(EmailDraft.status)
    )
    counts = {
        s.value if s else "unknown": int(c)
        for s, c in (await db.execute(histo_q)).all()
    }

    return items, len(items), counts


async def update_draft(
    db: AsyncSession, draft_id: int, subject: str, body_html: str,
) -> EmailDraft | None:
    """User-driven edit. Sets edited_by_user=True so bulk regenerate skips
    this row by default."""
    draft = await db.get(EmailDraft, draft_id)
    if not draft:
        return None
    if draft.status in {EmailDraftStatus.sending, EmailDraftStatus.sent}:
        # Frozen — once we've handed the draft to the sender it's
        # immutable for audit reasons.
        return draft
    draft.subject = subject
    draft.body_html = body_html
    draft.edited_by_user = True
    if draft.status in {EmailDraftStatus.failed, EmailDraftStatus.pending}:
        draft.status = EmailDraftStatus.edited
    elif draft.status == EmailDraftStatus.ready:
        draft.status = EmailDraftStatus.edited
    await db.commit()
    await db.refresh(draft)
    return draft


async def regenerate_single_draft(
    db: AsyncSession,
    draft_id: int,
    angle: Optional[str],
    extra_notes: Optional[str],
    use_premium_model: bool,
) -> EmailDraft | None:
    """Force LLM regen for one draft. Caller uses this for the per-row
    'try again' button + 'change angle' workflow. Resets edited_by_user
    so the new content reflects the new angle (user can re-edit after)."""
    draft = await db.get(EmailDraft, draft_id)
    if not draft:
        return None
    if draft.status in {EmailDraftStatus.sending, EmailDraftStatus.sent}:
        return draft

    influencer = await db.get(Influencer, draft.influencer_id)
    if not influencer:
        draft.status = EmailDraftStatus.failed
        draft.error_message = "Influencer no longer exists"
        await db.commit()
        return draft

    template = await db.get(Template, draft.template_id) if draft.template_id else None

    angle_key = angle if angle in ANGLE_DEFINITIONS else (
        draft.angle_used or DEFAULT_ANGLE
    )
    model = "gpt-4o" if use_premium_model else "gpt-4o-mini"

    draft.status = EmailDraftStatus.generating
    await db.commit()

    subject, body_html, model_used, error_msg = await generate_or_fallback(
        influencer=influencer,
        angle_key=angle_key,
        base_template=template,
        extra_notes=extra_notes,
        model=model,
    )
    draft.subject = subject
    draft.body_html = body_html
    draft.angle_used = angle_key
    draft.generation_model = model_used
    draft.generation_prompt_hash = compute_prompt_hash(
        influencer.id, angle_key, draft.template_id, model, extra_notes,
    )
    draft.generated_at = datetime.now(timezone.utc)
    draft.error_message = error_msg
    draft.status = EmailDraftStatus.ready
    draft.edited_by_user = False  # regen wipes the "user edited" flag
    await db.commit()
    await db.refresh(draft)
    return draft


async def cancel_draft(db: AsyncSession, draft_id: int) -> EmailDraft | None:
    draft = await db.get(EmailDraft, draft_id)
    if not draft:
        return None
    if draft.status in {EmailDraftStatus.sending, EmailDraftStatus.sent}:
        return draft
    draft.status = EmailDraftStatus.cancelled
    await db.commit()
    await db.refresh(draft)
    return draft


async def count_sendable(db: AsyncSession, campaign_id: int) -> int:
    """How many drafts are eligible for the actual send phase."""
    result = await db.execute(
        select(func.count())
        .select_from(EmailDraft)
        .where(
            EmailDraft.campaign_id == campaign_id,
            EmailDraft.status.in_(list(_SENDABLE_STATUSES)),
        )
    )
    return result.scalar_one()
