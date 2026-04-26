"""add facebook apify config columns to system_settings

Revision ID: c5d8f1a9b204
Revises: b7c3e9f4a803
Create Date: 2026-04-26

Facebook scraping went live 2026-04-26 (Brave SERP discovery + apify
facebook-pages-scraper + Playwright website cascade). Each platform
owns its own token + actor columns — same pattern as TikTok / IG /
Twitter.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d8f1a9b204"
down_revision: Union[str, None] = "b7c3e9f4a803"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("apify_facebook_token", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("apify_facebook_actor", sa.String(length=255), nullable=False, server_default=""),
    )


def downgrade() -> None:
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("apify_facebook_actor")
        batch.drop_column("apify_facebook_token")
