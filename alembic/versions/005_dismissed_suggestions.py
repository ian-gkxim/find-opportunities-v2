"""Dismissed suggestions table for one-time dashboard suggestions.

Revision ID: 005_suggestions
Revises: 004_voice
Create Date: 2024-02-20 00:00:00.000000

Creates a simple table to track dismissed one-time suggestions per beneficiary.
Used by the Dashboard Understand stage to show non-blocking suggestions
(e.g., "Create a Voice Asset") that can be permanently dismissed.

Requirements: 1.3
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "005_suggestions"
down_revision = "004_voice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dismissed_suggestions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("beneficiary_id", sa.String(50), nullable=False),
        sa.Column("suggestion_key", sa.String(100), nullable=False),
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "beneficiary_id", "suggestion_key", name="uq_dismissed_suggestions_beneficiary_key"
        ),
    )
    op.create_index(
        "idx_dismissed_suggestions_beneficiary",
        "dismissed_suggestions",
        ["beneficiary_id"],
    )


def downgrade() -> None:
    op.drop_table("dismissed_suggestions")
