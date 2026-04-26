"""add tiktok_scrape_mode to system_settings

Revision ID: e8b9c2f4a701
Revises: d4e7a1b2c3f5
Create Date: 2026-04-26

Selector for the TikTok scrape pipeline:
  - "list_local" (default for new installs): clockworks/tiktok-scraper +
    local bio-regex email extraction. ~12x cheaper per email than the
    email-actor path, no third-party email leakage.
  - "email_actor": jurassic_jove/tiktok-email-scraper, kept as A/B fallback.

Existing rows get the new "list_local" default so live operators see the
new pipeline immediately on next scrape (the whole point of switching is
the lower cost / higher quality).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8b9c2f4a701"
down_revision: Union[str, None] = "d4e7a1b2c3f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "tiktok_scrape_mode",
            sa.String(length=32),
            nullable=False,
            server_default="list_local",
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("tiktok_scrape_mode")
