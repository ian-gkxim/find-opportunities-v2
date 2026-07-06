"""Sequence, SequenceStep, Variant, and ProspectEnrollment ORM models.

Manages Lemlist outreach sequences with steps, A/B variants, and enrollments.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.prospect import Prospect
    from app.models.touchpoint import Touchpoint


class Sequence(Base):
    """Lemlist outreach sequence definition."""

    __tablename__ = "sequences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    beneficiary_id: Mapped[str] = mapped_column(String(50), nullable=False)
    sync_status: Mapped[str] = mapped_column(
        String(20), server_default="'pending'", nullable=False
    )
    lemlist_campaign_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    steps: Mapped[list["SequenceStep"]] = relationship(
        "SequenceStep", back_populates="sequence", cascade="all, delete-orphan"
    )
    touchpoints: Mapped[list["Touchpoint"]] = relationship(
        "Touchpoint", back_populates="sequence"
    )
    enrollments: Mapped[list["ProspectEnrollment"]] = relationship(
        "ProspectEnrollment", back_populates="sequence"
    )


class SequenceStep(Base):
    """A single step within an outreach sequence."""

    __tablename__ = "sequence_steps"
    __table_args__ = (
        UniqueConstraint("sequence_id", "step_order", name="uq_sequence_step_order"),
        CheckConstraint(
            "step_order BETWEEN 1 AND 10", name="sequence_steps_valid_order"
        ),
        CheckConstraint(
            "delay_days BETWEEN 1 AND 30", name="sequence_steps_valid_delay"
        ),
        CheckConstraint(
            "length(content_template) <= 5000",
            name="sequence_steps_template_length",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sequences.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False)
    content_template: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    sequence: Mapped["Sequence"] = relationship(
        "Sequence", back_populates="steps"
    )
    variants: Mapped[list["Variant"]] = relationship(
        "Variant", back_populates="step", cascade="all, delete-orphan"
    )


class Variant(Base):
    """A/B test variant for a sequence step."""

    __tablename__ = "variants"
    __table_args__ = (
        UniqueConstraint("step_id", "variant_label", name="uq_step_variant_label"),
        CheckConstraint(
            "variant_label IN ('A','B','C','D')", name="variants_valid_label"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sequence_steps.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_label: Mapped[str] = mapped_column(String(1), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sends: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    opens: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    replies: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    is_winner: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    is_promoted: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )

    # Relationships
    step: Mapped["SequenceStep"] = relationship(
        "SequenceStep", back_populates="variants"
    )
    touchpoints: Mapped[list["Touchpoint"]] = relationship(
        "Touchpoint", back_populates="variant"
    )


class ProspectEnrollment(Base):
    """Tracks prospect enrollment in sequences."""

    __tablename__ = "prospect_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "prospect_id", "sequence_id", name="uq_prospect_sequence"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    prospect_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prospects.id"), nullable=False
    )
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequences.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), server_default="'active'", nullable=False
    )
    followup_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    prospect: Mapped["Prospect"] = relationship(
        "Prospect", back_populates="enrollments"
    )
    sequence: Mapped["Sequence"] = relationship(
        "Sequence", back_populates="enrollments"
    )
