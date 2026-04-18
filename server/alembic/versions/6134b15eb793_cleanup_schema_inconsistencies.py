"""cleanup schema inconsistencies

Revision ID: 6134b15eb793
Revises: 13091cc0ca0a
Create Date: 2026-04-18 08:57:21.344757

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6134b15eb793'
down_revision: Union[str, None] = '13091cc0ca0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1a: drop redundant index on feature_flags.flag_key
    # SQLAlchemy's unique=True,index=True on the model already creates
    # ix_feature_flags_flag_key; this duplicate named index came from the
    # retired main.py lifespan migration.
    op.execute("DROP INDEX IF EXISTS ix_feature_flags_key")

    # 1b: drop legacy index ix_key_rotation_created_at (created by retired
    # main.py lifespan migration). Model now declares index=True on
    # KeyRotationHistory.created_at, which uses SQLAlchemy default name
    # ix_key_rotation_history_created_at (already present in DB via baseline).
    op.execute("DROP INDEX IF EXISTS ix_key_rotation_created_at")

    # 1c: users.token_version NOT NULL via SQLite batch mode
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "token_version",
            existing_type=sa.Integer(),
            nullable=False,
            existing_server_default=sa.text("0"),
        )


def downgrade() -> None:
    # 1c reverse
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "token_version",
            existing_type=sa.Integer(),
            nullable=True,
            existing_server_default=sa.text("0"),
        )
    # 1b reverse — recreate legacy index
    op.create_index(
        "ix_key_rotation_created_at",
        "key_rotation_history",
        ["created_at"],
    )
    # 1a reverse — recreate the (redundant) index
    op.create_index(
        "ix_feature_flags_key",
        "feature_flags",
        ["flag_key"],
        unique=True,
    )
