"""Interview Prep ORM models.

SQLAlchemy models for interview preparation packs and generation history.
Tracks structured interview prep content generated on Interview state entry,
including likely questions, STAR talking points, company briefings, and
grounding verification results.

Requirements: 2.1, 3.2
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InterviewPrepPack(Base):
    """Interview preparation pack generated on Interview state entry.

    Contains likely questions, STAR talking points, company briefing,
    and suggested questions to ask. All Beneficiary-side claims are
    grounded via the Grounding_Verifier before delivery.
    """

    __tablename__ = "interview_prep_packs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('generating', 'grounding', 'ready', 'ready_with_flags', 'failed')",
            name="interview_prep_packs_valid_status",
        ),
        Index("idx_interview_prep_record", "pipeline_record_id"),
        Index("idx_interview_prep_status", "status"),
        Index("idx_interview_prep_beneficiary", "beneficiary_id"),
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
    beneficiary_id: Mapped[str] = mapped_column(String(50), nullable=False)
    opportunity_type_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), server_default="'generating'", nullable=False
    )
    likely_questions: Mapped[list] = mapped_column(
        JSONB(astext_type=String()),
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    star_talking_points: Mapped[list] = mapped_column(
        JSONB(astext_type=String()),
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    company_briefing: Mapped[str] = mapped_column(
        Text, server_default="''", nullable=False
    )
    questions_to_ask: Mapped[list] = mapped_column(
        JSONB(astext_type=String()),
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    omission_notes: Mapped[list] = mapped_column(
        JSONB(astext_type=String()),
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    grounding_flags: Mapped[list] = mapped_column(
        JSONB(astext_type=String()),
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    generation_duration_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interview_prep_packs.id"),
        nullable=True,
    )


class InterviewPrepHistory(Base):
    """Pack generation history for regeneration tracking.

    Records each generation event with the trigger reason and a hash
    of the assembled context, enabling deduplication and audit of
    regeneration requests.
    """

    __tablename__ = "interview_prep_history"
    __table_args__ = (
        CheckConstraint(
            "trigger_reason IN ('state_entry', 'manual_regenerate', 'profile_update')",
            name="interview_prep_history_valid_trigger_reason",
        ),
        Index("idx_interview_prep_history_pack", "pack_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interview_prep_packs.id"),
        nullable=False,
    )
    trigger_reason: Mapped[str] = mapped_column(String(30), nullable=False)
    generation_context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
