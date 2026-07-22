# Feature: sender-voice-assets, Property 6: Conflict resolution
"""Property-based test for conflict resolution in _build_voice_directives().

Generates all Formality_Level (SeniorityLevel) × VoiceRegister combinations
and verifies that the directive text instructs the LLM to apply Formality_Level
for salutation and closing conventions and Voice_Asset for body prose.

**Validates: Requirements 2.2**
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

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

formality_level_st = st.sampled_from(list(SeniorityLevel))
voice_register_st = st.sampled_from(list(VoiceRegister))


@st.composite
def valid_voice_asset_strategy(draw, register=None):
    """Generate a valid VoiceAsset with a specific or random register."""
    chosen_register = register if register is not None else draw(voice_register_st)
    num_exemplars = draw(st.integers(min_value=2, max_value=3))
    exemplars = [
        ExemplarPassage(
            text=draw(
                st.text(
                    alphabet=st.characters(
                        whitelist_categories=("L", "N", "P", "Z"),
                        min_codepoint=32,
                        max_codepoint=126,
                    ),
                    min_size=50,
                    max_size=100,
                )
            ),
            context=draw(st.one_of(st.none(), st.text(min_size=1, max_size=20))),
        )
        for _ in range(num_exemplars)
    ]

    return VoiceAsset(
        id=draw(st.uuids().map(str)),
        beneficiary_id=draw(st.text(min_size=1, max_size=10)),
        asset_type=VoiceAssetType.WRITING_STYLE,
        register=chosen_register,
        sentence_length=draw(st.sampled_from(list(SentenceLengthPreference))),
        first_person_usage=draw(st.sampled_from(list(FirstPersonUsage))),
        vocabulary_prefer=draw(
            st.lists(st.text(min_size=1, max_size=15), min_size=1, max_size=4)
        ),
        vocabulary_avoid=draw(
            st.lists(st.text(min_size=1, max_size=15), min_size=1, max_size=4)
        ),
        exemplar_passages=exemplars,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@st.composite
def optional_behavioral_profile_strategy(draw):
    """Generate an optional BehavioralProfileAsset."""
    if draw(st.booleans()):
        return BehavioralProfileAsset(
            id=draw(st.uuids().map(str)),
            beneficiary_id=draw(st.text(min_size=1, max_size=10)),
            asset_type=VoiceAssetType.BEHAVIORAL_PROFILE,
            interpersonal_style=draw(
                st.sampled_from(["collaborative", "driving", "analytical", "expressive"])
            ),
            communication_traits=draw(
                st.lists(st.text(min_size=3, max_size=20), min_size=1, max_size=3)
            ),
            avoid_impressions=draw(
                st.lists(st.text(min_size=3, max_size=20), min_size=1, max_size=3)
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    return None


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestProperty6ConflictResolution:
    """Property 6: Conflict resolution — Formality wins salutation/closing, Voice wins body.

    **Validates: Requirements 2.2**
    """

    def _create_engine(self) -> PersonalizationEngine:
        """Create a PersonalizationEngine with mocked LLM dependency."""
        mock_llm = MagicMock()
        return PersonalizationEngine(llm_router=mock_llm)

    @given(
        formality_level=formality_level_st,
        voice_register=voice_register_st,
        behavioral_profile=optional_behavioral_profile_strategy(),
    )
    @settings(max_examples=200)
    def test_directive_instructs_formality_for_salutation_and_closing(
        self,
        formality_level: SeniorityLevel,
        voice_register: VoiceRegister,
        behavioral_profile: BehavioralProfileAsset | None,
    ) -> None:
        """FOR ANY combination of Formality_Level and VoiceRegister, the
        directive text instructs to follow FORMALITY_LEVEL for salutation
        and closing conventions.

        **Validates: Requirements 2.2**
        """
        engine = self._create_engine()
        voice_asset = VoiceAsset(
            id="test-id",
            beneficiary_id="test-ben",
            asset_type=VoiceAssetType.WRITING_STYLE,
            register=voice_register,
            sentence_length=SentenceLengthPreference.MEDIUM,
            first_person_usage=FirstPersonUsage.MODERATE,
            vocabulary_prefer=["build", "ship"],
            vocabulary_avoid=["leverage"],
            exemplar_passages=[
                ExemplarPassage(text="x" * 50, context="test"),
                ExemplarPassage(text="y" * 50, context="test"),
            ],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        directives = engine._build_voice_directives(
            voice_asset=voice_asset,
            behavioral_profile=behavioral_profile,
            formality_level=formality_level,
        )

        # Verify: directive instructs formality level for salutation/closing
        expected_formality_instruction = (
            f"For salutation and closing: follow FORMALITY_LEVEL ({formality_level.value})"
        )
        assert expected_formality_instruction in directives, (
            f"Directive missing formality instruction for salutation/closing.\n"
            f"Expected: '{expected_formality_instruction}'\n"
            f"Formality: {formality_level.value}, Register: {voice_register.value}\n"
            f"Got directive:\n{directives}"
        )

    @given(
        formality_level=formality_level_st,
        voice_register=voice_register_st,
        behavioral_profile=optional_behavioral_profile_strategy(),
    )
    @settings(max_examples=200)
    def test_directive_instructs_voice_asset_for_body_prose(
        self,
        formality_level: SeniorityLevel,
        voice_register: VoiceRegister,
        behavioral_profile: BehavioralProfileAsset | None,
    ) -> None:
        """FOR ANY combination of Formality_Level and VoiceRegister, the
        directive text instructs to follow VOICE DIRECTIVES for body prose.

        **Validates: Requirements 2.2**
        """
        engine = self._create_engine()
        voice_asset = VoiceAsset(
            id="test-id",
            beneficiary_id="test-ben",
            asset_type=VoiceAssetType.WRITING_STYLE,
            register=voice_register,
            sentence_length=SentenceLengthPreference.MEDIUM,
            first_person_usage=FirstPersonUsage.MODERATE,
            vocabulary_prefer=["build", "ship"],
            vocabulary_avoid=["leverage"],
            exemplar_passages=[
                ExemplarPassage(text="x" * 50, context="test"),
                ExemplarPassage(text="y" * 50, context="test"),
            ],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        directives = engine._build_voice_directives(
            voice_asset=voice_asset,
            behavioral_profile=behavioral_profile,
            formality_level=formality_level,
        )

        # Verify: directive instructs voice asset for body prose
        expected_body_instruction = (
            "For body prose: follow these VOICE DIRECTIVES"
        )
        assert expected_body_instruction in directives, (
            f"Directive missing voice instruction for body prose.\n"
            f"Expected: '{expected_body_instruction}'\n"
            f"Formality: {formality_level.value}, Register: {voice_register.value}\n"
            f"Got directive:\n{directives}"
        )

    @given(
        formality_level=formality_level_st,
        voice_asset=valid_voice_asset_strategy(),
        behavioral_profile=optional_behavioral_profile_strategy(),
    )
    @settings(max_examples=200)
    def test_all_combinations_produce_both_conflict_resolution_instructions(
        self,
        formality_level: SeniorityLevel,
        voice_asset: VoiceAsset,
        behavioral_profile: BehavioralProfileAsset | None,
    ) -> None:
        """FOR ANY Formality_Level × VoiceRegister combination with varied
        VoiceAsset content, the directive text contains BOTH conflict
        resolution instructions: Formality for salutation/closing AND
        Voice for body prose.

        **Validates: Requirements 2.2**
        """
        engine = self._create_engine()

        directives = engine._build_voice_directives(
            voice_asset=voice_asset,
            behavioral_profile=behavioral_profile,
            formality_level=formality_level,
        )

        # Must contain the conflict resolution section header
        assert "CONFLICT RESOLUTION:" in directives, (
            f"Directive missing 'CONFLICT RESOLUTION:' section.\n"
            f"Got directive:\n{directives}"
        )

        # Must instruct formality for salutation/closing
        expected_formality = (
            f"For salutation and closing: follow FORMALITY_LEVEL ({formality_level.value})"
        )
        assert expected_formality in directives, (
            f"Missing formality instruction for salutation/closing.\n"
            f"Expected: '{expected_formality}'\n"
            f"Got directive:\n{directives}"
        )

        # Must instruct voice for body prose
        assert "For body prose: follow these VOICE DIRECTIVES" in directives, (
            f"Missing voice instruction for body prose.\n"
            f"Got directive:\n{directives}"
        )

        # Additionally verify the voice register is declared in the directive
        assert f"Register: {voice_asset.register.value}" in directives, (
            f"Missing register declaration in directive.\n"
            f"Expected register: {voice_asset.register.value}\n"
            f"Got directive:\n{directives}"
        )
