"""Prospect ORM model.

Represents discovered companies in the pipeline.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.account_score import AccountScore
    from app.models.contact import Contact
    from app.models.enrichment import EnrichmentRecord
    from app.models.intent_signal import IntentSignal
    from app.models.pipeline_record import PipelineRecord
    from app.models.prospect_enrollment import ProspectEnrollment


class Prospect(Base):
    """Core prospect table representing discovered companies."""

    __tablename__ = "prospects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    company_name: Mapped[str] = mapped_column(String(500), nullable=False)
    company_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    beneficiary_id: Mapped[str] = mapped_column(String(50), nullable=False)
    opportunity_type_id: Mapped[str] = mapped_column(String(50), nullable=False)
    discovery_source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_count: Mapped[int] = mapped_column(
        Integer, server_default="1", nullable=False
    )
    first_discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    enrichment_record: Mapped["EnrichmentRecord | None"] = relationship(
        "EnrichmentRecord", back_populates="prospect", uselist=False
    )
    contacts: Mapped[list["Contact"]] = relationship(
        "Contact", back_populates="prospect"
    )
    intent_signals: Mapped[list["IntentSignal"]] = relationship(
        "IntentSignal", back_populates="prospect"
    )
    account_score: Mapped["AccountScore | None"] = relationship(
        "AccountScore", back_populates="prospect", uselist=False
    )
    pipeline_records: Mapped[list["PipelineRecord"]] = relationship(
        "PipelineRecord", back_populates="prospect"
    )
    enrollments: Mapped[list["ProspectEnrollment"]] = relationship(
        "ProspectEnrollment", back_populates="prospect"
    )
