"""EnrichmentScanHistory ORM model.

Records each enrichment scan cycle: when it started, completed,
how many proposals were generated, and whether it succeeded or failed.

Requirements: 1.2, 1.4
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.public_source import PublicSource


class EnrichmentScanHistory(Base):
    """Record of an enrichment scan cycle for a Consultant's source."""

    __tablename__ = "enrichment_scan_history"
    __table_args__ = (
        CheckConstraint(
            "scan_type IN ('scheduled', 'on_demand')",
            name="scan_history_valid_scan_type",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="scan_history_valid_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    consultant_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public_sources.id"), nullable=True
    )
    scan_type: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default="'running'", nullable=False
    )
    proposals_generated: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    source: Mapped["PublicSource | None"] = relationship(
        "PublicSource", back_populates="scan_histories"
    )
