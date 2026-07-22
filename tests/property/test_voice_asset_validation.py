# Feature: sender-voice-assets, Property 2: Voice_Asset structured template validation
"""Property-based test for VoiceAsset.validate() method.

Generates random VoiceAsset instances with varying exemplar counts (0–5),
exemplar lengths (0–600 chars), and avoid list sizes (0–10). Verifies that
validate() returns an empty list if and only if the asset has 2–3 exemplar
passages (each 50–500 chars) and a non-empty vocabulary_avoid list. Otherwise
it returns specific error messages for each violated constraint.

**Validates: Requirements 1.2**
"""

from datetime import datetime, timezone

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.voice_asset import (
    ExemplarPassage,
    FirstPersonUsage,
    SentenceLengthPreference,
    VoiceAsset,
    VoiceAssetType,
    VoiceRegister,
)


# ─── Strategies ───────────────────────────────────────────────────────────────

# Valid char range for exemplar text (printable ASCII for simplicity)
_text_char_strategy = st.characters(
    whitelist_categories=("L", "N", "P", "Z"),
    min_codepoint=32,
    max_codepoint=126,
)


@st.composite
def exemplar_passage_strategy(draw, min_length=0, max_length=600):
    """Generate an ExemplarPassage with text length in the given range."""
    length = draw(st.integers(min_value=min_length, max_value=max_length))
    text = draw(st.text(alphabet=_text_char_strategy, min_size=length, max_size=length))
    context = draw(st.one_of(st.none(), st.text(min_size=1, max_size=30)))
    return ExemplarPassage(text=text, context=context)


@st.composite
def voice_asset_strategy(draw):
    """Generate a random VoiceAsset with varying exemplar counts, lengths, and avoid list sizes."""
    num_exemplars = draw(st.integers(min_value=0, max_value=5))
    exemplars = draw(
        st.lists(
            exemplar_passage_strategy(min_length=0, max_length=600),
            min_size=num_exemplars,
            max_size=num_exemplars,
        )
    )
    avoid_size = draw(st.integers(min_value=0, max_value=10))
    vocabulary_avoid = draw(
        st.lists(
            st.text(min_size=1, max_size=30),
            min_size=avoid_size,
            max_size=avoid_size,
        )
    )

    return VoiceAsset(
        id=draw(st.uuids().map(str)),
        beneficiary_id=draw(st.text(min_size=1, max_size=20)),
        asset_type=draw(st.sampled_from(VoiceAssetType)),
        register=draw(st.sampled_from(VoiceRegister)),
        sentence_length=draw(st.sampled_from(SentenceLengthPreference)),
        first_person_usage=draw(st.sampled_from(FirstPersonUsage)),
        vocabulary_prefer=draw(st.lists(st.text(min_size=1, max_size=20), max_size=5)),
        vocabulary_avoid=vocabulary_avoid,
        exemplar_passages=exemplars,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ─── Helper ──────────────────────────────────────────────────────────────────


def _is_valid_asset(asset: VoiceAsset) -> bool:
    """Determine if a VoiceAsset should pass validation based on the spec rules.

    Valid iff:
    - 2 <= len(exemplar_passages) <= 3
    - All exemplar texts have 50 <= len(text) <= 500
    - len(vocabulary_avoid) >= 1
    """
    if not (2 <= len(asset.exemplar_passages) <= 3):
        return False
    for ex in asset.exemplar_passages:
        if not (50 <= len(ex.text) <= 500):
            return False
    if not asset.vocabulary_avoid:
        return False
    return True


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestVoiceAssetValidation:
    """Property 2: Voice_Asset structured template validation."""

    @given(asset=voice_asset_strategy())
    @settings(max_examples=200)
    def test_validate_returns_empty_iff_valid(self, asset: VoiceAsset) -> None:
        """FOR ANY VoiceAsset instance, validate() returns an empty error list
        if and only if the asset has 2–3 exemplar passages (each 50–500 chars)
        and a non-empty vocabulary_avoid list.

        **Validates: Requirements 1.2**
        """
        errors = asset.validate()
        expected_valid = _is_valid_asset(asset)

        if expected_valid:
            assert errors == [], (
                f"Expected no errors for valid asset, got: {errors}"
            )
        else:
            assert len(errors) > 0, (
                f"Expected errors for invalid asset "
                f"(exemplars={len(asset.exemplar_passages)}, "
                f"lengths={[len(e.text) for e in asset.exemplar_passages]}, "
                f"avoid_count={len(asset.vocabulary_avoid)})"
            )

    @given(asset=voice_asset_strategy())
    @settings(max_examples=200)
    def test_too_few_exemplars_produces_specific_error(self, asset: VoiceAsset) -> None:
        """WHEN a VoiceAsset has fewer than 2 exemplar passages, THEN validate()
        returns an error mentioning "At least 2 exemplar passages required".

        **Validates: Requirements 1.2**
        """
        assume(len(asset.exemplar_passages) < 2)
        errors = asset.validate()
        assert any("At least 2 exemplar passages required" in e for e in errors), (
            f"Expected 'At least 2 exemplar passages required' error, got: {errors}"
        )

    @given(asset=voice_asset_strategy())
    @settings(max_examples=200)
    def test_too_many_exemplars_produces_specific_error(self, asset: VoiceAsset) -> None:
        """WHEN a VoiceAsset has more than 3 exemplar passages, THEN validate()
        returns an error mentioning "At most 3 exemplar passages allowed".

        **Validates: Requirements 1.2**
        """
        assume(len(asset.exemplar_passages) > 3)
        errors = asset.validate()
        assert any("At most 3 exemplar passages allowed" in e for e in errors), (
            f"Expected 'At most 3 exemplar passages allowed' error, got: {errors}"
        )

    @given(asset=voice_asset_strategy())
    @settings(max_examples=200)
    def test_short_exemplar_produces_specific_error(self, asset: VoiceAsset) -> None:
        """WHEN any exemplar passage text is shorter than 50 chars, THEN validate()
        returns an error mentioning "too short (min 50 chars)" for that exemplar.

        **Validates: Requirements 1.2**
        """
        short_indices = [
            i for i, ex in enumerate(asset.exemplar_passages)
            if len(ex.text) < 50
        ]
        assume(len(short_indices) > 0)

        errors = asset.validate()
        for idx in short_indices:
            expected_msg = f"Exemplar {idx + 1} too short (min 50 chars)"
            assert expected_msg in errors, (
                f"Expected '{expected_msg}' in errors, got: {errors}"
            )

    @given(asset=voice_asset_strategy())
    @settings(max_examples=200)
    def test_long_exemplar_produces_specific_error(self, asset: VoiceAsset) -> None:
        """WHEN any exemplar passage text is longer than 500 chars, THEN validate()
        returns an error mentioning "too long (max 500 chars)" for that exemplar.

        **Validates: Requirements 1.2**
        """
        long_indices = [
            i for i, ex in enumerate(asset.exemplar_passages)
            if len(ex.text) > 500
        ]
        assume(len(long_indices) > 0)

        errors = asset.validate()
        for idx in long_indices:
            expected_msg = f"Exemplar {idx + 1} too long (max 500 chars)"
            assert expected_msg in errors, (
                f"Expected '{expected_msg}' in errors, got: {errors}"
            )

    @given(asset=voice_asset_strategy())
    @settings(max_examples=200)
    def test_empty_vocabulary_avoid_produces_specific_error(self, asset: VoiceAsset) -> None:
        """WHEN a VoiceAsset has an empty vocabulary_avoid list, THEN validate()
        returns an error mentioning "vocabulary_avoid must contain at least one item".

        **Validates: Requirements 1.2**
        """
        assume(len(asset.vocabulary_avoid) == 0)
        errors = asset.validate()
        assert "vocabulary_avoid must contain at least one item" in errors, (
            f"Expected 'vocabulary_avoid must contain at least one item' error, got: {errors}"
        )
