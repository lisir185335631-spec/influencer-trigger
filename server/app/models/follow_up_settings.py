from datetime import datetime
from sqlalchemy import Boolean, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FollowUpSettings(Base):
    """Singleton settings row (id=1) for the monthly follow-up scheduler."""

    __tablename__ = "follow_up_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # How many days must have passed since last email before a follow-up is sent
    interval_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    # Maximum number of follow-up emails per influencer
    max_count: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    # UTC hour (0-23) at which the daily check runs
    hour_utc: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
