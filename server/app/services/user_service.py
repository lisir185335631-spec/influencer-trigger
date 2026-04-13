from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.services.auth_service import hash_password

MAX_TEAM_SIZE = 10


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def count_users(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User))
    return result.scalar_one()


async def create_user_admin(
    db: AsyncSession,
    username: str,
    email: str,
    password: str,
    role: str = "operator",
) -> User:
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role=UserRole(role),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(
    db: AsyncSession,
    user: User,
    role: Optional[str] = None,
    email: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> User:
    if role is not None:
        user.role = UserRole(role)
    if email is not None:
        user.email = email
    if is_active is not None:
        user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    return user
