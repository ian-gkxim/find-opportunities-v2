"""EnrichmentRecord ORM model.

Stores Apollo.io firmographic and technographic data for prospects.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.prospect import Prospect


class EnrichmentRecord(Base):
    """Apollo enrichment data for a prospect company."""

    __tablename__ = "enrichment_records"
    __table_args__ = (
        UniqueConstraint("prospect_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    prospect_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prospects.id"), nullable=False
    )
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revenue_range: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tech_stack: Mapped[list | None] = mapped_column(
        JSONB(astext_type=String()), server_default=text("'[]'::jsonb"), nullable=True
    )
    funding_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hq_city: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hq_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), server_default="'pending'", nullable=False
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    prospect: Mapped["Prospect"] = relationship(
        "Prospect", back_populates="enrichment_record"
    )
