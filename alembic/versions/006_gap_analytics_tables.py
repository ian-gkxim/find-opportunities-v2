"""Capability gap analytics tables.

Revision ID: 006_gap_analytics
Revises: 005_suggestions
Create Date: 2024-03-01 00:00:00.000000

Creates the schema for Capability Gap Analytics:
- canonical_capabilities: registry of normalized capability names
- capability_synonyms: alias-to-canonical mappings for normalization
- opportunity_extractions: cached LLM extraction results per opportunity
- extracted_capabilities: individual capabilities extracted from opportunities
- beneficiary_capabilities: what each Consultant/team can do
- gap_heatmaps: gap heatmap reports per Beneficiary per cycle
- gap_heatmap_entries: individual ranked gap entries within a heatmap
- gap_extraction_queue: carry-forward queue for unprocessed opportunities
- gap_analysis_config: configuration parameters for gap analysis

Includes all indexes, CHECK constraints, UNIQUE constraints, and foreign keys.

Requirements: 1.1, 1.2, 2.1, 2.2
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "006_gap_analytics"
down_revision = "005_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. canonical_capabilities - Registry of normalized capability names
    # =========================================================================
    op.create_table(
        "canonical_capabilities",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("canonical_name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_name", name="uq_canonical_capabilities_name"),
    )
    op.create_index(
        "idx_canonical_capabilities_name",
        "canonical_capabilities",
        ["canonical_name"],
    )
    op.create_index(
        "idx_canonical_capabilities_category",
        "canonical_capabilities",
        ["category"],
    )

    # =========================================================================
    # 2. capability_synonyms - Alias-to-canonical mappings for normalization
    # =========================================================================
    op.create_table(
        "capability_synonyms",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("alias", sa.String(200), nullable=False),
        sa.Column("canonical_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias", name="uq_capability_synonyms_alias"),
        sa.ForeignKeyConstraint(
            ["canonical_id"],
            ["canonical_capabilities.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_capability_synonyms_alias",
        "capability_synonyms",
        ["alias"],
    )

    # =========================================================================
    # 3. opportunity_extractions - Cached LLM extraction results per opportunity
    # =========================================================================
    op.create_table(
        "opportunity_extractions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pipeline_record_id", sa.UUID(), nullable=False),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("extraction_model", sa.String(100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pipeline_record_id", name="uq_opportunity_extractions_pipeline_record"
        ),
        sa.ForeignKeyConstraint(["pipeline_record_id"], ["pipeline_records.id"]),
    )
    op.create_index(
        "idx_opportunity_extractions_record",
        "opportunity_extractions",
        ["pipeline_record_id"],
    )

    # =========================================================================
    # 4. extracted_capabilities - Individual capabilities from each opportunity
    # =========================================================================
    op.create_table(
        "extracted_capabilities",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("extraction_id", sa.UUID(), nullable=False),
        sa.Column("canonical_id", sa.UUID(), nullable=False),
        sa.Column("raw_name", sa.String(200), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["opportunity_extractions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_id"],
            ["canonical_capabilities.id"],
        ),
        sa.CheckConstraint(
            "level IN ('required', 'preferred')",
            name="extracted_capabilities_valid_level",
        ),
    )
    op.create_index(
        "idx_extracted_capabilities_extraction",
        "extracted_capabilities",
        ["extraction_id"],
    )
    op.create_index(
        "idx_extracted_capabilities_canonical",
        "extracted_capabilities",
        ["canonical_id"],
    )
    op.create_index(
        "idx_extracted_capabilities_level",
        "extracted_capabilities",
        ["level"],
    )

    # =========================================================================
    # 5. beneficiary_capabilities - What each Consultant/team can do
    # =========================================================================
    op.create_table(
        "beneficiary_capabilities",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("beneficiary_id", sa.String(50), nullable=False),
        sa.Column("canonical_id", sa.UUID(), nullable=False),
        sa.Column(
            "proficiency_level",
            sa.String(20),
            server_default="senior",
            nullable=False,
        ),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "beneficiary_id", "canonical_id", name="uq_beneficiary_capabilities_ben_cap"
        ),
        sa.ForeignKeyConstraint(
            ["canonical_id"],
            ["canonical_capabilities.id"],
        ),
        sa.CheckConstraint(
            "proficiency_level IN ('senior', 'mid', 'junior')",
            name="beneficiary_capabilities_valid_proficiency",
        ),
    )
    op.create_index(
        "idx_beneficiary_capabilities_ben",
        "beneficiary_capabilities",
        ["beneficiary_id"],
    )

    # =========================================================================
    # 6. gap_heatmaps - Gap heatmap reports per Beneficiary per cycle
    # =========================================================================
    op.create_table(
        "gap_heatmaps",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("beneficiary_id", sa.String(50), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "analysis_window_days", sa.Integer(), server_default="90", nullable=False
        ),
        sa.Column(
            "total_opportunities_analyzed",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_blocked_value",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("previous_heatmap_id", sa.UUID(), nullable=True),
        sa.Column("opportunity_type_filter", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["previous_heatmap_id"],
            ["gap_heatmaps.id"],
        ),
    )
    op.create_index(
        "idx_gap_heatmaps_beneficiary",
        "gap_heatmaps",
        ["beneficiary_id", sa.text("generated_at DESC")],
    )
    op.create_index(
        "idx_gap_heatmaps_generated",
        "gap_heatmaps",
        [sa.text("generated_at DESC")],
    )

    # =========================================================================
    # 7. gap_heatmap_entries - Individual ranked gap entries within a heatmap
    # =========================================================================
    op.create_table(
        "gap_heatmap_entries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("heatmap_id", sa.UUID(), nullable=False),
        sa.Column("canonical_id", sa.UUID(), nullable=False),
        sa.Column("classification", sa.String(10), nullable=False),
        sa.Column(
            "opportunity_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "blocked_pipeline_value",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "is_single_blocker",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "weighted_rank_score",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("trend", sa.String(20), nullable=True),
        sa.Column("rank_position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "heatmap_id", "canonical_id", name="uq_gap_heatmap_entries_heatmap_cap"
        ),
        sa.ForeignKeyConstraint(
            ["heatmap_id"],
            ["gap_heatmaps.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_id"],
            ["canonical_capabilities.id"],
        ),
        sa.CheckConstraint(
            "classification IN ('hard', 'soft')",
            name="gap_heatmap_entries_valid_classification",
        ),
        sa.CheckConstraint(
            "trend IN ('new', 'growing', 'shrinking', 'resolved')",
            name="gap_heatmap_entries_valid_trend",
        ),
    )
    op.create_index(
        "idx_gap_entries_heatmap",
        "gap_heatmap_entries",
        ["heatmap_id", "rank_position"],
    )
    op.create_index(
        "idx_gap_entries_canonical",
        "gap_heatmap_entries",
        ["canonical_id"],
    )
    op.create_index(
        "idx_gap_entries_blocker",
        "gap_heatmap_entries",
        ["is_single_blocker"],
        postgresql_where=sa.text("is_single_blocker = TRUE"),
    )

    # =========================================================================
    # 8. gap_extraction_queue - Carry-forward queue for unprocessed opportunities
    # =========================================================================
    op.create_table(
        "gap_extraction_queue",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pipeline_record_id", sa.UUID(), nullable=False),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "priority_score",
            sa.Numeric(10, 4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "processed", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pipeline_record_id", name="uq_gap_extraction_queue_pipeline_record"
        ),
        sa.ForeignKeyConstraint(["pipeline_record_id"], ["pipeline_records.id"]),
    )
    op.create_index(
        "idx_gap_queue_unprocessed",
        "gap_extraction_queue",
        [sa.text("priority_score DESC")],
        postgresql_where=sa.text("processed = FALSE"),
    )

    # =========================================================================
    # 9. gap_analysis_config - Configuration parameters for gap analysis
    # =========================================================================
    op.create_table(
        "gap_analysis_config",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_gap_analysis_config_key"),
    )


def downgrade() -> None:
    op.drop_table("gap_analysis_config")
    op.drop_table("gap_extraction_queue")
    op.drop_table("gap_heatmap_entries")
    op.drop_table("gap_heatmaps")
    op.drop_table("beneficiary_capabilities")
    op.drop_table("extracted_capabilities")
    op.drop_table("opportunity_extractions")
    op.drop_table("capability_synonyms")
    op.drop_table("canonical_capabilities")
