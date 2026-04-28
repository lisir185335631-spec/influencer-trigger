"""WebhookPushLog — one row per outbound notification webhook call.

Records every Server酱 / Feishu / Slack push so the dashboard can show
the operator "did the WeChat ping actually go out, and how long did
it take" without having to grep journald. Append-only; no updates
after insert.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebhookPushLog(Base):
    __tablename__ = "webhook_push_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # serverchan / feishu / slack — kept as plain string (not enum) so
    # adding a new channel doesn't require a schema migration.
    channel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # The reply email + influencer that triggered this push. Both
    # nullable: webhook test pushes (from /api/settings/test/serverchan)
    # have neither, and email_id is SET NULL on email delete so purging
    # old emails doesn't cascade-kill push history.
    email_id: Mapped[int | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    influencer_id: Mapped[int | None] = mapped_column(
        ForeignKey("influencers.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    # First 512 chars of the push body — enough to recognize "what was
    # sent" in the audit log without bloating row size for high-volume
    # senders.
    content_preview: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # "success" | "failed" — string so the UI can format directly,
    # avoiding an enum import cycle for the modal renderer.
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # HTTP status code returned by the webhook endpoint. None when the
    # request never reached the server (DNS, timeout, TLS error).
    http_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Provider-side error message (Server酱 returns JSON {code, message}
    # for sub-200 errors) or local exception text. Capped at 500 chars
    # at write time.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True,
    )

    __table_args__ = (
        # Composite index supporting the common dashboard query
        # "newest first, filtered by channel".
        Index("ix_webhook_logs_channel_created", "channel", "created_at"),
    )
