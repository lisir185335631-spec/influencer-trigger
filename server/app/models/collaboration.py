import enum
from datetime import datetime
from sqlalchemy import String, Enum, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CollaborationStatus(str, enum.Enum):
    negotiating = "negotiating"
    signed = "signed"
    completed = "completed"
    cancelled = "cancelled"


class Collaboration(Base):
    __tablename__ = "collaborations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    influencer_id: Mapped[int] = mapped_column(ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[CollaborationStatus] = mapped_column(Enum(CollaborationStatus), default=CollaborationStatus.negotiating, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
