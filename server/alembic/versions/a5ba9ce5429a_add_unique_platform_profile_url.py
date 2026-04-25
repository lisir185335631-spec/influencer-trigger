"""add unique (platform, profile_url) partial index on influencers

Revision ID: a5ba9ce5429a
Revises: fbc6461b6b0e
Create Date: 2026-04-24 19:00:00.000000

One YouTube channel often exposes multiple emails; the old scraper created
one Influencer row per email, so the same channel appeared N times in the
list. We now treat (platform, profile_url) as the channel identity and
refuse to insert a second row for the same channel. NULL/empty profile_url
rows are excluded from the index (legacy data where scraper failed to fill
profile_url — these can still coexist, and Influencer.email's existing
UNIQUE constraint prevents cross-row email collisions anyway).

Run `python scripts/dedup_influencers.py` BEFORE this migration to collapse
existing duplicates — otherwise the CREATE INDEX will fail on duplicate keys.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a5ba9ce5429a"
down_revision: Union[str, None] = "fbc6461b6b0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Partial unique index — same syntax on SQLite and PostgreSQL.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_influencers_platform_profile_url "
        "ON influencers(platform, profile_url) "
        "WHERE profile_url IS NOT NULL AND profile_url != ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_influencers_platform_profile_url")
