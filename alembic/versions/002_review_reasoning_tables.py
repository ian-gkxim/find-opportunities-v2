"""Review reasoning and cycle details tables.

Revision ID: 002_review
Revises: 001_initial
Create Date: 2024-01-15 00:00:00.000000

Creates the review telemetry schema for the Review Critique Loop:
- review_reasoning_logs: tracks full review process per material
- review_cycle_details: tracks individual cycle metrics within a review

Includes indexes for pipeline lookup and status filtering.

Requirements: 3.2
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "002_review"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. review_reasoning_logs - Complete review telemetry per material
    # =========================================================================
    op.create_table(
        "review_reasoning_logs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("material_id", sa.UUID(), nullable=False),
        sa.Column("pipeline_record_id", sa.UUID(), nullable=False),
        sa.Column("prepare_technique_id", sa.String(50), nullable=False),
        sa.Column("review_technique_id", sa.String(50), nullable=False),
        sa.Column("total_cycles_executed", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_cycles_configured", sa.Integer(), nullable=False),
        sa.Column("final_review_status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_record_id"], ["pipeline_records.id"]),
    )
    op.create_index(
        "idx_review_logs_pipeline", "review_reasoning_logs", ["pipeline_record_id"]
    )
    op.create_index(
        "idx_review_logs_status", "review_reasoning_logs", ["final_review_status"]
    )

    # =========================================================================
    # 2. review_cycle_details - Per-cycle metrics within a review
    # =========================================================================
    op.create_table(
        "review_cycle_details",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("reasoning_log_id", sa.UUID(), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("edits_applied", sa.Integer(), server_default="0", nullable=False),
        sa.Column("edits_skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("edits_discarded", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "narrative_findings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("quality_score_before", sa.Integer(), nullable=False),
        sa.Column("quality_score_after", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "skipped_edits_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
        sa.Column(
            "discarded_edits_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["reasoning_log_id"],
            ["review_reasoning_logs.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("reasoning_log_id", "cycle_number", name="uq_cycle_per_log"),
    )


def downgrade() -> None:
    op.drop_table("review_cycle_details")
    op.drop_table("review_reasoning_logs")
