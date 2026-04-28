"""add webhook_push_logs table

Revision ID: h3c4d5e6f7a8
Revises: g2b3c4d5e6f7
Create Date: 2026-04-28

Adds a per-push audit log table so the dashboard can surface
notification-channel health (Server酱 / Feishu / Slack) and the
operator can see "did my WeChat push fire" without grep journald.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h3c4d5e6f7a8"
down_revision: Union[str, None] = "g2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_push_logs",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("email_id", sa.Integer(), nullable=True),
        sa.Column("influencer_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("content_preview", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("http_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["influencer_id"], ["influencers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_push_logs_channel", "webhook_push_logs", ["channel"])
    op.create_index("ix_webhook_push_logs_email_id", "webhook_push_logs", ["email_id"])
    op.create_index(
        "ix_webhook_push_logs_influencer_id", "webhook_push_logs", ["influencer_id"],
    )
    op.create_index("ix_webhook_push_logs_status", "webhook_push_logs", ["status"])
    op.create_index("ix_webhook_push_logs_created_at", "webhook_push_logs", ["created_at"])
    op.create_index(
        "ix_webhook_logs_channel_created",
        "webhook_push_logs",
        ["channel", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_logs_channel_created", table_name="webhook_push_logs")
    op.drop_index("ix_webhook_push_logs_created_at", table_name="webhook_push_logs")
    op.drop_index("ix_webhook_push_logs_status", table_name="webhook_push_logs")
    op.drop_index(
        "ix_webhook_push_logs_influencer_id", table_name="webhook_push_logs",
    )
    op.drop_index("ix_webhook_push_logs_email_id", table_name="webhook_push_logs")
    op.drop_index("ix_webhook_push_logs_channel", table_name="webhook_push_logs")
    op.drop_table("webhook_push_logs")
