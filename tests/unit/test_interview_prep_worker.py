"""Unit tests for app.workers.interview_prep_worker.

Validates worker task execution, timeout handling, error surfacing,
and correct status dict structure for both process and regenerate flows.

Requirements: 1.1, 3.3
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.interview_prep_models import (
    DeadlineExceededError,
    Interview_Prep_Pack,
    InterviewPrepError,
    PackStatus,
    STAR_Talking_Point,
)
from app.workers.interview_prep_worker import (
    process_interview_prep,
    regenerate_interview_prep,
)


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_context() -> dict:
    """Build an ARQ-style context dict with the expected shared resource keys."""
    return {
        "session_factory": MagicMock(),
        "llm_router": MagicMock(),
        "schema_registry": MagicMock(),
        "grounding_verifier": MagicMock(),
        "event_publisher": MagicMock(),
    }


def _make_pack(
    pack_id: str = "pack-001",
    pipeline_record_id: str = "record-123",
    status: PackStatus = PackStatus.READY,
) -> Interview_Prep_Pack:
    """Create a minimal Interview_Prep_Pack for testing."""
    return Interview_Prep_Pack(
        id=pack_id,
        pipeline_record_id=pipeline_record_id,
        beneficiary_id="beneficiary-1",
        opportunity_type_id="job_site",
        likely_questions=["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"],
        star_talking_points=[
            STAR_Talking_Point(
                competency=f"Competency {i}",
                question=f"Question {i}",
                situation=f"Situation {i}",
                task=f"Task {i}",
                action=f"Action {i}",
                result=f"Result {i}",
                source_asset_refs=["resume"],
            )
            for i in range(5)
        ],
        company_briefing="A brief company overview.",
        questions_to_ask=["Ask Q1", "Ask Q2", "Ask Q3"],
        status=status,
    )


# ─── TEST: SUCCESSFUL GENERATION ─────────────────────────────────────────────


class TestProcessInterviewPrepSuccess:
    """process_interview_prep returns correct status on successful generation."""

    @pytest.mark.asyncio
    @patch("app.workers.interview_prep_worker._build_service")
    async def test_process_interview_prep_success_returns_ready(
        self, mock_build_service
    ):
        """Successful generation with READY status returns ready and pack_id."""
        # Arrange
        pack = _make_pack(pack_id="pack-ready-1", status=PackStatus.READY)
        mock_service = MagicMock()
        mock_service.generate_pack = AsyncMock(return_value=pack)
        mock_build_service.return_value = mock_service

        ctx = _make_context()

        # Act
        result = await process_interview_prep(ctx, "record-123")

        # Assert
        assert result["status"] == "ready"
        assert result["pack_id"] == "pack-ready-1"
        mock_service.generate_pack.assert_called_once_with("record-123")

    @pytest.mark.asyncio
    @patch("app.workers.interview_prep_worker._build_service")
    async def test_process_interview_prep_success_returns_ready_with_flags(
        self, mock_build_service
    ):
        """Successful generation with READY_WITH_FLAGS status returns ready_with_flags."""
        # Arrange
        pack = _make_pack(
            pack_id="pack-flags-1", status=PackStatus.READY_WITH_FLAGS
        )
        mock_service = MagicMock()
        mock_service.generate_pack = AsyncMock(return_value=pack)
        mock_build_service.return_value = mock_service

        ctx = _make_context()

        # Act
        result = await process_interview_prep(ctx, "record-456")

        # Assert
        assert result["status"] == "ready_with_flags"
        assert result["pack_id"] == "pack-flags-1"
        mock_service.generate_pack.assert_called_once_with("record-456")


# ─── TEST: TIMEOUT / DEADLINE EXCEEDED ────────────────────────────────────────


class TestProcessInterviewPrepTimeout:
    """process_interview_prep handles deadline exceeded correctly."""

    @pytest.mark.asyncio
    @patch("app.workers.interview_prep_worker._build_service")
    async def test_process_interview_prep_timeout_returns_failed(
        self, mock_build_service
    ):
        """DeadlineExceededError marks pack as failed with no pack_id."""
        # Arrange
        mock_service = MagicMock()
        mock_service.generate_pack = AsyncMock(
            side_effect=DeadlineExceededError(
                pipeline_record_id="record-789",
                deadline_seconds=120.0,
            )
        )
        mock_build_service.return_value = mock_service

        ctx = _make_context()

        # Act
        result = await process_interview_prep(ctx, "record-789")

        # Assert
        assert result["status"] == "failed"
        assert result["pack_id"] is None

    @pytest.mark.asyncio
    @patch("app.workers.interview_prep_worker._build_service")
    async def test_process_interview_prep_asyncio_timeout_returns_failed(
        self, mock_build_service
    ):
        """asyncio.TimeoutError (from asyncio.timeout) marks pack as failed."""
        # Arrange
        mock_service = MagicMock()
        mock_service.generate_pack = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        mock_build_service.return_value = mock_service

        ctx = _make_context()

        # Act
        result = await process_interview_prep(ctx, "record-timeout")

        # Assert
        assert result["status"] == "failed"
        assert result["pack_id"] is None


# ─── TEST: ERROR HANDLING ─────────────────────────────────────────────────────


class TestProcessInterviewPrepErrors:
    """process_interview_prep handles errors and returns failed status."""

    @pytest.mark.asyncio
    @patch("app.workers.interview_prep_worker._build_service")
    async def test_process_interview_prep_error_returns_failed(
        self, mock_build_service
    ):
        """InterviewPrepError after retry exhaustion returns failed."""
        # Arrange
        mock_service = MagicMock()
        mock_service.generate_pack = AsyncMock(
            side_effect=InterviewPrepError(
                "Generation failed after retries",
                pipeline_record_id="record-err",
                retryable=False,
            )
        )
        mock_build_service.return_value = mock_service

        ctx = _make_context()

        # Act
        result = await process_interview_prep(ctx, "record-err")

        # Assert
        assert result["status"] == "failed"
        assert result["pack_id"] is None

    @pytest.mark.asyncio
    @patch("app.workers.interview_prep_worker._build_service")
    async def test_process_interview_prep_unexpected_error_returns_failed(
        self, mock_build_service
    ):
        """Unexpected RuntimeError returns failed without crashing the worker."""
        # Arrange
        mock_service = MagicMock()
        mock_service.generate_pack = AsyncMock(
            side_effect=RuntimeError("Unexpected internal error")
        )
        mock_build_service.return_value = mock_service

        ctx = _make_context()

        # Act
        result = await process_interview_prep(ctx, "record-unexpected")

        # Assert
        assert result["status"] == "failed"
        assert result["pack_id"] is None


# ─── TEST: REGENERATION ───────────────────────────────────────────────────────


class TestRegenerateInterviewPrep:
    """regenerate_interview_prep handles success and failure correctly."""

    @pytest.mark.asyncio
    @patch("app.workers.interview_prep_worker._build_service")
    async def test_regenerate_interview_prep_success(self, mock_build_service):
        """Successful regeneration returns ready status with new pack_id."""
        # Arrange
        pack = _make_pack(pack_id="pack-regen-1", status=PackStatus.READY)
        mock_service = MagicMock()
        mock_service.regenerate_pack = AsyncMock(return_value=pack)
        mock_build_service.return_value = mock_service

        ctx = _make_context()

        # Act
        result = await regenerate_interview_prep(ctx, "record-regen")

        # Assert
        assert result["status"] == "ready"
        assert result["pack_id"] == "pack-regen-1"
        mock_service.regenerate_pack.assert_called_once_with("record-regen")

    @pytest.mark.asyncio
    @patch("app.workers.interview_prep_worker._build_service")
    async def test_regenerate_interview_prep_failure(self, mock_build_service):
        """Regeneration failure (InterviewPrepError) returns failed."""
        # Arrange
        mock_service = MagicMock()
        mock_service.regenerate_pack = AsyncMock(
            side_effect=InterviewPrepError(
                "Regeneration failed",
                pipeline_record_id="record-regen-fail",
                retryable=False,
            )
        )
        mock_build_service.return_value = mock_service

        ctx = _make_context()

        # Act
        result = await regenerate_interview_prep(ctx, "record-regen-fail")

        # Assert
        assert result["status"] == "failed"
        assert result["pack_id"] is None
