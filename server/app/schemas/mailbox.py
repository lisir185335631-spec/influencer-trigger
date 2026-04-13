from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict, Field


class MailboxCreate(BaseModel):
    email: EmailStr
    display_name: str | None = None
    smtp_host: str
    smtp_port: int = 587
    smtp_password: str
    smtp_use_tls: bool = True
    imap_host: str | None = None
    imap_port: int = 993
    daily_limit: int = Field(default=500, ge=1, le=10000)
    hourly_limit: int = Field(default=50, ge=1, le=1000)


class MailboxUpdate(BaseModel):
    display_name: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    daily_limit: int | None = Field(default=None, ge=1, le=10000)
    hourly_limit: int | None = Field(default=None, ge=1, le=1000)


class MailboxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str | None
    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool
    imap_host: str | None
    imap_port: int
    daily_limit: int
    hourly_limit: int
    today_sent: int
    total_sent: int
    bounce_rate: float
    status: str
    created_at: datetime
    updated_at: datetime


class TestConnectionRequest(BaseModel):
    test_to: EmailStr | None = None
