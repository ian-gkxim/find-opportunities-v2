# Feature: sender-voice-assets, Property 3: Graceful degradation and voice_applied tagging
"""Property-based test for PersonalizationEngine graceful degradation.

Generates random enrichment data with optional Voice_Asset presence.
Verifies:
- voice_applied=False when no asset is provided
- voice_applied=True when a valid VoiceAsset is provided
- No exceptions in either case (graceful degradation)

**Validates: Requirements 1.3, 4.1**
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.personalization_engine import (
    EnrichmentData,
    PersonalizationEngine,
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

# Text strategy for fields that need printable content
_printable_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        min_codepoint=32,
        max_codepoint=126,
    ),
    min_size=1,
    max_size=50,
)


@st.composite
def enrichment_data_strategy(draw):
    """Generate random EnrichmentData with optional fields."""
    industry = draw(st.one_of(st.none(), _printable_text))
    tech_stack = draw(st.lists(_printable_text, min_size=0, max_size=3))
    company_size = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=100000)))
    recent_funding = draw(st.one_of(st.none(), _printable_text))
    intent_signals = draw(st.lists(_printable_text, min_size=0, max_size=3))

    hook_st = st.fixed_dictionaries({
        "type": st.sampled_from(["news", "job_posting", "tech_adoption"]),
        "topic": _printable_text,
    })
    hooks = draw(st.lists(hook_st, min_size=0, max_size=2))

    return EnrichmentData(
        industry=industry,
        tech_stack=tech_stack,
        company_size=company_size,
        recent_funding=recent_funding,
        intent_signals=intent_signals,
        hooks=hooks,
    )


# Exemplar text must be 50-500 chars for a valid VoiceAsset
_exemplar_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        min_codepoint=32,
        max_codepoint=126,
    ),
    min_size=50,
    max_size=200,
)


@st.composite
def valid_voice_asset_strategy(draw):
    """Generate a valid VoiceAsset (passes validate())."""
    num_exemplars = draw(st.integers(min_value=2, max_value=3))
    exemplars = [
        ExemplarPassage(
            text=draw(_exemplar_text),
            context=draw(st.one_of(st.none(), st.text(min_size=1, max_size=20))),
        )
        for _ in range(num_exemplars)
    ]

    avoid_count = draw(st.integers(min_value=1, max_value=5))
    vocabulary_avoid = draw(
        st.lists(_printable_text, min_size=avoid_count, max_size=avoid_count)
    )

    return VoiceAsset(
        id=draw(st.uuids().map(str)),
        beneficiary_id="consultant",
        asset_type=VoiceAssetType.WRITING_STYLE,
        register=draw(st.sampled_from(VoiceRegister)),
        sentence_length=draw(st.sampled_from(SentenceLengthPreference)),
        first_person_usage=draw(st.sampled_from(FirstPersonUsage)),
        vocabulary_prefer=draw(st.lists(_printable_text, min_size=0, max_size=4)),
        vocabulary_avoid=vocabulary_avoid,
        exemplar_passages=exemplars,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# Material type strategy
material_type_st = st.sampled_from(["cv", "cover_letter", "proposal", "email"])

# Contact seniority strategy (including None for unknown)
seniority_st = st.one_of(
    st.none(),
    st.sampled_from(["c_suite", "director", "manager", "other"]),
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _create_engine() -> PersonalizationEngine:
    """Create a PersonalizationEngine with a mocked LLM router."""
    mock_llm = MagicMock()
    mock_llm.generate_content = AsyncMock(return_value="Generated outreach content.")
    return PersonalizationEngine(llm_router=mock_llm)


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestProperty3GracefulDegradationAndVoiceApplied:
    """Property 3: Graceful degradation and voice_applied tagging.

    For any generation request where the beneficiary has no Voice_Asset configured,
    the Personalization_Engine SHALL produce a valid PersonalizationResult without
    error, and the result's voice_applied field SHALL be False. Conversely, for any
    generation request where a Voice_Asset IS present, voice_applied SHALL be True.

    **Validates: Requirements 1.3, 4.1**
    """

    @given(
        enrichment=enrichment_data_strategy(),
        material_type=material_type_st,
        contact_seniority=seniority_st,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_no_voice_asset_produces_voice_applied_false(
        self,
        enrichment: EnrichmentData,
        material_type: str,
        contact_seniority: str | None,
    ) -> None:
        """FOR ANY generation request without a Voice_Asset, the result SHALL
        have voice_applied=False and no exception is raised.

        **Validates: Requirements 1.3, 4.1**
        """
        engine = _create_engine()

        # Should not raise any exception (graceful degradation)
        result = await engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant",
            material_type=material_type,
            contact_seniority=contact_seniority,
            voice_asset=None,
        )

        assert result.voice_applied is False, (
            f"Expected voice_applied=False when no Voice_Asset provided, "
            f"got voice_applied={result.voice_applied}"
        )

    @given(
        enrichment=enrichment_data_strategy(),
        material_type=material_type_st,
        contact_seniority=seniority_st,
        voice_asset=valid_voice_asset_strategy(),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_voice_asset_present_produces_voice_applied_true(
        self,
        enrichment: EnrichmentData,
        material_type: str,
        contact_seniority: str | None,
        voice_asset: VoiceAsset,
    ) -> None:
        """FOR ANY generation request with a valid Voice_Asset, the result SHALL
        have voice_applied=True and no exception is raised.

        **Validates: Requirements 1.3, 4.1**
        """
        engine = _create_engine()

        # Should not raise any exception
        result = await engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant",
            material_type=material_type,
            contact_seniority=contact_seniority,
            voice_asset=voice_asset,
        )

        assert result.voice_applied is True, (
            f"Expected voice_applied=True when Voice_Asset is present, "
            f"got voice_applied={result.voice_applied}"
        )

    @given(
        enrichment=enrichment_data_strategy(),
        material_type=material_type_st,
        contact_seniority=seniority_st,
        voice_asset=valid_voice_asset_strategy(),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_no_error_in_either_case(
        self,
        enrichment: EnrichmentData,
        material_type: str,
        contact_seniority: str | None,
        voice_asset: VoiceAsset,
    ) -> None:
        """FOR ANY enrichment data, both with and without a Voice_Asset,
        generate_materials() SHALL produce a valid PersonalizationResult
        without raising any exceptions.

        **Validates: Requirements 1.3, 4.1**
        """
        engine = _create_engine()

        # Case 1: No voice asset — graceful degradation
        result_no_voice = await engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant",
            material_type=material_type,
            contact_seniority=contact_seniority,
            voice_asset=None,
        )
        assert result_no_voice is not None
        assert isinstance(result_no_voice.content, str)
        assert result_no_voice.voice_applied is False

        # Case 2: With voice asset
        result_with_voice = await engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant",
            material_type=material_type,
            contact_seniority=contact_seniority,
            voice_asset=voice_asset,
        )
        assert result_with_voice is not None
        assert isinstance(result_with_voice.content, str)
        assert result_with_voice.voice_applied is True
