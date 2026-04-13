from sqlalchemy import ForeignKey, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScrapeTaskInfluencer(Base):
    """Association between a scrape task and influencers it discovered."""

    __tablename__ = "scrape_task_influencers"

    scrape_task_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_tasks.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    influencer_id: Mapped[int] = mapped_column(
        ForeignKey("influencers.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    created_at: Mapped[object] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
