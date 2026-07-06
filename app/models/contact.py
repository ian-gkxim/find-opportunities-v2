"""Contact ORM model.

Stores decision-maker contacts discovered via Apollo.io.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.prospect import Prospect


class Contact(Base):
    """Contacts discovered via Apollo for a prospect company."""

    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR linkedin_url IS NOT NULL",
            name="contacts_require_contact_method",
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
    full_name: Mapped[str] = mapped_column(String(300), nullable=False)
    job_title: Mapped[str] = mapped_column(String(300), nullable=False)
    email: Mapped[str | None] = mapped_column(String(300), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email_verification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    seniority_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    search_status: Mapped[str | None] = mapped_column(
        String(30), server_default="'standard'", nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    prospect: Mapped["Prospect"] = relationship(
        "Prospect", back_populates="contacts"
    )
