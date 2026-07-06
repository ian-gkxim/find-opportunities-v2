"""PipelineRecord ORM model.

Tracks the pipeline state machine per opportunity type for each prospect.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.prospect import Prospect
    from app.models.touchpoint import Touchpoint


class PipelineRecord(Base):
    """Pipeline state machine record for a prospect opportunity."""

    __tablename__ = "pipeline_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    prospect_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prospects.id"), nullable=False
    )
    opportunity_type_id: Mapped[str] = mapped_column(String(50), nullable=False)
    beneficiary_id: Mapped[str] = mapped_column(String(50), nullable=False)
    current_status: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    discovery_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    first_response_source: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    outcome_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_terminal: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    prospect: Mapped["Prospect"] = relationship(
        "Prospect", back_populates="pipeline_records"
    )
    touchpoints: Mapped[list["Touchpoint"]] = relationship(
        "Touchpoint", back_populates="pipeline_record"
    )
