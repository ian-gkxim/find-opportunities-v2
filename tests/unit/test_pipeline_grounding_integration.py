"""Unit tests for pipeline grounding integration (Tasks 16.1 and 16.2).

Tests:
- Task 16.1: GroundingVerifier wired into ReviewPipelineStage after Review_Service
  - Grounding invoked when grounding_technique is configured
  - Grounding skipped when grounding_technique is absent
  - Grounding_unverified handled gracefully (pipeline proceeds)
  - Notification sent for blocked/unverified results

- Task 16.2: Resolution responses wired to pipeline unblocking
  - WebSocket notification emitted when no ungrounded claims remain
  - Still-blocked notification sent when ungrounded claims persist

Requirements: 1.1, 1.4, 3.2, 3.3
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingReport,
    GroundingResult,
    GroundingStatus,
    MaterialGroundingStatus,
)
from app.core.review_models import (
    DraftMaterial,
    ReasoningLog,
    ReviewResult,
    ReviewStatus,
)
from app.core.review_pipeline_stage import ReviewPipelineStage


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


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
def mock_schema_with_grounding():
    """SchemaRegistry mock with both review_technique and grounding_technique."""
    schema = MagicMock()
    # Review technique
    review_technique = MagicMock()
    review_technique.id = "standard_material_review"
    review_technique.max_review_cycles = 2
    review_technique.critique_categories = [
        "missed_keywords", "company_angles", "reframing", "tone_style"
    ]
    schema.get_review_technique_for_prepare.return_value = review_technique
    # Grounding technique
    grounding_technique = MagicMock()
    grounding_technique.id = "standard_grounding"
    schema.get_grounding_technique_for_prepare.return_value = grounding_technique
    return schema


@pytest.fixture
def mock_schema_without_grounding():
    """SchemaRegistry mock with review_technique but no grounding_technique."""
    schema = MagicMock()
    # Review technique
    review_technique = MagicMock()
    review_technique.id = "standard_material_review"
    review_technique.max_review_cycles = 2
    review_technique.critique_categories = [
        "missed_keywords", "company_angles", "reframing", "tone_style"
    ]
    schema.get_review_technique_for_prepare.return_value = review_technique
    # No grounding technique
    schema.get_grounding_technique_for_prepare.return_value = None
    return schema


@pytest.fixture
def mock_schema_no_review_no_grounding():
    """SchemaRegistry with neither review nor grounding configured."""
    schema = MagicMock()
    schema.get_review_technique_for_prepare.return_value = None
    schema.get_grounding_technique_for_prepare.return_value = None
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


def _make_grounding_result(
    *,
    status: MaterialGroundingStatus = MaterialGroundingStatus.GROUNDING_VERIFIED,
    ungrounded_count: int = 0,
    requires_action: bool = False,
    blocked_states: list[str] | None = None,
) -> GroundingResult:
    """Create a GroundingResult for testing."""
    now = datetime.now(timezone.utc)
    report = GroundingReport(
        id="rpt-001",
        material_id="mat-001",
        pipeline_record_id="pr-001",
        claims=[],
        total_claims=3,
        grounded_count=3 - ungrounded_count,
        partially_grounded_count=0,
        ungrounded_count=ungrounded_count,
        material_grounding_status=status,
        extraction_duration_ms=100,
        verification_duration_ms=50,
        created_at=now,
        updated_at=now,
    )
    return GroundingResult(
        material_id="mat-001",
        material_grounding_status=status,
        grounding_report=report,
        blocked_states=blocked_states or [],
        requires_action=requires_action,
    )


# ─── Task 16.1: Wire GroundingVerifier into pipeline ─────────────────────────


class TestGroundingWiredIntoPipeline:
    """Tests for grounding verification wired into the prepare pipeline (Task 16.1)."""

    @pytest.mark.asyncio
    async def test_grounding_invoked_when_configured(
        self, sample_draft_material, mock_schema_with_grounding, mock_review_service
    ):
        """When grounding_technique is configured, verify_material is called."""
        mock_verifier = AsyncMock()
        mock_verifier.verify_material.return_value = _make_grounding_result()

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_grounding,
            grounding_verifier=mock_verifier,
        )

        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        mock_verifier.verify_material.assert_called_once()
        assert result["grounding_result"] is not None
        assert result["grounding_result"].material_grounding_status == (
            MaterialGroundingStatus.GROUNDING_VERIFIED
        )

    @pytest.mark.asyncio
    async def test_grounding_skipped_when_not_configured(
        self, sample_draft_material, mock_schema_without_grounding, mock_review_service
    ):
        """When no grounding_technique configured, grounding is skipped."""
        mock_verifier = AsyncMock()

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_without_grounding,
            grounding_verifier=mock_verifier,
        )

        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        mock_verifier.verify_material.assert_not_called()
        assert result["grounding_result"] is None

    @pytest.mark.asyncio
    async def test_grounding_skipped_when_no_verifier_available(
        self, sample_draft_material, mock_schema_with_grounding, mock_review_service
    ):
        """When grounding is configured but no verifier provided, skip gracefully."""
        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_grounding,
            grounding_verifier=None,  # No verifier available
        )

        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        assert result["grounding_result"] is None

    @pytest.mark.asyncio
    async def test_grounding_unverified_handled_gracefully(
        self, sample_draft_material, mock_schema_with_grounding, mock_review_service
    ):
        """Grounding_unverified allows pipeline to proceed (Requirement 1.4)."""
        mock_verifier = AsyncMock()
        mock_verifier.verify_material.return_value = _make_grounding_result(
            status=MaterialGroundingStatus.GROUNDING_UNVERIFIED,
            requires_action=True,
        )

        mock_notification = AsyncMock()

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_grounding,
            grounding_verifier=mock_verifier,
            notification_service=mock_notification,
        )

        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        # Pipeline proceeds — revised content returned
        assert result["revised_content"] == "This is the REVISED content after review."
        # Grounding result shows unverified
        assert result["grounding_result"].material_grounding_status == (
            MaterialGroundingStatus.GROUNDING_UNVERIFIED
        )
        # Notification service was called
        mock_notification.notify_requires_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_grounding_failure_handled_gracefully(
        self, sample_draft_material, mock_schema_with_grounding, mock_review_service
    ):
        """If grounding raises an exception, pipeline proceeds gracefully."""
        mock_verifier = AsyncMock()
        mock_verifier.verify_material.side_effect = RuntimeError("LLM exploded")

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_grounding,
            grounding_verifier=mock_verifier,
        )

        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        # Pipeline proceeds — revised content returned
        assert result["revised_content"] == "This is the REVISED content after review."
        assert result["grounding_result"] is None

    @pytest.mark.asyncio
    async def test_grounding_receives_reviewed_content(
        self, sample_draft_material, mock_schema_with_grounding, mock_review_service
    ):
        """GroundingVerifier receives the reviewed (not original) content."""
        mock_verifier = AsyncMock()
        mock_verifier.verify_material.return_value = _make_grounding_result()

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_grounding,
            grounding_verifier=mock_verifier,
        )

        await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        # Check that the reviewed material passed to verify_material has revised text
        call_kwargs = mock_verifier.verify_material.call_args[1]
        reviewed_material = call_kwargs["reviewed_material"]
        assert reviewed_material.text == "This is the REVISED content after review."
        assert reviewed_material.id == "mat-001"
        assert reviewed_material.pipeline_record_id == "pr-001"

    @pytest.mark.asyncio
    async def test_grounding_invoked_even_when_review_skipped(
        self, sample_draft_material, mock_schema_no_review_no_grounding
    ):
        """When both review and grounding are absent, both are skipped."""
        mock_verifier = AsyncMock()

        stage = ReviewPipelineStage(
            review_service=AsyncMock(),
            schema_registry=mock_schema_no_review_no_grounding,
            grounding_verifier=mock_verifier,
        )

        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        mock_verifier.verify_material.assert_not_called()
        assert result["grounding_result"] is None

    @pytest.mark.asyncio
    async def test_grounding_blocked_sends_notification(
        self, sample_draft_material, mock_schema_with_grounding, mock_review_service
    ):
        """When grounding is blocked, notification service is called."""
        mock_verifier = AsyncMock()
        mock_verifier.verify_material.return_value = _make_grounding_result(
            status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            ungrounded_count=2,
            requires_action=True,
            blocked_states=["Approve", "Applied", "Sent", "Proposal Submitted"],
        )

        mock_notification = AsyncMock()

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_grounding,
            grounding_verifier=mock_verifier,
            notification_service=mock_notification,
        )

        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        mock_notification.notify_requires_action.assert_called_once()
        assert result["grounding_result"].requires_action is True

    @pytest.mark.asyncio
    async def test_grounding_verified_no_notification(
        self, sample_draft_material, mock_schema_with_grounding, mock_review_service
    ):
        """When grounding is verified, no notification is sent."""
        mock_verifier = AsyncMock()
        mock_verifier.verify_material.return_value = _make_grounding_result(
            status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            requires_action=False,
        )

        mock_notification = AsyncMock()

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_grounding,
            grounding_verifier=mock_verifier,
            notification_service=mock_notification,
        )

        await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        # No notification for verified materials
        mock_notification.notify_requires_action.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_break_pipeline(
        self, sample_draft_material, mock_schema_with_grounding, mock_review_service
    ):
        """If notification service fails, pipeline still proceeds."""
        mock_verifier = AsyncMock()
        mock_verifier.verify_material.return_value = _make_grounding_result(
            status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            requires_action=True,
        )

        mock_notification = AsyncMock()
        mock_notification.notify_requires_action.side_effect = RuntimeError("WS down")

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema_with_grounding,
            grounding_verifier=mock_verifier,
            notification_service=mock_notification,
        )

        result = await stage.process_after_generation(
            draft_material=sample_draft_material,
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            enrichment=MagicMock(),
            opportunity_description="Test opportunity",
        )

        # Pipeline still returns grounding result despite notification failure
        assert result["grounding_result"] is not None


# ─── Task 16.2: Resolution responses wired to pipeline unblocking ─────────


class TestResolutionPipelineUnblocking:
    """Tests for resolution endpoint emitting pipeline unblocked notification (Task 16.2)."""

    @pytest.mark.asyncio
    async def test_unblocked_notification_emitted_on_successful_resolution(self):
        """When resolution leaves no ungrounded claims, pipeline_unblocked is emitted."""
        from app.api.grounding import _notify_resolution_outcome

        result = _make_grounding_result(
            status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            requires_action=False,
        )

        mock_ws = MagicMock()
        mock_ws.broadcast_notification = AsyncMock()

        with patch(
            "app.core.websocket_manager.WebSocketManager", return_value=mock_ws
        ), patch(
            "app.core.grounding_notifications.GroundingNotificationService"
        ):
            await _notify_resolution_outcome(result)

            mock_ws.broadcast_notification.assert_called_once()
            notification = mock_ws.broadcast_notification.call_args[0][0]
            assert notification["category"] == "pipeline_unblocked"
            assert notification["severity"] == "success"
            assert notification["material_id"] == "mat-001"
            assert notification["material_grounding_status"] == "grounding_verified"

    @pytest.mark.asyncio
    async def test_still_blocked_notification_emitted_when_ungrounded_remain(self):
        """When resolution still has ungrounded claims, blocked notification is re-sent."""
        from app.api.grounding import _notify_resolution_outcome

        result = _make_grounding_result(
            status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            ungrounded_count=1,
            requires_action=True,
            blocked_states=["Approve", "Applied", "Sent", "Proposal Submitted"],
        )

        mock_ws = MagicMock()
        mock_ws.broadcast_notification = AsyncMock()

        mock_notif = MagicMock()
        mock_notif.notify_requires_action = AsyncMock()

        with patch(
            "app.core.websocket_manager.WebSocketManager", return_value=mock_ws
        ), patch(
            "app.core.grounding_notifications.GroundingNotificationService",
            return_value=mock_notif,
        ):
            await _notify_resolution_outcome(result)

            # Still-blocked sends notification via GroundingNotificationService
            mock_notif.notify_requires_action.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_raise(self):
        """Notification failure in resolution is non-critical and doesn't raise."""
        from app.api.grounding import _notify_resolution_outcome

        result = _make_grounding_result(
            status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            requires_action=False,
        )

        mock_ws = MagicMock()
        mock_ws.broadcast_notification = AsyncMock(
            side_effect=RuntimeError("Redis down")
        )

        with patch(
            "app.core.websocket_manager.WebSocketManager", return_value=mock_ws
        ), patch(
            "app.core.grounding_notifications.GroundingNotificationService"
        ):
            # Should not raise
            await _notify_resolution_outcome(result)
