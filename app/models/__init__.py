"""SQLAlchemy ORM models and database configuration.

All models are exported here for convenient access throughout the application.
"""

from app.models.account_score import AccountScore
from app.models.base import Base, get_async_engine, get_async_session_factory
from app.models.competency_proposal import CompetencyProposal
from app.models.config import (
    FunnelSnapshot,
    IntegrationHealth,
    LLMCache,
    ScoringConfig,
    SourceHealth,
)
from app.models.contact import Contact
from app.models.enrichment import EnrichmentRecord
from app.models.enrichment_scan_history import EnrichmentScanHistory
from app.models.gap_analytics import (
    BeneficiaryCapability,
    CanonicalCapability,
    CapabilitySynonym,
    ExtractedCapability,
    GapAnalysisConfig,
    GapExtractionQueue,
    GapHeatmap,
    GapHeatmapEntry,
    OpportunityExtraction,
)
from app.models.intent_signal import IntentSignal
from app.models.pipeline_record import PipelineRecord
from app.models.profile_enrichment_audit import ProfileEnrichmentAudit
from app.models.prospect import Prospect
from app.models.public_source import PublicSource
from app.models.sequence import ProspectEnrollment, Sequence, SequenceStep, Variant
from app.models.touchpoint import Touchpoint
from app.models.validation_report import ValidationReportModel

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
    # Validation
    "ValidationReportModel",
    # Gap analytics models
    "CanonicalCapability",
    "CapabilitySynonym",
    "OpportunityExtraction",
    "ExtractedCapability",
    "BeneficiaryCapability",
    "GapHeatmap",
    "GapHeatmapEntry",
    "GapExtractionQueue",
    "GapAnalysisConfig",
    # Profile enrichment models
    "PublicSource",
    "CompetencyProposal",
    "ProfileEnrichmentAudit",
    "EnrichmentScanHistory",
]
