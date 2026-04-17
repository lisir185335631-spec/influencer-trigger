import imaplib
import smtplib
import ssl
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select, update

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.email import Email, EmailStatus
from app.models.influencer import Influencer
from app.models.mailbox import Mailbox, MailboxStatus
from app.schemas.auth import TokenData
from app.services.mailbox_service import decrypt_password

router = APIRouter(prefix="/mailboxes", tags=["admin-mailboxes"])

FAILED_STATUSES = [EmailStatus.bounced, EmailStatus.failed]
SENT_STATUSES = [
    EmailStatus.sent, EmailStatus.delivered, EmailStatus.opened,
    EmailStatus.clicked, EmailStatus.replied, EmailStatus.bounced, EmailStatus.failed,
]


def _compute_health(failure_rate: float, quota_pct: float, status: MailboxStatus) -> dict:
    if status == MailboxStatus.inactive:
        return {"score": "disabled", "color": "gray"}
    if failure_rate > 5.0:
        return {"score": "critical", "color": "red"}
    if failure_rate >= 1.0:
        return {"score": "warning", "color": "yellow"}
    return {"score": "healthy", "color": "green"}


@router.get("")
async def list_mailboxes_admin(
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        mailboxes = (
            await db.execute(select(Mailbox).order_by(Mailbox.id))
        ).scalars().all()

        stats_rows = (
            await db.execute(
                select(
                    Email.mailbox_id,
                    func.count(Email.id).label("total_sent"),
                    func.sum(case((Email.status.in_(FAILED_STATUSES), 1), else_=0)).label("total_failed"),
                    func.max(
                        case((Email.status.in_(SENT_STATUSES) & (Email.status.notin_(FAILED_STATUSES)), Email.sent_at), else_=None)
                    ).label("last_success"),
                    func.max(
                        case((Email.status.in_(FAILED_STATUSES), Email.sent_at), else_=None)
                    ).label("last_failure"),
                )
                .where(Email.mailbox_id.isnot(None))
                .group_by(Email.mailbox_id)
            )
        ).mappings().all()

    stats_by_id: dict[int, dict] = {r["mailbox_id"]: dict(r) for r in stats_rows}

    items = []
    health_counts = {"healthy": 0, "warning": 0, "critical": 0, "disabled": 0}

    for mb in mailboxes:
        s = stats_by_id.get(mb.id, {})
        total = s.get("total_sent") or 0
        failed = s.get("total_failed") or 0
        failure_rate = round(failed / total * 100, 2) if total else 0.0
        quota_pct = round(mb.today_sent / mb.daily_limit * 100, 1) if mb.daily_limit else 0.0

        health = _compute_health(failure_rate, quota_pct, mb.status)
        score = health["score"]
        if score in health_counts:
            health_counts[score] += 1

        last_success = s.get("last_success")
        last_failure = s.get("last_failure")

        items.append({
            "id": mb.id,
            "email": mb.email,
            "display_name": mb.display_name,
            "status": mb.status.value,
            "smtp_host": mb.smtp_host,
            "smtp_port": mb.smtp_port,
            "imap_host": mb.imap_host,
            "imap_port": mb.imap_port,
            "today_sent": mb.today_sent,
            "daily_limit": mb.daily_limit,
            "quota_pct": quota_pct,
            "total_sent": total,
            "failure_rate": failure_rate,
            "last_success_at": last_success.isoformat() if last_success else None,
            "last_failure_at": last_failure.isoformat() if last_failure else None,
            "health_score": score,
            "health_color": health["color"],
            "created_at": mb.created_at.isoformat(),
            "last_reset_at": mb.last_reset_at.isoformat() if mb.last_reset_at else None,
        })

    return {
        "total": len(items),
        "healthy": health_counts["healthy"],
        "warning": health_counts["warning"],
        "critical": health_counts["critical"],
        "disabled": health_counts["disabled"],
        "items": items,
    }


@router.post("/{mailbox_id}/test-smtp")
async def test_smtp(
    mailbox_id: int,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        mb = await db.get(Mailbox, mailbox_id)
    if not mb:
        raise HTTPException(status_code=404, detail="Mailbox not found")

    try:
        password = decrypt_password(mb.smtp_password_encrypted)
    except Exception:
        return {"success": False, "error": "Cannot decrypt password — check encryption key config"}

    try:
        if mb.smtp_use_tls:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(mb.smtp_host, mb.smtp_port, timeout=10) as srv:
                srv.starttls(context=ctx)
                srv.login(mb.email, password)
        else:
            with smtplib.SMTP_SSL(mb.smtp_host, mb.smtp_port, timeout=10) as srv:
                srv.login(mb.email, password)
        return {"success": True, "error": None}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.post("/{mailbox_id}/test-imap")
async def test_imap(
    mailbox_id: int,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        mb = await db.get(Mailbox, mailbox_id)
    if not mb:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    if not mb.imap_host:
        return {"success": False, "error": "No IMAP host configured"}

    try:
        password = decrypt_password(mb.smtp_password_encrypted)
    except Exception:
        return {"success": False, "error": "Cannot decrypt password"}

    try:
        with imaplib.IMAP4_SSL(mb.imap_host, mb.imap_port, timeout=10) as imap:
            imap.login(mb.email, password)
        return {"success": True, "error": None}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.post("/{mailbox_id}/disable")
async def disable_mailbox(
    mailbox_id: int,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        mb = await db.get(Mailbox, mailbox_id)
        if not mb:
            raise HTTPException(status_code=404, detail="Mailbox not found")
        mb.status = MailboxStatus.inactive
        mb.updated_at = datetime.now(timezone.utc)
        await db.commit()
    return {"id": mailbox_id, "status": "inactive"}


@router.post("/{mailbox_id}/reset-quota")
async def reset_quota(
    mailbox_id: int,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        mb = await db.get(Mailbox, mailbox_id)
        if not mb:
            raise HTTPException(status_code=404, detail="Mailbox not found")
        mb.today_sent = 0
        mb.this_hour_sent = 0
        mb.last_reset_at = datetime.now(timezone.utc)
        mb.updated_at = datetime.now(timezone.utc)
        await db.commit()
    return {"id": mailbox_id, "today_sent": 0}


@router.get("/{mailbox_id}/send-history")
async def send_history(
    mailbox_id: int,
    current_user: TokenData = Depends(require_admin),
) -> list:
    async with AsyncSessionLocal() as db:
        mb = await db.get(Mailbox, mailbox_id)
        if not mb:
            raise HTTPException(status_code=404, detail="Mailbox not found")

        rows = (
            await db.execute(
                select(
                    Email.id,
                    Email.subject,
                    Email.status,
                    Email.sent_at,
                    Email.created_at,
                    Influencer.email.label("recipient_email"),
                    Influencer.nickname.label("recipient_name"),
                )
                .join(Influencer, Email.influencer_id == Influencer.id)
                .where(Email.mailbox_id == mailbox_id)
                .order_by(Email.created_at.desc())
                .limit(100)
            )
        ).mappings().all()

    return [
        {
            "id": r["id"],
            "subject": r["subject"],
            "status": r["status"].value if r["status"] else None,
            "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "recipient_email": r["recipient_email"],
            "recipient_name": r["recipient_name"],
        }
        for r in rows
    ]
