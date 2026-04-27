"""add follow-up phase 1 fields (intensive cadence)

Revision ID: f1a2b3c4d5e6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-27

Splits the auto follow-up cadence into two configurable phases:
  Phase 1 (intensive) — `phase1_count` follow-ups at `phase1_interval_days` apart
                       (default: 3 follow-ups, 2 days apart → days 3/5/7).
  Phase 2 (cold)      — uses the existing `max_count` and `interval_days` columns
                       as-is (default: 6 follow-ups, 30 days apart).

Existing rows ({interval_days=30, max_count=6}) become "phase 2 only" — the
new phase 1 columns get their server_default of 3 / 2, producing the agreed
"3-intensive + 6-cold = 9 total follow-ups, ~6 months end-to-end" cadence
without any data migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "follow_up_settings",
        sa.Column("phase1_count", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "follow_up_settings",
        sa.Column("phase1_interval_days", sa.Integer(), nullable=False, server_default="2"),
    )


def downgrade() -> None:
    # SQLite needs batch mode for DROP COLUMN
    with op.batch_alter_table("follow_up_settings") as batch:
        batch.drop_column("phase1_interval_days")
        batch.drop_column("phase1_count")
