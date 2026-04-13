from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


class FollowUpSettingsNested(BaseModel):
    enabled: Optional[bool] = None
    interval_days: Optional[int] = Field(None, ge=1, le=365)
    max_count: Optional[int] = Field(None, ge=1, le=50)
    hour_utc: Optional[int] = Field(None, ge=0, le=23)


class SettingsOut(BaseModel):
    # follow-up strategy
    follow_up_enabled: bool
    interval_days: int
    max_count: int
    hour_utc: int
    # scrape
    scrape_concurrency: int
    # webhooks
    webhook_feishu: str
    webhook_slack: str


class SettingsUpdate(BaseModel):
    # follow-up strategy (optional)
    follow_up_enabled: Optional[bool] = None
    interval_days: Optional[int] = Field(None, ge=1, le=365)
    max_count: Optional[int] = Field(None, ge=1, le=50)
    hour_utc: Optional[int] = Field(None, ge=0, le=23)
    # scrape (optional)
    scrape_concurrency: Optional[int] = Field(None, ge=1, le=50)
    # webhooks (optional)
    webhook_feishu: Optional[str] = None
    webhook_slack: Optional[str] = None
