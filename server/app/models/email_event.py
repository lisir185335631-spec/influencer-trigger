import enum
from datetime import datetime
from sqlalchemy import String, Enum, Text, DateTime, ForeignKey, func, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EventType(str, enum.Enum):
    sent = "sent"
    delivered = "delivered"
    opened = "opened"
    clicked = "clicked"
    replied = "replied"
    bounced = "bounced"
    unsubscribed = "unsubscribed"
    spam = "spam"


class EmailEvent(Base):
    __tablename__ = "email_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id", ondelete="CASCADE"), nullable=False, index=True)
    influencer_id: Mapped[int] = mapped_column(ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[EventType] = mapped_column(Enum(EventType), nullable=False, index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # additional event data
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)  # webhook / imap
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_email_events_email_type", "email_id", "event_type"),
    )
