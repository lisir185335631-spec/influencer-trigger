import logging
import email.mime.multipart
import email.mime.text
from datetime import datetime, timezone

import aiosmtplib
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.mailbox import Mailbox, MailboxStatus
from app.schemas.mailbox import MailboxCreate, MailboxUpdate

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    key = get_settings().encryption_key
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        raise ValueError(
            "Invalid encryption_key in settings. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from exc


def encrypt_password(password: str) -> str:
    return _get_fernet().encrypt(password.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()


async def _create_smtp_client(
    host: str, port: int, use_tls: bool, start_tls: bool, timeout: int
) -> aiosmtplib.SMTP:
    """Build an aiosmtplib SMTP client, dialling through SMTP_PROXY when set.

    Pass `start_tls` explicitly so callers don't rely on aiosmtplib's
    `start_tls=None` auto-mode — that auto-STARTTLS-on-connect bit us in
    production: connect() upgrades TLS, then a separate `smtp.starttls()`
    call raises "Connection already using TLS". With explicit start_tls,
    callers stop calling starttls() themselves and aiosmtplib does it
    exactly once during connect().

    Without a proxy this returns a vanilla aiosmtplib SMTP. With
    SMTP_PROXY set we dial via python-socks first and hand the socket to
    aiosmtplib; aiosmtplib still wraps implicit TLS (port 465 / use_tls)
    or runs STARTTLS (port 587 / start_tls) on top of the socket.
    """
    proxy_url = get_settings().smtp_proxy
    common = dict(
        hostname=host, port=port,
        use_tls=use_tls, start_tls=start_tls,
        timeout=timeout,
    )
    if not proxy_url:
        return aiosmtplib.SMTP(**common)
    # Lazy import keeps python-socks out of the dependency graph for direct-
    # connect deployments where the package may not be installed.
    from python_socks.async_.asyncio import Proxy

    proxy = Proxy.from_url(proxy_url)
    sock = await proxy.connect(dest_host=host, dest_port=port, timeout=timeout)
    return aiosmtplib.SMTP(sock=sock, **common)


async def list_mailboxes(db: AsyncSession) -> list[Mailbox]:
    result = await db.execute(select(Mailbox).order_by(Mailbox.created_at.desc()))
    return list(result.scalars().all())


async def get_mailbox(db: AsyncSession, mailbox_id: int) -> Mailbox | None:
    result = await db.execute(select(Mailbox).where(Mailbox.id == mailbox_id))
    return result.scalar_one_or_none()


async def create_mailbox(db: AsyncSession, data: MailboxCreate) -> Mailbox:
    encrypted = encrypt_password(data.smtp_password)
    mailbox = Mailbox(
        email=data.email,
        display_name=data.display_name,
        smtp_host=data.smtp_host,
        smtp_port=data.smtp_port,
        smtp_password_encrypted=encrypted,
        smtp_use_tls=data.smtp_use_tls,
        imap_host=data.imap_host,
        imap_port=data.imap_port,
        daily_limit=data.daily_limit,
        hourly_limit=data.hourly_limit,
    )
    db.add(mailbox)
    await db.commit()
    await db.refresh(mailbox)
    return mailbox


async def update_mailbox(db: AsyncSession, mailbox_id: int, data: MailboxUpdate) -> Mailbox | None:
    mailbox = await get_mailbox(db, mailbox_id)
    if not mailbox:
        return None

    update_data = data.model_dump(exclude_unset=True)
    if "smtp_password" in update_data:
        mailbox.smtp_password_encrypted = encrypt_password(update_data.pop("smtp_password"))
    for field, value in update_data.items():
        setattr(mailbox, field, value)

    await db.commit()
    await db.refresh(mailbox)
    return mailbox


async def delete_mailbox(db: AsyncSession, mailbox_id: int) -> bool:
    mailbox = await get_mailbox(db, mailbox_id)
    if not mailbox:
        return False
    await db.delete(mailbox)
    await db.commit()
    return True


async def test_smtp_connection(mailbox: Mailbox, test_to: str | None = None) -> dict:
    try:
        password = decrypt_password(mailbox.smtp_password_encrypted)
    except (InvalidToken, ValueError) as e:
        return {"success": False, "error": f"Password decryption failed: {e}"}

    recipient = test_to or mailbox.email

    msg = email.mime.multipart.MIMEMultipart()
    sender_label = mailbox.display_name or mailbox.email
    msg["From"] = f"{sender_label} <{mailbox.email}>"
    msg["To"] = recipient
    msg["Subject"] = "SMTP Connection Test — Influencer Trigger"
    msg.attach(email.mime.text.MIMEText(
        "This is a test email to verify your SMTP configuration is working correctly.",
        "plain",
    ))

    try:
        # Port 465 = implicit TLS; otherwise STARTTLS upgrade controlled by
        # smtp_use_tls. start_tls=True tells aiosmtplib to perform STARTTLS
        # exactly once during connect(); we don't call smtp.starttls()
        # ourselves anymore (would double-upgrade and raise
        # "Connection already using TLS").
        use_tls = mailbox.smtp_port == 465
        start_tls = (not use_tls) and mailbox.smtp_use_tls
        smtp = await _create_smtp_client(
            host=mailbox.smtp_host,
            port=mailbox.smtp_port,
            use_tls=use_tls,
            start_tls=start_tls,
            timeout=15,
        )
        await smtp.connect()
        await smtp.login(mailbox.email, password)
        await smtp.send_message(msg)
        await smtp.quit()
        return {"success": True, "message": f"Test email sent to {recipient}"}
    except Exception as e:
        logger.warning("SMTP test failed for %s: %s", mailbox.email, e)
        return {"success": False, "error": str(e)}


async def reset_today_sent(db: AsyncSession) -> int:
    """Reset today_sent + this_hour_sent. Called daily at 00:00 UTC.

    Daily reset also clears the hourly counter (00:00 is the top of an
    hour, so the hourly job would fire too — keeping it here as well makes
    the daily job self-sufficient if the hourly cron is ever disabled).
    """
    result = await db.execute(
        update(Mailbox).values(
            today_sent=0,
            this_hour_sent=0,
            last_reset_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return result.rowcount


async def reset_this_hour_sent(db: AsyncSession) -> int:
    """Reset this_hour_sent to 0. Called hourly at minute=0.

    Without this job, MailboxRotator gates by `this_hour_sent < hourly_limit`
    forever after the first hour the limit is hit, freezing the mailbox
    until the next daily reset 23 hours later.
    """
    result = await db.execute(update(Mailbox).values(this_hour_sent=0))
    await db.commit()
    return result.rowcount
