"""Integration tests for voice generation end-to-end flow.

Tests the full pipeline: VoiceAsset fetch → PersonalizationEngine generation
with voice → ReviewService critique with voice compliance check.

Uses mocked LLM_Router to avoid external calls while verifying the wiring
between components.

Requirements: 2.1, 3.1, 4.1
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.personalization_engine import (
    EnrichmentData,
    PersonalizationEngine,
)
from app.core.review_models import CritiqueCategory, DraftMaterial, ReviewStatus
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


# ─── FAKE LLM ROUTER ─────────────────────────────────────────────────────────


class FakeLLMRouter:
    """Fake LLM router that captures prompts and returns predictable content.

    Captures the last prompt sent for assertion, and tracks call count.
    """

    def __init__(self, response: str = "Generated outreach content."):
        self._response = response
        self.last_prompt: str | None = None
        self.call_count = 0

    async def generate_content(
        self, prompt: str, context: dict, material_type: str
    ) -> str:
        self.last_prompt = prompt
        self.call_count += 1
        return self._response


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


@pytest.fixture
def voice_asset() -> VoiceAsset:
    """A fully valid VoiceAsset simulating a DB-fetched asset."""
    return VoiceAsset(
        id="va-integ-001",
        beneficiary_id="consultant-1",
        asset_type=VoiceAssetType.WRITING_STYLE,
        register=VoiceRegister.DIRECT,
        sentence_length=SentenceLengthPreference.VARIED,
        first_person_usage=FirstPersonUsage.FREQUENT,
        vocabulary_prefer=["ship", "build", "trade-off", "bet"],
        vocabulary_avoid=["leverage", "synergize", "I would be a great fit"],
        exemplar_passages=[
            ExemplarPassage(
                text="I noticed your team just shipped a React Native rewrite — "
                "that's a bold move for a Series B company, and it tells me "
                "you value speed over committee consensus.",
                context="cold email opener",
            ),
            ExemplarPassage(
                text="Let me be direct: I've built three platform teams from "
                "scratch in fintech, and each time the hardest part wasn't "
                "the architecture — it was convincing leadership that 'move "
                "fast' and 'don't break things' aren't contradictions.",
                context="cover letter body",
            ),
        ],
        created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )


@pytest.fixture
def behavioral_profile() -> BehavioralProfileAsset:
    """A BehavioralProfileAsset simulating a DB-fetched profile."""
    return BehavioralProfileAsset(
        id="bp-integ-001",
        beneficiary_id="consultant-1",
        asset_type=VoiceAssetType.BEHAVIORAL_PROFILE,
        interpersonal_style="collaborative",
        communication_traits=["asks questions", "uses 'we'", "acknowledges others"],
        avoid_impressions=["combative", "apologetic"],
        created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )


@pytest.fixture
def enrichment() -> EnrichmentData:
    """Enrichment data representing a prospect."""
    return EnrichmentData(
        industry="fintech",
        tech_stack=["Python", "React", "AWS"],
        company_size=250,
        recent_funding="Series B $40M",
        intent_signals=["hiring ML engineers", "expanding platform team"],
        hooks=[
            {"type": "news", "text": "Just shipped React Native rewrite"},
            {"type": "job", "text": "Hiring Senior Platform Engineer"},
        ],
    )


@pytest.fixture
def fake_llm() -> FakeLLMRouter:
    """Fake LLM router that captures prompts."""
    return FakeLLMRouter(response="Personalized outreach content for the prospect.")


@pytest.fixture
def personalization_engine(fake_llm) -> PersonalizationEngine:
    """PersonalizationEngine wired with the fake LLM."""
    return PersonalizationEngine(llm_router=fake_llm)


# ─── TEST 1: VoiceAsset in DB → PersonalizationEngine → voice directives + voice_applied=True ─


class TestVoiceAssetGenerationEndToEnd:
    """Integration: VoiceAsset fetched from DB → PersonalizationEngine generates
    content with voice directives injected and voice_applied=True.

    Requirements: 2.1, 4.1
    """

    @pytest.mark.asyncio
    async def test_voice_asset_produces_voice_applied_true(
        self, personalization_engine, enrichment, voice_asset
    ):
        """Full flow: voice asset present → voice_applied=True on result."""
        result = await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="director",
            voice_asset=voice_asset,
        )

        assert result.voice_applied is True

    @pytest.mark.asyncio
    async def test_prompt_contains_voice_directives_header(
        self, personalization_engine, fake_llm, enrichment, voice_asset
    ):
        """Full flow: voice directives block injected into generation prompt."""
        await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="c_suite",
            voice_asset=voice_asset,
        )

        prompt = fake_llm.last_prompt
        assert "SENDER VOICE DIRECTIVES:" in prompt

    @pytest.mark.asyncio
    async def test_prompt_contains_register_value(
        self, personalization_engine, fake_llm, enrichment, voice_asset
    ):
        """Full flow: prompt includes the Voice_Asset register value."""
        await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="director",
            voice_asset=voice_asset,
        )

        prompt = fake_llm.last_prompt
        assert "Register: direct" in prompt

    @pytest.mark.asyncio
    async def test_prompt_contains_all_avoid_prohibitions(
        self, personalization_engine, fake_llm, enrichment, voice_asset
    ):
        """Full flow: every vocabulary_avoid item appears as NEVER prohibition."""
        await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="cover_letter",
            contact_seniority="director",
            voice_asset=voice_asset,
        )

        prompt = fake_llm.last_prompt
        assert "PROHIBITIONS (never use these words/constructions):" in prompt
        assert "- NEVER: leverage" in prompt
        assert "- NEVER: synergize" in prompt
        assert "- NEVER: I would be a great fit" in prompt

    @pytest.mark.asyncio
    async def test_prompt_contains_exemplar_passages(
        self, personalization_engine, fake_llm, enrichment, voice_asset
    ):
        """Full flow: exemplar passages from Voice_Asset appear in prompt."""
        await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="director",
            voice_asset=voice_asset,
        )

        prompt = fake_llm.last_prompt
        assert "VOICE EXEMPLARS (write in this style):" in prompt
        assert "React Native rewrite" in prompt
        assert "Let me be direct" in prompt

    @pytest.mark.asyncio
    async def test_prompt_contains_vocabulary_prefer(
        self, personalization_engine, fake_llm, enrichment, voice_asset
    ):
        """Full flow: vocabulary prefer items appear in prompt."""
        await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="director",
            voice_asset=voice_asset,
        )

        prompt = fake_llm.last_prompt
        assert "VOCABULARY TO PREFER:" in prompt
        assert '"ship"' in prompt
        assert '"build"' in prompt
        assert '"trade-off"' in prompt

    @pytest.mark.asyncio
    async def test_prompt_contains_conflict_resolution(
        self, personalization_engine, fake_llm, enrichment, voice_asset
    ):
        """Full flow: conflict resolution instructions present in prompt."""
        await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="c_suite",
            voice_asset=voice_asset,
        )

        prompt = fake_llm.last_prompt
        assert "CONFLICT RESOLUTION:" in prompt
        assert "FORMALITY_LEVEL (c_suite)" in prompt
        assert "VOICE DIRECTIVES" in prompt

    @pytest.mark.asyncio
    async def test_with_behavioral_profile_includes_tone_guidance(
        self,
        personalization_engine,
        fake_llm,
        enrichment,
        voice_asset,
        behavioral_profile,
    ):
        """Full flow: behavioral profile adds tone guidance to prompt."""
        await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="director",
            voice_asset=voice_asset,
            behavioral_profile=behavioral_profile,
        )

        prompt = fake_llm.last_prompt
        assert "TONE GUIDANCE:" in prompt
        assert "Interpersonal style: collaborative" in prompt
        assert "asks questions" in prompt


# ─── TEST 2: No VoiceAsset → PersonalizationEngine → default behavior, voice_applied=False ─


class TestNoVoiceAssetDefaultBehavior:
    """Integration: No VoiceAsset configured → PersonalizationEngine uses
    default behavior (formality only) and voice_applied=False.

    Requirements: 1.3, 4.1
    """

    @pytest.mark.asyncio
    async def test_no_voice_asset_produces_voice_applied_false(
        self, personalization_engine, enrichment
    ):
        """Without voice asset, result has voice_applied=False."""
        result = await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="director",
            voice_asset=None,
        )

        assert result.voice_applied is False

    @pytest.mark.asyncio
    async def test_no_voice_directives_in_prompt(
        self, personalization_engine, fake_llm, enrichment
    ):
        """Without voice asset, no voice directive sections in prompt."""
        await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="director",
            voice_asset=None,
        )

        prompt = fake_llm.last_prompt
        assert "SENDER VOICE DIRECTIVES:" not in prompt
        assert "PROHIBITIONS (never use these words/constructions):" not in prompt
        assert "VOICE EXEMPLARS (write in this style):" not in prompt

    @pytest.mark.asyncio
    async def test_no_error_without_voice_asset(
        self, personalization_engine, enrichment
    ):
        """System generates content without error when voice asset absent."""
        result = await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="director",
            voice_asset=None,
        )

        # Content is generated successfully
        assert result.content is not None
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_tone_still_applied_without_voice(
        self, personalization_engine, enrichment
    ):
        """Without voice asset, formality-based tone is still applied."""
        result = await personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            contact_seniority="c_suite",
            voice_asset=None,
        )

        # Tone is set based on seniority regardless of voice
        assert result.tone_applied == "company-vision and ROI-focused"


# ─── TEST 3: VoiceAsset → ReviewService → TONE_STYLE critique includes voice compliance ─


class TestVoiceAssetReviewServiceIntegration:
    """Integration: VoiceAsset present → ReviewService builds critique prompt
    with TONE_STYLE category extended for voice compliance checking.

    Requirements: 3.1
    """

    @pytest.fixture
    def critique_response_dict(self):
        """A valid CritiqueResponse dict simulating a voice-aware critique."""
        return {
            "structured_edits": [
                {
                    "target_material_id": "mat-integ-001",
                    "old_string": "I would leverage my experience",
                    "new_string": "I've built similar systems",
                    "reason": "style",
                    "category": "tone_style",
                }
            ],
            "narrative_findings": {
                "missed_keywords": [],
                "company_angles": [],
                "reframing": [],
                "tone_style": [
                    {
                        "description": "Draft uses 'leverage' which is in the "
                        "sender's vocabulary_avoid list",
                        "flagged_passage": "I would leverage my experience",
                    }
                ],
            },
        }

    @pytest.fixture
    def review_service_with_mocks(self, critique_response_dict):
        """ReviewService wired with mocked LLM and schema registry."""
        llm_router = MagicMock()
        llm_router.dispatch_critique = AsyncMock(return_value=critique_response_dict)
        llm_router.dispatch_revision = AsyncMock(return_value=None)

        schema_registry = MagicMock()
        technique = MagicMock()
        technique.id = "standard_material_review"
        technique.max_review_cycles = 1
        technique.critique_categories = [
            "missed_keywords",
            "company_angles",
            "reframing",
            "tone_style",
        ]
        schema_registry.get_review_technique_for_prepare.return_value = technique

        review_repo = MagicMock()
        review_repo.save_reasoning_log = AsyncMock()
        review_repo.mark_unreviewed = AsyncMock()

        personalization_engine = MagicMock()

        service = ReviewService(
            llm_router=llm_router,
            schema_registry=schema_registry,
            review_repository=review_repo,
            personalization_engine=personalization_engine,
        )

        return service, llm_router

    def test_fresh_context_prompt_includes_voice_compliance_check(
        self, voice_asset
    ):
        """ReviewService._build_fresh_context_prompt includes voice compliance
        instructions when voice_asset is provided."""
        service = ReviewService(
            llm_router=None,
            schema_registry=None,
            review_repository=None,
            personalization_engine=None,
        )

        categories = list(CritiqueCategory)
        prompt = service._build_fresh_context_prompt(
            material_text="I would leverage my deep experience to synergize with your team.",
            opportunity_description="Senior Platform Engineer at FinTech Co",
            enrichment={
                "firmographics": {"industry": "FinTech", "size": "250"},
                "technographics": {"stack": ["Python", "React", "AWS"]},
                "intent_signals": ["hiring ML engineers"],
                "contact_seniority": "VP",
            },
            beneficiary={
                "profile_assets": {
                    "skills": ["Python", "Platform Engineering"],
                    "achievements": ["Built 3 platform teams from scratch"],
                }
            },
            categories=categories,
            voice_asset=voice_asset,
        )

        # Voice compliance check content present in prompt
        assert "VOICE COMPLIANCE CHECK:" in prompt
        assert "direct" in prompt  # register value
        assert "leverage" in prompt  # vocabulary_avoid item
        assert "synergize" in prompt  # vocabulary_avoid item
        assert "React Native rewrite" in prompt  # exemplar passage text

    def test_fresh_context_prompt_voice_asset_reference_xml_block(
        self, voice_asset
    ):
        """Prompt contains <voice_asset_reference> XML tagged section."""
        service = ReviewService(
            llm_router=None,
            schema_registry=None,
            review_repository=None,
            personalization_engine=None,
        )

        categories = list(CritiqueCategory)
        prompt = service._build_fresh_context_prompt(
            material_text="Draft material content.",
            opportunity_description="ML Engineer role",
            enrichment={
                "firmographics": {},
                "technographics": {},
                "intent_signals": [],
                "contact_seniority": "Director",
            },
            beneficiary={"profile_assets": {"skills": ["Python"]}},
            categories=categories,
            voice_asset=voice_asset,
        )

        assert "<voice_asset_reference>" in prompt
        assert "</voice_asset_reference>" in prompt

    def test_tone_style_extended_for_voice_compliance(self, voice_asset):
        """TONE_STYLE category description is extended to mention voice compliance."""
        service = ReviewService(
            llm_router=None,
            schema_registry=None,
            review_repository=None,
            personalization_engine=None,
        )

        categories = list(CritiqueCategory)
        prompt = service._build_fresh_context_prompt(
            material_text="Draft content here.",
            opportunity_description="Platform role",
            enrichment={
                "firmographics": {},
                "technographics": {},
                "intent_signals": [],
                "contact_seniority": "Manager",
            },
            beneficiary={"profile_assets": {}},
            categories=categories,
            voice_asset=voice_asset,
        )

        # The tone_style category description mentions voice compliance
        assert "voice" in prompt.lower()
        # StructuredEdit and NarrativeFinding instructions present
        assert "StructuredEdit" in prompt
        assert "NarrativeFinding" in prompt

    def test_behavioral_profile_adds_profile_check_to_critique(
        self, voice_asset, behavioral_profile
    ):
        """When behavioral profile is also present, critique prompt includes
        BEHAVIORAL PROFILE CHECK section."""
        service = ReviewService(
            llm_router=None,
            schema_registry=None,
            review_repository=None,
            personalization_engine=None,
        )

        categories = list(CritiqueCategory)
        prompt = service._build_fresh_context_prompt(
            material_text="I single-handedly dominated the market.",
            opportunity_description="Team Lead role",
            enrichment={
                "firmographics": {"industry": "SaaS"},
                "technographics": {},
                "intent_signals": [],
                "contact_seniority": "VP",
            },
            beneficiary={"profile_assets": {"skills": ["Leadership"]}},
            categories=categories,
            voice_asset=voice_asset,
            behavioral_profile=behavioral_profile,
        )

        assert "BEHAVIORAL PROFILE CHECK:" in prompt
        assert "collaborative" in prompt
        assert "combative" in prompt
        assert "apologetic" in prompt

    def test_no_voice_asset_omits_voice_compliance_from_critique(self):
        """Without voice_asset, critique prompt has no voice compliance section."""
        service = ReviewService(
            llm_router=None,
            schema_registry=None,
            review_repository=None,
            personalization_engine=None,
        )

        categories = list(CritiqueCategory)
        prompt = service._build_fresh_context_prompt(
            material_text="Standard draft content.",
            opportunity_description="Engineer role",
            enrichment={
                "firmographics": {},
                "technographics": {},
                "intent_signals": [],
                "contact_seniority": "Manager",
            },
            beneficiary={"profile_assets": {}},
            categories=categories,
            # voice_asset=None (default)
        )

        assert "VOICE COMPLIANCE CHECK" not in prompt
        assert "<voice_asset_reference>" not in prompt

    @pytest.mark.asyncio
    async def test_review_with_voice_asset_completes_successfully(
        self, review_service_with_mocks, voice_asset
    ):
        """End-to-end: ReviewService.review_material completes with voice-aware
        critique response when voice_asset would be used in prompt building.

        Note: The current review_material doesn't directly accept voice_asset
        as a parameter — the integration happens via _build_fresh_context_prompt
        when called with voice_asset. This test verifies the service can process
        a critique response that includes voice-related edits (category=tone_style,
        reason=style) without error.

        The edit replaces "I would leverage my experience" with "I've built
        similar systems" — the beneficiary assets must ground "built similar systems"
        to pass the grounding check.
        """
        service, llm_router = review_service_with_mocks

        draft = DraftMaterial(
            id="mat-integ-001",
            pipeline_record_id="pipeline-integ-001",
            prepare_technique_id="cv_and_cover_letter",
            material_type="tailored_cv",
            content="I would leverage my experience to synergize with your team.",
            quality_score=70,
            generated_at=datetime.now(timezone.utc),
        )

        result = await service.review_material(
            draft_material=draft,
            prospect={"name": "FinTech Co", "contact": "Jane VP"},
            beneficiary={
                "profile_assets": {
                    "skills": ["Python", "Platform Engineering"],
                    "achievements": [
                        "Built 3 platform teams from scratch",
                        "I've built similar systems in fintech",
                    ],
                }
            },
            enrichment={
                "firmographics": {"industry": "FinTech"},
                "technographics": {"stack": ["Python"]},
                "intent_signals": ["hiring"],
                "contact_seniority": "VP",
            },
            opportunity_description="Senior Platform Engineer",
        )

        # Review completes successfully
        assert result.review_status == ReviewStatus.REVIEWED

        # The voice-aware edit (replacing "leverage") was applied
        assert "I've built similar systems" in result.revised_content
        assert "I would leverage" not in result.revised_content

        # LLM critique was dispatched
        assert llm_router.dispatch_critique.call_count == 1
