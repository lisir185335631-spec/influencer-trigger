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
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.campaign import Campaign, CampaignStatus
from app.models.email import Email, EmailStatus, EmailType
from app.models.email_draft import EmailDraft, EmailDraftStatus
from app.models.influencer import Influencer, InfluencerStatus
from app.models.mailbox import Mailbox, MailboxStatus
from app.models.template import Template
from app.services.mailbox_service import decrypt_password
from app.services.sender_service import is_blacklisted
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


class MailboxRotator:
    """Rotate through active mailboxes with uniform distribution."""

    def __init__(self, mailboxes: list[Mailbox]) -> None:
        self._mailboxes = list(mailboxes)

    def next(self) -> Optional[Mailbox]:
        """Return the active mailbox with lowest today_sent that's under both daily and hourly limits."""
        available = [
            m for m in self._mailboxes
            if m.today_sent < m.daily_limit and m.this_hour_sent < m.hourly_limit
        ]
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


_sandbox_env = SandboxedEnvironment()


def _render_template(body_html: str, subject: str, influencer: Influencer) -> tuple[str, str]:
    """Render Jinja2 template variables for an influencer."""
    ctx = {
        "influencer_name": influencer.nickname or influencer.email.split("@")[0],
        "platform": influencer.platform.value if influencer.platform else "social media",
        "followers": f"{influencer.followers:,}" if influencer.followers else "many",
        "industry": influencer.industry or "your industry",
    }
    rendered_body = _sandbox_env.from_string(body_html).render(**ctx)
    rendered_subject = _sandbox_env.from_string(subject).render(**ctx)
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
    """Main Sender Agent — runs as a FastAPI BackgroundTask.

    Two modes (chosen by Campaign.use_drafts):
    - **Template mode** (default): renders the campaign template via Jinja2
      per influencer. Salutation-level personalization (4 placeholders).
    - **Draft mode**: reads pre-generated subject/body_html from the
      email_drafts table (one row per influencer in this campaign). LLM
      content has already been reviewed and possibly edited by the user;
      this branch does NOT call the LLM and does NOT touch Jinja2 — it
      just delivers what's already in the draft.
    """
    async with AsyncSessionLocal() as db:
        # Load campaign first — its `use_drafts` flag selects the mode.
        campaign = await db.get(Campaign, campaign_id)
        if not campaign:
            logger.error("Campaign %d not found; aborting", campaign_id)
            return

        use_drafts = bool(campaign.use_drafts)

        # Template only required in template mode. In draft mode the draft
        # row already contains the rendered subject + body_html.
        tmpl = None
        if not use_drafts:
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
        campaign.status = CampaignStatus.running
        campaign.started_at = datetime.now(timezone.utc)
        await db.commit()

        sent_count = success_count = failed_count = 0
        total = len(influencer_ids)

        for i, inf_id in enumerate(influencer_ids):
            influencer = await db.get(Influencer, inf_id)
            if not influencer:
                failed_count += 1
                # Sync the bump immediately so the campaign-detail UI
                # doesn't underreport during a long batch — the campaign
                # row was previously only re-written further down on the
                # success path, leaving early failures invisible until
                # the loop finished.
                await db.execute(
                    update(Campaign)
                    .where(Campaign.id == campaign_id)
                    .values(failed_count=failed_count)
                )
                await db.commit()
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

            # Skip blacklisted recipients
            if await is_blacklisted(influencer.email, db):
                blocked_record = Email(
                    influencer_id=inf_id,
                    campaign_id=campaign_id,
                    mailbox_id=mailbox.id,
                    template_id=template_id,
                    email_type=EmailType.initial,
                    subject="",
                    body_html="",
                    message_id=None,
                    status=EmailStatus.blocked,
                    sent_at=None,
                )
                db.add(blocked_record)
                failed_count += 1
                await db.commit()
                continue

            # Pick subject + body source based on campaign mode.
            draft = None
            if use_drafts:
                # Atomic claim: UPDATE ... WHERE status IN (ready, edited)
                # → sending. If two send-tasks race on the same draft, only
                # one rowcount==1 wins; the loser sees rowcount==0 and skips.
                # We then SELECT to read the row's snapshot (subject/body/id).
                claim_stmt = (
                    update(EmailDraft)
                    .where(
                        EmailDraft.campaign_id == campaign_id,
                        EmailDraft.influencer_id == inf_id,
                        EmailDraft.status.in_([
                            EmailDraftStatus.ready,
                            EmailDraftStatus.edited,
                        ]),
                    )
                    .values(status=EmailDraftStatus.sending)
                )
                claim_res = await db.execute(claim_stmt)
                if claim_res.rowcount == 0:
                    # Either nothing was sendable (status changed mid-flight)
                    # or another sender beat us to it. Either way, don't
                    # double-send.
                    await db.commit()
                    logger.info(
                        "Campaign %d: no claimable draft for influencer %d; skipping",
                        campaign_id, inf_id,
                    )
                    failed_count += 1
                    continue
                await db.commit()
                draft_q = await db.execute(
                    select(EmailDraft)
                    .where(
                        EmailDraft.campaign_id == campaign_id,
                        EmailDraft.influencer_id == inf_id,
                    )
                )
                draft = draft_q.scalar_one_or_none()
                if not draft:
                    failed_count += 1
                    continue
                rendered_subject = draft.subject
                rendered_body = draft.body_html
            else:
                rendered_subject, rendered_body = _render_template(
                    tmpl.body_html, tmpl.subject, influencer,
                )

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

            # Persist email record (FK back to draft when present — supports
            # audit trail "which draft produced this email").
            email_record = Email(
                influencer_id=inf_id,
                campaign_id=campaign_id,
                mailbox_id=mailbox.id,
                template_id=template_id,
                draft_id=draft.id if draft else None,
                email_type=EmailType.initial,
                subject=rendered_subject,
                body_html=rendered_body,
                message_id=msg_id,
                status=EmailStatus.sent if success else EmailStatus.failed,
                sent_at=datetime.now(timezone.utc) if success else None,
            )
            db.add(email_record)
            await db.flush()  # need email_record.id to FK-link the draft

            # Close out the draft side of the relationship.
            if draft:
                draft.email_id = email_record.id
                draft.status = (
                    EmailDraftStatus.sent if success else EmailDraftStatus.failed
                )
                draft.sent_at = (
                    datetime.now(timezone.utc) if success else None
                )
                if not success:
                    draft.error_message = (
                        f"Send failed: {err}" if 'err' in locals() else "Send failed"
                    )

            if success:
                success_count += 1
                from app.services.sender_service import record_sent as _rec_sent
                asyncio.create_task(_rec_sent(user_id=None, count=1))
                # Increment mailbox counters in DB and locally
                await db.execute(
                    update(Mailbox)
                    .where(Mailbox.id == mailbox.id)
                    .values(
                        today_sent=Mailbox.today_sent + 1,
                        this_hour_sent=Mailbox.this_hour_sent + 1,
                        total_sent=Mailbox.total_sent + 1,
                    )
                )
                mailbox.today_sent += 1  # keep local rotator view in sync
                mailbox.this_hour_sent += 1
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

            # Also broadcast a row-level event so any open monitor list (which
            # subscribes to email:status_change for delivery / open / reply
            # transitions) picks up the new send too. Without this, the
            # initial-send row only appears after the user manually reloads
            # — visually inconsistent with follow_up:sent behaviour, which
            # already lights up the list in real time.
            await manager.broadcast("email:status_change", {
                "email_id": email_record.id,
                "influencer_id": inf_id,
                "status": email_record.status.value,
                "campaign_id": campaign_id,
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
