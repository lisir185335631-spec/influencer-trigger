import enum
from datetime import datetime
from sqlalchemy import String, Enum, Integer, BigInteger, Text, DateTime, func, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InfluencerPlatform(str, enum.Enum):
    tiktok = "tiktok"
    instagram = "instagram"
    youtube = "youtube"
    twitter = "twitter"
    facebook = "facebook"
    other = "other"


class InfluencerStatus(str, enum.Enum):
    new = "new"
    contacted = "contacted"
    replied = "replied"
    archived = "archived"


class InfluencerPriority(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ReplyIntent(str, enum.Enum):
    interested = "interested"
    pricing = "pricing"
    declined = "declined"
    auto_reply = "auto_reply"
    irrelevant = "irrelevant"


class Influencer(Base):
    __tablename__ = "influencers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nickname: Mapped[str | None] = mapped_column(String(256), nullable=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    platform: Mapped[InfluencerPlatform | None] = mapped_column(Enum(InfluencerPlatform), nullable=True, index=True)
    profile_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    followers: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[InfluencerStatus] = mapped_column(Enum(InfluencerStatus), default=InfluencerStatus.new, nullable=False, index=True)
    priority: Mapped[InfluencerPriority] = mapped_column(Enum(InfluencerPriority), default=InfluencerPriority.medium, nullable=False)
    reply_intent: Mapped[ReplyIntent | None] = mapped_column(Enum(ReplyIntent), nullable=True)
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(nullable=True)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_influencers_status_priority", "status", "priority"),
        Index("ix_influencers_platform_status", "platform", "status"),
    )
