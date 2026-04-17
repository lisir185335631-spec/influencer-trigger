"""
Admin Holidays API — full CRUD + investment reports + sensitive regions.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.params import Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.email import Email, EmailStatus, EmailType
from app.models.holiday import Holiday
from app.schemas.auth import TokenData
from app.services.holiday_service import (
    create_holiday,
    delete_holiday,
    get_holiday,
    list_holidays,
    update_holiday,
)

router = APIRouter(prefix="/holidays", tags=["admin-holidays"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class HolidayAdminOut(BaseModel):
    id: int
    name: str
    date: str
    is_recurring: bool
    is_active: bool
    greeting_template: Optional[str]
    sensitive_regions: str
    created_at: str
    send_count: int = 0
    open_rate: float = 0.0
    reply_rate: float = 0.0


class HolidayCreate(BaseModel):
    name: str
    date: str
    is_recurring: bool = True
    is_active: bool = True
    greeting_template: Optional[str] = None
    sensitive_regions: str = ''


class HolidayPatch(BaseModel):
    name: Optional[str] = None
    date: Optional[str] = None
    is_recurring: Optional[bool] = None
    is_active: Optional[bool] = None
    greeting_template: Optional[str] = None
    sensitive_regions: Optional[str] = None


class SensitiveRegionsPatch(BaseModel):
    holiday_id: int
    regions: str


# ─── Stats helper ─────────────────────────────────────────────────────────────

async def _holiday_stats(db, holiday_name: str) -> tuple[int, float, float]:
    """Return (send_count, open_rate, reply_rate) for a holiday by name."""
    total = (await db.execute(
        select(func.count()).where(
            Email.email_type == EmailType.holiday,
            Email.subject.contains(holiday_name),
        )
    )).scalar_one() or 0
    if total == 0:
        return 0, 0.0, 0.0
    opened = (await db.execute(
        select(func.count()).where(
            Email.email_type == EmailType.holiday,
            Email.subject.contains(holiday_name),
            Email.status.in_([EmailStatus.opened.value, EmailStatus.clicked.value, EmailStatus.replied.value]),
        )
    )).scalar_one() or 0
    replied = (await db.execute(
        select(func.count()).where(
            Email.email_type == EmailType.holiday,
            Email.subject.contains(holiday_name),
            Email.status == EmailStatus.replied.value,
        )
    )).scalar_one() or 0
    return total, round(opened / total * 100, 1), round(replied / total * 100, 1)


def _fmt(h: Holiday, send_count: int = 0, open_rate: float = 0.0, reply_rate: float = 0.0) -> HolidayAdminOut:
    return HolidayAdminOut(
        id=h.id,
        name=h.name,
        date=h.date.isoformat(),
        is_recurring=h.is_recurring,
        is_active=h.is_active,
        greeting_template=h.greeting_template,
        sensitive_regions=h.sensitive_regions or '',
        created_at=h.created_at.isoformat(),
        send_count=send_count,
        open_rate=open_rate,
        reply_rate=reply_rate,
    )


# ─── List ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[HolidayAdminOut])
async def list_admin_holidays(_: TokenData = Depends(require_admin)) -> list[HolidayAdminOut]:
    async with AsyncSessionLocal() as db:
        holidays = await list_holidays(db)
        result = []
        for h in holidays:
            send_count, open_rate, reply_rate = await _holiday_stats(db, h.name)
            result.append(_fmt(h, send_count, open_rate, reply_rate))
        return result


# ─── Create ───────────────────────────────────────────────────────────────────

@router.post("", response_model=HolidayAdminOut, status_code=201)
async def create_admin_holiday(
    body: HolidayCreate,
    _: TokenData = Depends(require_admin),
) -> HolidayAdminOut:
    async with AsyncSessionLocal() as db:
        h = await create_holiday(
            db,
            name=body.name,
            holiday_date=date.fromisoformat(body.date),
            is_recurring=body.is_recurring,
            is_active=body.is_active,
            greeting_template=body.greeting_template,
        )
        if body.sensitive_regions:
            h.sensitive_regions = body.sensitive_regions
            await db.commit()
            await db.refresh(h)
        return _fmt(h)


# ─── Update ───────────────────────────────────────────────────────────────────

@router.patch("/{holiday_id}", response_model=HolidayAdminOut)
async def patch_admin_holiday(
    holiday_id: int,
    body: HolidayPatch,
    _: TokenData = Depends(require_admin),
) -> HolidayAdminOut:
    async with AsyncSessionLocal() as db:
        update_data = body.model_dump(exclude_unset=True)
        # sensitive_regions handled separately
        sensitive_regions = update_data.pop("sensitive_regions", None)
        if "date" in update_data:
            update_data["holiday_date"] = date.fromisoformat(update_data.pop("date"))

        h = await update_holiday(db, holiday_id, **update_data)
        if h is None:
            raise HTTPException(status_code=404, detail="Holiday not found")

        if sensitive_regions is not None:
            h.sensitive_regions = sensitive_regions
            await db.commit()
            await db.refresh(h)

        return _fmt(h)


# ─── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/{holiday_id}", status_code=204)
async def delete_admin_holiday(
    holiday_id: int,
    _: TokenData = Depends(require_admin),
) -> None:
    async with AsyncSessionLocal() as db:
        ok = await delete_holiday(db, holiday_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Holiday not found")


# ─── Investment Report ────────────────────────────────────────────────────────

@router.get("/{holiday_id}/investment-report")
async def get_investment_report(
    holiday_id: int,
    _: TokenData = Depends(require_admin),
) -> dict:
    """Historical send report for a holiday: total/open-rate/reply-rate per year."""
    async with AsyncSessionLocal() as db:
        h = await get_holiday(db, holiday_id)
        if h is None:
            raise HTTPException(status_code=404, detail="Holiday not found")

        rows = (await db.execute(
            select(
                func.strftime('%Y', Email.sent_at).label("year"),
                func.count(Email.id).label("total"),
                func.sum(
                    func.case(
                        (Email.status.in_([
                            EmailStatus.opened.value, EmailStatus.clicked.value, EmailStatus.replied.value
                        ]), 1),
                        else_=0,
                    )
                ).label("opened"),
                func.sum(
                    func.case(
                        (Email.status == EmailStatus.replied.value, 1),
                        else_=0,
                    )
                ).label("replied"),
            )
            .where(
                Email.email_type == EmailType.holiday,
                Email.subject.contains(h.name),
                Email.sent_at.isnot(None),
            )
            .group_by(func.strftime('%Y', Email.sent_at))
            .order_by(func.strftime('%Y', Email.sent_at).asc())
        )).all()

        yearly = []
        for row in rows:
            total = row.total or 0
            opened = row.opened or 0
            replied = row.replied or 0
            yearly.append({
                "year": row.year,
                "total": total,
                "open_rate": round(opened / total * 100, 1) if total else 0.0,
                "reply_rate": round(replied / total * 100, 1) if total else 0.0,
            })

        return {"holiday_id": holiday_id, "name": h.name, "yearly": yearly}


# ─── Sensitive Regions ────────────────────────────────────────────────────────

@router.post("/sensitive-regions")
async def set_sensitive_regions(
    body: SensitiveRegionsPatch,
    _: TokenData = Depends(require_admin),
) -> dict:
    """Set comma-separated region codes that should not receive this holiday email."""
    async with AsyncSessionLocal() as db:
        h = await get_holiday(db, body.holiday_id)
        if h is None:
            raise HTTPException(status_code=404, detail="Holiday not found")
        h.sensitive_regions = body.regions
        await db.commit()
        return {"holiday_id": h.id, "sensitive_regions": h.sensitive_regions}
