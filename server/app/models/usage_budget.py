from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UsageBudget(Base):
    __tablename__ = "usage_budgets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Format: YYYY-MM  e.g. "2026-04"
    month: Mapped[str] = mapped_column(String(7), unique=True, nullable=False)
    budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    alert_threshold_pct: Mapped[float] = mapped_column(Float, nullable=False, default=80)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
