"""Unit tests for the Personalization Engine.

Tests cover tone determination, quality scoring, hook referencing,
sparse enrichment handling, and end-to-end generation flow.
"""

import asyncio

import pytest

from app.core.personalization_engine import (
    EnrichmentData,
    MaterialType,
    PersonalizationEngine,
    PersonalizationResult,
    SeniorityLevel,
)


# ─── Fake LLM Router ─────────────────────────────────────────────────────────


class FakeLLMRouter:
    """Fake LLM router that returns predictable content for testing.

    By default, references all enrichment fields passed in context.
    Can be configured to return specific content or simulate timeouts.
    """

    def __init__(self, response: str | None = None, timeout: bool = False):
        self._response = response
        self._timeout = timeout
        self.last_prompt: str | None = None
        self.last_context: dict | None = None
        self.last_material_type: str | None = None
        self.call_count = 0

    async def generate_content(
        self, prompt: str, context: dict, material_type: str
    ) -> str:
        self.last_prompt = prompt
        self.last_context = context
        self.last_material_type = material_type
        self.call_count += 1

        if self._timeout:
            await asyncio.sleep(60)  # Will be cancelled by timeout

        if self._response is not None:
            return self._response

        # Default: Generate content that references context fields
        parts = [f"Generated {material_type} content."]
        if "industry" in context:
            parts.append(f"Your company in the {context['industry']} industry.")
        if "tech_stack" in context:
            parts.append(f"We noticed you use {', '.join(context['tech_stack'])}.")
        if "company_size" in context:
            parts.append(f"With {context['company_size']} employees.")
        if "recent_funding" in context:
            parts.append(f"Congratulations on your {context['recent_funding']} funding.")
        if "intent_signals" in context:
            parts.append(f"We see interest in {', '.join(context['intent_signals'])}.")
        if "hooks" in context:
            for hook in context["hooks"]:
                topic = hook.get("topic") or hook.get("title", "")
                parts.append(f"Regarding {topic}.")
        return " ".join(parts)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_llm() -> FakeLLMRouter:
    return FakeLLMRouter()


@pytest.fixture
def engine(fake_llm) -> PersonalizationEngine:
    return PersonalizationEngine(llm_router=fake_llm)


@pytest.fixture
def full_enrichment() -> EnrichmentData:
    """Enrichment data with all fields populated."""
    return EnrichmentData(
        industry="fintech",
        tech_stack=["python", "react", "kubernetes"],
        company_size=250,
        recent_funding="series b",
        intent_signals=["cloud migration", "devops tooling"],
        hooks=[
            {"type": "news", "topic": "new CTO hire"},
            {"type": "job_posting", "topic": "senior backend engineer"},
        ],
    )


@pytest.fixture
def sparse_enrichment() -> EnrichmentData:
    """Enrichment data with fewer than 3 fields."""
    return EnrichmentData(
        industry="healthcare",
        tech_stack=[],
        company_size=None,
        recent_funding=None,
        intent_signals=[],
        hooks=[],
    )


# ─── Tone Determination Tests ────────────────────────────────────────────────


class TestDetermineTone:
    """Test _determine_tone() mapping from seniority to tone level."""

    def test_c_suite_tone(self, engine):
        assert engine._determine_tone("c_suite") == SeniorityLevel.C_SUITE

    def test_director_tone(self, engine):
        assert engine._determine_tone("director") == SeniorityLevel.DIRECTOR

    def test_manager_tone(self, engine):
        assert engine._determine_tone("manager") == SeniorityLevel.MANAGER

    def test_other_tone(self, engine):
        assert engine._determine_tone("other") == SeniorityLevel.OTHER

    def test_none_defaults_to_director(self, engine):
        """Requirement 11.7: Default to director when seniority unknown."""
        assert engine._determine_tone(None) == SeniorityLevel.DIRECTOR

    def test_unknown_value_defaults_to_director(self, engine):
        """Unknown seniority values default to director."""
        assert engine._determine_tone("intern") == SeniorityLevel.DIRECTOR
        assert engine._determine_tone("unknown") == SeniorityLevel.DIRECTOR

    def test_case_insensitive(self, engine):
        assert engine._determine_tone("C_SUITE") == SeniorityLevel.C_SUITE
        assert engine._determine_tone("Director") == SeniorityLevel.DIRECTOR


# ─── Quality Score Tests ──────────────────────────────────────────────────────


class TestComputeQualityScore:
    """Test _compute_quality_score() computation logic."""

    def test_all_fields_referenced(self, engine, full_enrichment):
        """Score should be 100 when all available fields are referenced."""
        content = (
            "The fintech industry is growing. "
            "Using python and react with kubernetes. "
            "With 250 employees. "
            "After series b funding. "
            "Interest in cloud migration. "
            "Regarding new CTO hire."
        )
        score, used, unused = engine._compute_quality_score(content, full_enrichment)
        assert score == 100
        assert len(unused) == 0
        assert set(used) == {
            "industry", "tech_stack", "company_size",
            "recent_funding", "intent_signals", "hooks",
        }

    def test_no_fields_referenced(self, engine, full_enrichment):
        """Score should be 0 when no fields are referenced."""
        content = "Hello, we would like to connect with you."
        score, used, unused = engine._compute_quality_score(content, full_enrichment)
        assert score == 0
        assert len(used) == 0
        assert len(unused) == 6

    def test_partial_fields_referenced(self, engine, full_enrichment):
        """Score should be proportional to fields referenced."""
        # Reference 3 out of 6 fields = 50%
        content = (
            "The fintech industry is exciting. "
            "Your python team. "
            "With 250 employees."
        )
        score, used, unused = engine._compute_quality_score(content, full_enrichment)
        assert score == 50
        assert len(used) == 3
        assert len(unused) == 3

    def test_empty_enrichment(self, engine):
        """Score should be 0 when no fields are available."""
        enrichment = EnrichmentData()
        content = "Some content here."
        score, used, unused = engine._compute_quality_score(content, enrichment)
        assert score == 0
        assert used == []
        assert unused == []

    def test_sparse_enrichment_score(self, engine, sparse_enrichment):
        """Score with sparse data (1 field available, 1 referenced)."""
        content = "In the healthcare sector, we can help."
        score, used, unused = engine._compute_quality_score(content, sparse_enrichment)
        assert score == 100  # 1/1 = 100%
        assert used == ["industry"]
        assert unused == []


# ─── Generation Tests ─────────────────────────────────────────────────────────


class TestGenerateMaterials:
    """Test the full generate_materials() flow."""

    @pytest.mark.asyncio
    async def test_generates_content_with_full_enrichment(self, engine, full_enrichment):
        """Full enrichment produces high quality content."""
        result = await engine.generate_materials(
            enrichment=full_enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="c_suite",
        )
        assert isinstance(result, PersonalizationResult)
        assert result.content  # Non-empty
        assert result.quality_score > 0
        assert result.tone_applied == "company-vision and ROI-focused"
        assert "seniority_unknown" not in result.flags

    @pytest.mark.asyncio
    async def test_seniority_unknown_flag(self, engine, full_enrichment):
        """Requirement 11.7: Flag seniority_unknown when contact seniority is None."""
        result = await engine.generate_materials(
            enrichment=full_enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority=None,
        )
        assert "seniority_unknown" in result.flags
        assert result.tone_applied == "implementation-focused and team-impact"

    @pytest.mark.asyncio
    async def test_low_quality_flagging(self, fake_llm, full_enrichment):
        """Requirement 11.6: Flag low personalization when score < 40."""
        # LLM returns content that doesn't reference any enrichment fields
        fake_llm._response = "Hello, we would like to connect with your team."
        engine = PersonalizationEngine(llm_router=fake_llm)

        result = await engine.generate_materials(
            enrichment=full_enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="director",
        )
        assert result.is_low_quality is True
        assert "low personalization" in result.flags
        assert len(result.fields_available_unused) <= 3

    @pytest.mark.asyncio
    async def test_sparse_enrichment_graceful(self, engine, sparse_enrichment):
        """Requirement 11.3: Handle < 3 fields gracefully."""
        result = await engine.generate_materials(
            enrichment=sparse_enrichment,
            beneficiary_id="consultant",
            material_type="cover_letter",
            contact_seniority="manager",
        )
        # Should still produce content without error
        assert result.content
        assert result.tone_applied == "hands-on and collaboration-focused"

    @pytest.mark.asyncio
    async def test_hooks_referenced(self, engine, full_enrichment):
        """Requirement 11.2: Reference at least one hook when available."""
        result = await engine.generate_materials(
            enrichment=full_enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="director",
        )
        # FakeLLMRouter references hooks by default
        assert len(result.hooks_referenced) > 0

    @pytest.mark.asyncio
    async def test_invalid_material_type_raises(self, engine, full_enrichment):
        """Invalid material type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid material_type"):
            await engine.generate_materials(
                enrichment=full_enrichment,
                beneficiary_id="consultant",
                material_type="invalid_type",
                contact_seniority="director",
            )

    @pytest.mark.asyncio
    async def test_all_material_types(self, engine, full_enrichment):
        """All valid material types should work."""
        for mat_type in ["cv", "cover_letter", "proposal", "email"]:
            result = await engine.generate_materials(
                enrichment=full_enrichment,
                beneficiary_id="consultant",
                material_type=mat_type,
                contact_seniority="director",
            )
            assert result.content

    @pytest.mark.asyncio
    async def test_timeout_raises(self, full_enrichment):
        """Generation timeout raises asyncio.TimeoutError."""
        timeout_llm = FakeLLMRouter(timeout=True)
        engine = PersonalizationEngine(llm_router=timeout_llm, generation_timeout=0.1)

        with pytest.raises(asyncio.TimeoutError):
            await engine.generate_materials(
                enrichment=full_enrichment,
                beneficiary_id="consultant",
                material_type="email",
                contact_seniority="director",
            )

    @pytest.mark.asyncio
    async def test_tone_mapping_c_suite(self, engine, full_enrichment):
        """C-suite contacts get company-vision and ROI-focused tone."""
        result = await engine.generate_materials(
            enrichment=full_enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="c_suite",
        )
        assert result.tone_applied == "company-vision and ROI-focused"

    @pytest.mark.asyncio
    async def test_tone_mapping_manager(self, engine, full_enrichment):
        """Manager contacts get hands-on and collaboration-focused tone."""
        result = await engine.generate_materials(
            enrichment=full_enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="manager",
        )
        assert result.tone_applied == "hands-on and collaboration-focused"

    @pytest.mark.asyncio
    async def test_context_passed_to_llm(self, fake_llm, full_enrichment):
        """Verify enrichment data is passed in LLM context."""
        engine = PersonalizationEngine(llm_router=fake_llm)
        await engine.generate_materials(
            enrichment=full_enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="director",
        )
        assert fake_llm.last_context is not None
        assert fake_llm.last_context["industry"] == "fintech"
        assert fake_llm.last_context["tech_stack"] == ["python", "react", "kubernetes"]
        assert fake_llm.last_context["company_size"] == 250
        assert fake_llm.last_context["tone"] == "implementation-focused and team-impact"

    @pytest.mark.asyncio
    async def test_quality_score_100_when_all_referenced(self, engine, full_enrichment):
        """Quality score is 100 when all available fields are referenced."""
        result = await engine.generate_materials(
            enrichment=full_enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority="director",
        )
        # FakeLLMRouter references all context fields
        assert result.quality_score == 100
        assert result.is_low_quality is False

    @pytest.mark.asyncio
    async def test_empty_enrichment_generates(self):
        """Empty enrichment still generates content without error."""
        fake_llm = FakeLLMRouter(response="Generic outreach content here.")
        engine = PersonalizationEngine(llm_router=fake_llm)
        enrichment = EnrichmentData()

        result = await engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id="consultant",
            material_type="email",
            contact_seniority=None,
        )
        assert result.content == "Generic outreach content here."
        assert result.quality_score == 0
        assert "seniority_unknown" in result.flags


# ─── Hook Reference Tests ────────────────────────────────────────────────────


class TestHookReferencing:
    """Test hook identification in generated content."""

    def test_hook_found_by_topic(self, engine):
        hooks = [{"type": "news", "topic": "new CTO appointment"}]
        content = "We noticed the new CTO appointment at your company."
        referenced = engine._find_hooks_referenced(content, hooks)
        assert len(referenced) == 1
        assert "news:new CTO appointment" in referenced[0]

    def test_hook_not_found(self, engine):
        hooks = [{"type": "news", "topic": "funding round"}]
        content = "Hello, we would like to discuss a partnership."
        referenced = engine._find_hooks_referenced(content, hooks)
        assert len(referenced) == 0

    def test_multiple_hooks_some_referenced(self, engine):
        hooks = [
            {"type": "news", "topic": "expansion to europe"},
            {"type": "job_posting", "topic": "hiring senior devops"},
            {"type": "tech_adoption", "topic": "migrating to kubernetes"},
        ]
        content = "We see you're hiring senior devops engineers and migrating to kubernetes."
        referenced = engine._find_hooks_referenced(content, hooks)
        assert len(referenced) == 2


# ─── Available Fields Tests ───────────────────────────────────────────────────


class TestGetAvailableFields:
    """Test _get_available_fields() detection of populated fields."""

    def test_all_fields_available(self, engine, full_enrichment):
        fields = engine._get_available_fields(full_enrichment)
        assert set(fields) == {
            "industry", "tech_stack", "company_size",
            "recent_funding", "intent_signals", "hooks",
        }

    def test_no_fields_available(self, engine):
        enrichment = EnrichmentData()
        fields = engine._get_available_fields(enrichment)
        assert fields == []

    def test_partial_fields(self, engine):
        enrichment = EnrichmentData(industry="tech", company_size=50)
        fields = engine._get_available_fields(enrichment)
        assert set(fields) == {"industry", "company_size"}
