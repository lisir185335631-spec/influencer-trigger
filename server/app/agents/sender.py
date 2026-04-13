import asyncio
import email as stdlib_email
import email.mime.multipart
import email.mime.text
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Optional

import aiosmtplib
from jinja2 import Template as JinjaTemplate
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.campaign import Campaign, CampaignStatus
from app.models.email import Email, EmailStatus, EmailType
from app.models.influencer import Influencer, InfluencerStatus
from app.models.mailbox import Mailbox, MailboxStatus
from app.models.template import Template
from app.services.mailbox_service import decrypt_password
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


class MailboxRotator:
    """Rotate through active mailboxes with uniform distribution."""

    def __init__(self, mailboxes: list[Mailbox]) -> None:
        self._mailboxes = list(mailboxes)

    def next(self) -> Optional[Mailbox]:
        """Return the active mailbox with lowest today_sent that's under daily_limit."""
        available = [m for m in self._mailboxes if m.today_sent < m.daily_limit]
        if not available:
            return None
        return min(available, key=lambda m: m.today_sent)


async def _send_one(
    mailbox: Mailbox,
    to_email: str,
    subject: str,
    body_html: str,
) -> tuple[bool, str, Optional[str]]:
    """Send a single email. Returns (success, error_msg, message_id)."""
    try:
        password = decrypt_password(mailbox.smtp_password_encrypted)
    except Exception as exc:
        return False, f"Decrypt error: {exc}", None

    domain = mailbox.email.split("@")[-1]
    msg_id = f"<{uuid.uuid4()}@{domain}>"

    msg = stdlib_email.mime.multipart.MIMEMultipart("alternative")
    sender_label = mailbox.display_name or mailbox.email
    msg["From"] = f"{sender_label} <{mailbox.email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Message-ID"] = msg_id
    msg.attach(stdlib_email.mime.text.MIMEText(body_html, "html", "utf-8"))

    try:
        use_tls = mailbox.smtp_port == 465
        smtp = aiosmtplib.SMTP(
            hostname=mailbox.smtp_host,
            port=mailbox.smtp_port,
            use_tls=use_tls,
            timeout=30,
        )
        await smtp.connect()
        if not use_tls and mailbox.smtp_use_tls:
            await smtp.starttls()
        await smtp.login(mailbox.email, password)
        await smtp.send_message(msg)
        await smtp.quit()
        return True, "", msg_id
    except Exception as exc:
        logger.warning("SMTP send failed for %s → %s: %s", mailbox.email, to_email, exc)
        return False, str(exc), None


def _render_template(body_html: str, subject: str, influencer: Influencer) -> tuple[str, str]:
    """Render Jinja2 template variables for an influencer."""
    ctx = {
        "influencer_name": influencer.nickname or influencer.email.split("@")[0],
        "platform": influencer.platform.value if influencer.platform else "social media",
        "followers": f"{influencer.followers:,}" if influencer.followers else "many",
        "industry": influencer.industry or "your industry",
    }
    rendered_body = JinjaTemplate(body_html).render(**ctx)
    rendered_subject = JinjaTemplate(subject).render(**ctx)
    return rendered_subject, rendered_body


async def _mark_campaign_failed(db: AsyncSession, campaign_id: int) -> None:
    await db.execute(
        update(Campaign)
        .where(Campaign.id == campaign_id)
        .values(status=CampaignStatus.failed, completed_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def run_sender_agent(
    campaign_id: int,
    influencer_ids: list[int],
    template_id: int,
) -> None:
    """Main Sender Agent — runs as a FastAPI BackgroundTask."""
    async with AsyncSessionLocal() as db:
        # Load template
        tmpl = await db.get(Template, template_id)
        if not tmpl:
            logger.error("Template %d not found; aborting campaign %d", template_id, campaign_id)
            await _mark_campaign_failed(db, campaign_id)
            return

        # Load all active mailboxes
        result = await db.execute(
            select(Mailbox)
            .where(Mailbox.status == MailboxStatus.active)
            .order_by(Mailbox.today_sent.asc())
        )
        mailboxes = list(result.scalars().all())
        if not mailboxes:
            logger.error("No active mailboxes; aborting campaign %d", campaign_id)
            await _mark_campaign_failed(db, campaign_id)
            return

        rotator = MailboxRotator(mailboxes)

        # Mark campaign running
        campaign = await db.get(Campaign, campaign_id)
        if campaign:
            campaign.status = CampaignStatus.running
            campaign.started_at = datetime.now(timezone.utc)
            await db.commit()

        sent_count = success_count = failed_count = 0
        total = len(influencer_ids)

        for i, inf_id in enumerate(influencer_ids):
            influencer = await db.get(Influencer, inf_id)
            if not influencer:
                failed_count += 1
                continue

            mailbox = rotator.next()
            if mailbox is None:
                logger.warning(
                    "All mailboxes at daily limit; stopping campaign %d at %d/%d",
                    campaign_id, i, total,
                )
                remaining = total - i
                failed_count += remaining
                break

            rendered_subject, rendered_body = _render_template(tmpl.body_html, tmpl.subject, influencer)

            # Send with 1 retry on failure
            success = False
            msg_id = None
            for attempt in range(2):
                ok, err, msg_id = await _send_one(mailbox, influencer.email, rendered_subject, rendered_body)
                if ok:
                    success = True
                    break
                if attempt == 0:
                    logger.info("Retry send to %s (attempt 2): %s", influencer.email, err)
                    await asyncio.sleep(2)

            sent_count += 1

            # Persist email record
            email_record = Email(
                influencer_id=inf_id,
                campaign_id=campaign_id,
                mailbox_id=mailbox.id,
                template_id=template_id,
                email_type=EmailType.initial,
                subject=rendered_subject,
                body_html=rendered_body,
                message_id=msg_id,
                status=EmailStatus.sent if success else EmailStatus.failed,
                sent_at=datetime.now(timezone.utc) if success else None,
            )
            db.add(email_record)

            if success:
                success_count += 1
                # Increment mailbox counters in DB and locally
                await db.execute(
                    update(Mailbox)
                    .where(Mailbox.id == mailbox.id)
                    .values(
                        today_sent=Mailbox.today_sent + 1,
                        total_sent=Mailbox.total_sent + 1,
                    )
                )
                mailbox.today_sent += 1  # keep local rotator view in sync
                # Mark influencer as contacted
                influencer.status = InfluencerStatus.contacted
                influencer.last_email_sent_at = datetime.now(timezone.utc)
            else:
                failed_count += 1

            # Update campaign counters
            await db.execute(
                update(Campaign)
                .where(Campaign.id == campaign_id)
                .values(
                    sent_count=sent_count,
                    success_count=success_count,
                    failed_count=failed_count,
                )
            )
            await db.commit()

            # Push progress via WebSocket
            await manager.broadcast("email:progress", {
                "campaign_id": campaign_id,
                "sent": sent_count,
                "success": success_count,
                "failed": failed_count,
                "total": total,
                "current_email": influencer.email,
            })

            # Random delay before next send (30-60 s), skip after last item
            if i < total - 1:
                delay = random.uniform(30, 60)
                logger.info("Campaign %d: sleeping %.1fs before next send", campaign_id, delay)
                await asyncio.sleep(delay)

        # Finalise campaign
        final_status = CampaignStatus.completed if success_count > 0 else CampaignStatus.failed
        await db.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .values(
                status=final_status,
                completed_at=datetime.now(timezone.utc),
                sent_count=sent_count,
                success_count=success_count,
                failed_count=failed_count,
            )
        )
        await db.commit()

        await manager.broadcast("email:completed", {
            "campaign_id": campaign_id,
            "sent": sent_count,
            "success": success_count,
            "failed": failed_count,
            "total": total,
        })
        logger.info(
            "Campaign %d finished: %d/%d sent successfully, %d failed",
            campaign_id, success_count, total, failed_count,
        )
