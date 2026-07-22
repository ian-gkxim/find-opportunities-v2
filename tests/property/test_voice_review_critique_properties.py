# Feature: sender-voice-assets, Property 7: Review critique prompt includes Voice_Asset when present
"""Property-based test for ReviewService voice critique instructions.

Generates random valid VoiceAssets with varied register, vocabulary_avoid lists,
and exemplar passages. Verifies that the output of _build_voice_critique_instructions()
contains:
- The register value (e.g., "direct", "warm")
- All vocabulary_avoid items
- All exemplar passage texts

**Validates: Requirements 3.1**
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.review_service import ReviewService
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
    """Generate a valid VoiceAsset with varied register, avoid lists, and exemplars."""
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

    # Non-empty vocabulary_avoid (required by VoiceAsset validation, 1-5 items)
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


@st.composite
def behavioral_profile_strategy(draw):
    """Generate a random BehavioralProfileAsset."""
    interpersonal_styles = ["collaborative", "driving", "analytical", "expressive"]
    communication_traits = [
        "asks questions",
        "uses 'we'",
        "summarizes frequently",
        "prefers bullet points",
        "leads with data",
        "focuses on outcomes",
    ]
    avoid_impressions = [
        "combative",
        "apologetic",
        "passive",
        "arrogant",
        "indecisive",
        "over-hedged",
    ]

    return BehavioralProfileAsset(
        id=draw(st.uuids().map(str)),
        beneficiary_id="consultant",
        asset_type=VoiceAssetType.BEHAVIORAL_PROFILE,
        interpersonal_style=draw(st.sampled_from(interpersonal_styles)),
        communication_traits=draw(
            st.lists(
                st.sampled_from(communication_traits),
                min_size=1,
                max_size=4,
                unique=True,
            )
        ),
        avoid_impressions=draw(
            st.lists(
                st.sampled_from(avoid_impressions),
                min_size=1,
                max_size=3,
                unique=True,
            )
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _create_review_service() -> ReviewService:
    """Create a ReviewService with mocked dependencies."""
    mock_llm = MagicMock()
    mock_llm.dispatch = AsyncMock(return_value="mocked response")
    mock_schema = MagicMock()
    mock_repo = MagicMock()
    mock_pe = MagicMock()
    return ReviewService(
        llm_router=mock_llm,
        schema_registry=mock_schema,
        review_repository=mock_repo,
        personalization_engine=mock_pe,
    )


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestProperty7ReviewCritiqueVoiceInclusion:
    """Property 7: Review critique prompt includes Voice_Asset when present.

    For any beneficiary with a Voice_Asset, the fresh-context critique prompt
    constructed by Review_Service SHALL include the Voice_Asset's register,
    vocabulary_avoid items, and exemplar passages as reference material for
    the reviewer.

    **Validates: Requirements 3.1**
    """

    @given(voice_asset=valid_voice_asset_strategy())
    @settings(max_examples=200)
    def test_register_value_included_in_critique_instructions(
        self,
        voice_asset: VoiceAsset,
    ) -> None:
        """FOR ANY valid VoiceAsset, the critique instructions SHALL contain
        the register value.

        **Validates: Requirements 3.1**
        """
        service = _create_review_service()
        instructions = service._build_voice_critique_instructions(
            voice_asset=voice_asset,
            behavioral_profile=None,
        )

        assert voice_asset.register.value in instructions, (
            f"Register value {voice_asset.register.value!r} not found in "
            f"critique instructions.\nGot:\n{instructions}"
        )

    @given(voice_asset=valid_voice_asset_strategy())
    @settings(max_examples=200)
    def test_all_vocabulary_avoid_items_included(
        self,
        voice_asset: VoiceAsset,
    ) -> None:
        """FOR ANY valid VoiceAsset, all vocabulary_avoid items SHALL appear
        in the critique instructions.

        **Validates: Requirements 3.1**
        """
        service = _create_review_service()
        instructions = service._build_voice_critique_instructions(
            voice_asset=voice_asset,
            behavioral_profile=None,
        )

        for item in voice_asset.vocabulary_avoid:
            assert item in instructions, (
                f"vocabulary_avoid item {item!r} not found in critique "
                f"instructions.\nAvoid list: {voice_asset.vocabulary_avoid}\n"
                f"Got:\n{instructions}"
            )

    @given(voice_asset=valid_voice_asset_strategy())
    @settings(max_examples=200)
    def test_all_exemplar_passage_texts_included(
        self,
        voice_asset: VoiceAsset,
    ) -> None:
        """FOR ANY valid VoiceAsset, all exemplar passage texts SHALL appear
        in the critique instructions.

        **Validates: Requirements 3.1**
        """
        service = _create_review_service()
        instructions = service._build_voice_critique_instructions(
            voice_asset=voice_asset,
            behavioral_profile=None,
        )

        for exemplar in voice_asset.exemplar_passages:
            assert exemplar.text in instructions, (
                f"Exemplar text not found in critique instructions.\n"
                f"Missing: {exemplar.text[:80]!r}...\n"
                f"Got:\n{instructions}"
            )

    @given(
        voice_asset=valid_voice_asset_strategy(),
        behavioral_profile=behavioral_profile_strategy(),
    )
    @settings(max_examples=200)
    def test_combined_voice_and_behavioral_profile_inclusion(
        self,
        voice_asset: VoiceAsset,
        behavioral_profile: BehavioralProfileAsset,
    ) -> None:
        """FOR ANY valid VoiceAsset with a BehavioralProfileAsset, the critique
        instructions SHALL contain register, all vocabulary_avoid items, all
        exemplar texts, AND the behavioral profile's interpersonal_style.

        **Validates: Requirements 3.1**
        """
        service = _create_review_service()
        instructions = service._build_voice_critique_instructions(
            voice_asset=voice_asset,
            behavioral_profile=behavioral_profile,
        )

        # Register value must be present
        assert voice_asset.register.value in instructions, (
            f"Register {voice_asset.register.value!r} not in critique instructions"
        )

        # All vocabulary_avoid items must be present
        for item in voice_asset.vocabulary_avoid:
            assert item in instructions, (
                f"vocabulary_avoid item {item!r} not in critique instructions"
            )

        # All exemplar passage texts must be present
        for exemplar in voice_asset.exemplar_passages:
            assert exemplar.text in instructions, (
                f"Exemplar text not in critique instructions: {exemplar.text[:80]!r}..."
            )

        # Behavioral profile interpersonal_style must be present
        assert behavioral_profile.interpersonal_style in instructions, (
            f"interpersonal_style {behavioral_profile.interpersonal_style!r} "
            f"not in critique instructions"
        )

        # Behavioral profile avoid_impressions must be present
        for avoid in behavioral_profile.avoid_impressions:
            assert avoid in instructions, (
                f"avoid_impression {avoid!r} not in critique instructions"
            )
