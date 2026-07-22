"""Unit tests for GapAnalyzer.generate_learning_recommendation().

Tests requirement 3.3:
- Generate LLM-based learning recommendation for a specific gap
- Return resources, effort estimate, and advisory label
- Clearly labeled as advisory
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.core.gap_analyzer import (
    GapAnalysisConfig,
    GapAnalyzer,
    LearningRecommendation,
)


@pytest.fixture
def mock_llm_router():
    """Create a mock LLM router with dispatch_extraction."""
    router = AsyncMock()
    router.dispatch_extraction = AsyncMock(return_value={
        "resources": [
            "Official Kubernetes documentation (kubernetes.io)",
            "CKA Certification prep course on Udemy",
            "Kubernetes in Action (book by Marko Lukša)",
            "KodeKloud hands-on labs",
        ],
        "effort_estimate": "4-6 weeks part-time",
    })
    return router


@pytest.fixture
def analyzer(mock_llm_router) -> GapAnalyzer:
    """Create a GapAnalyzer with mock LLM router."""
    config = GapAnalysisConfig(default_opportunity_value=10000.0)
    return GapAnalyzer(
        config=config,
        llm_router=mock_llm_router,
        schema_registry=None,
        db_session=None,
        redis_client=None,
        ws_manager=None,
    )


class TestGenerateLearningRecommendation:
    """Tests for generate_learning_recommendation()."""

    @pytest.mark.asyncio
    async def test_returns_learning_recommendation_dataclass(
        self, analyzer: GapAnalyzer
    ):
        """Should return a LearningRecommendation with correct fields."""
        result = await analyzer.generate_learning_recommendation("kubernetes")

        assert isinstance(result, LearningRecommendation)
        assert result.canonical_name == "kubernetes"

    @pytest.mark.asyncio
    async def test_resources_populated_from_llm_response(
        self, analyzer: GapAnalyzer
    ):
        """Resources list should come from the LLM response."""
        result = await analyzer.generate_learning_recommendation("kubernetes")

        assert len(result.resources) == 4
        assert "Official Kubernetes documentation (kubernetes.io)" in result.resources
        assert "CKA Certification prep course on Udemy" in result.resources

    @pytest.mark.asyncio
    async def test_effort_estimate_from_llm_response(
        self, analyzer: GapAnalyzer
    ):
        """Effort estimate should come from LLM response."""
        result = await analyzer.generate_learning_recommendation("kubernetes")

        assert result.effort_estimate == "4-6 weeks part-time"

    @pytest.mark.asyncio
    async def test_advisory_note_present(self, analyzer: GapAnalyzer):
        """Result must include advisory disclaimer."""
        result = await analyzer.generate_learning_recommendation("kubernetes")

        assert "advisory only" in result.advisory_note.lower()
        assert "AI-generated" in result.advisory_note

    @pytest.mark.asyncio
    async def test_generated_at_is_utc_timestamp(self, analyzer: GapAnalyzer):
        """generated_at should be a recent UTC datetime."""
        before = datetime.now(timezone.utc)
        result = await analyzer.generate_learning_recommendation("kubernetes")
        after = datetime.now(timezone.utc)

        assert before <= result.generated_at <= after
        assert result.generated_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_llm_called_with_capability_in_prompt(
        self, analyzer: GapAnalyzer, mock_llm_router
    ):
        """LLM dispatch_extraction should be called with a prompt containing the capability."""
        await analyzer.generate_learning_recommendation("terraform")

        mock_llm_router.dispatch_extraction.assert_called_once()
        call_args = mock_llm_router.dispatch_extraction.call_args
        prompt = call_args[0][0]
        assert "terraform" in prompt.lower()

    @pytest.mark.asyncio
    async def test_handles_missing_resources_key(self, mock_llm_router):
        """Should handle LLM response missing the resources key."""
        mock_llm_router.dispatch_extraction.return_value = {
            "effort_estimate": "2-3 weeks part-time",
        }
        config = GapAnalysisConfig()
        analyzer = GapAnalyzer(
            config=config,
            llm_router=mock_llm_router,
            schema_registry=None,
            db_session=None,
            redis_client=None,
            ws_manager=None,
        )

        result = await analyzer.generate_learning_recommendation("python")

        assert result.resources == []
        assert result.effort_estimate == "2-3 weeks part-time"

    @pytest.mark.asyncio
    async def test_handles_missing_effort_estimate_key(self, mock_llm_router):
        """Should provide default effort estimate when missing from response."""
        mock_llm_router.dispatch_extraction.return_value = {
            "resources": ["Some resource"],
        }
        config = GapAnalysisConfig()
        analyzer = GapAnalyzer(
            config=config,
            llm_router=mock_llm_router,
            schema_registry=None,
            db_session=None,
            redis_client=None,
            ws_manager=None,
        )

        result = await analyzer.generate_learning_recommendation("react")

        assert result.resources == ["Some resource"]
        assert result.effort_estimate == "2-4 weeks part-time"

    @pytest.mark.asyncio
    async def test_handles_non_list_resources(self, mock_llm_router):
        """Should handle LLM returning a non-list resources value."""
        mock_llm_router.dispatch_extraction.return_value = {
            "resources": "Just a single string resource",
            "effort_estimate": "1-2 weeks",
        }
        config = GapAnalysisConfig()
        analyzer = GapAnalyzer(
            config=config,
            llm_router=mock_llm_router,
            schema_registry=None,
            db_session=None,
            redis_client=None,
            ws_manager=None,
        )

        result = await analyzer.generate_learning_recommendation("docker")

        assert isinstance(result.resources, list)
        assert len(result.resources) == 1
        assert result.resources[0] == "Just a single string resource"

    @pytest.mark.asyncio
    async def test_propagates_extraction_error_on_llm_failure(
        self, mock_llm_router
    ):
        """Should propagate ExtractionError when LLM fails after retries."""
        from app.core.gap_errors import ExtractionError

        mock_llm_router.dispatch_extraction.side_effect = Exception(
            "LLM service unavailable"
        )
        config = GapAnalysisConfig()
        analyzer = GapAnalyzer(
            config=config,
            llm_router=mock_llm_router,
            schema_registry=None,
            db_session=None,
            redis_client=None,
            ws_manager=None,
        )

        with pytest.raises(ExtractionError):
            await analyzer.generate_learning_recommendation("rust")
