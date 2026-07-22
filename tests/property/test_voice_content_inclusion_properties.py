# Feature: sender-voice-assets, Property 4: Voice_Asset content inclusion in generation prompt
"""Property-based test for PersonalizationEngine voice content inclusion.

Generates random valid VoiceAssets with varied register, vocabulary_prefer,
and exemplar passages. Verifies that the combined output from
_build_voice_directives() and _build_exemplar_section() contains:
- The register value (e.g., "direct", "warm")
- All vocabulary_prefer items
- All exemplar passage texts

**Validates: Requirements 2.1**
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.personalization_engine import (
    PersonalizationEngine,
    SeniorityLevel,
)
from app.core.voice_asset import (
    BehavioralProfileAsset,
    ExemplarPassage,
    FirstPersonUsage,
    SentenceLengthPreference,
    VoiceAsset,
    VoiceAssetType,
    VoiceRegister,
)


# ─── Strategies ───────────────────────────────────────────────────────────────

# Printable text for vocabulary items — avoids empty/whitespace-only
_printable_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        min_codepoint=32,
        max_codepoint=126,
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

# Exemplar text must be 50-500 chars for a valid VoiceAsset
_exemplar_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        min_codepoint=32,
        max_codepoint=126,
    ),
    min_size=50,
    max_size=500,
)


@st.composite
def valid_voice_asset_strategy(draw):
    """Generate a valid VoiceAsset with varied register/vocab/exemplars."""
    num_exemplars = draw(st.integers(min_value=2, max_value=3))
    exemplars = [
        ExemplarPassage(
            text=draw(_exemplar_text),
            context=draw(st.one_of(st.none(), st.text(min_size=1, max_size=30))),
        )
        for _ in range(num_exemplars)
    ]

    # Non-empty vocabulary_prefer (1-5 items)
    vocabulary_prefer = draw(
        st.lists(_printable_text, min_size=1, max_size=5)
    )

    # Non-empty vocabulary_avoid (required by VoiceAsset validation)
    vocabulary_avoid = draw(
        st.lists(_printable_text, min_size=1, max_size=5)
    )

    return VoiceAsset(
        id=draw(st.uuids().map(str)),
        beneficiary_id="consultant",
        asset_type=VoiceAssetType.WRITING_STYLE,
        register=draw(st.sampled_from(VoiceRegister)),
        sentence_length=draw(st.sampled_from(SentenceLengthPreference)),
        first_person_usage=draw(st.sampled_from(FirstPersonUsage)),
        vocabulary_prefer=vocabulary_prefer,
        vocabulary_avoid=vocabulary_avoid,
        exemplar_passages=exemplars,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _create_engine() -> PersonalizationEngine:
    """Create a PersonalizationEngine with mocked dependencies."""
    mock_llm = MagicMock()
    mock_llm.generate_content = AsyncMock(return_value="generated content")
    return PersonalizationEngine(llm_router=mock_llm)


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestProperty4VoiceContentInclusion:
    """Property 4: Voice_Asset content inclusion in generation prompt.

    For any valid Voice_Asset, the generation prompt constructed by
    PersonalizationEngine SHALL contain the Voice_Asset's register value,
    all vocabulary_prefer items, and all exemplar passage texts.

    **Validates: Requirements 2.1**
    """

    @given(
        voice_asset=valid_voice_asset_strategy(),
        formality_level=st.sampled_from(SeniorityLevel),
    )
    @settings(max_examples=200)
    def test_register_value_included_in_directives(
        self,
        voice_asset: VoiceAsset,
        formality_level: SeniorityLevel,
    ) -> None:
        """FOR ANY valid VoiceAsset, the combined output from
        _build_voice_directives() SHALL contain the register value.

        **Validates: Requirements 2.1**
        """
        engine = _create_engine()
        directives = engine._build_voice_directives(
            voice_asset=voice_asset,
            behavioral_profile=None,
            formality_level=formality_level,
        )

        assert voice_asset.register.value in directives, (
            f"Register value {voice_asset.register.value!r} not found in "
            f"voice directives output.\nGot:\n{directives}"
        )

    @given(
        voice_asset=valid_voice_asset_strategy(),
        formality_level=st.sampled_from(SeniorityLevel),
    )
    @settings(max_examples=200)
    def test_all_vocabulary_prefer_items_included(
        self,
        voice_asset: VoiceAsset,
        formality_level: SeniorityLevel,
    ) -> None:
        """FOR ANY valid VoiceAsset with non-empty vocabulary_prefer, all
        vocabulary_prefer items SHALL appear in the voice directives output.

        **Validates: Requirements 2.1**
        """
        engine = _create_engine()
        directives = engine._build_voice_directives(
            voice_asset=voice_asset,
            behavioral_profile=None,
            formality_level=formality_level,
        )

        for item in voice_asset.vocabulary_prefer:
            assert item in directives, (
                f"vocabulary_prefer item {item!r} not found in voice "
                f"directives output.\nPrefer list: {voice_asset.vocabulary_prefer}\n"
                f"Got:\n{directives}"
            )

    @given(voice_asset=valid_voice_asset_strategy())
    @settings(max_examples=200)
    def test_all_exemplar_texts_included_in_exemplar_section(
        self,
        voice_asset: VoiceAsset,
    ) -> None:
        """FOR ANY valid VoiceAsset, all exemplar passage texts SHALL appear
        in the output of _build_exemplar_section().

        **Validates: Requirements 2.1**
        """
        engine = _create_engine()
        exemplar_output = engine._build_exemplar_section(
            voice_asset.exemplar_passages
        )

        for exemplar in voice_asset.exemplar_passages:
            assert exemplar.text in exemplar_output, (
                f"Exemplar text not found in exemplar section output.\n"
                f"Missing: {exemplar.text[:80]!r}...\n"
                f"Got:\n{exemplar_output}"
            )

    @given(
        voice_asset=valid_voice_asset_strategy(),
        formality_level=st.sampled_from(SeniorityLevel),
    )
    @settings(max_examples=200)
    def test_combined_output_contains_all_voice_content(
        self,
        voice_asset: VoiceAsset,
        formality_level: SeniorityLevel,
    ) -> None:
        """FOR ANY valid VoiceAsset, the combined output from
        _build_voice_directives() + _build_exemplar_section() SHALL contain:
        - The register value
        - All vocabulary_prefer items
        - All exemplar passage texts

        This tests the full generation prompt content inclusion property.

        **Validates: Requirements 2.1**
        """
        engine = _create_engine()
        directives = engine._build_voice_directives(
            voice_asset=voice_asset,
            behavioral_profile=None,
            formality_level=formality_level,
        )
        exemplar_section = engine._build_exemplar_section(
            voice_asset.exemplar_passages
        )

        combined = directives + "\n" + exemplar_section

        # Register value must be present
        assert voice_asset.register.value in combined, (
            f"Register {voice_asset.register.value!r} not in combined output"
        )

        # All vocabulary_prefer items must be present
        for item in voice_asset.vocabulary_prefer:
            assert item in combined, (
                f"vocabulary_prefer item {item!r} not in combined output"
            )

        # All exemplar passage texts must be present
        for exemplar in voice_asset.exemplar_passages:
            assert exemplar.text in combined, (
                f"Exemplar text not in combined output: {exemplar.text[:80]!r}..."
            )
