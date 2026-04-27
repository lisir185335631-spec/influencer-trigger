from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_admin
from app.schemas.auth import TokenData
from app.schemas.user import (
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.services.auth_service import get_user_by_username
from app.services.user_service import (
    MAX_TEAM_SIZE,
    count_users,
    create_user_admin,
    get_user_by_id,
    list_users,
    update_user,
)

router = APIRouter(tags=["users"])


@router.get("/users", response_model=UserListResponse)
async def list_users_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    users = await list_users(db)
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=len(users),
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user_endpoint(
    body: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    total = await count_users(db)
    if total >= MAX_TEAM_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Team size limit reached ({MAX_TEAM_SIZE} members max)",
        )
    existing = await get_user_by_username(db, body.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    if body.role not in ("admin", "manager", "operator"):
        raise HTTPException(status_code=400, detail="Invalid role")
    user = await create_user_admin(db, body.username, body.email, body.password, body.role)
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user_endpoint(
    user_id: int,
    body: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Prevent admin from demoting themselves
    if user_id == current_user.user_id and body.role is not None and body.role != "admin":
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    if body.role is not None and body.role not in ("admin", "manager", "operator"):
        raise HTTPException(status_code=400, detail="Invalid role")
    user = await update_user(db, user, body.role, body.email, body.is_active)
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disable_user_endpoint(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    if user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot disable yourself")
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await update_user(db, user, is_active=False)


@router.post("/users/{user_id}/hard-delete", status_code=status.HTTP_204_NO_CONTENT)
async def hard_delete_user_endpoint(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    """Permanently delete a user row (irreversible).

    Differs from DELETE /users/{id} (which only sets is_active=false and
    can be reversed). All FKs to users.id are declared nullable +
    ondelete=SET NULL, so historical records (templates / scrape_tasks /
    notes / login_history / etc.) survive — their author column simply
    becomes None.

    Same self-protection as the soft-delete: an admin cannot wipe their
    own account out of the system.
    """
    if user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
