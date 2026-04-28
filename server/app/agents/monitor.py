"""
Monitor Agent — 24/7 IMAP polling for email replies and DSN bounce notifications.

Lifecycle:
  FastAPI lifespan starts run_monitor_agent() as an asyncio.Task on startup.
  The task loops every POLL_INTERVAL_SECONDS, polling all active mailboxes
  that have an IMAP host configured.
  Per-mailbox errors use exponential back-off (5→10→30→60 s expressed as
  "skip N poll cycles").
"""
import asyncio
import email as stdlib_email
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import aioimaplib
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.email import Email, EmailStatus
from app.models.email_event import EmailEvent, EventType
from app.models.influencer import Influencer, InfluencerPriority, InfluencerStatus, ReplyIntent
from app.models.mailbox import Mailbox, MailboxStatus
from app.models.notification import Notification, NotificationLevel
from app.services.mailbox_service import decrypt_password
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300  # 5 minutes
# Back-off steps in seconds; expressed as skip-cycles relative to POLL_INTERVAL
_BACKOFF_SECS = [5, 10, 30, 60]


# ---------------------------------------------------------------------------
# IMAP helpers
# ---------------------------------------------------------------------------

async def _connect_imap(mailbox: Mailbox, password: str) -> Optional[aioimaplib.IMAP4]:
    """Create and authenticate an IMAP connection. Returns client or None on failure."""
    host = mailbox.imap_host
    port = mailbox.imap_port or 993

    if port == 993:
        client: aioimaplib.IMAP4 = aioimaplib.IMAP4_SSL(host=host, port=port)
    else:
        client = aioimaplib.IMAP4(host=host, port=port)

    try:
        await client.wait_hello_from_server()
        status, _ = await client.login(mailbox.email, password)
        if status != "OK":
            logger.warning("IMAP login failed for %s (status=%s)", mailbox.email, status)
            return None
        return client
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("IMAP connect error for %s: %s", mailbox.email, exc)
        return None


def _parse_email_from_fetch(data: list) -> Optional[stdlib_email.message.Message]:
    """
    Extract raw bytes from an aioimaplib fetch response and parse as email.
    Scans all items in data looking for something that parses as a valid message.

    aioimaplib delivers the RFC822 payload as `bytearray`, not `bytes` —
    a bare `isinstance(item, bytes)` silently skipped the message body
    on every poll, so IMAP-driven reply / bounce detection never
    actually fired in production. Accept both types and convert to
    `bytes` for the email parser.
    """
    for item in data:
        if not isinstance(item, (bytes, bytearray)) or len(item) < 80:
            continue
        try:
            msg = stdlib_email.message_from_bytes(bytes(item))
            # A real email has at least one of these headers
            if msg.get("From") or msg.get("To") or msg.get("Date"):
                return msg
        except Exception:
            pass
    return None


async def _fetch_unseen(
    mailbox: Mailbox,
    password: str,
) -> list[stdlib_email.message.Message]:
    """Connect via IMAP and fetch recent messages.

    Searches by date (`SINCE`) rather than by UNSEEN flag. The mailbox
    owner can open Gmail web / Apple Mail / Outlook in parallel and
    flip the SEEN flag before our 5-minute poll runs — at which point
    a UNSEEN search silently drops the reply and we'd never detect it.
    SINCE is independent of SEEN, and the downstream handlers
    (`_handle_reply` / `_handle_bounce`) already filter on
    `Email.status != replied/bounced` so re-encountering an already-
    processed message is a no-op. The 2-day window covers cross-day /
    cross-timezone edge cases without bloating the per-cycle workload.

    Function name kept as `_fetch_unseen` for API stability across the
    private call site in `_poll_mailbox`; renaming would touch one
    extra line for no real benefit.
    """
    client = await _connect_imap(mailbox, password)
    if client is None:
        return []

    messages: list[stdlib_email.message.Message] = []
    try:
        status, _ = await client.select("INBOX")
        if status != "OK":
            return messages

        cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%d-%b-%Y")
        status, lines = await client.search(f"SINCE {cutoff}")
        if status != "OK" or not lines:
            return messages

        raw_ids = lines[0] if lines else b""
        if isinstance(raw_ids, bytes):
            raw_ids = raw_ids.decode(errors="replace")
        uid_list = [u for u in str(raw_ids).strip().split() if u]

        # Take the most-recent 50 (uids are monotonic per mailbox in
        # IMAP, so the tail is the freshest slice). The 50 cap protects
        # against weird bursts; downstream is idempotent.
        for uid in uid_list[-50:]:
            try:
                fetch_status, fetch_data = await client.fetch(uid, "(RFC822)")
                if fetch_status == "OK" and fetch_data:
                    msg = _parse_email_from_fetch(fetch_data)
                    if msg is not None:
                        messages.append(msg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Fetch uid=%s from %s failed: %s", uid, mailbox.email, exc)

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("IMAP search/fetch error for %s: %s", mailbox.email, exc)
    finally:
        try:
            await asyncio.wait_for(client.logout(), timeout=5.0)
        except Exception:
            pass

    return messages


# ---------------------------------------------------------------------------
# Message analysis helpers
# ---------------------------------------------------------------------------

def _extract_body(msg: stdlib_email.message.Message) -> str:
    """Extract plain-text (preferred) or HTML body from a message, max 4 KB."""
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = part.get("Content-Disposition", "")
            if "attachment" in cd:
                continue
            if ct in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset("utf-8") or "utf-8"
                        parts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset("utf-8") or "utf-8"
                parts.append(payload.decode(charset, errors="replace"))
        except Exception:
            pass
    return "\n".join(parts)[:4096]


_DSN_SUBJECT_RE = re.compile(
    r"(undeliverable|delivery\s+fail|mail\s+delivery\s+fail|"
    r"returned\s+mail|non.delivery|failed\s+delivery|bounce)",
    re.I,
)
_STATUS_CODE_RE = re.compile(r"Status:\s*(5\.\d+\.\d+)", re.I)
_RECIPIENT_RE = re.compile(
    r"(?:Final-Recipient|Original-Recipient):\s*rfc822;\s*(.+)", re.I
)


def _detect_bounce(msg: stdlib_email.message.Message) -> Optional[tuple[str, Optional[str]]]:
    """
    Check if msg is a permanent bounce (DSN).
    Returns (bounce_code, bounced_to_email) or None if not a bounce.
    """
    content_type = msg.get_content_type()

    # Check for multipart/report with message/delivery-status
    if content_type == "multipart/report":
        code: Optional[str] = None
        recipient: Optional[str] = None
        for part in msg.walk():
            pt = part.get_content_type()
            if pt == "message/delivery-status":
                try:
                    payload = part.get_payload(decode=False)
                    if isinstance(payload, list):
                        payload_str = "\n".join(
                            (p.as_string() if hasattr(p, "as_string") else str(p))
                            for p in payload
                        )
                    elif isinstance(payload, bytes):
                        payload_str = payload.decode(errors="replace")
                    else:
                        payload_str = str(payload) if payload else ""

                    m = _STATUS_CODE_RE.search(payload_str)
                    if m:
                        code = m.group(1)
                    r = _RECIPIENT_RE.search(payload_str)
                    if r:
                        recipient = r.group(1).strip()
                except Exception:
                    pass
        if code and code.startswith("5"):
            return code, recipient

    # Fallback: subject heuristic
    subject = msg.get("Subject", "")
    if _DSN_SUBJECT_RE.search(subject):
        # Try to find recipient in the body
        body = _extract_body(msg)
        email_match = re.search(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}", body)
        recipient = email_match.group(0).lower() if email_match else None
        return "5.0.0", recipient

    return None


def _extract_from_email(msg: stdlib_email.message.Message) -> str:
    """Extract plain email address from From header."""
    from_header = msg.get("From", "")
    m = re.search(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}", from_header)
    return m.group(0).lower() if m else ""


# ---------------------------------------------------------------------------
# Database update helpers
# ---------------------------------------------------------------------------

async def _handle_bounce(
    mailbox_id: int,
    bounce_code: str,
    bounced_to: Optional[str],
) -> None:
    """Update email/influencer status for a detected bounce."""
    if not bounced_to:
        return

    bounced_to = bounced_to.lower()
    async with AsyncSessionLocal() as db:
        # Find the most recent sent email to this address
        result = await db.execute(
            select(Email)
            .join(Influencer, Email.influencer_id == Influencer.id)
            .where(Influencer.email == bounced_to)
            .where(Email.status.in_([EmailStatus.sent, EmailStatus.delivered]))
            .order_by(Email.sent_at.desc())
            .limit(1)
        )
        email_record = result.scalar_one_or_none()
        if not email_record or email_record.status == EmailStatus.bounced:
            return

        now = datetime.now(timezone.utc)
        email_record.status = EmailStatus.bounced
        email_record.bounced_at = now

        db.add(EmailEvent(
            email_id=email_record.id,
            influencer_id=email_record.influencer_id,
            event_type=EventType.bounced,
            metadata_json=json.dumps({"code": bounce_code, "to": bounced_to}),
            source="imap",
            occurred_at=now,
        ))
        await db.commit()

        # Recalculate bounce_rate for the mailbox
        mailbox = await db.get(Mailbox, mailbox_id)
        if mailbox and mailbox.total_sent > 0:
            bounce_result = await db.execute(
                select(Email)
                .where(Email.mailbox_id == mailbox_id)
                .where(Email.status == EmailStatus.bounced)
            )
            bounce_count = len(list(bounce_result.scalars().all()))
            mailbox.bounce_rate = round(bounce_count / mailbox.total_sent, 4)
            await db.commit()

        await manager.broadcast("email:status_change", {
            "email_id": email_record.id,
            "influencer_id": email_record.influencer_id,
            "status": "bounced",
            "bounce_code": bounce_code,
        })
        logger.info("Bounce recorded for %s (code=%s)", bounced_to, bounce_code)


async def _handle_reply(
    msg: stdlib_email.message.Message,
    from_email: str,
) -> None:
    """Match a reply message to a sent email and update records."""
    in_reply_to = msg.get("In-Reply-To", "").strip()
    references = msg.get("References", "").strip()

    async with AsyncSessionLocal() as db:
        email_record: Optional[Email] = None

        # Strategy 1: In-Reply-To exact match
        if in_reply_to:
            result = await db.execute(
                select(Email)
                .where(Email.message_id == in_reply_to)
                .where(Email.status != EmailStatus.replied)
                .limit(1)
            )
            email_record = result.scalar_one_or_none()

        # Strategy 2: References header — check each message-id
        if not email_record and references:
            for ref_id in references.split():
                result = await db.execute(
                    select(Email)
                    .where(Email.message_id == ref_id.strip())
                    .where(Email.status != EmailStatus.replied)
                    .limit(1)
                )
                email_record = result.scalar_one_or_none()
                if email_record:
                    break

        # Strategy 3: Sender email matches an influencer we contacted
        if not email_record and from_email:
            result = await db.execute(
                select(Email)
                .join(Influencer, Email.influencer_id == Influencer.id)
                .where(Influencer.email == from_email)
                .where(Email.status.in_([
                    EmailStatus.sent,
                    EmailStatus.delivered,
                    EmailStatus.opened,
                ]))
                .order_by(Email.sent_at.desc())
                .limit(1)
            )
            email_record = result.scalar_one_or_none()

        if not email_record:
            return  # Not related to any sent email

        body = _extract_body(msg)
        now = datetime.now(timezone.utc)

        email_record.status = EmailStatus.replied
        email_record.reply_content = body[:4096]
        email_record.reply_from = from_email
        email_record.replied_at = now

        # Backfill opened_at when the recipient replied without ever
        # loading the tracking pixel. Most non-Gmail clients (QQ, Outlook,
        # 163, Yahoo) hide remote images by default, so a reply often
        # arrives before any open event — but a reply *implies* the email
        # was opened. Recording it here removes the puzzling
        # "1 reply / 0 opens" state from the dashboard. We don't change
        # `status` (replied is terminal and outranks opened); we only
        # ensure the time-stamp + audit-trail event get written.
        if email_record.opened_at is None:
            email_record.opened_at = now
            db.add(EmailEvent(
                email_id=email_record.id,
                influencer_id=email_record.influencer_id,
                event_type=EventType.opened,
                metadata_json=json.dumps({"inferred_from": "reply"}),
                source="imap-reply-inference",
                occurred_at=now,
            ))

        # Update influencer status
        influencer = await db.get(Influencer, email_record.influencer_id)
        if influencer:
            influencer.status = InfluencerStatus.replied

        db.add(EmailEvent(
            email_id=email_record.id,
            influencer_id=email_record.influencer_id,
            event_type=EventType.replied,
            metadata_json=json.dumps({"from": from_email}),
            source="imap",
            occurred_at=now,
        ))
        await db.commit()

        await manager.broadcast("email:status_change", {
            "email_id": email_record.id,
            "influencer_id": email_record.influencer_id,
            "status": "replied",
            "reply_from": from_email,
            "reply_preview": body[:256],
        })
        logger.info(
            "Reply recorded: email_id=%d from=%s", email_record.id, from_email
        )

        # Trigger Classifier Agent as a non-blocking background task
        asyncio.create_task(
            _classify_and_notify(email_record.id, email_record.influencer_id, body)
        )


# ---------------------------------------------------------------------------
# Classifier integration
# ---------------------------------------------------------------------------

# Notification level per intent. auto_reply is `info` (low salience but
# still surfaced) — earlier code excluded auto_reply entirely on the
# theory that OOO autoresponders are noise, but at the volumes this
# tool runs at the operator wants confirmation that *every* reply
# round-trip actually closed, even the low-value ones. The dashboard
# bell on a 0.90-confidence "auto_reply" classification on a literal
# "收到" was the smoking gun: the system was working but the user
# couldn't tell.
_INTENT_LEVEL: dict[str, NotificationLevel] = {
    "interested": NotificationLevel.urgent,
    "pricing": NotificationLevel.urgent,
    "declined": NotificationLevel.warning,
    "irrelevant": NotificationLevel.info,
    "auto_reply": NotificationLevel.info,
}



async def _classify_and_notify(
    email_id: int,
    influencer_id: int,
    reply_content: str,
) -> None:
    """
    Run Classifier Agent on a reply, then:
      - Write reply_intent to influencers table
      - Update influencer priority using composite score (intent + followers tier)
      - Create a Notification record so the bell surfaces every reply
      - Broadcast classification result via WebSocket
    """
    from app.agents.classifier import classify_reply  # local import avoids circular

    try:
        result = await classify_reply(reply_content)
    except Exception as exc:
        logger.error(
            "Classifier failed for email_id=%d influencer_id=%d: %s",
            email_id, influencer_id, exc,
        )
        return

    try:
        async with AsyncSessionLocal() as db:
            influencer = await db.get(Influencer, influencer_id)
            if not influencer:
                return

            # Update intent
            try:
                influencer.reply_intent = ReplyIntent(result.intent)
            except ValueError:
                influencer.reply_intent = ReplyIntent.irrelevant

            # Update priority using composite score (intent + followers tier).
            # auto_reply gets 1 intent-point in _INTENT_SCORE so it lands
            # at low/medium depending on followers — consistent with the
            # rest of the score table.
            from app.services.influencer_service import compute_priority_score  # local import avoids circular
            influencer.priority = compute_priority_score(result.intent, influencer.followers)

            # Create notification for every classified intent, including
            # auto_reply. The bell badge needs to surface *all* reply
            # round-trips so the operator can confirm the full pipeline
            # closed. Per-intent salience (urgent/warning/info) is
            # encoded in `level` for UI sorting / filtering.
            display_name = influencer.nickname or influencer.email
            platform_str = influencer.platform.value if influencer.platform else "unknown"
            content = (
                f"[{platform_str}] {display_name} · {result.intent}: "
                f"{result.summary} — 请前往您的邮箱回复"
            )
            notification = Notification(
                influencer_id=influencer_id,
                email_id=email_id,
                title=f"Reply from {display_name}",
                content=content,
                level=_INTENT_LEVEL.get(result.intent, NotificationLevel.info),
                intent=result.intent,
            )
            db.add(notification)
            await db.flush()
            notification_data: dict | None = {
                "id": notification.id,
                "influencer_id": influencer_id,
                "influencer_name": display_name,
                "title": notification.title,
                "content": notification.content,
                "level": notification.level.value,
                "intent": notification.intent,
                "is_read": False,
                "created_at": notification.created_at.isoformat() if notification.created_at else None,
            }

            await db.commit()

        if notification_data:
            await manager.broadcast("notification", notification_data)
            # Optional: push to Feishu / Slack / Server酱 if configured
            from app.services.webhook_service import send_notification_webhooks  # local import

            # Build a webhook-only content variant with a deep link to the
            # influencer detail page, so a recipient on WeChat (Server酱)
            # can tap the message and land directly on the conversation
            # context. The in-app bell content (saved to Notification.content)
            # intentionally stays plain — clicking the bell already routes
            # via influencer_id, so no markdown link is needed there
            # (and the bell UI doesn't render markdown anyway).
            from app.config import get_settings as _get_settings_for_link
            base_url = _get_settings_for_link().public_base_url.rstrip("/")
            webhook_content = notification_data["content"]
            if base_url:
                deep_link = f"{base_url}/crm/{influencer_id}"
                webhook_content = (
                    f"{webhook_content}\n\n👉 [点击查看网红详情]({deep_link})"
                )

            asyncio.create_task(
                send_notification_webhooks(
                    notification_data["title"],
                    webhook_content,
                )
            )

        await manager.broadcast("influencer:intent_classified", {
            "influencer_id": influencer_id,
            "email_id": email_id,
            "intent": result.intent,
            "confidence": result.confidence,
            "summary": result.summary,
        })
        logger.info(
            "Classified email_id=%d influencer_id=%d intent=%s confidence=%.2f",
            email_id, influencer_id, result.intent, result.confidence,
        )
    except Exception as exc:
        logger.error(
            "Failed to persist classification for email_id=%d: %s", email_id, exc
        )


async def _process_message(
    msg: stdlib_email.message.Message,
    mailbox_id: int,
) -> None:
    """Route a single IMAP message to bounce or reply handler."""
    # Bounce check first (DSN notifications are usually not replies)
    bounce_info = _detect_bounce(msg)
    if bounce_info:
        code, bounced_to = bounce_info
        await _handle_bounce(mailbox_id, code, bounced_to)
        return

    # Otherwise treat as potential reply
    from_email = _extract_from_email(msg)
    if from_email:
        await _handle_reply(msg, from_email)


# ---------------------------------------------------------------------------
# Poll loop
# ---------------------------------------------------------------------------

async def _poll_mailbox(mailbox: Mailbox) -> None:
    """Poll one mailbox for new messages."""
    try:
        password = decrypt_password(mailbox.smtp_password_encrypted)
    except Exception as exc:
        logger.error("Cannot decrypt password for mailbox %d: %s", mailbox.id, exc)
        return

    messages = await _fetch_unseen(mailbox, password)
    for msg in messages:
        try:
            await _process_message(msg, mailbox.id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Error processing message from mailbox %s: %s", mailbox.email, exc
            )


async def run_monitor_agent() -> None:
    """
    Main Monitor Agent loop.
    Started as an asyncio.Task inside FastAPI lifespan.
    Polls all active IMAP-configured mailboxes every POLL_INTERVAL_SECONDS.
    Exponential back-off per mailbox on repeated errors.
    """
    logger.info(
        "Monitor Agent started (poll_interval=%ds)", POLL_INTERVAL_SECONDS
    )

    # Track per-mailbox error state: mailbox_id → (error_count, skip_cycles_remaining)
    error_state: dict[int, tuple[int, int]] = {}

    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Mailbox)
                    .where(Mailbox.status == MailboxStatus.active)
                    .where(Mailbox.imap_host.isnot(None))
                )
                mailboxes = list(result.scalars().all())

            for mailbox in mailboxes:
                mid = mailbox.id
                err_count, skip_remaining = error_state.get(mid, (0, 0))

                # Skip this mailbox if it's in back-off
                if skip_remaining > 0:
                    error_state[mid] = (err_count, skip_remaining - 1)
                    logger.debug(
                        "Mailbox %s in back-off, %d cycles remaining",
                        mailbox.email, skip_remaining,
                    )
                    continue

                try:
                    await _poll_mailbox(mailbox)
                    # Success — clear error state
                    error_state.pop(mid, None)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    new_count = err_count + 1
                    step = min(new_count - 1, len(_BACKOFF_SECS) - 1)
                    # Convert backoff seconds to approximate poll cycles
                    skip = max(1, _BACKOFF_SECS[step] // max(POLL_INTERVAL_SECONDS, 1))
                    error_state[mid] = (new_count, skip)
                    logger.warning(
                        "Mailbox %s poll error #%d, backing off %d cycle(s): %s",
                        mailbox.email, new_count, skip, exc,
                    )

        except asyncio.CancelledError:
            logger.info("Monitor Agent cancelled, shutting down.")
            return
        except Exception as exc:
            logger.exception("Monitor Agent outer loop error: %s", exc)

        try:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Monitor Agent cancelled during sleep, shutting down.")
            return
