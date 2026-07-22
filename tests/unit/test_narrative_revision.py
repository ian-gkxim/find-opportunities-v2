"""Unit tests for ReviewService._dispatch_narrative_revision() and _build_revision_prompt().

Validates graceful degradation on failure, prompt construction with findings,
and correct behavior when no findings are present.

Requirements: 2.5
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.review_models import CritiqueCategory, NarrativeFinding
from app.core.review_service import ReviewService


@pytest.fixture
def review_service() -> ReviewService:
    """Create a ReviewService with mocked dependencies."""
    llm_router = MagicMock()
    llm_router.dispatch_revision = AsyncMock()
    schema_registry = MagicMock()
    review_repository = MagicMock()
    personalization_engine = MagicMock()
    return ReviewService(
        llm_router=llm_router,
        schema_registry=schema_registry,
        review_repository=review_repository,
        personalization_engine=personalization_engine,
    )


@pytest.fixture
def sample_findings() -> dict[CritiqueCategory, list[NarrativeFinding]]:
    """Sample findings with items across multiple categories."""
    return {
        CritiqueCategory.MISSED_KEYWORDS: [
            NarrativeFinding(
                category=CritiqueCategory.MISSED_KEYWORDS,
                description="Missing keyword 'cloud migration'",
                flagged_passage="we have broad technology experience",
            )
        ],
        CritiqueCategory.COMPANY_ANGLES: [],
        CritiqueCategory.REFRAMING: [
            NarrativeFinding(
                category=CritiqueCategory.REFRAMING,
                description="Passive phrasing should be action-oriented",
                flagged_passage="was responsible for managing",
            )
        ],
        CritiqueCategory.TONE_STYLE: [],
    }


@pytest.fixture
def empty_findings() -> dict[CritiqueCategory, list[NarrativeFinding]]:
    """Findings dict with all categories empty."""
    return {
        CritiqueCategory.MISSED_KEYWORDS: [],
        CritiqueCategory.COMPANY_ANGLES: [],
        CritiqueCategory.REFRAMING: [],
        CritiqueCategory.TONE_STYLE: [],
    }


class TestDispatchNarrativeRevision:
    """Tests for _dispatch_narrative_revision() method."""

    @pytest.mark.asyncio
    async def test_returns_revised_text_on_success(
        self, review_service: ReviewService, sample_findings
    ):
        """Successful dispatch returns the revised text from LLM."""
        review_service._llm.dispatch_revision.return_value = "Revised material content"

        result = await review_service._dispatch_narrative_revision(
            "Original material text", sample_findings
        )

        assert result == "Revised material content"
        review_service._llm.dispatch_revision.assert_called_once()

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_response(
        self, review_service: ReviewService, sample_findings
    ):
        """Strips leading/trailing whitespace from LLM response."""
        review_service._llm.dispatch_revision.return_value = "  Revised text  \n"

        result = await review_service._dispatch_narrative_revision(
            "Original text", sample_findings
        )

        assert result == "Revised text"

    @pytest.mark.asyncio
    async def test_returns_original_on_all_retries_failed(
        self, review_service: ReviewService, sample_findings
    ):
        """Graceful degradation: returns original material after all attempts fail."""
        review_service._llm.dispatch_revision.side_effect = Exception("LLM timeout")

        result = await review_service._dispatch_narrative_revision(
            "Original material text", sample_findings
        )

        assert result == "Original material text"
        # Should have tried MAX_RETRIES + 1 times (3 total)
        assert review_service._llm.dispatch_revision.call_count == 3

    @pytest.mark.asyncio
    async def test_returns_original_when_llm_returns_empty(
        self, review_service: ReviewService, sample_findings
    ):
        """Graceful degradation when LLM returns empty string."""
        review_service._llm.dispatch_revision.return_value = ""

        result = await review_service._dispatch_narrative_revision(
            "Original material text", sample_findings
        )

        assert result == "Original material text"

    @pytest.mark.asyncio
    async def test_returns_original_when_llm_returns_whitespace_only(
        self, review_service: ReviewService, sample_findings
    ):
        """Graceful degradation when LLM returns only whitespace."""
        review_service._llm.dispatch_revision.return_value = "   \n  "

        result = await review_service._dispatch_narrative_revision(
            "Original material text", sample_findings
        )

        assert result == "Original material text"

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(
        self, review_service: ReviewService, sample_findings
    ):
        """Retries on first failure, succeeds on second attempt."""
        review_service._llm.dispatch_revision.side_effect = [
            Exception("timeout"),
            "Revised on second attempt",
        ]

        result = await review_service._dispatch_narrative_revision(
            "Original text", sample_findings
        )

        assert result == "Revised on second attempt"
        assert review_service._llm.dispatch_revision.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_original_when_no_findings(
        self, review_service: ReviewService, empty_findings
    ):
        """Returns original material unchanged when all finding lists are empty."""
        result = await review_service._dispatch_narrative_revision(
            "Original material text", empty_findings
        )

        assert result == "Original material text"
        # Should never call LLM if no findings
        review_service._llm.dispatch_revision.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_dispatch_revision_with_timeout(
        self, review_service: ReviewService, sample_findings
    ):
        """Passes CRITIQUE_TIMEOUT (60s) to dispatch_revision."""
        review_service._llm.dispatch_revision.return_value = "Revised"

        await review_service._dispatch_narrative_revision(
            "Original", sample_findings
        )

        call_kwargs = review_service._llm.dispatch_revision.call_args
        assert call_kwargs[1]["timeout"] == 60.0


class TestBuildRevisionPrompt:
    """Tests for _build_revision_prompt() helper method."""

    def test_includes_material_text_in_xml_tags(
        self, review_service: ReviewService, sample_findings
    ):
        """Prompt includes material text within <current_material> tags."""
        prompt = review_service._build_revision_prompt(
            "My outreach content here", sample_findings
        )

        assert "<current_material>\nMy outreach content here\n</current_material>" in prompt

    def test_includes_narrative_findings_in_xml_tags(
        self, review_service: ReviewService, sample_findings
    ):
        """Prompt includes findings within <narrative_findings> tags."""
        prompt = review_service._build_revision_prompt(
            "Material text", sample_findings
        )

        assert "<narrative_findings>" in prompt
        assert "</narrative_findings>" in prompt

    def test_includes_category_and_description(
        self, review_service: ReviewService, sample_findings
    ):
        """Prompt includes category value and finding description."""
        prompt = review_service._build_revision_prompt(
            "Material text", sample_findings
        )

        assert "[missed_keywords]" in prompt
        assert "Missing keyword 'cloud migration'" in prompt
        assert "[reframing]" in prompt
        assert "Passive phrasing should be action-oriented" in prompt

    def test_includes_flagged_passage(
        self, review_service: ReviewService, sample_findings
    ):
        """Prompt includes flagged passage when present."""
        prompt = review_service._build_revision_prompt(
            "Material text", sample_findings
        )

        assert 'Flagged passage: "we have broad technology experience"' in prompt
        assert 'Flagged passage: "was responsible for managing"' in prompt

    def test_excludes_empty_categories(
        self, review_service: ReviewService, sample_findings
    ):
        """Empty categories produce no finding entries in the prompt."""
        prompt = review_service._build_revision_prompt(
            "Material text", sample_findings
        )

        # company_angles and tone_style have no findings, so their values should not appear
        assert "[company_angles]" not in prompt
        assert "[tone_style]" not in prompt

    def test_returns_empty_string_when_no_findings(
        self, review_service: ReviewService, empty_findings
    ):
        """Returns empty string when all finding lists are empty."""
        prompt = review_service._build_revision_prompt(
            "Material text", empty_findings
        )

        assert prompt == ""

    def test_includes_revision_instructions(
        self, review_service: ReviewService, sample_findings
    ):
        """Prompt instructs targeted revision only of flagged passages."""
        prompt = review_service._build_revision_prompt(
            "Material text", sample_findings
        )

        assert "Revise ONLY the specific passages flagged below" in prompt
        assert "Preserve ALL other content exactly as-is" in prompt
        assert "Do not add new claims, skills, or credentials" in prompt

    def test_finding_without_flagged_passage(self, review_service: ReviewService):
        """Finding without flagged_passage only shows description."""
        findings = {
            CritiqueCategory.MISSED_KEYWORDS: [
                NarrativeFinding(
                    category=CritiqueCategory.MISSED_KEYWORDS,
                    description="Draft omits the keyword 'machine learning'",
                    flagged_passage=None,
                )
            ],
            CritiqueCategory.COMPANY_ANGLES: [],
            CritiqueCategory.REFRAMING: [],
            CritiqueCategory.TONE_STYLE: [],
        }

        prompt = review_service._build_revision_prompt("Material text", findings)

        assert "Draft omits the keyword 'machine learning'" in prompt
        assert "Flagged passage:" not in prompt
