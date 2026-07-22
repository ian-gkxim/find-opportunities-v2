"""Profile enrichment tables for Internal Profile Enrichment.

Revision ID: 008_profile_enrichment
Revises: 007_validation_reports
Create Date: 2024-03-20 00:00:00.000000

Creates the schema for Internal Profile Enrichment:
- public_sources: Consultant-configured public source URLs for scanning
- competency_proposals: LLM-extracted competency candidates awaiting review
- profile_enrichment_audit_log: immutable audit trail for profile merges
- enrichment_scan_history: records of each enrichment scan cycle

Includes all indexes, CHECK constraints, UNIQUE constraints, and foreign keys.

Requirements: 1.1, 1.2, 1.4, 2.1, 2.3, 3.2, 3.4
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "008_profile_enrichment"
down_revision = "007_validation_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. public_sources - Consultant-configured public source URLs for scanning
    # =========================================================================
    op.create_table(
        "public_sources",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("consultant_id", sa.String(50), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column(
            "scan_interval_days", sa.Integer(), server_default="30", nullable=False
        ),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.UniqueConstraint("consultant_id", "url", name="uq_public_sources_consultant_url"),
        sa.CheckConstraint(
            "scan_interval_days >= 1 AND scan_interval_days <= 365",
            name="public_sources_valid_scan_interval",
        ),
    )
    op.create_index(
        "idx_public_sources_consultant",
        "public_sources",
        ["consultant_id"],
    )

    # =========================================================================
    # 2. competency_proposals - LLM-extracted competency candidates
    # =========================================================================
    op.create_table(
        "competency_proposals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("consultant_id", sa.String(50), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("raw_evidence", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(20), server_default="'pending'", nullable=False
        ),
        sa.Column("merged_content", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["source_id"], ["public_sources.id"]),
        sa.CheckConstraint(
            "confidence IN ('strong', 'inferred')",
            name="competency_proposals_valid_confidence",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name="competency_proposals_valid_status",
        ),
    )
    op.create_index(
        "idx_proposals_consultant_status",
        "competency_proposals",
        ["consultant_id", "status"],
    )
    op.create_index(
        "idx_proposals_consultant_name_category",
        "competency_proposals",
        ["consultant_id", sa.text("lower(name)"), "category"],
    )

    # =========================================================================
    # 3. profile_enrichment_audit_log - Immutable audit trail for merges
    # =========================================================================
    op.create_table(
        "profile_enrichment_audit_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("consultant_id", sa.String(50), nullable=False),
        sa.Column("proposal_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("added_content", sa.Text(), nullable=True),
        sa.Column("evidence_source_url", sa.Text(), nullable=True),
        sa.Column("profile_section", sa.String(100), nullable=True),
        sa.Column("edited", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["proposal_id"], ["competency_proposals.id"]),
        sa.CheckConstraint(
            "action IN ('accept', 'accept_with_edit', 'reject')",
            name="audit_log_valid_action",
        ),
    )
    op.create_index(
        "idx_audit_log_consultant",
        "profile_enrichment_audit_log",
        ["consultant_id"],
    )
    op.create_index(
        "idx_audit_log_proposal",
        "profile_enrichment_audit_log",
        ["proposal_id"],
    )

    # =========================================================================
    # 4. enrichment_scan_history - Records of each enrichment scan cycle
    # =========================================================================
    op.create_table(
        "enrichment_scan_history",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("consultant_id", sa.String(50), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column(
            "scan_type", sa.String(20), nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(20), server_default="'running'", nullable=False
        ),
        sa.Column(
            "proposals_generated", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_id"], ["public_sources.id"]),
        sa.CheckConstraint(
            "scan_type IN ('scheduled', 'on_demand')",
            name="scan_history_valid_scan_type",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="scan_history_valid_status",
        ),
    )
    op.create_index(
        "idx_scan_history_consultant",
        "enrichment_scan_history",
        ["consultant_id", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("enrichment_scan_history")
    op.drop_table("profile_enrichment_audit_log")
    op.drop_table("competency_proposals")
    op.drop_table("public_sources")
