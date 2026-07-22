"""Interview prep tables.

Revision ID: 009_interview_prep
Revises: 008_profile_enrichment
Create Date: 2024-03-01 00:00:00.000000

Creates the schema for Interview Prep Technique:
- interview_prep_packs: structured interview prep content per pipeline record
- interview_prep_history: generation history for regeneration tracking

Includes all indexes, CHECK constraints, and foreign keys.

Requirements: 2.1, 3.2
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "009_interview_prep"
down_revision = "008_profile_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. interview_prep_packs - Structured interview prep content per record
    # =========================================================================
    op.create_table(
        "interview_prep_packs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pipeline_record_id", sa.UUID(), nullable=False),
        sa.Column("beneficiary_id", sa.String(50), nullable=False),
        sa.Column("opportunity_type_id", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default="generating", nullable=False),
        sa.Column(
            "likely_questions",
            postgresql.JSONB(astext_type=sa.String()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "star_talking_points",
            postgresql.JSONB(astext_type=sa.String()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("company_briefing", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "questions_to_ask",
            postgresql.JSONB(astext_type=sa.String()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "omission_notes",
            postgresql.JSONB(astext_type=sa.String()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "grounding_flags",
            postgresql.JSONB(astext_type=sa.String()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("generation_duration_ms", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("superseded_by", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["pipeline_record_id"],
            ["pipeline_records.id"],
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"],
            ["interview_prep_packs.id"],
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'grounding', 'ready', 'ready_with_flags', 'failed')",
            name="interview_prep_packs_valid_status",
        ),
    )
    op.create_index(
        "idx_interview_prep_record",
        "interview_prep_packs",
        ["pipeline_record_id"],
    )
    op.create_index(
        "idx_interview_prep_status",
        "interview_prep_packs",
        ["status"],
    )
    op.create_index(
        "idx_interview_prep_beneficiary",
        "interview_prep_packs",
        ["beneficiary_id"],
    )

    # =========================================================================
    # 2. interview_prep_history - Generation history for regeneration tracking
    # =========================================================================
    op.create_table(
        "interview_prep_history",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pack_id", sa.UUID(), nullable=False),
        sa.Column("trigger_reason", sa.String(30), nullable=False),
        sa.Column("generation_context_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["pack_id"],
            ["interview_prep_packs.id"],
        ),
        sa.CheckConstraint(
            "trigger_reason IN ('state_entry', 'manual_regenerate', 'profile_update')",
            name="interview_prep_history_valid_trigger_reason",
        ),
    )
    op.create_index(
        "idx_interview_prep_history_pack",
        "interview_prep_history",
        ["pack_id"],
    )


def downgrade() -> None:
    op.drop_table("interview_prep_history")
    op.drop_table("interview_prep_packs")
