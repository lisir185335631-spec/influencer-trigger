"""
Holidays API — CRUD for holiday management and greeting log list.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.deps import get_current_user
from app.models.user import User
from app.schemas.holiday import (
    HolidayCreate,
    HolidayUpdate,
    HolidayResponse,
    HolidayGreetingLogItem,
    HolidayGreetingLogsResponse,
)
from app.services.holiday_service import (
    list_holidays,
    get_holiday,
    create_holiday,
    update_holiday,
    delete_holiday,
    list_greeting_logs,
    holiday_greeting_check,
)

router = APIRouter(prefix="/holidays", tags=["holidays"])


async def get_db():  # type: ignore[return]
    async with AsyncSessionLocal() as db:
        yield db


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=list[HolidayResponse])
async def list_holidays_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[HolidayResponse]:
    holidays = await list_holidays(db)
    return [HolidayResponse.model_validate(h) for h in holidays]


@router.post("", response_model=HolidayResponse, status_code=201)
async def create_holiday_endpoint(
    body: HolidayCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HolidayResponse:
    holiday = await create_holiday(
        db,
        name=body.name,
        holiday_date=body.date,
        is_recurring=body.is_recurring,
        is_active=body.is_active,
        greeting_template=body.greeting_template,
    )
    return HolidayResponse.model_validate(holiday)


@router.put("/{holiday_id}", response_model=HolidayResponse)
async def update_holiday_endpoint(
    holiday_id: int,
    body: HolidayUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HolidayResponse:
    update_data = body.model_dump(exclude_unset=True)
    if "date" in update_data:
        update_data["holiday_date"] = update_data.pop("date")

    holiday = await update_holiday(db, holiday_id, **update_data)
    if holiday is None:
        raise HTTPException(status_code=404, detail="Holiday not found")
    return HolidayResponse.model_validate(holiday)


@router.delete("/{holiday_id}", status_code=204)
async def delete_holiday_endpoint(
    holiday_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await delete_holiday(db, holiday_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Holiday not found")


# ---------------------------------------------------------------------------
# Greeting logs
# ---------------------------------------------------------------------------

@router.get("/logs", response_model=HolidayGreetingLogsResponse)
async def list_greeting_logs_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HolidayGreetingLogsResponse:
    rows, total = await list_greeting_logs(db, page=page, page_size=page_size)
    return HolidayGreetingLogsResponse(
        items=[HolidayGreetingLogItem(**r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------

@router.post("/trigger", status_code=202)
async def trigger_greeting(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Manually trigger the holiday greeting check (runs in background)."""
    asyncio.create_task(holiday_greeting_check())
    return {"message": "Holiday greeting check triggered"}
