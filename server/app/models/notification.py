import enum
from datetime import datetime
from sqlalchemy import String, Enum, Text, Boolean, DateTime, ForeignKey, func, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NotificationLevel(str, enum.Enum):
    info = "info"
    warning = "warning"
    urgent = "urgent"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    influencer_id: Mapped[int | None] = mapped_column(ForeignKey("influencers.id", ondelete="SET NULL"), nullable=True, index=True)
    email_id: Mapped[int | None] = mapped_column(ForeignKey("emails.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[NotificationLevel] = mapped_column(Enum(NotificationLevel), default=NotificationLevel.info, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)  # reply intent tag
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_notifications_is_read_created", "is_read", "created_at"),
    )
