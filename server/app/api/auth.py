from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.limiter import limiter
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
    user = await get_user_by_username(db, body.username)
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")
    access_token = create_access_token(user.id, user.username, user.role.value)
    refresh_token = create_refresh_token(user.id, user.username, user.role.value)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest):
    # Check blacklist before decoding (prevents reuse of rotated tokens)
    if await is_refresh_token_blacklisted(body.refresh_token):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")
    token_data = decode_token(body.refresh_token)
    if token_data is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    # Blacklist the old refresh token immediately (token rotation)
    await blacklist_refresh_token(body.refresh_token)
    access_token = create_access_token(
        token_data.user_id, token_data.username, token_data.role
    )
    new_refresh = create_refresh_token(
        token_data.user_id, token_data.username, token_data.role
    )
    return TokenResponse(access_token=access_token, refresh_token=new_refresh)
