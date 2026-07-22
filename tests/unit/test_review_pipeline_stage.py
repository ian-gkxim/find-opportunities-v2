"""Unit tests for ReviewPipelineStage.

Validates that the pipeline stage:
- Calls ReviewService when a review_technique is configured
- Skips review and passes material through when review_technique is absent
- Enforces DISPATCH_DEADLINE observability (logs warning if exceeded)
- Gracefully degrades on unexpected errors

Requirements: 1.1, 4.2
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.review_models import (
    DraftMaterial,
    ReasoningLog,
    ReviewResult,
    ReviewStatus,
)
from app.core.review_pipeline_stage import ReviewPipelineStage


@pytest.fixture
def sample_draft_material():
    """A minimal DraftMaterial for testing."""
    return DraftMaterial(
        id="mat-001",
        pipeline_record_id="pr-001",
        prepare_technique_id="cv_and_cover_letter",
        material_type="tailored_cv",
        content="This is the draft content for testing.",
        quality_score=72,
        generated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_schema_with_review():
    """SchemaRegistry mock that returns a review_technique."""
    schema = MagicMock()
    technique = MagicMock()
    technique.id = "standard_material_review"
    technique.max_review_cycles = 2
    technique.critique_categories = [
        "missed_keywords", "company_angles", "reframing", "tone_style"
    ]
    schema.get_review_technique_for_prepare.return_value = technique
    return schema


@pytest.fixture
def mock_schema_without_review():
    """SchemaRegistry mock that returns None (no review configured)."""
    schema = MagicMock()
    schema.get_review_technique_for_prepare.return_value = None
    return schema


@pytest.fixture
def mock_review_service():
    """ReviewService mock with a successful review_material response."""
    service = AsyncMock()
    service.review_material.return_value = ReviewResult(
        material_id="mat-001",
        revised_content="This is the REVISED content after review.",
        review_status=ReviewStatus.REVIEWED,
        reasoning_log=MagicMock(spec=ReasoningLog),
        quality_score_final=85,
        total_edits_applied=3,
    )
    return service


class TestReviewPipelineStageSkipReview:
    """Tests for when review_technique is absent — review should be skipped."""

    @pytest.mark.asyncio
    async def test_skip_review_returns_original_content(
        self, sample_draft_material, mock_schema_without_review, mock_review_service
    ):
        """When no review_technique is configured, original content is returned."""
        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_without_review,
        )
        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        assert result["revised_content"] == sample_draft_material.content
        assert result["review_status"] == ReviewStatus.REVIEWED
        assert result["reasoning_log"] is None
        assert result["quality_score"] == sample_draft_material.quality_score

    @pytest.mark.asyncio
    async def test_skip_review_does_not_call_review_service(
        self, sample_draft_material, mock_schema_without_review, mock_review_service
    ):
        """When no review_technique is configured, ReviewService is never called."""
        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_without_review,
        )
        await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        mock_review_service.review_material.assert_not_called()


class TestReviewPipelineStageDispatchReview:
    """Tests for when review_technique is configured — review is dispatched."""

    @pytest.mark.asyncio
    async def test_dispatch_review_returns_revised_content(
        self, sample_draft_material, mock_schema_with_review, mock_review_service
    ):
        """When review_technique is configured, revised content is returned."""
        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_review,
        )
        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        assert result["revised_content"] == "This is the REVISED content after review."
        assert result["review_status"] == ReviewStatus.REVIEWED
        assert result["reasoning_log"] is not None
        assert result["quality_score"] == 85

    @pytest.mark.asyncio
    async def test_dispatch_review_calls_review_service(
        self, sample_draft_material, mock_schema_with_review, mock_review_service
    ):
        """When review_technique is configured, ReviewService.review_material is called."""
        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_review,
        )
        prospect = MagicMock()
        beneficiary = MagicMock()
        enrichment = MagicMock()

        await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=prospect,
            beneficiary=beneficiary,
            enrichment=enrichment,
            opportunity_description="Test opportunity",
        )

        mock_review_service.review_material.assert_called_once_with(
            draft_material=sample_draft_material,
            prospect=prospect,
            beneficiary=beneficiary,
            enrichment=enrichment,
            opportunity_description="Test opportunity",
            voice_asset=None,
            behavioral_profile=None,
        )


class TestReviewPipelineStageGracefulDegradation:
    """Tests for error handling and graceful degradation."""

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_original_content(
        self, sample_draft_material, mock_schema_with_review
    ):
        """On unexpected error, original content passes through as UNREVIEWED."""
        failing_service = AsyncMock()
        failing_service.review_material.side_effect = RuntimeError("LLM down")

        stage = ReviewPipelineStage(
            review_service=failing_service,
            schema_registry=mock_schema_with_review,
        )
        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        assert result["revised_content"] == sample_draft_material.content
        assert result["review_status"] == ReviewStatus.UNREVIEWED
        assert result["reasoning_log"] is None
        assert result["quality_score"] == sample_draft_material.quality_score


class TestReviewPipelineStageDispatchDeadline:
    """Tests for DISPATCH_DEADLINE enforcement (Requirement 1.1)."""

    @pytest.mark.asyncio
    async def test_dispatch_deadline_constant_is_10_seconds(self):
        """DISPATCH_DEADLINE is set to 10 seconds."""
        assert ReviewPipelineStage.DISPATCH_DEADLINE == 10.0

    @pytest.mark.asyncio
    async def test_logs_warning_when_deadline_exceeded(
        self, sample_draft_material, mock_schema_with_review, mock_review_service
    ):
        """When time exceeds DISPATCH_DEADLINE before dispatch, a warning is logged."""
        # Ensure grounding_technique is not configured so no extra warnings
        mock_schema_with_review.get_grounding_technique_for_prepare.return_value = None

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_review,
        )
        # Temporarily set a very low deadline to simulate exceeding it
        stage.DISPATCH_DEADLINE = 0.0  # Anything > 0 elapsed will exceed

        with patch("app.core.review_pipeline_stage.logger") as mock_logger:
            await stage.process_after_generation(
                draft_material=sample_draft_material,
                prospect=MagicMock(),
                beneficiary=MagicMock(),
                enrichment=MagicMock(),
                opportunity_description="Test opportunity",
            )

            # Should have logged a warning about exceeding the deadline
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "DISPATCH_DEADLINE" in warning_msg
