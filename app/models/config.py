"""Configuration and health ORM models.

Includes scoring configuration, LLM cache, integration health,
source health, and funnel snapshots.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScoringConfig(Base):
    """Scoring weight configuration."""

    __tablename__ = "scoring_configs"
    __table_args__ = (
        CheckConstraint(
            "firmographic_weight BETWEEN 0 AND 100",
            name="scoring_configs_firmographic_range",
        ),
        CheckConstraint(
            "technographic_weight BETWEEN 0 AND 100",
            name="scoring_configs_technographic_range",
        ),
        CheckConstraint(
            "intent_weight BETWEEN 0 AND 100",
            name="scoring_configs_intent_range",
        ),
        CheckConstraint(
            "llm_relevance_weight BETWEEN 0 AND 100",
            name="scoring_configs_llm_relevance_range",
        ),
        CheckConstraint(
            "historical_weight BETWEEN 0 AND 100",
            name="scoring_configs_historical_range",
        ),
        CheckConstraint(
            "min_score_threshold BETWEEN 0 AND 100",
            name="scoring_configs_threshold_range",
        ),
        CheckConstraint(
            "firmographic_weight + technographic_weight + intent_weight + "
            "llm_relevance_weight + historical_weight = 100",
            name="weights_sum_100",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    firmographic_weight: Mapped[int] = mapped_column(
        Integer, server_default="30", nullable=False
    )
    technographic_weight: Mapped[int] = mapped_column(
        Integer, server_default="25", nullable=False
    )
    intent_weight: Mapped[int] = mapped_column(
        Integer, server_default="20", nullable=False
    )
    llm_relevance_weight: Mapped[int] = mapped_column(
        Integer, server_default="15", nullable=False
    )
    historical_weight: Mapped[int] = mapped_column(
        Integer, server_default="10", nullable=False
    )
    min_score_threshold: Mapped[int] = mapped_column(
        Integer, server_default="25", nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )


class LLMCache(Base):
    """7-day LLM response cache."""

    __tablename__ = "llm_cache"
    __table_args__ = (
        UniqueConstraint(
            "prospect_id", "profile_hash", name="uq_llm_cache_prospect_hash"
        ),
        CheckConstraint(
            "relevance_score BETWEEN 0 AND 100", name="llm_cache_valid_score"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    prospect_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    relevance_score: Mapped[int] = mapped_column(Integer, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(String(500), nullable=True)
    context_status: Mapped[str | None] = mapped_column(
        String(20), server_default="'full'", nullable=True
    )
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class IntegrationHealth(Base):
    """API integration status tracking."""

    __tablename__ = "integration_health"
    __table_args__ = (UniqueConstraint("integration_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    integration_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), server_default="'disconnected'", nullable=False
    )
    usage_current: Mapped[int | None] = mapped_column(
        Integer, server_default="0", nullable=True
    )
    usage_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )


class SourceHealth(Base):
    """Discovery source health status."""

    __tablename__ = "source_health"
    __table_args__ = (UniqueConstraint("source_type"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), server_default="'active'", nullable=False
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_attempts: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )


class FunnelSnapshot(Base):
    """Daily analytics funnel snapshots."""

    __tablename__ = "funnel_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "opportunity_type_id",
            "beneficiary_id",
            "stage_name",
            name="uq_funnel_snapshot",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    opportunity_type_id: Mapped[str] = mapped_column(String(50), nullable=False)
    beneficiary_id: Mapped[str] = mapped_column(String(50), nullable=False)
    stage_name: Mapped[str] = mapped_column(String(100), nullable=False)
    entered_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    exited_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    avg_days_in_stage: Mapped[float | None] = mapped_column(
        Numeric(5, 1), nullable=True
    )
