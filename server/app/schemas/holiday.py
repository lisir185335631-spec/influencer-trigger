from datetime import date, datetime
from pydantic import BaseModel, ConfigDict


class HolidayCreate(BaseModel):
    name: str
    date: date
    is_recurring: bool = True
    is_active: bool = True
    greeting_template: str | None = None


class HolidayUpdate(BaseModel):
    name: str | None = None
    date: date | None = None
    is_recurring: bool | None = None
    is_active: bool | None = None
    greeting_template: str | None = None


class HolidayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    date: date
    is_recurring: bool
    is_active: bool
    greeting_template: str | None
    created_at: datetime


class HolidayGreetingLogItem(BaseModel):
    id: int
    influencer_id: int
    influencer_name: str | None
    influencer_email: str
    influencer_platform: str | None
    subject: str
    status: str
    sent_at: str | None
    created_at: str


class HolidayGreetingLogsResponse(BaseModel):
    items: list[HolidayGreetingLogItem]
    total: int
    page: int
    page_size: int
