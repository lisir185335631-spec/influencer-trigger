"""add webhook_serverchan to system_settings

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-04-27

Adds a Server-酱 SendKey column so reply notifications can fan out to
WeChat (via sct.ftqq.com) alongside the existing Feishu / Slack channels.
Empty string default keeps existing rows valid; webhook_service falls back
to the env var (SERVERCHAN_SEND_KEY) when DB value is empty.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("webhook_serverchan", sa.String(length=512), nullable=False, server_default=""),
    )


def downgrade() -> None:
    # SQLite needs batch mode for DROP COLUMN
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("webhook_serverchan")
