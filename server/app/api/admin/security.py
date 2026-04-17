"""
Admin Security API — anomaly alerts, 2FA config, key rotation.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal, get_db
from app.models.audit_log import AuditLog
from app.models.login_history import LoginHistory
from app.models.security_alert import KeyRotationHistory, SecurityAlert
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.schemas.auth import TokenData
from app.services.auth_service import verify_password

router = APIRouter(prefix="/security", tags=["admin-security"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class SecurityAlertOut(BaseModel):
    id: int
    alert_type: str
    user_id: Optional[int]
    details_json: Optional[str]
    acknowledged: bool
    acknowledged_by: Optional[int]
    acknowledged_at: Optional[datetime]
    created_at: datetime


class TwoFAConfig(BaseModel):
    require_password_for_sensitive: bool
    totp_enabled: bool


class TwoFAConfigPatch(BaseModel):
    require_password_for_sensitive: Optional[bool] = None
    totp_enabled: Optional[bool] = None


class RotateKeysBody(BaseModel):
    admin_password: str


class KeyRotationHistoryOut(BaseModel):
    id: int
    rotated_by_user_id: int
    rotated_by_username: str
    note: Optional[str]
    created_at: datetime


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_or_create_settings(db: AsyncSession) -> SystemSettings:
    row = (await db.execute(select(SystemSettings))).scalar_one_or_none()
    if row is None:
        row = SystemSettings()
        db.add(row)
        await db.flush()
    return row


async def _detect_anomalies(db: AsyncSession) -> None:
    """Check login_history and create SecurityAlert records for new anomalies."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=10)
    since_30d = now - timedelta(days=30)

    # Get all users with recent login activity
    user_ids_q = (
        select(LoginHistory.user_id)
        .where(LoginHistory.user_id.isnot(None))
        .distinct()
    )
    user_ids = (await db.execute(user_ids_q)).scalars().all()

    for uid in user_ids:
        # Rule 1: ≥5 failures in 10 minutes
        fail_count = (
            await db.execute(
                select(func.count()).where(
                    LoginHistory.user_id == uid,
                    LoginHistory.success.is_(False),
                    LoginHistory.created_at >= window_start,
                )
            )
        ).scalar_one()

        if fail_count >= 5:
            # Avoid duplicate alert within same 10-min window
            existing = (
                await db.execute(
                    select(SecurityAlert).where(
                        SecurityAlert.user_id == uid,
                        SecurityAlert.alert_type == "brute_force",
                        SecurityAlert.created_at >= window_start,
                    )
                )
            ).scalar_one_or_none()
            if not existing:
                db.add(SecurityAlert(
                    alert_type="brute_force",
                    user_id=uid,
                    details_json=json.dumps({"fail_count": fail_count, "window_minutes": 10}),
                ))

        # Rule 2: new IP (not seen in past 30 days for this user)
        recent_logins = (
            await db.execute(
                select(LoginHistory.ip, LoginHistory.success, LoginHistory.created_at)
                .where(
                    LoginHistory.user_id == uid,
                    LoginHistory.created_at >= since_30d,
                )
                .order_by(LoginHistory.created_at.desc())
                .limit(200)
            )
        ).all()

        if len(recent_logins) >= 2:
            latest_ip = recent_logins[0].ip
            historical_ips = {r.ip for r in recent_logins[1:] if r.ip}
            if latest_ip and latest_ip not in historical_ips:
                existing_ip = (
                    await db.execute(
                        select(SecurityAlert).where(
                            SecurityAlert.user_id == uid,
                            SecurityAlert.alert_type == "new_ip",
                            SecurityAlert.details_json.contains(latest_ip),
                            SecurityAlert.created_at >= now - timedelta(hours=1),
                        )
                    )
                ).scalar_one_or_none()
                if not existing_ip:
                    db.add(SecurityAlert(
                        alert_type="new_ip",
                        user_id=uid,
                        details_json=json.dumps({"ip": latest_ip}),
                    ))

    await db.commit()


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/alerts")
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
) -> dict:
    await _detect_anomalies(db)
    rows = (
        await db.execute(
            select(SecurityAlert).order_by(SecurityAlert.created_at.desc()).limit(100)
        )
    ).scalars().all()
    return {
        "items": [
            SecurityAlertOut(
                id=r.id,
                alert_type=r.alert_type,
                user_id=r.user_id,
                details_json=r.details_json,
                acknowledged=r.acknowledged,
                acknowledged_by=r.acknowledged_by,
                acknowledged_at=r.acknowledged_at,
                created_at=r.created_at,
            )
            for r in rows
        ]
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
) -> dict:
    alert = (
        await db.execute(select(SecurityAlert).where(SecurityAlert.id == alert_id))
    ).scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    alert.acknowledged_by = current_user.user_id
    alert.acknowledged_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


@router.get("/2fa-config")
async def get_2fa_config(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
) -> TwoFAConfig:
    settings = await _get_or_create_settings(db)
    raw = settings.security_config or "{}"
    cfg = json.loads(raw)
    return TwoFAConfig(
        require_password_for_sensitive=cfg.get("require_password_for_sensitive", True),
        totp_enabled=cfg.get("totp_enabled", False),
    )


@router.patch("/2fa-config")
async def patch_2fa_config(
    body: TwoFAConfigPatch,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
) -> TwoFAConfig:
    settings = await _get_or_create_settings(db)
    raw = settings.security_config or "{}"
    cfg = json.loads(raw)
    if body.require_password_for_sensitive is not None:
        cfg["require_password_for_sensitive"] = body.require_password_for_sensitive
    if body.totp_enabled is not None:
        cfg["totp_enabled"] = body.totp_enabled
    settings.security_config = json.dumps(cfg)
    await db.commit()
    return TwoFAConfig(
        require_password_for_sensitive=cfg.get("require_password_for_sensitive", True),
        totp_enabled=cfg.get("totp_enabled", False),
    )


@router.post("/rotate-keys")
async def rotate_keys(
    body: RotateKeysBody,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
) -> dict:
    # Verify admin password
    admin_user = (
        await db.execute(select(User).where(User.id == current_user.user_id))
    ).scalar_one_or_none()
    if not admin_user or not verify_password(body.admin_password, admin_user.password_hash):
        raise HTTPException(status_code=403, detail="Invalid password")

    # Generate new keys
    new_jwt_secret = secrets.token_hex(32)
    new_fernet_key = Fernet.generate_key().decode()

    # Write new keys to .env file
    import os
    env_path = os.path.join(os.path.dirname(__file__), "../../../../.env")
    env_path = os.path.normpath(env_path)
    _update_env_key(env_path, "SECRET_KEY", new_jwt_secret)
    _update_env_key(env_path, "ENCRYPTION_KEY", new_fernet_key)

    # Invalidate all JWTs by incrementing token_version for all users
    await db.execute(update(User).values(token_version=User.token_version + 1))

    # Record rotation history
    db.add(KeyRotationHistory(
        rotated_by_user_id=current_user.user_id,
        rotated_by_username=current_user.username,
        note="JWT SECRET + Fernet KEY rotated, all sessions invalidated",
    ))

    # Write audit log
    db.add(AuditLog(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role,
        action="rotate_keys",
        resource_type="security",
        request_method="POST",
        request_path="/api/admin/security/rotate-keys",
        status_code=200,
    ))

    await db.commit()
    return {"ok": True, "message": "Keys rotated. All active sessions have been invalidated."}


def _update_env_key(env_path: str, key: str, value: str) -> None:
    import os
    if not os.path.exists(env_path):
        return
    with open(env_path, "r") as f:
        lines = f.readlines()
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(new_lines)


@router.get("/key-rotation-history")
async def key_rotation_history(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
) -> dict:
    rows = (
        await db.execute(
            select(KeyRotationHistory).order_by(KeyRotationHistory.created_at.desc()).limit(50)
        )
    ).scalars().all()

    # Calculate age of last rotation
    last_rotation: Optional[datetime] = rows[0].created_at if rows else None
    key_age_days: Optional[int] = None
    if last_rotation:
        now = datetime.now(timezone.utc)
        last_dt = last_rotation.replace(tzinfo=timezone.utc) if last_rotation.tzinfo is None else last_rotation
        key_age_days = (now - last_dt).days

    return {
        "key_age_days": key_age_days,
        "items": [
            KeyRotationHistoryOut(
                id=r.id,
                rotated_by_user_id=r.rotated_by_user_id,
                rotated_by_username=r.rotated_by_username,
                note=r.note,
                created_at=r.created_at,
            )
            for r in rows
        ],
    }
