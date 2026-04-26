"""add apify config columns to system_settings

Revision ID: d4e7a1b2c3f5
Revises: c8d2e1f3a401
Create Date: 2026-04-26

Adds per-platform Apify token + actor columns to the system_settings
singleton. Empty string default keeps existing rows valid and means the
scraper falls back to the env var in config.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e7a1b2c3f5"
down_revision: Union[str, None] = "c8d2e1f3a401"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("apify_tiktok_token", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("apify_tiktok_actor", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("apify_ig_token", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("apify_ig_actor", sa.String(length=255), nullable=False, server_default=""),
    )


def downgrade() -> None:
    # SQLite needs batch mode for DROP COLUMN
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("apify_ig_actor")
        batch.drop_column("apify_ig_token")
        batch.drop_column("apify_tiktok_actor")
        batch.drop_column("apify_tiktok_token")
