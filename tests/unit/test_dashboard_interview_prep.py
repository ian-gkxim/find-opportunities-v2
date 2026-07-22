"""Unit tests for Dashboard interview prep integration.

Tests:
- Pack summary returned for pipeline record detail when ready
- Pack summary returns None when no pack exists
- Failed packs appear in PipelineManager "Requires Action" list
- No interview prep items when no failed packs
- Regenerate URL included in summary

Requirements: 3.2, 3.3
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.interview_prep_enrichment import (
    InterviewPrepSummary,
    get_interview_prep_summary,
)
from app.core.interview_prep_models import (
    Interview_Prep_Pack,
    PackStatus,
    STAR_Talking_Point,
)
from app.core.pipeline_manager import (
    PipelineManager,
    PipelineRecordData,
    RequiresActionType,
)


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


def _make_star_point(competency: str = "Leadership") -> STAR_Talking_Point:
    """Helper to create a minimal STAR_Talking_Point for testing."""
    return STAR_Talking_Point(
        competency=competency,
        question=f"Tell me about your {competency} experience.",
        situation="At previous company...",
        task="Needed to lead the team.",
        action="Organized sprints and retros.",
        result="Delivered project 2 weeks early.",
        source_asset_refs=["resume"],
    )


def _make_pack(
    *,
    pack_id: str = "pack-001",
    pipeline_record_id: str = "pr-001",
    beneficiary_id: str = "ben-001",
    status: PackStatus = PackStatus.READY,
) -> Interview_Prep_Pack:
    """Helper to create an Interview_Prep_Pack for testing."""
    now = datetime.now(timezone.utc)
    return Interview_Prep_Pack(
        id=pack_id,
        pipeline_record_id=pipeline_record_id,
        beneficiary_id=beneficiary_id,
        opportunity_type_id="job_site",
        likely_questions=[f"Question {i}" for i in range(10)],
        star_talking_points=[_make_star_point(f"Competency {i}") for i in range(5)],
        company_briefing="A brief company overview for the interview.",
        questions_to_ask=["What is the team size?", "What tech stack?", "Growth plans?"],
        status=status,
        omission_notes=[],
        grounding_flags=[],
        generation_duration_ms=5000,
        created_at=now,
        updated_at=now,
    )


# ─── Tests: get_interview_prep_summary ────────────────────────────────────────


class TestGetInterviewPrepSummary:
    """Tests for get_interview_prep_summary function (Requirement 3.2)."""

    @pytest.mark.asyncio
    async def test_pack_summary_returned_for_pipeline_record(self):
        """When a pack exists, summary is returned with pack data."""
        pack = _make_pack(pipeline_record_id="pr-100")
        mock_repo = AsyncMock()
        mock_repo.get_pack = AsyncMock(return_value=pack)

        with (
            patch(
                "app.core.interview_prep_repository.InterviewPrepRepository",
                return_value=mock_repo,
            ),
            patch(
                "app.models.base.get_async_session_factory",
                return_value=MagicMock(),
            ),
        ):
            result = await get_interview_prep_summary("pr-100")

        assert result is not None
        assert isinstance(result, InterviewPrepSummary)
        assert result.pack_id == "pack-001"
        assert result.status == "ready"
        assert len(result.likely_questions) == 10
        assert result.star_talking_points_count == 5
        assert result.company_briefing == "A brief company overview for the interview."
        assert len(result.questions_to_ask) == 3
        assert result.has_grounding_flags is False
        assert result.generation_duration_ms == 5000

    @pytest.mark.asyncio
    async def test_pack_summary_returns_none_when_no_pack(self):
        """When no pack exists for the pipeline record, returns None."""
        mock_repo = AsyncMock()
        mock_repo.get_pack = AsyncMock(return_value=None)

        with (
            patch(
                "app.core.interview_prep_repository.InterviewPrepRepository",
                return_value=mock_repo,
            ),
            patch(
                "app.models.base.get_async_session_factory",
                return_value=MagicMock(),
            ),
        ):
            result = await get_interview_prep_summary("pr-nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_regenerate_url_in_summary(self):
        """Summary includes a regenerate_url for on-demand regeneration."""
        pack = _make_pack(pipeline_record_id="pr-200")
        mock_repo = AsyncMock()
        mock_repo.get_pack = AsyncMock(return_value=pack)

        with (
            patch(
                "app.core.interview_prep_repository.InterviewPrepRepository",
                return_value=mock_repo,
            ),
            patch(
                "app.models.base.get_async_session_factory",
                return_value=MagicMock(),
            ),
        ):
            result = await get_interview_prep_summary("pr-200")

        assert result is not None
        assert result.regenerate_url == "/api/interview-prep/pr-200/regenerate"
        assert result.detail_url == "/api/interview-prep/pr-200"


# ─── Tests: PipelineManager.get_requires_action_items with interview prep ─────


class TestFailedPackInRequiresAction:
    """Tests for failed interview prep packs in Requires Action (Requirement 3.3)."""

    @pytest.mark.asyncio
    async def test_failed_pack_in_requires_action(self):
        """Failed interview prep packs appear in the requires action list."""
        failed_pack = _make_pack(
            pack_id="pack-fail-1",
            pipeline_record_id="pr-300",
            beneficiary_id="ben-300",
            status=PackStatus.FAILED,
        )

        # Pipeline repo mock (returns empty lists for other action types)
        pipeline_repo = AsyncMock()
        pipeline_repo.get_stale_records = AsyncMock(return_value=[])
        pipeline_repo.get_failed_sequence_records = AsyncMock(return_value=[])
        pipeline_repo.get_enrichment_error_records = AsyncMock(return_value=[])

        # Interview prep repo mock
        interview_prep_repo = AsyncMock()
        interview_prep_repo.get_failed_packs = AsyncMock(return_value=[failed_pack])

        manager = PipelineManager(
            repository=pipeline_repo,
            interview_prep_repo=interview_prep_repo,
        )

        items = await manager.get_requires_action_items()

        assert len(items) == 1
        assert items[0].action_type == RequiresActionType.INTERVIEW_PREP_FAILED
        assert items[0].record_id == "pr-300"
        assert items[0].beneficiary_id == "ben-300"
        assert "interview prep" in items[0].description.lower()

    @pytest.mark.asyncio
    async def test_no_failed_packs_in_requires_action_when_empty(self):
        """No interview prep items when no failed packs exist."""
        # Pipeline repo mock
        pipeline_repo = AsyncMock()
        pipeline_repo.get_stale_records = AsyncMock(return_value=[])
        pipeline_repo.get_failed_sequence_records = AsyncMock(return_value=[])
        pipeline_repo.get_enrichment_error_records = AsyncMock(return_value=[])

        # Interview prep repo mock — no failed packs
        interview_prep_repo = AsyncMock()
        interview_prep_repo.get_failed_packs = AsyncMock(return_value=[])

        manager = PipelineManager(
            repository=pipeline_repo,
            interview_prep_repo=interview_prep_repo,
        )

        items = await manager.get_requires_action_items()

        assert len(items) == 0
        # Verify the repo was still called
        interview_prep_repo.get_failed_packs.assert_called_once_with(limit=20)
