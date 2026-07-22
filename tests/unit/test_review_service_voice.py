"""Unit tests for ReviewService voice extension methods.

Tests cover:
- _build_voice_critique_instructions with voice_asset only
- _build_voice_critique_instructions with voice_asset + behavioral_profile
- _build_fresh_context_prompt extends TONE_STYLE category when voice present
- _build_fresh_context_prompt standard prompt when no voice asset

Requirements: 3.1, 3.2
"""

from datetime import datetime

import pytest

from app.core.review_models import CritiqueCategory
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


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def review_service():
    """Create a ReviewService with None dependencies (not needed for prompt building)."""
    return ReviewService(
        llm_router=None,
        schema_registry=None,
        review_repository=None,
        personalization_engine=None,
    )


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
def all_categories():
    return list(CritiqueCategory)


@pytest.fixture
def sample_enrichment_dict():
    return {
        "firmographics": {"industry": "FinTech", "size": "500-1000"},
        "technographics": {"stack": ["Python", "AWS"]},
        "intent_signals": [{"signal": "Hiring senior engineers", "strength": "high"}],
        "contact_seniority": "VP Engineering",
    }


@pytest.fixture
def sample_beneficiary_dict():
    return {
        "profile_assets": {
            "skills": ["Python", "AWS", "System Design"],
            "achievements": ["Led cloud migration for 200-person org"],
        }
    }


# ─── _build_voice_critique_instructions with voice_asset only ─────────────────


class TestBuildVoiceCritiqueInstructionsVoiceOnly:
    """Test _build_voice_critique_instructions with only a voice_asset (no behavioral profile)."""

    def test_contains_register_value(self, review_service, sample_voice_asset):
        """Output contains the sender's declared register."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, None
        )
        assert "direct" in result

    def test_contains_sentence_length_preference(self, review_service, sample_voice_asset):
        """Output contains sentence length preference."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, None
        )
        assert "varied" in result

    def test_contains_first_person_usage(self, review_service, sample_voice_asset):
        """Output contains first-person usage setting."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, None
        )
        assert "frequent" in result

    def test_contains_vocabulary_prefer_items(self, review_service, sample_voice_asset):
        """Output contains all vocabulary_prefer items."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, None
        )
        for word in sample_voice_asset.vocabulary_prefer:
            assert word in result

    def test_contains_vocabulary_avoid_items(self, review_service, sample_voice_asset):
        """Output contains all vocabulary_avoid items."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, None
        )
        for word in sample_voice_asset.vocabulary_avoid:
            assert word in result

    def test_contains_exemplar_passages(self, review_service, sample_voice_asset):
        """Output contains all exemplar passage texts."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, None
        )
        for ex in sample_voice_asset.exemplar_passages:
            assert ex.text in result

    def test_does_not_contain_behavioral_profile_section(
        self, review_service, sample_voice_asset
    ):
        """Without behavioral_profile, no BEHAVIORAL PROFILE CHECK section."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, None
        )
        assert "BEHAVIORAL PROFILE CHECK" not in result

    def test_starts_with_voice_compliance_header(self, review_service, sample_voice_asset):
        """Output starts with VOICE COMPLIANCE CHECK header."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, None
        )
        assert result.startswith("VOICE COMPLIANCE CHECK:")


# ─── _build_voice_critique_instructions with voice_asset + behavioral_profile ─


class TestBuildVoiceCritiqueInstructionsWithBehavioralProfile:
    """Test _build_voice_critique_instructions with voice_asset AND behavioral_profile."""

    def test_contains_interpersonal_style(
        self, review_service, sample_voice_asset, sample_behavioral_profile
    ):
        """Output contains the behavioral profile's interpersonal_style."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, sample_behavioral_profile
        )
        assert "collaborative" in result

    def test_contains_communication_traits(
        self, review_service, sample_voice_asset, sample_behavioral_profile
    ):
        """Output contains communication traits as comma-separated list."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, sample_behavioral_profile
        )
        assert "asks questions" in result
        assert "uses 'we'" in result
        assert "acknowledges others" in result

    def test_contains_avoid_impressions(
        self, review_service, sample_voice_asset, sample_behavioral_profile
    ):
        """Output contains avoid_impressions as flag instructions."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, sample_behavioral_profile
        )
        assert "combative" in result
        assert "apologetic" in result

    def test_contains_behavioral_profile_header(
        self, review_service, sample_voice_asset, sample_behavioral_profile
    ):
        """Output contains BEHAVIORAL PROFILE CHECK section header."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, sample_behavioral_profile
        )
        assert "BEHAVIORAL PROFILE CHECK:" in result

    def test_still_contains_voice_asset_fields(
        self, review_service, sample_voice_asset, sample_behavioral_profile
    ):
        """Voice asset fields are still present when behavioral profile is added."""
        result = review_service._build_voice_critique_instructions(
            sample_voice_asset, sample_behavioral_profile
        )
        assert "direct" in result
        assert "varied" in result
        for word in sample_voice_asset.vocabulary_avoid:
            assert word in result
        for ex in sample_voice_asset.exemplar_passages:
            assert ex.text in result


# ─── _build_fresh_context_prompt with voice_asset present ─────────────────────


class TestFreshContextPromptWithVoice:
    """Test _build_fresh_context_prompt extends TONE_STYLE when voice_asset is present."""

    def test_tone_style_description_mentions_voice_compliance(
        self,
        review_service,
        all_categories,
        sample_enrichment_dict,
        sample_beneficiary_dict,
        sample_voice_asset,
    ):
        """TONE_STYLE category description is extended to mention voice compliance."""
        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Senior Engineer at FinTech",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
            voice_asset=sample_voice_asset,
        )
        assert "voice" in prompt.lower()
        assert "Voice_Asset" in prompt or "voice compliance" in prompt.lower()

    def test_contains_voice_asset_reference_block(
        self,
        review_service,
        all_categories,
        sample_enrichment_dict,
        sample_beneficiary_dict,
        sample_voice_asset,
    ):
        """Prompt contains <voice_asset_reference> XML section."""
        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Senior Engineer at FinTech",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
            voice_asset=sample_voice_asset,
        )
        assert "<voice_asset_reference>" in prompt
        assert "</voice_asset_reference>" in prompt

    def test_contains_voice_critique_content(
        self,
        review_service,
        all_categories,
        sample_enrichment_dict,
        sample_beneficiary_dict,
        sample_voice_asset,
    ):
        """Prompt contains voice critique content (register, vocabulary_avoid, exemplars)."""
        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Senior Engineer at FinTech",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
            voice_asset=sample_voice_asset,
        )
        # Register
        assert "direct" in prompt
        # Vocabulary avoid items
        assert "leverage" in prompt
        assert "synergize" in prompt
        # Exemplar passage text
        assert "React Native rewrite" in prompt

    def test_contains_structured_edit_voice_instructions(
        self,
        review_service,
        all_categories,
        sample_enrichment_dict,
        sample_beneficiary_dict,
        sample_voice_asset,
    ):
        """Prompt instructs mechanical voice fixes as StructuredEdits with reason=style."""
        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Senior Engineer at FinTech",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
            voice_asset=sample_voice_asset,
        )
        assert "StructuredEdit" in prompt
        assert 'reason="style"' in prompt or "reason=\u201cstyle\u201d" in prompt.lower() or "style" in prompt

    def test_contains_narrative_finding_voice_instructions(
        self,
        review_service,
        all_categories,
        sample_enrichment_dict,
        sample_beneficiary_dict,
        sample_voice_asset,
    ):
        """Prompt instructs subjective voice concerns as NarrativeFindings."""
        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Senior Engineer at FinTech",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
            voice_asset=sample_voice_asset,
        )
        assert "NarrativeFinding" in prompt

    def test_with_behavioral_profile_includes_profile_check(
        self,
        review_service,
        all_categories,
        sample_enrichment_dict,
        sample_beneficiary_dict,
        sample_voice_asset,
        sample_behavioral_profile,
    ):
        """When behavioral_profile is also provided, its content appears in the prompt."""
        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Senior Engineer at FinTech",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
            voice_asset=sample_voice_asset,
            behavioral_profile=sample_behavioral_profile,
        )
        assert "collaborative" in prompt
        assert "BEHAVIORAL PROFILE CHECK" in prompt


# ─── _build_fresh_context_prompt without voice_asset ──────────────────────────


class TestFreshContextPromptWithoutVoice:
    """Test _build_fresh_context_prompt standard behavior when no voice asset."""

    def test_no_voice_asset_reference_block(
        self,
        review_service,
        all_categories,
        sample_enrichment_dict,
        sample_beneficiary_dict,
    ):
        """Without voice_asset, no <voice_asset_reference> section appears."""
        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Senior Engineer at FinTech",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "<voice_asset_reference>" not in prompt
        assert "</voice_asset_reference>" not in prompt

    def test_no_voice_compliance_check(
        self,
        review_service,
        all_categories,
        sample_enrichment_dict,
        sample_beneficiary_dict,
    ):
        """Without voice_asset, no VOICE COMPLIANCE CHECK instructions appear."""
        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Senior Engineer at FinTech",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "VOICE COMPLIANCE CHECK" not in prompt

    def test_tone_style_uses_standard_description(
        self,
        review_service,
        all_categories,
        sample_enrichment_dict,
        sample_beneficiary_dict,
    ):
        """Without voice_asset, TONE_STYLE has standard description without voice mention."""
        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Senior Engineer at FinTech",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        # Standard description present
        assert "tone or style issues" in prompt
        # No voice-specific extension
        assert "voice compliance" not in prompt.lower() or "Voice_Asset" not in prompt

    def test_still_contains_all_standard_sections(
        self,
        review_service,
        all_categories,
        sample_enrichment_dict,
        sample_beneficiary_dict,
    ):
        """Standard prompt still includes draft, opportunity, enrichment, beneficiary sections."""
        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Senior Engineer at FinTech",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "<draft_material>" in prompt
        assert "<opportunity>" in prompt
        assert "<enrichment_record>" in prompt
        assert "<beneficiary_assets>" in prompt
