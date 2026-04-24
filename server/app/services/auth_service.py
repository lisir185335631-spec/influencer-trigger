import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User, UserRole
from app.schemas.auth import TokenData

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(data: dict, expires_delta: timedelta) -> str:
    settings = get_settings()
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_access_token(user_id: int, username: str, role: str, token_version: int = 0) -> str:
    settings = get_settings()
    return _create_token(
        {"sub": str(user_id), "username": username, "role": role, "tv": token_version, "type": "access"},
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: int, username: str, role: str, token_version: int = 0) -> str:
    settings = get_settings()
    return _create_token(
        {"sub": str(user_id), "username": username, "role": role, "tv": token_version, "type": "refresh"},
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str) -> Optional[TokenData]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = payload.get("sub")
        username = payload.get("username")
        role = payload.get("role")
        if user_id is None or username is None or role is None:
            return None
        token_version = payload.get("tv", 0)
        return TokenData(user_id=int(user_id), username=username, role=role, token_version=token_version)
    except JWTError:
        return None


async def write_login_history(
    user_id: int | None,
    ip: str | None,
    user_agent: str | None,
    success: bool,
    failed_reason: str | None = None,
) -> None:
    from app.models.login_history import LoginHistory
    from app.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as session:
            entry = LoginHistory(
                user_id=user_id,
                ip=ip,
                user_agent=user_agent,
                success=success,
                failed_reason=failed_reason,
            )
            session.add(entry)
            await session.commit()
    except Exception as exc:
        logger.warning("Failed to write login history: %s", exc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Short Redis timeouts so a missing Redis instance doesn't stall /auth/refresh
# by the default 5s-per-op × 2-ops path (connect + command). Fail open in that
# case — the blacklist is a defense-in-depth, not the primary guard.
_REDIS_CONNECT_TIMEOUT = 0.5
_REDIS_OP_TIMEOUT = 0.5


async def blacklist_refresh_token(token: str) -> None:
    """Add a refresh token to the Redis blacklist so it cannot be reused."""
    settings = get_settings()
    ttl_seconds = settings.refresh_token_expire_days * 86400
    key = f"rt_blacklist:{_token_hash(token)}"
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=_REDIS_CONNECT_TIMEOUT,
            socket_timeout=_REDIS_OP_TIMEOUT,
        )
        await r.setex(key, ttl_seconds, "1")
        await r.aclose()
    except Exception as exc:
        logger.debug("Redis blacklist write failed (non-fatal): %s", exc)


async def is_refresh_token_blacklisted(token: str) -> bool:
    """Return True if the refresh token has been blacklisted."""
    settings = get_settings()
    key = f"rt_blacklist:{_token_hash(token)}"
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=_REDIS_CONNECT_TIMEOUT,
            socket_timeout=_REDIS_OP_TIMEOUT,
        )
        result = await r.get(key)
        await r.aclose()
        return result is not None
    except Exception as exc:
        logger.debug("Redis blacklist read failed (fail-open): %s", exc)
        return False  # Fail open — do not block login if Redis is down


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def create_user(
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
