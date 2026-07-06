"""AccountScore ORM model.

Stores composite account scores computed by the Scoring Engine.
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.prospect import Prospect


class AccountScore(Base):
    """Composite account score for a prospect."""

    __tablename__ = "account_scores"
    __table_args__ = (
        UniqueConstraint("prospect_id"),
        CheckConstraint(
            "total_score BETWEEN 0 AND 100", name="account_scores_valid_score"
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
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    tier: Mapped[str] = mapped_column(String(10), nullable=False)
    factor_scores: Mapped[dict] = mapped_column(
        JSONB(astext_type=String()), server_default="'{}'", nullable=False
    )
    missing_factors: Mapped[list | None] = mapped_column(
        JSONB(astext_type=String()), server_default="'[]'", nullable=True
    )
    is_partial: Mapped[bool | None] = mapped_column(
        Boolean, server_default="false", nullable=True
    )
    multi_source_bonus: Mapped[int | None] = mapped_column(
        Integer, server_default="0", nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    prospect: Mapped["Prospect"] = relationship(
        "Prospect", back_populates="account_score"
    )
