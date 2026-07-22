"""Validation reports table for Outbound Validation Gate.

Revision ID: 007_validation_reports
Revises: 006_gap_analytics
Create Date: 2024-03-15 00:00:00.000000

Creates the schema for the Outbound Validation Gate:
- validation_reports: stores a Validation_Report for every send attempt,
  linked to the pipeline record, with rule results in JSONB

Includes indexes:
- idx_validation_reports_pipeline on pipeline_record_id (FK lookup)
- idx_validation_reports_created on created_at DESC (recent reports)
- idx_validation_reports_failed partial index on passed WHERE passed = FALSE

Requirements: 1.4
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "007_validation_reports"
down_revision = "006_gap_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # validation_reports - Stores a Validation_Report for every send attempt
    # =========================================================================
    op.create_table(
        "validation_reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pipeline_record_id", sa.UUID(), nullable=False),
        sa.Column("outreach_technique", sa.String(50), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column(
            "has_warnings", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("total_execution_ms", sa.Float(), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_record_id"], ["pipeline_records.id"]),
    )

    # Index for FK lookups on pipeline_record_id
    op.create_index(
        "idx_validation_reports_pipeline",
        "validation_reports",
        ["pipeline_record_id"],
    )

    # Index for querying recent reports by creation time
    op.create_index(
        "idx_validation_reports_created",
        "validation_reports",
        [sa.text("created_at DESC")],
    )

    # Partial index for quickly finding failed validations
    op.create_index(
        "idx_validation_reports_failed",
        "validation_reports",
        ["passed"],
        postgresql_where=sa.text("passed = FALSE"),
    )


def downgrade() -> None:
    op.drop_table("validation_reports")
