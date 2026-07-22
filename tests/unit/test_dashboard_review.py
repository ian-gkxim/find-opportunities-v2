"""Unit tests for Dashboard review status integration.

Tests that:
- Review status is included in pipeline record detail response
- Unreviewed materials appear in the "Requires Action" list

Requirements: 3.4
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.api.pipeline import (
    PipelineRecordDetail,
    _get_review_status_for_record,
)
from app.api.dashboard import (
    ActionItemEntry,
    _get_requires_action,
)


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_mock_session_with_review_data(
    review_status: str | None = "reviewed",
    edits_applied: int = 3,
) -> AsyncMock:
    """Create a mock async session that returns review data for a pipeline record."""
    session = AsyncMock()

    if review_status is not None:
        # Simulate a row returned from the JOIN query
        mock_row = (review_status, edits_applied)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
    else:
        # Simulate no review data
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None

    session.execute = AsyncMock(return_value=mock_result)
    return session


def _make_mock_session_with_unreviewed_materials(
    materials: list[dict] | None = None,
) -> AsyncMock:
    """Create a mock async session that returns unreviewed materials.

    The session.execute returns different results depending on the query.
    """
    session = AsyncMock()

    if materials is None:
        materials = []

    # Build rows matching the SELECT columns:
    # material_id, pipeline_record_id, prepare_technique_id, completed_at
    rows = [
        (
            m.get("material_id", str(uuid4())),
            m.get("pipeline_record_id", str(uuid4())),
            m.get("prepare_technique_id", "cv_and_cover_letter"),
            m.get("completed_at", datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)),
        )
        for m in materials
    ]

    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows
    session.execute = AsyncMock(return_value=mock_result)
    return session


# ─── TEST: REVIEW STATUS IN PIPELINE RECORD DETAIL ────────────────────────────


class TestPipelineRecordReviewStatus:
    """Review status is included in pipeline record detail response."""

    @pytest.mark.asyncio
    async def test_review_status_returned_when_review_exists(self):
        """Pipeline record with a completed review includes status and edit count."""
        session = _make_mock_session_with_review_data(
            review_status="reviewed", edits_applied=5
        )

        result = await _get_review_status_for_record(session, "some-pipeline-id")

        assert result["review_status"] == "reviewed"
        assert result["edits_applied_count"] == 5

    @pytest.mark.asyncio
    async def test_review_status_none_when_no_review_data(self):
        """Pipeline record without review data returns None for both fields."""
        session = _make_mock_session_with_review_data(review_status=None)

        result = await _get_review_status_for_record(session, "some-pipeline-id")

        assert result["review_status"] is None
        assert result["edits_applied_count"] is None

    @pytest.mark.asyncio
    async def test_unreviewed_status_returned_correctly(self):
        """Pipeline record marked unreviewed returns 'unreviewed' status."""
        session = _make_mock_session_with_review_data(
            review_status="unreviewed", edits_applied=0
        )

        result = await _get_review_status_for_record(session, "failed-record-id")

        assert result["review_status"] == "unreviewed"
        assert result["edits_applied_count"] == 0

    @pytest.mark.asyncio
    async def test_review_failed_status_returned_correctly(self):
        """Pipeline record with failed review returns 'review_failed'."""
        session = _make_mock_session_with_review_data(
            review_status="review_failed", edits_applied=0
        )

        result = await _get_review_status_for_record(session, "failed-record-id")

        assert result["review_status"] == "review_failed"
        assert result["edits_applied_count"] == 0

    def test_pipeline_record_detail_model_accepts_review_fields(self):
        """PipelineRecordDetail model includes optional review_status and edits_applied_count."""
        record_id = uuid4()
        detail = PipelineRecordDetail(
            id=record_id,
            prospect_id=record_id,
            opportunity_type_id="job_application",
            beneficiary_id="consultant",
            current_status="Drafted",
            created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            review_status="reviewed",
            edits_applied_count=3,
        )

        assert detail.review_status == "reviewed"
        assert detail.edits_applied_count == 3

    def test_pipeline_record_detail_model_allows_none_review_fields(self):
        """PipelineRecordDetail model allows None for review fields."""
        record_id = uuid4()
        detail = PipelineRecordDetail(
            id=record_id,
            prospect_id=record_id,
            opportunity_type_id="job_application",
            beneficiary_id="consultant",
            current_status="Drafted",
            created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )

        assert detail.review_status is None
        assert detail.edits_applied_count is None


# ─── TEST: UNREVIEWED MATERIALS IN REQUIRES ACTION ───────────────────────────


class TestUnreviewedMaterialsInRequiresAction:
    """Unreviewed materials appear in the 'Requires Action' list."""

    @pytest.mark.asyncio
    async def test_unreviewed_materials_returned_as_action_items(self):
        """Materials with unreviewed status appear in requires-action list."""
        material_id = str(uuid4())
        pipeline_record_id = str(uuid4())

        session = _make_mock_session_with_unreviewed_materials([
            {
                "material_id": material_id,
                "pipeline_record_id": pipeline_record_id,
                "prepare_technique_id": "cv_and_cover_letter",
                "completed_at": datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
            }
        ])

        result = await _get_requires_action(session, "consultant")

        assert len(result) == 1
        item = result[0]
        assert item.type == "unreviewed_material"
        assert item.id == material_id
        assert "cv_and_cover_letter" in item.title
        assert material_id[:8] in item.description

    @pytest.mark.asyncio
    async def test_multiple_unreviewed_materials_all_returned(self):
        """Multiple unreviewed materials all appear in action items."""
        materials = [
            {
                "material_id": str(uuid4()),
                "pipeline_record_id": str(uuid4()),
                "prepare_technique_id": "cv_and_cover_letter",
                "completed_at": datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
            },
            {
                "material_id": str(uuid4()),
                "pipeline_record_id": str(uuid4()),
                "prepare_technique_id": "cold_email_composition",
                "completed_at": datetime(2024, 6, 14, 8, 0, 0, tzinfo=timezone.utc),
            },
        ]

        session = _make_mock_session_with_unreviewed_materials(materials)

        result = await _get_requires_action(session, "consultant")

        assert len(result) == 2
        types = [item.type for item in result]
        assert all(t == "unreviewed_material" for t in types)

    @pytest.mark.asyncio
    async def test_empty_unreviewed_returns_empty_list(self):
        """When no unreviewed materials exist, action items list is empty."""
        session = _make_mock_session_with_unreviewed_materials([])

        result = await _get_requires_action(session, "consultant")

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_action_item_has_correct_created_at_format(self):
        """Action items use ISO format for createdAt field."""
        completed = datetime(2024, 7, 20, 14, 30, 0, tzinfo=timezone.utc)
        session = _make_mock_session_with_unreviewed_materials([
            {
                "material_id": str(uuid4()),
                "pipeline_record_id": str(uuid4()),
                "prepare_technique_id": "proposal_composition",
                "completed_at": completed,
            }
        ])

        result = await _get_requires_action(session, "consultant")

        assert len(result) == 1
        assert result[0].created_at == completed.isoformat()

    @pytest.mark.asyncio
    async def test_action_item_company_name_defaults_to_unknown(self):
        """Unreviewed material action items default company name to Unknown."""
        session = _make_mock_session_with_unreviewed_materials([
            {
                "material_id": str(uuid4()),
                "pipeline_record_id": str(uuid4()),
                "prepare_technique_id": "cv_and_cover_letter",
                "completed_at": datetime(2024, 6, 1, tzinfo=timezone.utc),
            }
        ])

        result = await _get_requires_action(session, "consultant")

        assert len(result) == 1
        assert result[0].company_name == "Unknown"
