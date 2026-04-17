from datetime import date, datetime, timezone
from sqlalchemy import Date, DateTime, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# metric_type valid values:
#   llm_token   – LLM token consumption (sub_key = model name)
#   email_sent  – outbound emails (sub_key = user_id or "system")
#   scrape_run  – scraper executions (sub_key = platform)
#   storage_mb  – storage usage (sub_key = storage category)


class UsageMetric(Base):
    __tablename__ = "usage_metrics"
    __table_args__ = (
        UniqueConstraint(
            "metric_date", "metric_type", "sub_key",
            name="ix_usage_metric_date_type_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sub_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
