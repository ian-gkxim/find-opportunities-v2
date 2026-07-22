"""Voice Asset domain models for sender voice definitions.

Provides structured voice declarations consumed at generation time
(Personalization_Engine) and validated at review time (Review_Service).

Requirements 1.2: Structured template for each Voice_Asset type covering
register, sentence-length preference, first-person usage, vocabulary to
prefer/avoid, and 2-3 short exemplar passages.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.core.errors import BaseServiceError


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class VoiceRegister(str, Enum):
    """The sender's natural communication register."""

    DIRECT = "direct"
    WARM = "warm"
    FORMAL = "formal"
    CONVERSATIONAL = "conversational"
    AUTHORITATIVE = "authoritative"


class SentenceLengthPreference(str, Enum):
    """Preferred sentence rhythm."""

    SHORT = "short"  # avg < 12 words
    MEDIUM = "medium"  # avg 12-20 words
    LONG = "long"  # avg 20+ words
    VARIED = "varied"  # deliberate mix


class FirstPersonUsage(str, Enum):
    """How the sender uses first person."""

    FREQUENT = "frequent"  # "I believe...", "I've seen..."
    MODERATE = "moderate"  # occasional first person
    MINIMAL = "minimal"  # prefers "we" or passive constructions


class VoiceAssetType(str, Enum):
    """Discriminator for Voice_Asset subtypes."""

    WRITING_STYLE = "writing_style"
    BEHAVIORAL_PROFILE = "behavioral_profile"
    BRAND_VOICE = "brand_voice"


# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------


@dataclass
class ExemplarPassage:
    """A short passage written in the Beneficiary's authentic voice."""

    text: str  # 50-500 chars of authentic writing
    context: str | None = None  # optional: "cold email opener", "proposal intro"


@dataclass
class VoiceAsset:
    """Base structured voice definition shared across all asset types.

    Covers: register, rhythm, vocabulary preferences/prohibitions,
    and exemplar passages demonstrating the voice in action.
    """

    id: str  # UUID
    beneficiary_id: str
    asset_type: VoiceAssetType
    register: VoiceRegister
    sentence_length: SentenceLengthPreference
    first_person_usage: FirstPersonUsage
    vocabulary_prefer: list[str]  # words/phrases to favor
    vocabulary_avoid: list[str]  # words/constructions to never use
    exemplar_passages: list[ExemplarPassage]  # 2-3 passages
    created_at: datetime
    updated_at: datetime

    def validate(self) -> list[str]:
        """Return list of validation errors, empty if valid.

        Enforces:
        - 2-3 exemplar passages
        - Each passage between 50-500 characters
        - Non-empty vocabulary_avoid list
        """
        errors: list[str] = []
        if len(self.exemplar_passages) < 2:
            errors.append("At least 2 exemplar passages required")
        if len(self.exemplar_passages) > 3:
            errors.append("At most 3 exemplar passages allowed")
        for i, ex in enumerate(self.exemplar_passages):
            if len(ex.text) < 50:
                errors.append(f"Exemplar {i+1} too short (min 50 chars)")
            if len(ex.text) > 500:
                errors.append(f"Exemplar {i+1} too long (max 500 chars)")
        if not self.vocabulary_avoid:
            errors.append("vocabulary_avoid must contain at least one item")
        return errors


@dataclass
class WritingStyleAsset(VoiceAsset):
    """Consultant's individual writing style.

    Extends VoiceAsset with consultant-specific fields.
    asset_type is always WRITING_STYLE.
    """

    # Inherited fields cover the full voice definition.
    # No additional fields beyond the base VoiceAsset for writing style.
    pass


@dataclass
class BehavioralProfileAsset:
    """Optional Consultant asset describing working style and interpersonal register.

    NOT a full VoiceAsset — it supplements the WritingStyleAsset with
    behavioral cues the reviewer uses to detect tone mismatches
    (e.g., flagging a combative, solo-hero tone for a collaborative profile).
    """

    id: str
    beneficiary_id: str
    asset_type: VoiceAssetType  # always BEHAVIORAL_PROFILE
    interpersonal_style: str  # e.g., "collaborative", "driving", "analytical"
    communication_traits: list[str]  # e.g., ["asks questions", "uses 'we'"]
    avoid_impressions: list[str]  # e.g., ["combative", "apologetic"]
    created_at: datetime
    updated_at: datetime


@dataclass
class BrandVoiceAsset(VoiceAsset):
    """Team-level brand voice definition.

    Extends VoiceAsset with brand-specific fields.
    asset_type is always BRAND_VOICE.
    """

    brand_personality: list[str] = field(
        default_factory=list
    )  # e.g., ["innovative", "approachable", "expert"]
    tagline_style: str | None = None  # optional: how the firm signs off


# --------------------------------------------------------------------------
# Exception Classes
# --------------------------------------------------------------------------


class VoiceAssetValidationError(BaseServiceError):
    """Raised when a Voice_Asset fails structural validation.

    Contains the list of specific validation errors returned by
    VoiceAsset.validate().
    """

    def __init__(
        self,
        message: str = "Voice asset validation failed",
        *,
        entity_id: str | None = None,
        validation_errors: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            service="voice_asset",
            entity_id=entity_id,
            details=details,
        )
        self.validation_errors = validation_errors or []


class VoiceAssetNotFoundError(BaseServiceError):
    """Raised when a requested Voice_Asset does not exist for a beneficiary.

    This is distinct from graceful degradation — it is raised when code
    explicitly requires a Voice_Asset (e.g., update operations on a
    non-existent asset).
    """

    def __init__(
        self,
        message: str = "Voice asset not found",
        *,
        entity_id: str | None = None,
        asset_type: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            service="voice_asset",
            entity_id=entity_id,
            details=details,
        )
        self.asset_type = asset_type
