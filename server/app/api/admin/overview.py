from fastapi import APIRouter, Depends

from app.api.admin.deps import require_admin
from app.schemas.auth import TokenData

router = APIRouter(prefix="/overview", tags=["admin-overview"])


@router.get("/ping")
async def ping(current_user: TokenData = Depends(require_admin)) -> dict:
    return {"pong": True, "user": current_user.username}
