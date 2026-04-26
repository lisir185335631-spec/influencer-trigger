"""add twitter apify config columns to system_settings

Revision ID: b7c3e9f4a803
Revises: f1a3c2b8d402
Create Date: 2026-04-26

Twitter / X scraping went live 2026-04-26 (kaitoeasyapi cheap scraper +
Playwright bio-URL cascade). Each platform owns its own token + actor
columns so operators can isolate billing / rotate credentials per
platform without touching the others — same pattern already in use for
TikTok and Instagram.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c3e9f4a803"
down_revision: Union[str, None] = "f1a3c2b8d402"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("apify_twitter_token", sa.String(length=512), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("apify_twitter_actor", sa.String(length=255), nullable=False, server_default=""),
    )


def downgrade() -> None:
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("apify_twitter_actor")
        batch.drop_column("apify_twitter_token")
