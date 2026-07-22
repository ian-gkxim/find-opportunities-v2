"""Grounding verification tables.

Revision ID: 003_grounding
Revises: 002_review
Create Date: 2024-02-01 00:00:00.000000

Creates the grounding verification schema for Claim Grounding Verification (P2):
- grounding_reports: verification report per material
- grounding_claims: individual claims extracted from materials
- grounding_resolutions: resolution records for blocked materials
- grounding_analytics_weekly: weekly analytics aggregation per technique

Includes composite indexes for analytics queries and foreign keys for joins.

Requirements: 2.4, 3.1, 3.3, 4.2
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "003_grounding"
down_revision = "002_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. grounding_reports - Complete verification report per material
    # =========================================================================
    op.create_table(
        "grounding_reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("material_id", sa.UUID(), nullable=False),
        sa.Column("pipeline_record_id", sa.UUID(), nullable=False),
        sa.Column("prepare_technique_id", sa.String(50), nullable=False),
        sa.Column("grounding_technique_id", sa.String(50), nullable=False),
        sa.Column("total_claims", sa.Integer(), server_default="0", nullable=False),
        sa.Column("grounded_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("partially_grounded_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ungrounded_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("material_grounding_status", sa.String(30), nullable=False),
        sa.Column("extraction_duration_ms", sa.Integer(), nullable=False),
        sa.Column("verification_duration_ms", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_record_id"], ["pipeline_records.id"]),
        sa.CheckConstraint(
            "material_grounding_status IN ('grounding_verified', 'grounding_blocked', 'grounding_unverified')",
            name="grounding_reports_valid_status",
        ),
    )
    # Composite index for analytics queries (requirement 4.2)
    op.create_index(
        "idx_grounding_reports_technique_created",
        "grounding_reports",
        ["prepare_technique_id", "created_at"],
    )
    # Index for pipeline record lookups
    op.create_index(
        "idx_grounding_reports_pipeline",
        "grounding_reports",
        ["pipeline_record_id"],
    )

    # =========================================================================
    # 2. grounding_claims - Individual claims extracted from materials
    # =========================================================================
    op.create_table(
        "grounding_claims",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("grounding_report_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("source_span", sa.Text(), nullable=False),
        sa.Column("source_span_start", sa.Integer(), nullable=False),
        sa.Column("source_span_end", sa.Integer(), nullable=False),
        sa.Column("grounding_status", sa.String(20), nullable=False),
        sa.Column("is_prospect_side", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("source_asset_type", sa.String(50), nullable=True),
        sa.Column("source_asset_id", sa.String(100), nullable=True),
        sa.Column("source_passage", sa.Text(), nullable=True),
        sa.Column("discrepancy", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["grounding_report_id"],
            ["grounding_reports.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "category IN ('skill_technology', 'achievement_outcome', 'quantified_metric', "
            "'credential_certification', 'named_client_employer', 'experience_duration')",
            name="grounding_claims_valid_category",
        ),
        sa.CheckConstraint(
            "grounding_status IN ('grounded', 'partially_grounded', 'ungrounded')",
            name="grounding_claims_valid_status",
        ),
    )
    # Index for joins on grounding_report_id
    op.create_index(
        "idx_grounding_claims_report",
        "grounding_claims",
        ["grounding_report_id"],
    )

    # =========================================================================
    # 3. grounding_resolutions - Resolution records for blocked materials
    # =========================================================================
    op.create_table(
        "grounding_resolutions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("grounding_report_id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("resolution_path", sa.String(20), nullable=False),
        sa.Column("resolved_by", sa.String(100), nullable=False),
        sa.Column(
            "resolution_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("re_verification_status", sa.String(20), nullable=True),
        sa.Column("re_verification_duration_ms", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["grounding_report_id"],
            ["grounding_reports.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["grounding_claims.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "resolution_path IN ('regenerate', 'manual_edit', 'confirm_and_add')",
            name="grounding_resolutions_valid_path",
        ),
    )
    op.create_index(
        "idx_grounding_resolutions_report",
        "grounding_resolutions",
        ["grounding_report_id"],
    )

    # =========================================================================
    # 4. grounding_analytics_weekly - Weekly analytics per technique
    # =========================================================================
    op.create_table(
        "grounding_analytics_weekly",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("prepare_technique_id", sa.String(50), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("total_claims_extracted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("grounded_claims", sa.Integer(), server_default="0", nullable=False),
        sa.Column("partially_grounded_claims", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ungrounded_claims", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ungrounded_rate", sa.Numeric(5, 4), server_default="0", nullable=False),
        sa.Column("materials_verified", sa.Integer(), server_default="0", nullable=False),
        sa.Column("materials_blocked", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "prepare_technique_id",
            "week_start",
            name="uq_analytics_technique_week",
        ),
    )
    op.create_index(
        "idx_grounding_analytics_technique",
        "grounding_analytics_weekly",
        ["prepare_technique_id"],
    )


def downgrade() -> None:
    op.drop_table("grounding_analytics_weekly")
    op.drop_table("grounding_resolutions")
    op.drop_table("grounding_claims")
    op.drop_table("grounding_reports")
