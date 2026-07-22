"""Domain models for the Review Critique Loop.

Defines enums, dataclasses, and exception classes used by the Review_Service
to dispatch fresh-context LLM critiques, apply structured edits, and track
review cycle telemetry.

Requirements: 2.1, 2.2, 3.2, 3.3
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.core.errors import BaseServiceError

# ─── ENUMS ────────────────────────────────────────────────────────────────────


class ReviewStatus(str, Enum):
    """Final status of a material after the review process."""

    REVIEWED = "reviewed"
    UNREVIEWED = "unreviewed"
    REVIEW_FAILED = "review_failed"


class EditReason(str, Enum):
    """Classification reason for a structured edit."""

    KEYWORD_MATCH = "keyword_match"
    COMPANY_ANGLE = "company_angle"
    REFRAMING = "reframing"
    STYLE = "style"


class EditSkipReason(str, Enum):
    """Reason a structured edit was skipped or discarded."""

    AMBIGUOUS_OR_STALE_TARGET = "ambiguous_or_stale_target"
    UNGROUNDED_SUGGESTION = "ungrounded_suggestion"


class CritiqueCategory(str, Enum):
    """Fixed critique categories the reviewer must report on."""

    MISSED_KEYWORDS = "missed_keywords"
    COMPANY_ANGLES = "company_angles"
    REFRAMING = "reframing"
    TONE_STYLE = "tone_style"


# ─── DATACLASSES ──────────────────────────────────────────────────────────────


@dataclass
class StructuredEdit:
    """A machine-applicable revision instruction.

    Contains the exact old_string to find in the material and its replacement,
    along with the reason and category classification.
    """

    target_material_id: str
    old_string: str
    new_string: str
    reason: EditReason
    category: CritiqueCategory


@dataclass
class NarrativeFinding:
    """A prose critique requiring drafter judgment.

    Assigned to one of the four fixed categories. The flagged_passage is an
    exact quote from the material (None when the finding is about an omission).
    """

    category: CritiqueCategory
    description: str
    flagged_passage: str | None = None


@dataclass
class CritiqueResponse:
    """Structured output from the reviewer LLM.

    The narrative_findings dict must contain keys for all four CritiqueCategory
    values, even when a category has zero findings.
    """

    structured_edits: list[StructuredEdit]
    narrative_findings: dict[CritiqueCategory, list[NarrativeFinding]]


@dataclass
class EditOutcome:
    """Tracks what happened to each structured edit during application."""

    edit: StructuredEdit
    applied: bool
    skip_reason: EditSkipReason | None = None


@dataclass
class CycleLog:
    """Telemetry for a single review cycle."""

    cycle_number: int
    edits_applied: int
    edits_skipped: int
    edits_discarded: int
    narrative_findings_by_category: dict[CritiqueCategory, int]
    quality_score_before: int
    quality_score_after: int
    duration_ms: int
    skipped_edits: list[EditOutcome] = field(default_factory=list)
    discarded_edits: list[EditOutcome] = field(default_factory=list)


@dataclass
class ReasoningLog:
    """Complete telemetry for all review cycles on a material."""

    material_id: str
    prepare_technique_id: str
    review_technique_id: str
    cycles: list[CycleLog]
    total_cycles_executed: int
    max_cycles_configured: int
    final_review_status: ReviewStatus
    started_at: datetime
    completed_at: datetime


@dataclass
class ReviewResult:
    """Final output of the review process for a single material."""

    material_id: str
    revised_content: str
    review_status: ReviewStatus
    reasoning_log: ReasoningLog
    quality_score_final: int
    total_edits_applied: int


@dataclass
class DraftMaterial:
    """Output of a prepare technique prior to review.

    Represents the raw material produced by the Personalization_Engine
    before the Review_Service applies its critique cycle(s).
    """

    id: str
    pipeline_record_id: str
    prepare_technique_id: str
    material_type: str  # tailored_cv, tailored_cover_letter, draft_email, proposal
    content: str
    quality_score: int  # 0-100 from PersonalizationEngine
    generated_at: datetime


# ─── EXCEPTION CLASSES ────────────────────────────────────────────────────────


class ReviewLLMError(BaseServiceError):
    """Critique LLM call failed after all retries.

    Raised when the review critique dispatch exhausts all retry attempts
    without receiving a valid response.
    """

    def __init__(self, message: str, material_id: str, attempts: int) -> None:
        super().__init__(
            message,
            service="llm_critique",
            entity_id=material_id,
        )
        self.material_id = material_id
        self.attempts = attempts


class ReviewTimeoutError(ReviewLLMError):
    """Critique exceeded 60-second timeout after all retry attempts."""

    pass


class CritiqueParseError(ReviewLLMError):
    """Critique response did not match expected JSON schema."""

    pass
