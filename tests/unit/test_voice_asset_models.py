"""Unit tests for app.core.voice_asset domain models.

Validates enum membership and string values, dataclass instantiation,
VoiceAsset.validate() boundary conditions, and exception class hierarchy.

Requirements: 1.2
"""

from datetime import datetime, timezone

import pytest

from app.core.errors import BaseServiceError
from app.core.voice_asset import (
    BehavioralProfileAsset,
    BrandVoiceAsset,
    ExemplarPassage,
    FirstPersonUsage,
    SentenceLengthPreference,
    VoiceAsset,
    VoiceAssetNotFoundError,
    VoiceAssetType,
    VoiceAssetValidationError,
    VoiceRegister,
    WritingStyleAsset,
)


# ─── ENUM TESTS ──────────────────────────────────────────────────────────────


class TestVoiceRegister:
    """VoiceRegister enum: 5 values with correct string representations."""

    def test_has_five_members(self):
        assert len(VoiceRegister) == 5

    def test_direct_value(self):
        assert VoiceRegister.DIRECT == "direct"
        assert VoiceRegister.DIRECT.value == "direct"

    def test_warm_value(self):
        assert VoiceRegister.WARM == "warm"
        assert VoiceRegister.WARM.value == "warm"

    def test_formal_value(self):
        assert VoiceRegister.FORMAL == "formal"
        assert VoiceRegister.FORMAL.value == "formal"

    def test_conversational_value(self):
        assert VoiceRegister.CONVERSATIONAL == "conversational"
        assert VoiceRegister.CONVERSATIONAL.value == "conversational"

    def test_authoritative_value(self):
        assert VoiceRegister.AUTHORITATIVE == "authoritative"
        assert VoiceRegister.AUTHORITATIVE.value == "authoritative"

    def test_is_str_enum(self):
        """VoiceRegister members are usable as plain strings."""
        assert isinstance(VoiceRegister.DIRECT, str)


class TestSentenceLengthPreference:
    """SentenceLengthPreference enum: 4 values with correct string representations."""

    def test_has_four_members(self):
        assert len(SentenceLengthPreference) == 4

    def test_short_value(self):
        assert SentenceLengthPreference.SHORT == "short"
        assert SentenceLengthPreference.SHORT.value == "short"

    def test_medium_value(self):
        assert SentenceLengthPreference.MEDIUM == "medium"
        assert SentenceLengthPreference.MEDIUM.value == "medium"

    def test_long_value(self):
        assert SentenceLengthPreference.LONG == "long"
        assert SentenceLengthPreference.LONG.value == "long"

    def test_varied_value(self):
        assert SentenceLengthPreference.VARIED == "varied"
        assert SentenceLengthPreference.VARIED.value == "varied"

    def test_is_str_enum(self):
        assert isinstance(SentenceLengthPreference.SHORT, str)


class TestFirstPersonUsage:
    """FirstPersonUsage enum: 3 values with correct string representations."""

    def test_has_three_members(self):
        assert len(FirstPersonUsage) == 3

    def test_frequent_value(self):
        assert FirstPersonUsage.FREQUENT == "frequent"
        assert FirstPersonUsage.FREQUENT.value == "frequent"

    def test_moderate_value(self):
        assert FirstPersonUsage.MODERATE == "moderate"
        assert FirstPersonUsage.MODERATE.value == "moderate"

    def test_minimal_value(self):
        assert FirstPersonUsage.MINIMAL == "minimal"
        assert FirstPersonUsage.MINIMAL.value == "minimal"

    def test_is_str_enum(self):
        assert isinstance(FirstPersonUsage.FREQUENT, str)


class TestVoiceAssetType:
    """VoiceAssetType enum: 3 values with correct string representations."""

    def test_has_three_members(self):
        assert len(VoiceAssetType) == 3

    def test_writing_style_value(self):
        assert VoiceAssetType.WRITING_STYLE == "writing_style"
        assert VoiceAssetType.WRITING_STYLE.value == "writing_style"

    def test_behavioral_profile_value(self):
        assert VoiceAssetType.BEHAVIORAL_PROFILE == "behavioral_profile"
        assert VoiceAssetType.BEHAVIORAL_PROFILE.value == "behavioral_profile"

    def test_brand_voice_value(self):
        assert VoiceAssetType.BRAND_VOICE == "brand_voice"
        assert VoiceAssetType.BRAND_VOICE.value == "brand_voice"

    def test_is_str_enum(self):
        assert isinstance(VoiceAssetType.WRITING_STYLE, str)


# ─── VOICEASSET VALIDATION TESTS ─────────────────────────────────────────────


class TestVoiceAssetValidation:
    """VoiceAsset.validate() edge cases and boundary conditions."""

    def _make_exemplar(self, length: int, context: str | None = None) -> ExemplarPassage:
        """Helper: create an ExemplarPassage with text of exact length."""
        return ExemplarPassage(text="x" * length, context=context)

    def _make_voice_asset(
        self,
        exemplar_count: int = 2,
        exemplar_length: int = 100,
        vocabulary_avoid: list[str] | None = None,
    ) -> VoiceAsset:
        """Helper: build a VoiceAsset with configurable exemplar count/length."""
        now = datetime.now(tz=timezone.utc)
        return VoiceAsset(
            id="asset-001",
            beneficiary_id="ben-001",
            asset_type=VoiceAssetType.WRITING_STYLE,
            register=VoiceRegister.DIRECT,
            sentence_length=SentenceLengthPreference.VARIED,
            first_person_usage=FirstPersonUsage.FREQUENT,
            vocabulary_prefer=["ship", "build"],
            vocabulary_avoid=vocabulary_avoid if vocabulary_avoid is not None else ["leverage"],
            exemplar_passages=[
                self._make_exemplar(exemplar_length) for _ in range(exemplar_count)
            ],
            created_at=now,
            updated_at=now,
        )

    def test_valid_with_exactly_2_exemplars(self):
        """Exactly 2 exemplars at valid length → no errors."""
        asset = self._make_voice_asset(exemplar_count=2, exemplar_length=100)
        errors = asset.validate()
        assert errors == []

    def test_valid_with_exactly_3_exemplars(self):
        """Exactly 3 exemplars at valid length → no errors."""
        asset = self._make_voice_asset(exemplar_count=3, exemplar_length=100)
        errors = asset.validate()
        assert errors == []

    def test_valid_with_boundary_50_chars(self):
        """Exemplar text at exactly 50 chars (min boundary) → no errors."""
        asset = self._make_voice_asset(exemplar_count=2, exemplar_length=50)
        errors = asset.validate()
        assert errors == []

    def test_valid_with_boundary_500_chars(self):
        """Exemplar text at exactly 500 chars (max boundary) → no errors."""
        asset = self._make_voice_asset(exemplar_count=2, exemplar_length=500)
        errors = asset.validate()
        assert errors == []

    def test_invalid_with_1_exemplar(self):
        """Only 1 exemplar → validation error."""
        asset = self._make_voice_asset(exemplar_count=1, exemplar_length=100)
        errors = asset.validate()
        assert "At least 2 exemplar passages required" in errors

    def test_invalid_with_0_exemplars(self):
        """Zero exemplars → validation error."""
        asset = self._make_voice_asset(exemplar_count=0, exemplar_length=100)
        errors = asset.validate()
        assert "At least 2 exemplar passages required" in errors

    def test_invalid_with_4_exemplars(self):
        """4 exemplars → validation error."""
        asset = self._make_voice_asset(exemplar_count=4, exemplar_length=100)
        errors = asset.validate()
        assert "At most 3 exemplar passages allowed" in errors

    def test_invalid_with_49_chars(self):
        """Exemplar text at 49 chars (one below min) → too short error."""
        asset = self._make_voice_asset(exemplar_count=2, exemplar_length=49)
        errors = asset.validate()
        assert "Exemplar 1 too short (min 50 chars)" in errors
        assert "Exemplar 2 too short (min 50 chars)" in errors

    def test_invalid_with_501_chars(self):
        """Exemplar text at 501 chars (one above max) → too long error."""
        asset = self._make_voice_asset(exemplar_count=2, exemplar_length=501)
        errors = asset.validate()
        assert "Exemplar 1 too long (max 500 chars)" in errors
        assert "Exemplar 2 too long (max 500 chars)" in errors

    def test_invalid_empty_vocabulary_avoid(self):
        """Empty vocabulary_avoid → validation error."""
        asset = self._make_voice_asset(vocabulary_avoid=[])
        errors = asset.validate()
        assert "vocabulary_avoid must contain at least one item" in errors

    def test_multiple_errors_returned(self):
        """Multiple validation violations → all errors reported."""
        now = datetime.now(tz=timezone.utc)
        asset = VoiceAsset(
            id="asset-bad",
            beneficiary_id="ben-001",
            asset_type=VoiceAssetType.WRITING_STYLE,
            register=VoiceRegister.WARM,
            sentence_length=SentenceLengthPreference.SHORT,
            first_person_usage=FirstPersonUsage.MINIMAL,
            vocabulary_prefer=[],
            vocabulary_avoid=[],  # empty → error
            exemplar_passages=[
                ExemplarPassage(text="x" * 30),  # too short → error
            ],  # only 1 → error
            created_at=now,
            updated_at=now,
        )
        errors = asset.validate()
        assert len(errors) == 3
        assert "At least 2 exemplar passages required" in errors
        assert "Exemplar 1 too short (min 50 chars)" in errors
        assert "vocabulary_avoid must contain at least one item" in errors


# ─── WRITINGSTYLEASSET TESTS ─────────────────────────────────────────────────


class TestWritingStyleAsset:
    """WritingStyleAsset inherits from VoiceAsset properly."""

    def test_inherits_voice_asset(self):
        assert issubclass(WritingStyleAsset, VoiceAsset)

    def test_instantiation_with_all_fields(self):
        now = datetime.now(tz=timezone.utc)
        asset = WritingStyleAsset(
            id="ws-001",
            beneficiary_id="consultant-001",
            asset_type=VoiceAssetType.WRITING_STYLE,
            register=VoiceRegister.CONVERSATIONAL,
            sentence_length=SentenceLengthPreference.MEDIUM,
            first_person_usage=FirstPersonUsage.MODERATE,
            vocabulary_prefer=["collaborate", "iterate"],
            vocabulary_avoid=["synergize", "leverage"],
            exemplar_passages=[
                ExemplarPassage(text="x" * 100, context="cold email opener"),
                ExemplarPassage(text="y" * 150, context="proposal intro"),
            ],
            created_at=now,
            updated_at=now,
        )
        assert asset.id == "ws-001"
        assert asset.beneficiary_id == "consultant-001"
        assert asset.asset_type == VoiceAssetType.WRITING_STYLE
        assert asset.register == VoiceRegister.CONVERSATIONAL
        assert asset.sentence_length == SentenceLengthPreference.MEDIUM
        assert asset.first_person_usage == FirstPersonUsage.MODERATE

    def test_validate_inherited_from_voice_asset(self):
        """WritingStyleAsset.validate() uses VoiceAsset validation logic."""
        now = datetime.now(tz=timezone.utc)
        asset = WritingStyleAsset(
            id="ws-002",
            beneficiary_id="consultant-001",
            asset_type=VoiceAssetType.WRITING_STYLE,
            register=VoiceRegister.DIRECT,
            sentence_length=SentenceLengthPreference.SHORT,
            first_person_usage=FirstPersonUsage.FREQUENT,
            vocabulary_prefer=[],
            vocabulary_avoid=["leverage"],
            exemplar_passages=[
                ExemplarPassage(text="x" * 100),
                ExemplarPassage(text="y" * 100),
            ],
            created_at=now,
            updated_at=now,
        )
        errors = asset.validate()
        assert errors == []


# ─── BEHAVIORALPROFILEASSET TESTS ─────────────────────────────────────────────


class TestBehavioralProfileAsset:
    """BehavioralProfileAsset instantiation with all required fields."""

    def test_instantiation_all_fields(self):
        now = datetime.now(tz=timezone.utc)
        profile = BehavioralProfileAsset(
            id="bp-001",
            beneficiary_id="consultant-001",
            asset_type=VoiceAssetType.BEHAVIORAL_PROFILE,
            interpersonal_style="collaborative",
            communication_traits=["asks questions", "uses 'we'", "builds consensus"],
            avoid_impressions=["combative", "apologetic", "dismissive"],
            created_at=now,
            updated_at=now,
        )
        assert profile.id == "bp-001"
        assert profile.beneficiary_id == "consultant-001"
        assert profile.asset_type == VoiceAssetType.BEHAVIORAL_PROFILE
        assert profile.interpersonal_style == "collaborative"
        assert profile.communication_traits == ["asks questions", "uses 'we'", "builds consensus"]
        assert profile.avoid_impressions == ["combative", "apologetic", "dismissive"]
        assert profile.created_at == now
        assert profile.updated_at == now

    def test_is_not_subclass_of_voice_asset(self):
        """BehavioralProfileAsset is NOT a VoiceAsset — it's a standalone dataclass."""
        assert not issubclass(BehavioralProfileAsset, VoiceAsset)

    def test_empty_communication_traits(self):
        """BehavioralProfileAsset allows empty communication_traits list."""
        now = datetime.now(tz=timezone.utc)
        profile = BehavioralProfileAsset(
            id="bp-002",
            beneficiary_id="consultant-002",
            asset_type=VoiceAssetType.BEHAVIORAL_PROFILE,
            interpersonal_style="driving",
            communication_traits=[],
            avoid_impressions=["passive"],
            created_at=now,
            updated_at=now,
        )
        assert profile.communication_traits == []


# ─── BRANDVOICEASSET TESTS ────────────────────────────────────────────────────


class TestBrandVoiceAsset:
    """BrandVoiceAsset with brand_personality and tagline_style."""

    def test_inherits_voice_asset(self):
        assert issubclass(BrandVoiceAsset, VoiceAsset)

    def test_instantiation_with_brand_personality(self):
        now = datetime.now(tz=timezone.utc)
        asset = BrandVoiceAsset(
            id="bv-001",
            beneficiary_id="team-001",
            asset_type=VoiceAssetType.BRAND_VOICE,
            register=VoiceRegister.AUTHORITATIVE,
            sentence_length=SentenceLengthPreference.MEDIUM,
            first_person_usage=FirstPersonUsage.MINIMAL,
            vocabulary_prefer=["innovative", "trusted"],
            vocabulary_avoid=["cheap", "basic"],
            exemplar_passages=[
                ExemplarPassage(text="a" * 100, context="firm overview"),
                ExemplarPassage(text="b" * 200, context="proposal opening"),
            ],
            created_at=now,
            updated_at=now,
            brand_personality=["innovative", "approachable", "expert"],
            tagline_style="Precision meets possibility.",
        )
        assert asset.brand_personality == ["innovative", "approachable", "expert"]
        assert asset.tagline_style == "Precision meets possibility."
        assert asset.asset_type == VoiceAssetType.BRAND_VOICE
        assert asset.register == VoiceRegister.AUTHORITATIVE

    def test_tagline_style_defaults_to_none(self):
        """tagline_style is optional and defaults to None."""
        now = datetime.now(tz=timezone.utc)
        asset = BrandVoiceAsset(
            id="bv-002",
            beneficiary_id="team-001",
            asset_type=VoiceAssetType.BRAND_VOICE,
            register=VoiceRegister.WARM,
            sentence_length=SentenceLengthPreference.VARIED,
            first_person_usage=FirstPersonUsage.MODERATE,
            vocabulary_prefer=["partner"],
            vocabulary_avoid=["vendor"],
            exemplar_passages=[
                ExemplarPassage(text="c" * 80),
                ExemplarPassage(text="d" * 80),
            ],
            created_at=now,
            updated_at=now,
            brand_personality=["approachable"],
        )
        assert asset.tagline_style is None

    def test_brand_personality_defaults_to_empty_list(self):
        """brand_personality defaults to an empty list."""
        now = datetime.now(tz=timezone.utc)
        asset = BrandVoiceAsset(
            id="bv-003",
            beneficiary_id="team-001",
            asset_type=VoiceAssetType.BRAND_VOICE,
            register=VoiceRegister.FORMAL,
            sentence_length=SentenceLengthPreference.LONG,
            first_person_usage=FirstPersonUsage.MINIMAL,
            vocabulary_prefer=[],
            vocabulary_avoid=["disrupt"],
            exemplar_passages=[
                ExemplarPassage(text="e" * 60),
                ExemplarPassage(text="f" * 60),
            ],
            created_at=now,
            updated_at=now,
        )
        assert asset.brand_personality == []

    def test_validate_inherited_from_voice_asset(self):
        """BrandVoiceAsset.validate() uses VoiceAsset validation logic."""
        now = datetime.now(tz=timezone.utc)
        asset = BrandVoiceAsset(
            id="bv-004",
            beneficiary_id="team-001",
            asset_type=VoiceAssetType.BRAND_VOICE,
            register=VoiceRegister.AUTHORITATIVE,
            sentence_length=SentenceLengthPreference.MEDIUM,
            first_person_usage=FirstPersonUsage.MINIMAL,
            vocabulary_prefer=["excellence"],
            vocabulary_avoid=["cheap"],
            exemplar_passages=[
                ExemplarPassage(text="g" * 100),
                ExemplarPassage(text="h" * 100),
                ExemplarPassage(text="i" * 100),
            ],
            created_at=now,
            updated_at=now,
            brand_personality=["professional", "trusted"],
            tagline_style="Where expertise meets execution.",
        )
        errors = asset.validate()
        assert errors == []


# ─── EXEMPLAR PASSAGE TESTS ──────────────────────────────────────────────────


class TestExemplarPassage:
    """ExemplarPassage dataclass instantiation."""

    def test_with_context(self):
        passage = ExemplarPassage(text="Hello world" * 10, context="cold email opener")
        assert passage.text == "Hello world" * 10
        assert passage.context == "cold email opener"

    def test_context_defaults_to_none(self):
        passage = ExemplarPassage(text="Some text here")
        assert passage.context is None


# ─── EXCEPTION CLASS TESTS ───────────────────────────────────────────────────


class TestVoiceAssetValidationError:
    """VoiceAssetValidationError exception class."""

    def test_stores_validation_errors(self):
        err = VoiceAssetValidationError(
            "Voice asset validation failed",
            entity_id="asset-001",
            validation_errors=["At least 2 exemplar passages required", "vocabulary_avoid must contain at least one item"],
        )
        assert err.validation_errors == [
            "At least 2 exemplar passages required",
            "vocabulary_avoid must contain at least one item",
        ]
        assert err.message == "Voice asset validation failed"
        assert err.entity_id == "asset-001"

    def test_inherits_base_service_error(self):
        err = VoiceAssetValidationError("failed", entity_id="asset-001")
        assert isinstance(err, BaseServiceError)
        assert isinstance(err, Exception)

    def test_service_is_voice_asset(self):
        err = VoiceAssetValidationError("failed")
        assert err.service == "voice_asset"

    def test_default_validation_errors_is_empty_list(self):
        err = VoiceAssetValidationError("failed")
        assert err.validation_errors == []

    def test_catchable_as_base_service_error(self):
        err = VoiceAssetValidationError("bad asset", entity_id="asset-999")
        with pytest.raises(BaseServiceError):
            raise err


class TestVoiceAssetNotFoundError:
    """VoiceAssetNotFoundError exception class."""

    def test_stores_asset_type(self):
        err = VoiceAssetNotFoundError(
            "Voice asset not found",
            entity_id="ben-001",
            asset_type="writing_style",
        )
        assert err.asset_type == "writing_style"
        assert err.message == "Voice asset not found"
        assert err.entity_id == "ben-001"

    def test_inherits_base_service_error(self):
        err = VoiceAssetNotFoundError("not found", entity_id="ben-001")
        assert isinstance(err, BaseServiceError)
        assert isinstance(err, Exception)

    def test_service_is_voice_asset(self):
        err = VoiceAssetNotFoundError("not found")
        assert err.service == "voice_asset"

    def test_asset_type_defaults_to_none(self):
        err = VoiceAssetNotFoundError("not found")
        assert err.asset_type is None

    def test_catchable_as_base_service_error(self):
        err = VoiceAssetNotFoundError("missing", entity_id="ben-123")
        with pytest.raises(BaseServiceError):
            raise err


class TestVoiceAssetExceptionHierarchy:
    """Verify the exception hierarchy for voice asset errors."""

    @pytest.mark.parametrize(
        "error_class",
        [VoiceAssetValidationError, VoiceAssetNotFoundError],
    )
    def test_all_catchable_as_base_service_error(self, error_class):
        err = error_class(message="test error", entity_id="test-001")
        with pytest.raises(BaseServiceError):
            raise err

    def test_validation_error_is_subclass_of_base_service_error(self):
        assert issubclass(VoiceAssetValidationError, BaseServiceError)

    def test_not_found_error_is_subclass_of_base_service_error(self):
        assert issubclass(VoiceAssetNotFoundError, BaseServiceError)
