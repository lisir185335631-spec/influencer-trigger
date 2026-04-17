import enum
from datetime import datetime
from sqlalchemy import String, Enum, Text, DateTime, ForeignKey, func, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmailStatus(str, enum.Enum):
    pending = "pending"
    queued = "queued"
    sent = "sent"
    delivered = "delivered"
    opened = "opened"
    clicked = "clicked"
    replied = "replied"
    bounced = "bounced"
    failed = "failed"
    blocked = "blocked"
    cancelled = "cancelled"


class EmailType(str, enum.Enum):
    initial = "initial"
    follow_up = "follow_up"
    holiday = "holiday"


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    influencer_id: Mapped[int] = mapped_column(ForeignKey("influencers.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    mailbox_id: Mapped[int | None] = mapped_column(ForeignKey("mailboxes.id", ondelete="SET NULL"), nullable=True, index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)

    email_type: Mapped[EmailType] = mapped_column(Enum(EmailType), default=EmailType.initial, nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True, index=True)

    status: Mapped[EmailStatus] = mapped_column(Enum(EmailStatus), default=EmailStatus.pending, nullable=False, index=True)
    reply_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_from: Mapped[str | None] = mapped_column(String(256), nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_emails_influencer_status", "influencer_id", "status"),
        Index("ix_emails_campaign_status", "campaign_id", "status"),
    )
