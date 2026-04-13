import enum
from datetime import datetime
from sqlalchemy import String, Enum, Integer, Float, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MailboxStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    error = "error"


class Mailbox(Base):
    __tablename__ = "mailboxes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # SMTP settings
    smtp_host: Mapped[str] = mapped_column(String(256), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587, nullable=False)
    smtp_password_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # IMAP settings
    imap_host: Mapped[str | None] = mapped_column(String(256), nullable=True)
    imap_port: Mapped[int] = mapped_column(Integer, default=993, nullable=False)

    # Rate limiting
    daily_limit: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    hourly_limit: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    today_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    this_hour_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Stats
    total_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bounce_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    status: Mapped[MailboxStatus] = mapped_column(Enum(MailboxStatus), default=MailboxStatus.active, nullable=False, index=True)
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
