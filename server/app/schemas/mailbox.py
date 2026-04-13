from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict


class MailboxCreate(BaseModel):
    email: EmailStr
    display_name: str | None = None
    smtp_host: str
    smtp_port: int = 587
    smtp_password: str
    smtp_use_tls: bool = True
    imap_host: str | None = None
    imap_port: int = 993
    daily_limit: int = 500
    hourly_limit: int = 50


class MailboxUpdate(BaseModel):
    display_name: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    daily_limit: int | None = None
    hourly_limit: int | None = None


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
