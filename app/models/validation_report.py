"""ValidationReport ORM model.

Stores the structured record of all Validation_Rule results for each send attempt,
linked to the pipeline record that was validated.

Requirements: 1.4
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.pipeline_record import PipelineRecord


class ValidationReportModel(Base):
    """Validation report for a single send attempt."""

    __tablename__ = "validation_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    pipeline_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_records.id"), nullable=False
    )
    outreach_technique: Mapped[str] = mapped_column(String(50), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_warnings: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    total_execution_ms: Mapped[float] = mapped_column(Float, nullable=False)
    results: Mapped[list] = mapped_column(
        JSONB(astext_type=String()), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    pipeline_record: Mapped["PipelineRecord"] = relationship(
        "PipelineRecord", backref="validation_reports"
    )
