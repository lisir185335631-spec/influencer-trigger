"""Email open tracking pixel.

Outbound emails carry a 1×1 transparent GIF whose URL embeds the email's
message-id token. When the recipient opens the email, their client fetches
the pixel and we record an open event.

This route is intentionally unauthenticated — the pixel must load inside
any mail client without cookies. Token confidentiality is the only
protection (uuid4 hex, 122 bits of entropy).

Caveats (worth knowing, not worth fixing):
- Gmail/Outlook proxy and pre-fetch images, so first-open ≠ recipient saw
  the email. Industry-wide known issue; matches what SendGrid / Mailchimp
  report.
- Some clients block remote images by default; opens from those readers
  won't be tracked. The send still works regardless.
"""
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.email import Email, EmailStatus
from app.models.email_event import EmailEvent, EventType
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tracking"])


# 43-byte 1×1 transparent GIF89a. Inlined so the pixel response is a single
# round-trip with zero filesystem touch (called once per email open, this
# keeps the open-tracking endpoint cheap even under bursty pre-fetch).
_PIXEL_GIF: bytes = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f9040100000000"
    "2c00000000010001000002024401003b"
)

# Headers that prevent caching at every layer. Without these, the
# recipient's mail client (or its image proxy) caches the GIF after the
# first fetch and we never see subsequent opens. Gmail's image proxy in
# particular is aggressive — these headers cut its cache window from
# ~indefinite to per-fetch.
_NO_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

# Tokens are uuid4().hex — 32 lowercase hex chars. Reject anything else
# upfront so a junk URL doesn't trigger a DB scan.
_TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")


def _pixel_response() -> Response:
    """Return the GIF response with strong no-cache headers."""
    return Response(
        content=_PIXEL_GIF,
        media_type="image/gif",
        headers=_NO_CACHE_HEADERS,
    )


@router.get("/track/open/{token}.gif")
async def track_open(token: str, db: AsyncSession = Depends(get_db)) -> Response:
    """Pixel endpoint. Always returns the GIF; DB write is best-effort.

    The pixel MUST always succeed back to the mail client — even if our
    DB hiccups, recipients should still see no broken-image icon. So all
    DB work is wrapped and any failure logs and falls through.
    """
    if not _TOKEN_RE.match(token):
        return _pixel_response()

    try:
        # message_id format produced by sender.py is `<{token}@{domain}>`.
        # Prefix-LIKE on the indexed unique column so this stays cheap.
        result = await db.execute(
            select(Email).where(Email.message_id.like(f"<{token}@%")).limit(1)
        )
        email = result.scalar_one_or_none()
        if email is None:
            return _pixel_response()

        now = datetime.now(timezone.utc)
        first_open = email.opened_at is None

        # Status precedence — never downgrade. A reply/bounce is more
        # informative than an open, so once we've seen those we leave the
        # status alone. Anything else (sent / delivered) climbs to opened.
        terminal = {
            EmailStatus.replied,
            EmailStatus.bounced,
            EmailStatus.failed,
            EmailStatus.blocked,
        }
        status_changed = False
        if email.status not in terminal and email.status != EmailStatus.opened:
            email.status = EmailStatus.opened
            status_changed = True

        if first_open:
            email.opened_at = now

        # Always record the event — counts subsequent opens too, so
        # downstream "open count per email" reports work without schema
        # changes.
        db.add(EmailEvent(
            email_id=email.id,
            influencer_id=email.influencer_id,
            event_type=EventType.opened,
            metadata_json=json.dumps({"first_open": first_open}),
            source="pixel",
            occurred_at=now,
        ))
        await db.commit()

        if first_open or status_changed:
            await manager.broadcast("email:status_change", {
                "email_id": email.id,
                "influencer_id": email.influencer_id,
                "status": "opened",
                "opened_at": now.isoformat(),
            })
            logger.info("Email open tracked: email_id=%d", email.id)
    except Exception as exc:
        # Never fail the pixel response — a 500 here would show a broken
        # image in the recipient's inbox. Log and serve the GIF anyway.
        logger.warning("track_open DB error for token=%s: %s", token, exc)

    return _pixel_response()
