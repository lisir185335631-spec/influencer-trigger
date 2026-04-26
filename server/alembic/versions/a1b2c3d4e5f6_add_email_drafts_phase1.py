"""add email_drafts table + use_drafts flag + draft_id FK

Revision ID: a1b2c3d4e5f6
Revises: c5d8f1a9b204
Create Date: 2026-04-26

Phase 1 of the per-recipient email personalization workflow:
- New `email_drafts` table holds LLM-generated subject + body_html per
  (campaign, influencer) pair, with status tracking and edit-protection
  for review-before-send.
- `campaigns.use_drafts` flag tells the Sender Agent to read from drafts
  rather than rendering the template inline.
- `emails.draft_id` ties each sent email back to the draft that produced
  it, for audit / regenerate / A-B telemetry.

Two new CampaignStatus values (`draft_pending`, `draft_ready`) are
added at the application layer; SQLite stores enums as plain strings,
so no schema change is required for that — the existing `status`
column already accepts arbitrary strings.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "c5d8f1a9b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create email_drafts table
    op.create_table(
        "email_drafts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "campaign_id",
            sa.Integer,
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "influencer_id",
            sa.Integer,
            sa.ForeignKey("influencers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            sa.Integer,
            sa.ForeignKey("templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("body_html", sa.Text, nullable=False, server_default=""),
        sa.Column("angle_used", sa.String(length=64), nullable=True),
        sa.Column("generation_model", sa.String(length=64), nullable=True),
        sa.Column("generation_prompt_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "generating", "ready", "edited",
                "failed", "sending", "sent", "cancelled",
                name="emaildraftstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("edited_by_user", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "email_id",
            sa.Integer,
            sa.ForeignKey("emails.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime, nullable=True),
        sa.Column("sent_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint(
            "campaign_id", "influencer_id",
            name="uq_email_drafts_campaign_influencer",
        ),
    )
    op.create_index(
        "ix_email_drafts_campaign_id", "email_drafts", ["campaign_id"],
    )
    op.create_index(
        "ix_email_drafts_influencer_id", "email_drafts", ["influencer_id"],
    )
    op.create_index(
        "ix_email_drafts_status", "email_drafts", ["status"],
    )
    op.create_index(
        "ix_email_drafts_email_id", "email_drafts", ["email_id"],
    )
    op.create_index(
        "ix_email_drafts_generation_prompt_hash",
        "email_drafts",
        ["generation_prompt_hash"],
    )
    op.create_index(
        "ix_email_drafts_campaign_status",
        "email_drafts",
        ["campaign_id", "status"],
    )

    # 2. campaigns.use_drafts flag
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(
            sa.Column(
                "use_drafts",
                sa.Boolean,
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # 3. emails.draft_id FK — SQLite batch_alter_table requires named
    # constraints, so we name the FK explicitly.
    with op.batch_alter_table("emails") as batch:
        batch.add_column(
            sa.Column(
                "draft_id",
                sa.Integer,
                sa.ForeignKey(
                    "email_drafts.id",
                    ondelete="SET NULL",
                    name="fk_emails_draft_id",
                ),
                nullable=True,
            ),
        )
        batch.create_index("ix_emails_draft_id", ["draft_id"])


def downgrade() -> None:
    with op.batch_alter_table("emails") as batch:
        batch.drop_index("ix_emails_draft_id")
        batch.drop_column("draft_id")
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_column("use_drafts")
    op.drop_index("ix_email_drafts_campaign_status", table_name="email_drafts")
    op.drop_index("ix_email_drafts_generation_prompt_hash", table_name="email_drafts")
    op.drop_index("ix_email_drafts_email_id", table_name="email_drafts")
    op.drop_index("ix_email_drafts_status", table_name="email_drafts")
    op.drop_index("ix_email_drafts_influencer_id", table_name="email_drafts")
    op.drop_index("ix_email_drafts_campaign_id", table_name="email_drafts")
    op.drop_table("email_drafts")
    sa.Enum(name="emaildraftstatus").drop(op.get_bind(), checkfirst=True)
