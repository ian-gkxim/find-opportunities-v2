"""Unit tests for PersonalizationEngine voice integration methods.

Tests cover:
- _build_voice_directives: formatting, conflict resolution
- _build_avoid_prohibitions: multiple avoid items
- _build_exemplar_section: with/without context
- C_SUITE + DIRECT register conflict resolution
- voice_applied tagging: True/False/graceful degradation

Requirements: 2.1, 2.2, 2.3
"""

import asyncio
from datetime import datetime

import pytest

from app.core.personalization_engine import (
    EnrichmentData,
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


# ─── Fake LLM Router ─────────────────────────────────────────────────────────


class FakeLLMRouter:
    """Fake LLM router that returns predictable content for testing."""

    def __init__(self, response: str | None = None, timeout: bool = False):
        self._response = response
        self._timeout = timeout
        self.last_prompt: str | None = None
        self.call_count = 0

    async def generate_content(
        self, prompt: str, context: dict, material_type: str
    ) -> str:
        self.last_prompt = prompt
        self.call_count += 1
        if self._timeout:
            await asyncio.sleep(60)
        return self._response or "Generated content."


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_llm() -> FakeLLMRouter:
    return FakeLLMRouter()


@pytest.fixture
def engine(fake_llm) -> PersonalizationEngine:
    return PersonalizationEngine(llm_router=fake_llm)


@pytest.fixture
def sample_voice_asset() -> VoiceAsset:
    """A valid VoiceAsset with DIRECT register for testing."""
    return VoiceAsset(
        id="va-001",
        beneficiary_id="consultant-1",
        asset_type=VoiceAssetType.WRITING_STYLE,
        register=VoiceRegister.DIRECT,
        sentence_length=SentenceLengthPreference.VARIED,
        first_person_usage=FirstPersonUsage.FREQUENT,
        vocabulary_prefer=["ship", "build", "trade-off"],
        vocabulary_avoid=["leverage", "synergize", "circle back"],
        exemplar_passages=[
            ExemplarPassage(
                text="I noticed your team just shipped a React Native rewrite — "
                "that's a bold move for a Series B company.",
                context="cold email opener",
            ),
            ExemplarPassage(
                text="Let me be direct: I've built three platform teams from scratch "
                "in fintech, and each time the hardest part wasn't the architecture.",
                context="cover letter body",
            ),
        ],
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
    )


@pytest.fixture
def sample_behavioral_profile() -> BehavioralProfileAsset:
    """A BehavioralProfileAsset for tone guidance testing."""
    return BehavioralProfileAsset(
        id="bp-001",
        beneficiary_id="consultant-1",
        asset_type=VoiceAssetType.BEHAVIORAL_PROFILE,
        interpersonal_style="collaborative",
        communication_traits=["asks questions", "uses 'we'", "acknowledges others"],
        avoid_impressions=["combative", "apologetic"],
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
    )


@pytest.fixture
def enrichment() -> EnrichmentData:
    return EnrichmentData(
        industry="fintech",
        tech_stack=["python", "react"],
        company_size=100,
    )


# ─── _build_voice_directives Tests ───────────────────────────────────────────


class TestBuildVoiceDirectives:
    """Test _build_voice_directives produces correctly formatted directive block."""

    def test_includes_header(self, engine, sample_voice_asset):
        """Directive block starts with SENDER VOICE DIRECTIVES header."""
        result = engine._build_voice_directives(
            sample_voice_asset, None, SeniorityLevel.DIRECTOR
        )
        assert result.startswith("SENDER VOICE DIRECTIVES:")

    def test_includes_register(self, engine, sample_voice_asset):
        """Directive block contains the register value."""
        result = engine._build_voice_directives(
            sample_voice_asset, None, SeniorityLevel.DIRECTOR
        )
        assert "Register: direct" in result

    def test_includes_sentence_length(self, engine, sample_voice_asset):
        """Directive block contains sentence length preference."""
        result = engine._build_voice_directives(
            sample_voice_asset, None, SeniorityLevel.DIRECTOR
        )
        assert "Sentence length: varied" in result

    def test_includes_first_person_usage(self, engine, sample_voice_asset):
        """Directive block contains first-person usage setting."""
        result = engine._build_voice_directives(
            sample_voice_asset, None, SeniorityLevel.DIRECTOR
        )
        assert "First-person usage: frequent" in result

    def test_includes_vocabulary_preferences(self, engine, sample_voice_asset):
        """Directive block includes vocabulary prefer items."""
        result = engine._build_voice_directives(
            sample_voice_asset, None, SeniorityLevel.DIRECTOR
        )
        assert "VOCABULARY TO PREFER:" in result
        assert '"ship"' in result
        assert '"build"' in result
        assert '"trade-off"' in result

    def test_includes_conflict_resolution(self, engine, sample_voice_asset):
        """Directive block includes conflict resolution instructions."""
        result = engine._build_voice_directives(
            sample_voice_asset, None, SeniorityLevel.DIRECTOR
        )
        assert "CONFLICT RESOLUTION:" in result
        assert "FORMALITY_LEVEL (director)" in result
        assert "VOICE DIRECTIVES" in result

    def test_no_behavioral_profile_omits_tone_guidance(self, engine, sample_voice_asset):
        """When no behavioral profile, tone guidance section is absent."""
        result = engine._build_voice_directives(
            sample_voice_asset, None, SeniorityLevel.DIRECTOR
        )
        assert "TONE GUIDANCE:" not in result

    def test_with_behavioral_profile_includes_tone_guidance(
        self, engine, sample_voice_asset, sample_behavioral_profile
    ):
        """When behavioral profile is present, tone guidance is included."""
        result = engine._build_voice_directives(
            sample_voice_asset, sample_behavioral_profile, SeniorityLevel.DIRECTOR
        )
        assert "TONE GUIDANCE:" in result
        assert "Interpersonal style: collaborative" in result
        assert "Communication traits: asks questions, uses 'we', acknowledges others" in result

    def test_empty_vocabulary_prefer_skips_section(self, engine):
        """When vocabulary_prefer is empty, VOCABULARY TO PREFER section is omitted."""
        asset = VoiceAsset(
            id="va-002",
            beneficiary_id="consultant-2",
            asset_type=VoiceAssetType.WRITING_STYLE,
            register=VoiceRegister.WARM,
            sentence_length=SentenceLengthPreference.MEDIUM,
            first_person_usage=FirstPersonUsage.MODERATE,
            vocabulary_prefer=[],
            vocabulary_avoid=["jargon"],
            exemplar_passages=[
                ExemplarPassage(text="x" * 50, context=None),
                ExemplarPassage(text="y" * 50, context=None),
            ],
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 1),
        )
        result = engine._build_voice_directives(asset, None, SeniorityLevel.MANAGER)
        assert "VOCABULARY TO PREFER:" not in result


# ─── _build_avoid_prohibitions Tests ──────────────────────────────────────────


class TestBuildAvoidProhibitions:
    """Test _build_avoid_prohibitions with multiple avoid items."""

    def test_header_present(self, engine):
        """Output starts with PROHIBITIONS header."""
        result = engine._build_avoid_prohibitions(["leverage"])
        assert result.startswith("PROHIBITIONS (never use these words/constructions):")

    def test_single_item(self, engine):
        """Single avoid item formatted correctly."""
        result = engine._build_avoid_prohibitions(["leverage"])
        assert "- NEVER: leverage" in result

    def test_multiple_items(self, engine):
        """Multiple avoid items each get their own NEVER line."""
        avoid_list = ["leverage", "synergize", "circle back", "deep dive"]
        result = engine._build_avoid_prohibitions(avoid_list)
        assert "- NEVER: leverage" in result
        assert "- NEVER: synergize" in result
        assert "- NEVER: circle back" in result
        assert "- NEVER: deep dive" in result

    def test_line_count_matches_items_plus_header(self, engine):
        """Output has exactly len(avoid_list) + 1 lines (header + items)."""
        avoid_list = ["a", "b", "c"]
        result = engine._build_avoid_prohibitions(avoid_list)
        lines = result.split("\n")
        assert len(lines) == 4  # 1 header + 3 items

    def test_preserves_phrases_and_special_chars(self, engine):
        """Phrases with spaces and special characters are preserved."""
        avoid_list = ["I would be a great fit", "passive voice in opening sentences"]
        result = engine._build_avoid_prohibitions(avoid_list)
        assert "- NEVER: I would be a great fit" in result
        assert "- NEVER: passive voice in opening sentences" in result


# ─── _build_exemplar_section Tests ────────────────────────────────────────────


class TestBuildExemplarSection:
    """Test _build_exemplar_section with context and without context."""

    def test_header_present(self, engine):
        """Output starts with VOICE EXEMPLARS header."""
        exemplars = [ExemplarPassage(text="Hello world " * 5, context=None)]
        result = engine._build_exemplar_section(exemplars)
        assert result.startswith("VOICE EXEMPLARS (write in this style):")

    def test_with_context(self, engine):
        """Exemplar with context includes context in parentheses."""
        exemplars = [
            ExemplarPassage(
                text="I noticed your team just shipped a React Native rewrite.",
                context="cold email opener",
            )
        ]
        result = engine._build_exemplar_section(exemplars)
        assert '(cold email opener)' in result
        assert 'Example 1 (cold email opener):' in result
        assert "I noticed your team just shipped a React Native rewrite." in result

    def test_without_context(self, engine):
        """Exemplar without context omits parentheses."""
        exemplars = [
            ExemplarPassage(
                text="Let me be direct about my experience in this domain.",
                context=None,
            )
        ]
        result = engine._build_exemplar_section(exemplars)
        assert 'Example 1:' in result
        # No parentheses after the number
        assert 'Example 1 (' not in result
        assert "Let me be direct about my experience in this domain." in result

    def test_multiple_exemplars_numbered(self, engine):
        """Multiple exemplars are numbered sequentially."""
        exemplars = [
            ExemplarPassage(text="First exemplar text " * 3, context="opener"),
            ExemplarPassage(text="Second exemplar text " * 3, context=None),
            ExemplarPassage(text="Third exemplar text " * 3, context="closing"),
        ]
        result = engine._build_exemplar_section(exemplars)
        assert "Example 1 (opener):" in result
        assert "Example 2:" in result
        assert "Example 3 (closing):" in result

    def test_mixed_context_and_no_context(self, engine):
        """Mix of exemplars with and without context both work correctly."""
        exemplars = [
            ExemplarPassage(text="A" * 60, context="cold email opener"),
            ExemplarPassage(text="B" * 60, context=None),
        ]
        result = engine._build_exemplar_section(exemplars)
        assert "Example 1 (cold email opener):" in result
        assert "Example 2:" in result
        # Ensure no spurious parentheses on example 2
        lines = result.split("\n")
        example_2_line = [l for l in lines if "Example 2" in l][0]
        assert "(" not in example_2_line.split("Example 2")[1].split(":")[0]


# ─── C_SUITE + DIRECT Register Conflict Resolution Tests ─────────────────────


class TestConflictResolutionCSuiteDirectRegister:
    """Test C_SUITE formality + DIRECT register → formal salutation but direct body."""

    def test_formal_salutation_direct_body(self, engine, sample_voice_asset):
        """C_SUITE formality level with DIRECT register:
        - Salutation/closing follows FORMALITY_LEVEL (c_suite)
        - Body prose follows VOICE DIRECTIVES (direct register)
        """
        result = engine._build_voice_directives(
            sample_voice_asset, None, SeniorityLevel.C_SUITE
        )
        # Conflict resolution states formality for salutation
        assert "FORMALITY_LEVEL (c_suite)" in result
        # Body follows voice directives
        assert "VOICE DIRECTIVES" in result
        # Register is direct (from the voice asset, not overridden by c_suite)
        assert "Register: direct" in result

    def test_all_seniority_levels_in_conflict_resolution(self, engine, sample_voice_asset):
        """All seniority levels produce correct FORMALITY_LEVEL reference."""
        for level in SeniorityLevel:
            result = engine._build_voice_directives(
                sample_voice_asset, None, level
            )
            assert f"FORMALITY_LEVEL ({level.value})" in result
            # Register is always the voice asset's register, independent of formality
            assert "Register: direct" in result


# ─── voice_applied Tag Tests ──────────────────────────────────────────────────


class TestVoiceAppliedTag:
    """Test voice_applied tag: True when present, False when absent, False on error."""

    @pytest.mark.asyncio
    async def test_voice_applied_true_when_voice_asset_present(
        self, engine, enrichment, sample_voice_asset
    ):
        """voice_applied=True when a valid Voice_Asset is provided."""
        result = await engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="director",
            voice_asset=sample_voice_asset,
        )
        assert result.voice_applied is True

    @pytest.mark.asyncio
    async def test_voice_applied_false_when_voice_asset_absent(
        self, engine, enrichment
    ):
        """voice_applied=False when no Voice_Asset is provided."""
        result = await engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="director",
            voice_asset=None,
        )
        assert result.voice_applied is False

    @pytest.mark.asyncio
    async def test_voice_applied_false_on_voice_integration_error(self, enrichment):
        """voice_applied=False when voice integration raises an exception (graceful degradation)."""
        fake_llm = FakeLLMRouter(response="Fallback content.")
        engine = PersonalizationEngine(llm_router=fake_llm)

        # Create a voice asset that will cause _build_voice_directives to fail
        # by providing a malformed object (register without .value attribute)
        class BrokenVoiceAsset:
            """Simulates a malformed voice asset that triggers an exception."""
            register = None  # Will raise AttributeError on .value access
            sentence_length = SentenceLengthPreference.SHORT
            first_person_usage = FirstPersonUsage.MODERATE
            vocabulary_prefer = ["test"]
            vocabulary_avoid = ["bad"]
            exemplar_passages = []

        result = await engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="director",
            voice_asset=BrokenVoiceAsset(),  # type: ignore[arg-type]
        )
        # Graceful degradation: no error, voice_applied=False
        assert result.voice_applied is False
        assert result.content == "Fallback content."

    @pytest.mark.asyncio
    async def test_voice_directives_injected_into_prompt(
        self, enrichment, sample_voice_asset
    ):
        """When voice_asset present, voice directives appear in the LLM prompt."""
        fake_llm = FakeLLMRouter(response="Voice content.")
        engine = PersonalizationEngine(llm_router=fake_llm)

        await engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="c_suite",
            voice_asset=sample_voice_asset,
        )

        prompt = fake_llm.last_prompt
        assert "SENDER VOICE DIRECTIVES:" in prompt
        assert "PROHIBITIONS (never use these words/constructions):" in prompt
        assert "VOICE EXEMPLARS (write in this style):" in prompt
        assert "Register: direct" in prompt
        assert "- NEVER: leverage" in prompt

    @pytest.mark.asyncio
    async def test_no_voice_directives_when_absent(self, enrichment):
        """When no voice_asset, voice directives do NOT appear in the prompt."""
        fake_llm = FakeLLMRouter(response="Standard content.")
        engine = PersonalizationEngine(llm_router=fake_llm)

        await engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="director",
            voice_asset=None,
        )

        prompt = fake_llm.last_prompt
        assert "SENDER VOICE DIRECTIVES:" not in prompt
        assert "PROHIBITIONS" not in prompt
        assert "VOICE EXEMPLARS" not in prompt
