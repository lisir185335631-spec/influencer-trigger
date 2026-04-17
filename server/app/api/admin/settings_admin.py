"""
Admin Settings API — system config + Feature Flag CRUD.
"""
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.feature_flag import FeatureFlag
from app.models.system_settings import SystemSettings
from app.schemas.auth import TokenData

router = APIRouter(prefix="/settings", tags=["admin-settings"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class LLMKeyStatus(BaseModel):
    status: str  # "configured" | "not_configured"
    last_four: Optional[str] = None


class SystemSettingsOut(BaseModel):
    scrape_concurrency: int
    webhook_feishu: str
    webhook_slack: str
    webhook_default_url: str
    default_daily_quota: int
    llm_key: LLMKeyStatus


class SystemSettingsPatch(BaseModel):
    webhook_default_url: Optional[str] = None
    default_daily_quota: Optional[int] = Field(None, ge=0)
    webhook_feishu: Optional[str] = None
    webhook_slack: Optional[str] = None


class FeatureFlagOut(BaseModel):
    id: int
    flag_key: str
    enabled: bool
    description: str
    rollout_percentage: int
    target_roles: str
    updated_by_user_id: Optional[int]
    created_at: str
    updated_at: str


class FeatureFlagCreate(BaseModel):
    flag_key: str = Field(..., min_length=1, max_length=128)
    enabled: bool = False
    description: str = ""
    rollout_percentage: int = Field(100, ge=0, le=100)
    target_roles: str = ""


class FeatureFlagPatch(BaseModel):
    enabled: Optional[bool] = None
    description: Optional[str] = None
    rollout_percentage: Optional[int] = Field(None, ge=0, le=100)
    target_roles: Optional[str] = None


class FlagCheckOut(BaseModel):
    flag_key: str
    enabled: bool
    rollout_percentage: int
    active_for_user: bool


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_or_create_system_settings(db) -> SystemSettings:
    row = (await db.execute(select(SystemSettings).where(SystemSettings.id == 1))).scalar_one_or_none()
    if row is None:
        row = SystemSettings(id=1, scrape_concurrency=3, webhook_feishu="", webhook_slack="",
                             webhook_default_url="", default_daily_quota=100)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _llm_key_status() -> LLMKeyStatus:
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return LLMKeyStatus(status="configured", last_four=key[-4:])
    return LLMKeyStatus(status="not_configured", last_four=None)


def _flag_out(f: FeatureFlag) -> FeatureFlagOut:
    return FeatureFlagOut(
        id=f.id,
        flag_key=f.flag_key,
        enabled=f.enabled,
        description=f.description,
        rollout_percentage=f.rollout_percentage,
        target_roles=f.target_roles,
        updated_by_user_id=f.updated_by_user_id,
        created_at=f.created_at.isoformat(),
        updated_at=f.updated_at.isoformat(),
    )


# ─── System Settings ──────────────────────────────────────────────────────────

@router.get("/system", response_model=SystemSettingsOut)
async def get_system_settings(_: TokenData = Depends(require_admin)) -> SystemSettingsOut:
    async with AsyncSessionLocal() as db:
        row = await _get_or_create_system_settings(db)
        return SystemSettingsOut(
            scrape_concurrency=row.scrape_concurrency,
            webhook_feishu=row.webhook_feishu or "",
            webhook_slack=row.webhook_slack or "",
            webhook_default_url=getattr(row, "webhook_default_url", "") or "",
            default_daily_quota=getattr(row, "default_daily_quota", 100) or 100,
            llm_key=_llm_key_status(),
        )


@router.patch("/system", response_model=SystemSettingsOut)
async def patch_system_settings(
    body: SystemSettingsPatch,
    _: TokenData = Depends(require_admin),
) -> SystemSettingsOut:
    async with AsyncSessionLocal() as db:
        row = await _get_or_create_system_settings(db)
        if body.webhook_default_url is not None:
            row.webhook_default_url = body.webhook_default_url
        if body.default_daily_quota is not None:
            row.default_daily_quota = body.default_daily_quota
        if body.webhook_feishu is not None:
            row.webhook_feishu = body.webhook_feishu
        if body.webhook_slack is not None:
            row.webhook_slack = body.webhook_slack
        await db.commit()
        await db.refresh(row)
        return SystemSettingsOut(
            scrape_concurrency=row.scrape_concurrency,
            webhook_feishu=row.webhook_feishu or "",
            webhook_slack=row.webhook_slack or "",
            webhook_default_url=getattr(row, "webhook_default_url", "") or "",
            default_daily_quota=getattr(row, "default_daily_quota", 100) or 100,
            llm_key=_llm_key_status(),
        )


# ─── Feature Flags ─────────────────────────────────────────────────────────────

@router.get("/flags", response_model=List[FeatureFlagOut])
async def list_flags(_: TokenData = Depends(require_admin)) -> List[FeatureFlagOut]:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(FeatureFlag).order_by(FeatureFlag.created_at.desc()))).scalars().all()
        return [_flag_out(f) for f in rows]


@router.post("/flags", response_model=FeatureFlagOut)
async def create_flag(
    body: FeatureFlagCreate,
    current_user: TokenData = Depends(require_admin),
) -> FeatureFlagOut:
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(FeatureFlag).where(FeatureFlag.flag_key == body.flag_key)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Flag key already exists")
        flag = FeatureFlag(
            flag_key=body.flag_key,
            enabled=body.enabled,
            description=body.description,
            rollout_percentage=body.rollout_percentage,
            target_roles=body.target_roles,
            updated_by_user_id=current_user.user_id,
        )
        db.add(flag)
        await db.commit()
        await db.refresh(flag)
        return _flag_out(flag)


@router.patch("/flags/{flag_key}", response_model=FeatureFlagOut)
async def update_flag(
    flag_key: str,
    body: FeatureFlagPatch,
    current_user: TokenData = Depends(require_admin),
) -> FeatureFlagOut:
    async with AsyncSessionLocal() as db:
        flag = (await db.execute(
            select(FeatureFlag).where(FeatureFlag.flag_key == flag_key)
        )).scalar_one_or_none()
        if not flag:
            raise HTTPException(status_code=404, detail="Flag not found")
        if body.enabled is not None:
            flag.enabled = body.enabled
        if body.description is not None:
            flag.description = body.description
        if body.rollout_percentage is not None:
            flag.rollout_percentage = body.rollout_percentage
        if body.target_roles is not None:
            flag.target_roles = body.target_roles
        flag.updated_by_user_id = current_user.user_id
        await db.commit()
        await db.refresh(flag)
        return _flag_out(flag)


@router.delete("/flags/{flag_key}")
async def delete_flag(
    flag_key: str,
    _: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(FeatureFlag).where(FeatureFlag.flag_key == flag_key)
        )
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Flag not found")
        return {"ok": True}


@router.get("/flags/{flag_key}/check")
async def check_flag(
    flag_key: str,
    user_id: Optional[int] = None,
    _: TokenData = Depends(require_admin),
) -> FlagCheckOut:
    async with AsyncSessionLocal() as db:
        flag = (await db.execute(
            select(FeatureFlag).where(FeatureFlag.flag_key == flag_key)
        )).scalar_one_or_none()
        if not flag:
            raise HTTPException(status_code=404, detail="Flag not found")
        active = flag.enabled and (user_id is None or (user_id % 100) < flag.rollout_percentage)
        return FlagCheckOut(
            flag_key=flag.flag_key,
            enabled=flag.enabled,
            rollout_percentage=flag.rollout_percentage,
            active_for_user=active,
        )
