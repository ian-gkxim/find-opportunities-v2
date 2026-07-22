"""Voice assets table and pipeline_records voice_applied column.

Revision ID: 004_voice
Revises: 003_grounding
Create Date: 2024-02-15 00:00:00.000000

Creates the voice assets schema for Sender Voice Assets (P3):
- voice_assets: per-beneficiary voice definitions (writing_style, behavioral_profile, brand_voice)
- Adds voice_applied boolean column to pipeline_records for A/B observability

Includes indexes for beneficiary lookup, asset type filtering, and partial index
for active voice assets.

Requirements: 1.1, 4.1
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "004_voice"
down_revision = "003_grounding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. voice_assets - Per-beneficiary voice definitions
    # =========================================================================
    op.create_table(
        "voice_assets",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("beneficiary_id", sa.String(50), nullable=False),
        sa.Column("asset_type", sa.String(30), nullable=False),
        sa.Column("register", sa.String(30), nullable=False),
        sa.Column("sentence_length", sa.String(20), nullable=False),
        sa.Column("first_person_usage", sa.String(20), nullable=False),
        sa.Column(
            "vocabulary_prefer",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "vocabulary_avoid",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "exemplar_passages",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        # Behavioral profile fields (NULL for non-behavioral_profile types)
        sa.Column("interpersonal_style", sa.String(50), nullable=True),
        sa.Column(
            "communication_traits",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "avoid_impressions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        # Brand voice fields (NULL for non-brand_voice types)
        sa.Column(
            "brand_personality",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("tagline_style", sa.String(200), nullable=True),
        # Metadata
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
        sa.UniqueConstraint("beneficiary_id", "asset_type", name="uq_voice_assets_beneficiary_type"),
    )
    # Index for beneficiary lookups
    op.create_index(
        "idx_voice_assets_beneficiary",
        "voice_assets",
        ["beneficiary_id"],
    )
    # Index for asset type filtering
    op.create_index(
        "idx_voice_assets_type",
        "voice_assets",
        ["asset_type"],
    )
    # Partial index for active voice assets
    op.create_index(
        "idx_voice_assets_active",
        "voice_assets",
        ["beneficiary_id", "is_active"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # =========================================================================
    # 2. pipeline_records - Add voice_applied column for A/B observability
    # =========================================================================
    op.add_column(
        "pipeline_records",
        sa.Column("voice_applied", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(
        "idx_pipeline_records_voice",
        "pipeline_records",
        ["voice_applied"],
    )


def downgrade() -> None:
    op.drop_index("idx_pipeline_records_voice", table_name="pipeline_records")
    op.drop_column("pipeline_records", "voice_applied")
    op.drop_table("voice_assets")
