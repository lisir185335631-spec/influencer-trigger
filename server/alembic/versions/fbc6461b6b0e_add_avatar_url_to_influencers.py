"""add avatar_url to influencers

Revision ID: fbc6461b6b0e
Revises: 6134b15eb793
Create Date: 2026-04-18 18:54:32.930915

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fbc6461b6b0e'
down_revision: Union[str, None] = '6134b15eb793'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "influencers",
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN directly — use batch mode
    with op.batch_alter_table("influencers") as batch:
        batch.drop_column("avatar_url")
