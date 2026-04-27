from datetime import datetime
from sqlalchemy import Boolean, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FollowUpSettings(Base):
    """Singleton settings row (id=1) for the two-phase follow-up scheduler.

    Cadence: phase 1 fires `phase1_count` follow-ups at `phase1_interval_days`
    apart starting from the initial send (default 3 × 2 days → days 3/5/7),
    then phase 2 takes over with `max_count` follow-ups at `interval_days`
    apart (default 6 × 30 days → ~6 months). The next-send-due check picks the
    interval based on the influencer's current `follow_up_count`.
    """

    __tablename__ = "follow_up_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Phase 1 (intensive cadence) — sent first, immediately after initial outreach
    phase1_count: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    phase1_interval_days: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    # Phase 2 (cold cadence) — kicks in after phase 1 exhausts. The column
    # NAMES are legacy from the pre-two-phase era ("monthly follow-up");
    # SEMANTICALLY they are now phase-2 interval & count. Renaming them in
    # DB would force a migration + break API contracts; we keep the names
    # and document the meaning here so callers don't get misled.
    # → interval_days  ≡ phase-2 interval (days between cold follow-ups)
    # → max_count      ≡ phase-2 count    (number of cold follow-ups)
    interval_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_count: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    # UTC hour (0-23) at which the daily check runs
    hour_utc: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
