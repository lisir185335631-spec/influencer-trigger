"""drop tiktok_scrape_mode column

Revision ID: f1a3c2b8d402
Revises: e8b9c2f4a701
Create Date: 2026-04-26

The selector existed only to A/B between v1 (jurassic_jove email actor)
and v2 (clockworks list + local extract). v1 was removed 2026-04-26 —
v2 is now the only TikTok pipeline, so the column has nothing to switch
between. Drop it.

Downgrade restores the column with the original default so a rollback
to a checkout that still has v1 keeps working.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a3c2b8d402"
down_revision: Union[str, None] = "e8b9c2f4a701"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite needs batch mode for DROP COLUMN.
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("tiktok_scrape_mode")


def downgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "tiktok_scrape_mode",
            sa.String(length=32),
            nullable=False,
            server_default="list_local",
        ),
    )
