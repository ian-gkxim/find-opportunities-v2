"""IntentSignal ORM model.

Stores intent signals from Apollo.io indicating prospect buying interest.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.prospect import Prospect


class IntentSignal(Base):
    """Intent signals from Apollo indicating prospect buying interest."""

    __tablename__ = "intent_signals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    prospect_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prospects.id"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    strength: Mapped[str] = mapped_column(String(20), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), nullable=False
    )

    # Relationships
    prospect: Mapped["Prospect"] = relationship(
        "Prospect", back_populates="intent_signals"
    )
