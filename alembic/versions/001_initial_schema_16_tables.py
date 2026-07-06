"""Initial schema with all 16 tables.

Revision ID: 001_initial
Revises:
Create Date: 2024-01-01 00:00:00.000000

Creates the full database schema for GKIM Opportunity Finder v2:
- prospects, enrichment_records, contacts, intent_signals, account_scores
- pipeline_records, sequences, sequence_steps, variants, touchpoints
- prospect_enrollments, scoring_configs, llm_cache
- integration_health, source_health, funnel_snapshots

Includes all indexes, constraints, CHECK constraints, and foreign keys
as specified in the design document.

Requirements: 12.1
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. prospects - Core prospect table
    # =========================================================================
    op.create_table(
        "prospects",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company_name", sa.String(500), nullable=False),
        sa.Column("company_domain", sa.String(255), nullable=True),
        sa.Column("normalized_name", sa.String(500), nullable=False),
        sa.Column("beneficiary_id", sa.String(50), nullable=False),
        sa.Column("opportunity_type_id", sa.String(50), nullable=False),
        sa.Column("discovery_source", sa.String(50), nullable=False),
        sa.Column("source_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "first_discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
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
    )
    op.create_index(
        "idx_prospects_domain_beneficiary",
        "prospects",
        ["company_domain", "beneficiary_id"],
        unique=True,
        postgresql_where=sa.text("company_domain IS NOT NULL"),
    )
    op.create_index("idx_prospects_normalized_name", "prospects", ["normalized_name"])
    op.create_index("idx_prospects_beneficiary", "prospects", ["beneficiary_id"])
    op.create_index("idx_prospects_created_at", "prospects", ["created_at"])

    # =========================================================================
    # 2. enrichment_records - Apollo enrichment data
    # =========================================================================
    op.create_table(
        "enrichment_records",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("prospect_id", sa.UUID(), nullable=False),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("revenue_range", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(200), nullable=True),
        sa.Column(
            "tech_stack",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
        sa.Column("funding_stage", sa.String(100), nullable=True),
        sa.Column("hq_city", sa.String(200), nullable=True),
        sa.Column("hq_country", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"]),
        sa.UniqueConstraint("prospect_id"),
    )
    op.create_index("idx_enrichment_records_status", "enrichment_records", ["status"])
    op.create_index("idx_enrichment_records_prospect", "enrichment_records", ["prospect_id"])

    # =========================================================================
    # 3. contacts - Contacts discovered via Apollo
    # =========================================================================
    op.create_table(
        "contacts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("prospect_id", sa.UUID(), nullable=False),
        sa.Column("full_name", sa.String(300), nullable=False),
        sa.Column("job_title", sa.String(300), nullable=False),
        sa.Column("email", sa.String(300), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email_verification", sa.String(20), nullable=True),
        sa.Column("seniority_level", sa.String(20), nullable=True),
        sa.Column("search_status", sa.String(30), server_default=sa.text("'standard'"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"]),
        sa.CheckConstraint(
            "email IS NOT NULL OR linkedin_url IS NOT NULL",
            name="contacts_require_contact_method",
        ),
    )
    op.create_index("idx_contacts_prospect", "contacts", ["prospect_id"])

    # =========================================================================
    # 4. intent_signals - Intent signals from Apollo
    # =========================================================================
    op.create_table(
        "intent_signals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("prospect_id", sa.UUID(), nullable=False),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("strength", sa.String(20), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"]),
    )
    op.create_index("idx_intent_signals_prospect", "intent_signals", ["prospect_id"])
    op.create_index(
        "idx_intent_signals_strength", "intent_signals", ["strength", "detected_at"]
    )

    # =========================================================================
    # 5. account_scores - Composite account scores
    # =========================================================================
    op.create_table(
        "account_scores",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("prospect_id", sa.UUID(), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(10), nullable=False),
        sa.Column(
            "factor_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "missing_factors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
        sa.Column("is_partial", sa.Boolean(), server_default="false", nullable=True),
        sa.Column("multi_source_bonus", sa.Integer(), server_default="0", nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"]),
        sa.UniqueConstraint("prospect_id"),
        sa.CheckConstraint("total_score BETWEEN 0 AND 100", name="account_scores_valid_score"),
    )
    op.create_index("idx_account_scores_tier", "account_scores", ["tier"])
    op.create_index(
        "idx_account_scores_total", "account_scores", ["total_score"], postgresql_using="btree"
    )

    # =========================================================================
    # 6. pipeline_records - Pipeline state machine per opportunity type
    # =========================================================================
    op.create_table(
        "pipeline_records",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("prospect_id", sa.UUID(), nullable=False),
        sa.Column("opportunity_type_id", sa.String(50), nullable=False),
        sa.Column("beneficiary_id", sa.String(50), nullable=False),
        sa.Column("current_status", sa.String(100), nullable=False),
        sa.Column("previous_status", sa.String(100), nullable=True),
        sa.Column("discovery_source", sa.String(50), nullable=True),
        sa.Column("first_response_source", sa.String(100), nullable=True),
        sa.Column("outcome_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_terminal", sa.Boolean(), server_default="false", nullable=False),
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
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"]),
    )
    op.create_index(
        "idx_pipeline_status", "pipeline_records", ["current_status", "opportunity_type_id"]
    )
    op.create_index("idx_pipeline_beneficiary", "pipeline_records", ["beneficiary_id"])
    op.create_index(
        "idx_pipeline_non_terminal",
        "pipeline_records",
        ["is_terminal"],
        postgresql_where=sa.text("is_terminal = FALSE"),
    )
    op.create_index("idx_pipeline_prospect", "pipeline_records", ["prospect_id"])

    # =========================================================================
    # 7. sequences - Lemlist outreach sequences
    # =========================================================================
    op.create_table(
        "sequences",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("beneficiary_id", sa.String(50), nullable=False),
        sa.Column("sync_status", sa.String(20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("lemlist_campaign_id", sa.String(100), nullable=True),
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
    )
    op.create_index("idx_sequences_beneficiary", "sequences", ["beneficiary_id"])

    # =========================================================================
    # 8. sequence_steps - Steps within sequences
    # =========================================================================
    op.create_table(
        "sequence_steps",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("sequence_id", sa.UUID(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("delay_days", sa.Integer(), nullable=False),
        sa.Column("content_template", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["sequence_id"], ["sequences.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("sequence_id", "step_order", name="uq_sequence_step_order"),
        sa.CheckConstraint("step_order BETWEEN 1 AND 10", name="sequence_steps_valid_order"),
        sa.CheckConstraint("delay_days BETWEEN 1 AND 30", name="sequence_steps_valid_delay"),
        sa.CheckConstraint(
            "length(content_template) <= 5000", name="sequence_steps_template_length"
        ),
    )
    op.create_index("idx_sequence_steps_sequence", "sequence_steps", ["sequence_id"])

    # =========================================================================
    # 9. variants - A/B test variants
    # =========================================================================
    op.create_table(
        "variants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("variant_label", sa.String(1), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sends", sa.Integer(), server_default="0", nullable=False),
        sa.Column("opens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("replies", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_winner", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_promoted", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["step_id"], ["sequence_steps.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("step_id", "variant_label", name="uq_step_variant_label"),
        sa.CheckConstraint(
            "variant_label IN ('A','B','C','D')", name="variants_valid_label"
        ),
    )
    op.create_index("idx_variants_step", "variants", ["step_id"])

    # =========================================================================
    # 10. touchpoints - Individual interaction records
    # =========================================================================
    op.create_table(
        "touchpoints",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pipeline_record_id", sa.UUID(), nullable=False),
        sa.Column("sequence_id", sa.UUID(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_record_id"], ["pipeline_records.id"]),
        sa.ForeignKeyConstraint(["sequence_id"], ["sequences.id"]),
        sa.ForeignKeyConstraint(["variant_id"], ["variants.id"]),
    )
    op.create_index("idx_touchpoints_pipeline", "touchpoints", ["pipeline_record_id"])
    op.create_index("idx_touchpoints_status", "touchpoints", ["status"])
    op.create_index("idx_touchpoints_sequence", "touchpoints", ["sequence_id"])

    # =========================================================================
    # 11. prospect_enrollments - Prospect-to-sequence mapping
    # =========================================================================
    op.create_table(
        "prospect_enrollments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("prospect_id", sa.UUID(), nullable=False),
        sa.Column("sequence_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(30), server_default=sa.text("'active'"), nullable=False),
        sa.Column("followup_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"]),
        sa.ForeignKeyConstraint(["sequence_id"], ["sequences.id"]),
        sa.UniqueConstraint("prospect_id", "sequence_id", name="uq_prospect_sequence"),
    )
    op.create_index("idx_enrollments_prospect", "prospect_enrollments", ["prospect_id"])
    op.create_index("idx_enrollments_sequence", "prospect_enrollments", ["sequence_id"])
    op.create_index("idx_enrollments_status", "prospect_enrollments", ["status"])

    # =========================================================================
    # 12. scoring_configs - Scoring weight configurations
    # =========================================================================
    op.create_table(
        "scoring_configs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("firmographic_weight", sa.Integer(), server_default="30", nullable=False),
        sa.Column("technographic_weight", sa.Integer(), server_default="25", nullable=False),
        sa.Column("intent_weight", sa.Integer(), server_default="20", nullable=False),
        sa.Column("llm_relevance_weight", sa.Integer(), server_default="15", nullable=False),
        sa.Column("historical_weight", sa.Integer(), server_default="10", nullable=False),
        sa.Column("min_score_threshold", sa.Integer(), server_default="25", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "firmographic_weight BETWEEN 0 AND 100",
            name="scoring_configs_firmographic_range",
        ),
        sa.CheckConstraint(
            "technographic_weight BETWEEN 0 AND 100",
            name="scoring_configs_technographic_range",
        ),
        sa.CheckConstraint(
            "intent_weight BETWEEN 0 AND 100",
            name="scoring_configs_intent_range",
        ),
        sa.CheckConstraint(
            "llm_relevance_weight BETWEEN 0 AND 100",
            name="scoring_configs_llm_relevance_range",
        ),
        sa.CheckConstraint(
            "historical_weight BETWEEN 0 AND 100",
            name="scoring_configs_historical_range",
        ),
        sa.CheckConstraint(
            "min_score_threshold BETWEEN 0 AND 100",
            name="scoring_configs_threshold_range",
        ),
        sa.CheckConstraint(
            "firmographic_weight + technographic_weight + intent_weight + "
            "llm_relevance_weight + historical_weight = 100",
            name="weights_sum_100",
        ),
    )

    # =========================================================================
    # 13. llm_cache - 7-day LLM response cache
    # =========================================================================
    op.create_table(
        "llm_cache",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("prospect_id", sa.UUID(), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("relevance_score", sa.Integer(), nullable=False),
        sa.Column("reasoning", sa.String(500), nullable=True),
        sa.Column("context_status", sa.String(20), server_default=sa.text("'full'"), nullable=True),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prospect_id", "profile_hash", name="uq_llm_cache_prospect_hash"),
        sa.CheckConstraint(
            "relevance_score BETWEEN 0 AND 100", name="llm_cache_valid_score"
        ),
    )
    op.create_index("idx_llm_cache_prospect", "llm_cache", ["prospect_id"])
    op.create_index("idx_llm_cache_expires", "llm_cache", ["expires_at"])

    # =========================================================================
    # 14. integration_health - API status tracking
    # =========================================================================
    op.create_table(
        "integration_health",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("integration_name", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'disconnected'"), nullable=False),
        sa.Column("usage_current", sa.Integer(), server_default="0", nullable=True),
        sa.Column("usage_limit", sa.Integer(), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("integration_name"),
    )

    # =========================================================================
    # 15. source_health - Discovery source status
    # =========================================================================
    op.create_table(
        "source_health",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), server_default=sa.text("'active'"), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type"),
    )

    # =========================================================================
    # 16. funnel_snapshots - Daily analytics snapshots
    # =========================================================================
    op.create_table(
        "funnel_snapshots",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("opportunity_type_id", sa.String(50), nullable=False),
        sa.Column("beneficiary_id", sa.String(50), nullable=False),
        sa.Column("stage_name", sa.String(100), nullable=False),
        sa.Column("entered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("exited_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("avg_days_in_stage", sa.Numeric(5, 1), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_date",
            "opportunity_type_id",
            "beneficiary_id",
            "stage_name",
            name="uq_funnel_snapshot",
        ),
    )
    op.create_index("idx_funnel_snapshots_date", "funnel_snapshots", ["snapshot_date"])
    op.create_index(
        "idx_funnel_snapshots_opp_type", "funnel_snapshots", ["opportunity_type_id"]
    )


def downgrade() -> None:
    op.drop_table("funnel_snapshots")
    op.drop_table("source_health")
    op.drop_table("integration_health")
    op.drop_table("llm_cache")
    op.drop_table("scoring_configs")
    op.drop_table("prospect_enrollments")
    op.drop_table("touchpoints")
    op.drop_table("variants")
    op.drop_table("sequence_steps")
    op.drop_table("sequences")
    op.drop_table("pipeline_records")
    op.drop_table("account_scores")
    op.drop_table("intent_signals")
    op.drop_table("contacts")
    op.drop_table("enrichment_records")
    op.drop_table("prospects")
