import enum
from datetime import datetime
from sqlalchemy import String, Enum, Integer, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScrapeTaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ScrapeTask(Base):
    __tablename__ = "scrape_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platforms: Mapped[str] = mapped_column(String(256), nullable=False)  # JSON array stored as string
    industry: Mapped[str] = mapped_column(String(128), nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    status: Mapped[ScrapeTaskStatus] = mapped_column(Enum(ScrapeTaskStatus), default=ScrapeTaskStatus.pending, nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0-100
    found_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_market: Mapped[str | None] = mapped_column(String(64), nullable=True)
    search_keywords: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: LLM-expanded queries
    competitor_brands: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
