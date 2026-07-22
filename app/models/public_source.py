"""PublicSource ORM model.

Stores Consultant-configured public source URLs for periodic scanning
by the Profile Enrichment Worker.

Requirements: 1.1, 1.2, 1.4
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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
    from app.models.competency_proposal import CompetencyProposal
    from app.models.enrichment_scan_history import EnrichmentScanHistory


class PublicSource(Base):
    """A Consultant-configured public source URL for enrichment scanning."""

    __tablename__ = "public_sources"
    __table_args__ = (
        UniqueConstraint(
            "consultant_id", "url", name="uq_public_sources_consultant_url"
        ),
        CheckConstraint(
            "scan_interval_days >= 1 AND scan_interval_days <= 365",
            name="public_sources_valid_scan_interval",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    consultant_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    scan_interval_days: Mapped[int] = mapped_column(
        Integer, server_default="30", nullable=False
    )
    last_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    competency_proposals: Mapped[list["CompetencyProposal"]] = relationship(
        "CompetencyProposal", back_populates="source"
    )
    scan_histories: Mapped[list["EnrichmentScanHistory"]] = relationship(
        "EnrichmentScanHistory", back_populates="source"
    )
