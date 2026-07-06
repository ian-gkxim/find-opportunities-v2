"""Touchpoint ORM model.

Tracks individual outreach interactions within sequences.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.pipeline_record import PipelineRecord
    from app.models.sequence import Sequence, Variant


class Touchpoint(Base):
    """Individual interaction record within a sequence."""

    __tablename__ = "touchpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    pipeline_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_records.id"), nullable=False
    )
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequences.id"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("variants.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default="'pending'", nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    pipeline_record: Mapped["PipelineRecord"] = relationship(
        "PipelineRecord", back_populates="touchpoints"
    )
    sequence: Mapped["Sequence"] = relationship(
        "Sequence", back_populates="touchpoints"
    )
    variant: Mapped["Variant | None"] = relationship(
        "Variant", back_populates="touchpoints"
    )
