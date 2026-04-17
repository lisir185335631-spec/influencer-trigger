from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_blacklist import EmailBlacklist


async def is_blacklisted(email: str, db: AsyncSession) -> bool:
    result = await db.execute(
        select(EmailBlacklist).where(EmailBlacklist.email == email.lower())
    )
    return result.scalar_one_or_none() is not None
