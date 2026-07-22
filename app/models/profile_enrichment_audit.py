"""ProfileEnrichmentAudit ORM model.

Immutable audit trail for profile merges from enrichment proposals.
Records the timestamp, added content, evidence source, and whether
the Consultant edited the content before accepting.

Requirements: 3.4
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.competency_proposal import CompetencyProposal


class ProfileEnrichmentAudit(Base):
    """Immutable audit log entry for a profile enrichment merge action."""

    __tablename__ = "profile_enrichment_audit_log"
    __table_args__ = (
        CheckConstraint(
            "action IN ('accept', 'accept_with_edit', 'reject')",
            name="audit_log_valid_action",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    consultant_id: Mapped[str] = mapped_column(String(50), nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("competency_proposals.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )
    added_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    edited: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    proposal: Mapped["CompetencyProposal"] = relationship(
        "CompetencyProposal", back_populates="audit_entries"
    )
