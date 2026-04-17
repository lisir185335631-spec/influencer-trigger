from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_blacklist import EmailBlacklist


async def is_blacklisted(email: str, db: AsyncSession) -> bool:
    result = await db.execute(
        select(EmailBlacklist).where(EmailBlacklist.email == email.lower())
    )
    return result.scalar_one_or_none() is not None


async def record_sent(user_id: Optional[str] = None, count: int = 1) -> None:
    """Record a successful email send via usage_service."""
    from app.services.admin.usage_service import record_email_sent
    await record_email_sent(user_id=user_id, count=count)
