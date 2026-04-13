from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemSettings(Base):
    """Singleton system-wide settings row (id=1)."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scrape_concurrency: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    webhook_feishu: Mapped[str] = mapped_column(String, default="", nullable=False)
    webhook_slack: Mapped[str] = mapped_column(String, default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
