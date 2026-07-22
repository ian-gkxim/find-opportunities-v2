"""Gap Analytics ORM models.

Models for capability gap analysis: canonical capabilities, synonyms,
opportunity extractions, beneficiary capabilities, gap heatmaps,
extraction queue, and analysis configuration.

Requirements: 1.1, 1.2, 2.1, 2.2, 3.1
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.pipeline_record import PipelineRecord


class CanonicalCapability(Base):
    """Registry of normalized capability names."""

    __tablename__ = "canonical_capabilities"
    __table_args__ = (
        UniqueConstraint("canonical_name", name="uq_canonical_capabilities_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    synonyms: Mapped[list["CapabilitySynonym"]] = relationship(
        "CapabilitySynonym", back_populates="canonical", cascade="all, delete-orphan"
    )
    extracted_capabilities: Mapped[list["ExtractedCapability"]] = relationship(
        "ExtractedCapability", back_populates="canonical"
    )
    beneficiary_capabilities: Mapped[list["BeneficiaryCapability"]] = relationship(
        "BeneficiaryCapability", back_populates="canonical"
    )
    gap_heatmap_entries: Mapped[list["GapHeatmapEntry"]] = relationship(
        "GapHeatmapEntry", back_populates="canonical"
    )


class CapabilitySynonym(Base):
    """Alias-to-canonical mappings for capability normalization."""

    __tablename__ = "capability_synonyms"
    __table_args__ = (
        UniqueConstraint("alias", name="uq_capability_synonyms_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_capabilities.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    canonical: Mapped["CanonicalCapability"] = relationship(
        "CanonicalCapability", back_populates="synonyms"
    )


class OpportunityExtraction(Base):
    """Cached LLM extraction results per opportunity (extracted at most once)."""

    __tablename__ = "opportunity_extractions"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_record_id", name="uq_opportunity_extractions_pipeline_record"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    pipeline_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_records.id"),
        nullable=False,
    )
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    extraction_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Relationships
    pipeline_record: Mapped["PipelineRecord"] = relationship(
        "PipelineRecord", foreign_keys=[pipeline_record_id]
    )
    extracted_capabilities: Mapped[list["ExtractedCapability"]] = relationship(
        "ExtractedCapability",
        back_populates="extraction",
        cascade="all, delete-orphan",
    )


class ExtractedCapability(Base):
    """Individual capabilities extracted from each opportunity."""

    __tablename__ = "extracted_capabilities"
    __table_args__ = (
        CheckConstraint(
            "level IN ('required', 'preferred')",
            name="extracted_capabilities_valid_level",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunity_extractions.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_capabilities.id"),
        nullable=False,
    )
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    extraction: Mapped["OpportunityExtraction"] = relationship(
        "OpportunityExtraction", back_populates="extracted_capabilities"
    )
    canonical: Mapped["CanonicalCapability"] = relationship(
        "CanonicalCapability", back_populates="extracted_capabilities"
    )


class BeneficiaryCapability(Base):
    """What each Consultant/team can do — their capability profile."""

    __tablename__ = "beneficiary_capabilities"
    __table_args__ = (
        UniqueConstraint(
            "beneficiary_id", "canonical_id", name="uq_beneficiary_capabilities_ben_cap"
        ),
        CheckConstraint(
            "proficiency_level IN ('senior', 'mid', 'junior')",
            name="beneficiary_capabilities_valid_proficiency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    beneficiary_id: Mapped[str] = mapped_column(String(50), nullable=False)
    canonical_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_capabilities.id"),
        nullable=False,
    )
    proficiency_level: Mapped[str] = mapped_column(
        String(20), server_default="'senior'", nullable=False
    )
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    canonical: Mapped["CanonicalCapability"] = relationship(
        "CanonicalCapability", back_populates="beneficiary_capabilities"
    )


class GapHeatmap(Base):
    """Gap heatmap report — one per Beneficiary per analysis cycle."""

    __tablename__ = "gap_heatmaps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    beneficiary_id: Mapped[str] = mapped_column(String(50), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    analysis_window_days: Mapped[int] = mapped_column(
        Integer, server_default="90", nullable=False
    )
    total_opportunities_analyzed: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    total_blocked_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), server_default="0", nullable=False
    )
    previous_heatmap_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gap_heatmaps.id"),
        nullable=True,
    )
    opportunity_type_filter: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    entries: Mapped[list["GapHeatmapEntry"]] = relationship(
        "GapHeatmapEntry", back_populates="heatmap", cascade="all, delete-orphan"
    )
    previous_heatmap: Mapped["GapHeatmap | None"] = relationship(
        "GapHeatmap", remote_side="GapHeatmap.id", foreign_keys=[previous_heatmap_id]
    )


class GapHeatmapEntry(Base):
    """Individual ranked gap entry within a heatmap."""

    __tablename__ = "gap_heatmap_entries"
    __table_args__ = (
        UniqueConstraint(
            "heatmap_id", "canonical_id", name="uq_gap_heatmap_entries_heatmap_cap"
        ),
        CheckConstraint(
            "classification IN ('hard', 'soft')",
            name="gap_heatmap_entries_valid_classification",
        ),
        CheckConstraint(
            "trend IN ('new', 'growing', 'shrinking', 'resolved')",
            name="gap_heatmap_entries_valid_trend",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    heatmap_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gap_heatmaps.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_capabilities.id"),
        nullable=False,
    )
    classification: Mapped[str] = mapped_column(String(10), nullable=False)
    opportunity_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    blocked_pipeline_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), server_default="0", nullable=False
    )
    is_single_blocker: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    weighted_rank_score: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), server_default="0", nullable=False
    )
    trend: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rank_position: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    heatmap: Mapped["GapHeatmap"] = relationship(
        "GapHeatmap", back_populates="entries"
    )
    canonical: Mapped["CanonicalCapability"] = relationship(
        "CanonicalCapability", back_populates="gap_heatmap_entries"
    )


class GapExtractionQueue(Base):
    """Carry-forward queue for opportunities not yet processed (over batch cap)."""

    __tablename__ = "gap_extraction_queue"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_record_id", name="uq_gap_extraction_queue_pipeline_record"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    pipeline_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_records.id"),
        nullable=False,
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    priority_score: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), server_default="0", nullable=False
    )
    processed: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    pipeline_record: Mapped["PipelineRecord"] = relationship(
        "PipelineRecord", foreign_keys=[pipeline_record_id]
    )


class GapAnalysisConfig(Base):
    """Configuration parameters for gap analysis."""

    __tablename__ = "gap_analysis_config"
    __table_args__ = (
        UniqueConstraint("key", name="uq_gap_analysis_config_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
