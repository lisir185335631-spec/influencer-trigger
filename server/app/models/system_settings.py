from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemSettings(Base):
    """Singleton system-wide settings row (id=1)."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scrape_concurrency: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    webhook_feishu: Mapped[str] = mapped_column(String, default="", nullable=False)
    webhook_slack: Mapped[str] = mapped_column(String, default="", nullable=False)
    webhook_default_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    default_daily_quota: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    security_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
