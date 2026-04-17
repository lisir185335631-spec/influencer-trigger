from datetime import date, datetime
from sqlalchemy import String, Boolean, Date, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Holiday(Base):
    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # repeat every year
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    greeting_template: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sensitive_regions: Mapped[str] = mapped_column(String(512), default='', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
