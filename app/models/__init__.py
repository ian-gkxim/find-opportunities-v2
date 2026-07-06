"""SQLAlchemy ORM models and database configuration.

All models are exported here for convenient access throughout the application.
"""

from app.models.account_score import AccountScore
from app.models.base import Base, get_async_engine, get_async_session_factory
from app.models.config import (
    FunnelSnapshot,
    IntegrationHealth,
    LLMCache,
    ScoringConfig,
    SourceHealth,
)
from app.models.contact import Contact
from app.models.enrichment import EnrichmentRecord
from app.models.intent_signal import IntentSignal
from app.models.pipeline_record import PipelineRecord
from app.models.prospect import Prospect
from app.models.sequence import ProspectEnrollment, Sequence, SequenceStep, Variant
from app.models.touchpoint import Touchpoint

__all__ = [
    # Base
    "Base",
    "get_async_engine",
    "get_async_session_factory",
    # Core models
    "Prospect",
    "EnrichmentRecord",
    "Contact",
    "IntentSignal",
    "AccountScore",
    "PipelineRecord",
    # Sequence models
    "Sequence",
    "SequenceStep",
    "Variant",
    "ProspectEnrollment",
    "Touchpoint",
    # Configuration and health models
    "ScoringConfig",
    "LLMCache",
    "IntegrationHealth",
    "SourceHealth",
    "FunnelSnapshot",
]
