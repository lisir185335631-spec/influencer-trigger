"""add new_count + reused_count to scrape_tasks

Revision ID: c8d2e1f3a401
Revises: a5ba9ce5429a
Create Date: 2026-04-25 02:00:00.000000

Splits the existing valid_count into:
  - new_count:    influencers actually inserted by this task (genuinely new)
  - reused_count: influencers re-linked from a prior task (already in DB)

Historical valid_count rows are backfilled with new_count = valid_count and
reused_count = 0 (we can't reconstruct which were re-links after the fact).

Why we need this: until now, a task that re-discovered N old influencers
showed valid_count = N — looking like success — even though no new contacts
were found. Splitting the counters lets the UI flag "all results are repeats"
and lets the backend gate progress on truly new finds.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d2e1f3a401"
down_revision: Union[str, None] = "a5ba9ce5429a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scrape_tasks",
        sa.Column("new_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "scrape_tasks",
        sa.Column("reused_count", sa.Integer(), server_default="0", nullable=False),
    )
    # Backfill: for completed historical tasks we have no way to know which
    # were re-links, so the safest interpretation is "treat valid_count as
    # new_count" — this preserves the existing UI count and only future tasks
    # will start populating reused_count.
    op.execute("UPDATE scrape_tasks SET new_count = valid_count WHERE new_count = 0")


def downgrade() -> None:
    op.drop_column("scrape_tasks", "reused_count")
    op.drop_column("scrape_tasks", "new_count")
