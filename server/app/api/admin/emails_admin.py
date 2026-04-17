from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.email import Email, EmailStatus
from app.models.email_blacklist import EmailBlacklist
from app.models.influencer import Influencer
from app.models.mailbox import Mailbox
from app.models.template import Template
from app.schemas.auth import TokenData

router = APIRouter(prefix="/emails", tags=["admin-emails"])

CANCELLABLE = {EmailStatus.pending, EmailStatus.queued}


# ── Schemas ────────────────────────────────────────────────────────────────────

class BatchCancelRequest(BaseModel):
    email_ids: list[int]


class BlacklistAddRequest(BaseModel):
    email: str
    reason: Optional[str] = None


# ── Email list ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_emails_admin(
    status: Optional[str] = None,
    sender_email: Optional[str] = None,
    recipient: Optional[str] = None,
    template_id: Optional[int] = None,
    sent_at_start: Optional[str] = None,
    sent_at_end: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        base_q = (
            select(
                Email.id,
                Email.status,
                Email.subject,
                Email.sent_at,
                Email.opened_at,
                Email.replied_at,
                Email.created_at,
                Influencer.email.label("recipient_email"),
                Influencer.nickname.label("recipient_name"),
                Mailbox.email.label("sender_email"),
                Template.name.label("template_name"),
                Email.template_id,
            )
            .join(Influencer, Email.influencer_id == Influencer.id)
            .outerjoin(Mailbox, Email.mailbox_id == Mailbox.id)
            .outerjoin(Template, Email.template_id == Template.id)
        )

        if status:
            base_q = base_q.where(Email.status == status)
        if sender_email:
            base_q = base_q.where(Mailbox.email.ilike(f"%{sender_email}%"))
        if recipient:
            base_q = base_q.where(Influencer.email.ilike(f"%{recipient}%"))
        if template_id:
            base_q = base_q.where(Email.template_id == template_id)
        if sent_at_start:
            base_q = base_q.where(Email.sent_at >= datetime.fromisoformat(sent_at_start))
        if sent_at_end:
            base_q = base_q.where(Email.sent_at <= datetime.fromisoformat(sent_at_end))

        total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar_one()
        rows = (
            await db.execute(
                base_q.order_by(Email.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).mappings().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r["id"],
                "status": r["status"].value if r["status"] else None,
                "subject": r["subject"],
                "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                "opened": r["opened_at"] is not None,
                "replied": r["replied_at"] is not None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "recipient_email": r["recipient_email"],
                "recipient_name": r["recipient_name"],
                "sender_email": r["sender_email"],
                "template_name": r["template_name"],
                "template_id": r["template_id"],
            }
            for r in rows
        ],
    }


# ── Batch cancel ───────────────────────────────────────────────────────────────

@router.post("/batch-cancel")
async def batch_cancel_emails(
    body: BatchCancelRequest,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    if not body.email_ids:
        raise HTTPException(status_code=422, detail="email_ids must not be empty")

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Email.id, Email.status, Influencer.email.label("recipient"))
                .join(Influencer, Email.influencer_id == Influencer.id)
                .where(Email.id.in_(body.email_ids))
            )
        ).mappings().all()

        cancellable_ids = [r["id"] for r in rows if r["status"] in CANCELLABLE]

        if cancellable_ids:
            await db.execute(
                update(Email)
                .where(Email.id.in_(cancellable_ids))
                .values(status=EmailStatus.cancelled, updated_at=datetime.now(timezone.utc))
            )
            await db.commit()

    return {
        "cancelled": len(cancellable_ids),
        "skipped": len(body.email_ids) - len(cancellable_ids),
    }


# ── Stats ──────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_email_stats_admin(
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        sent_statuses = [
            EmailStatus.sent,
            EmailStatus.delivered,
            EmailStatus.opened,
            EmailStatus.clicked,
            EmailStatus.replied,
            EmailStatus.bounced,
        ]
        total_sent = (
            await db.execute(
                select(func.count(Email.id)).where(Email.status.in_(sent_statuses))
            )
        ).scalar_one() or 0

        today_start = datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time())
        today_sent = (
            await db.execute(
                select(func.count(Email.id)).where(
                    Email.status.in_(sent_statuses),
                    Email.sent_at >= today_start,
                )
            )
        ).scalar_one() or 0

        bounced = (
            await db.execute(
                select(func.count(Email.id)).where(Email.status == EmailStatus.bounced)
            )
        ).scalar_one() or 0

        opened = (
            await db.execute(
                select(func.count(Email.id)).where(
                    Email.status.in_([EmailStatus.opened, EmailStatus.clicked, EmailStatus.replied])
                )
            )
        ).scalar_one() or 0

        replied = (
            await db.execute(
                select(func.count(Email.id)).where(Email.status == EmailStatus.replied)
            )
        ).scalar_one() or 0

        bounce_rate = round(bounced / total_sent * 100, 2) if total_sent else 0.0
        open_rate = round(opened / total_sent * 100, 2) if total_sent else 0.0
        reply_rate = round(replied / total_sent * 100, 2) if total_sent else 0.0

        # Per-mailbox breakdown
        mailbox_rows = (
            await db.execute(
                select(
                    Mailbox.email.label("mailbox_email"),
                    func.count(Email.id).label("total"),
                    func.sum(case((Email.status == EmailStatus.bounced, 1), else_=0)).label("bounced"),
                    func.sum(
                        case(
                            (Email.status.in_([EmailStatus.opened, EmailStatus.clicked, EmailStatus.replied]), 1),
                            else_=0,
                        )
                    ).label("opened"),
                    func.sum(case((Email.status == EmailStatus.replied, 1), else_=0)).label("replied"),
                )
                .join(Mailbox, Email.mailbox_id == Mailbox.id)
                .where(Email.status.in_(sent_statuses))
                .group_by(Mailbox.email)
            )
        ).mappings().all()

    per_mailbox = [
        {
            "mailbox_email": r["mailbox_email"],
            "total": r["total"],
            "bounce_rate": round(r["bounced"] / r["total"] * 100, 2) if r["total"] else 0.0,
            "open_rate": round(r["opened"] / r["total"] * 100, 2) if r["total"] else 0.0,
            "reply_rate": round(r["replied"] / r["total"] * 100, 2) if r["total"] else 0.0,
        }
        for r in mailbox_rows
    ]

    return {
        "total_sent": total_sent,
        "today_sent": today_sent,
        "bounce_rate": bounce_rate,
        "open_rate": open_rate,
        "reply_rate": reply_rate,
        "per_mailbox": per_mailbox,
    }


# ── Blacklist ──────────────────────────────────────────────────────────────────

@router.get("/blacklist")
async def list_blacklist(
    current_user: TokenData = Depends(require_admin),
) -> list:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(EmailBlacklist).order_by(EmailBlacklist.created_at.desc())
            )
        ).scalars().all()
    return [
        {
            "id": r.id,
            "email": r.email,
            "reason": r.reason,
            "added_by_user_id": r.added_by_user_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/blacklist")
async def add_to_blacklist(
    body: BlacklistAddRequest,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(EmailBlacklist).where(EmailBlacklist.email == body.email.lower())
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Email already in blacklist")

        entry = EmailBlacklist(
            email=body.email.lower(),
            reason=body.reason,
            added_by_user_id=current_user.user_id,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

    return {
        "id": entry.id,
        "email": entry.email,
        "reason": entry.reason,
        "added_by_user_id": entry.added_by_user_id,
        "created_at": entry.created_at.isoformat(),
    }


@router.delete("/blacklist/{entry_id}")
async def remove_from_blacklist(
    entry_id: int,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        entry = await db.get(EmailBlacklist, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Blacklist entry not found")
        await db.delete(entry)
        await db.commit()
    return {"deleted": True}
