from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin
from app.database import get_db
from app.models.login_history import LoginHistory
from app.models.user import User, UserRole
from app.schemas.auth import TokenData
from app.services.auth_service import hash_password, verify_password

router = APIRouter(prefix="/users", tags=["admin-users"])


class UserCreateBody(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: str = "operator"


class UserPatchBody(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


class ResetPasswordBody(BaseModel):
    new_password: str
    admin_password: str


class ForceLogoutBody(BaseModel):
    admin_password: str


@router.get("")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    q = select(User)
    if search:
        q = q.where(or_(
            User.username.ilike(f"%{search}%"),
            User.email.ilike(f"%{search}%"),
        ))
    if role:
        try:
            q = q.where(User.role == UserRole(role))
        except ValueError:
            pass

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    q = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    user_ids = [u.id for u in rows]
    last_login_map: dict = {}
    if user_ids:
        lh_q = (
            select(LoginHistory.user_id, func.max(LoginHistory.created_at).label("last_login"))
            .where(LoginHistory.user_id.in_(user_ids), LoginHistory.success == True)  # noqa: E712
            .group_by(LoginHistory.user_id)
        )
        for r in (await db.execute(lh_q)).all():
            last_login_map[r.user_id] = r.last_login

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role.value,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat(),
                "last_login": last_login_map[u.id].isoformat() if u.id in last_login_map else None,
            }
            for u in rows
        ],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user_admin(
    body: UserCreateBody,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    existing = (await db.execute(
        select(User).where(or_(User.username == body.username, User.email == body.email))
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    try:
        role = UserRole(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "username": user.username, "email": user.email, "role": user.role.value}


@router.patch("/{user_id}")
async def patch_user(
    user_id: int,
    body: UserPatchBody,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.role is not None:
        try:
            user.role = UserRole(body.role)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid role")
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            # Freeze: invalidate all existing tokens
            user.token_version += 1

    await db.commit()
    return {"id": user.id, "username": user.username, "role": user.role.value, "is_active": user.is_active}


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    body: ResetPasswordBody,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    admin = (await db.execute(select(User).where(User.id == current_user.user_id))).scalar_one_or_none()
    if not admin or not verify_password(body.admin_password, admin.hashed_password):
        raise HTTPException(status_code=403, detail="Admin password incorrect")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


@router.post("/{user_id}/force-logout")
async def force_logout(
    user_id: int,
    body: ForceLogoutBody,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    admin = (await db.execute(select(User).where(User.id == current_user.user_id))).scalar_one_or_none()
    if not admin or not verify_password(body.admin_password, admin.hashed_password):
        raise HTTPException(status_code=403, detail="Admin password incorrect")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.token_version += 1
    await db.commit()
    return {"ok": True, "token_version": user.token_version}


@router.get("/{user_id}/login-history")
async def get_login_history(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rows = (await db.execute(
        select(LoginHistory)
        .where(LoginHistory.user_id == user_id)
        .order_by(desc(LoginHistory.created_at))
        .limit(50)
    )).scalars().all()

    return [
        {
            "id": r.id,
            "ip": r.ip,
            "user_agent": r.user_agent,
            "success": r.success,
            "failed_reason": r.failed_reason,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
