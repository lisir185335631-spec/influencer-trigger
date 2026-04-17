from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.limiter import limiter
from app.models.user import User
from app.schemas.auth import (
    RefreshRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.services.auth_service import (
    blacklist_refresh_token,
    create_access_token,
    create_refresh_token,
    create_user,
    decode_token,
    get_user_by_username,
    is_refresh_token_blacklisted,
    verify_password,
    write_login_history,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await get_user_by_username(db, body.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    user = await create_user(db, body.username, body.email, body.password, body.role)
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/15minutes")
async def login(request: Request, body: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user = await get_user_by_username(db, body.username)
    if not user or not verify_password(body.password, user.hashed_password):
        user_id = user.id if user else None
        reason = "Wrong password" if user else "User not found"
        await write_login_history(user_id, ip, user_agent, success=False, failed_reason=reason)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        await write_login_history(user.id, ip, user_agent, success=False, failed_reason="User inactive")
        raise HTTPException(status_code=403, detail="User is inactive")

    await write_login_history(user.id, ip, user_agent, success=True)
    access_token = create_access_token(user.id, user.username, user.role.value, user.token_version)
    refresh_token = create_refresh_token(user.id, user.username, user.role.value, user.token_version)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    if await is_refresh_token_blacklisted(body.refresh_token):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")
    token_data = decode_token(body.refresh_token)
    if token_data is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Validate token_version: if force-logout happened, old refresh tokens must be rejected
    result = await db.execute(select(User).where(User.id == token_data.user_id))
    user = result.scalar_one_or_none()
    if not user or user.token_version != token_data.token_version:
        raise HTTPException(status_code=401, detail="Token has been invalidated")

    await blacklist_refresh_token(body.refresh_token)
    access_token = create_access_token(
        token_data.user_id, token_data.username, token_data.role, user.token_version
    )
    new_refresh = create_refresh_token(
        token_data.user_id, token_data.username, token_data.role, user.token_version
    )
    return TokenResponse(access_token=access_token, refresh_token=new_refresh)
