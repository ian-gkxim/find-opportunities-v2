"""Unit tests for PipelineManager state-entry technique dispatch.

Validates _dispatch_state_entry_techniques method and its integration
in _transition().

Requirements: 1.1, 3.1
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.pipeline_manager import (
    PipelineManager,
    PipelineRecordData,
    PipelineTransitionResult,
)
from app.core.schema_registry import PrepareTechnique


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_record(
    *,
    record_id: str = "rec-001",
    prospect_id: str = "prospect-001",
    opportunity_type_id: str = "job_site",
    beneficiary_id: str = "ben-001",
    current_status: str = "Sent",
) -> PipelineRecordData:
    """Create a lightweight PipelineRecordData for testing."""
    return PipelineRecordData(
        id=record_id,
        prospect_id=prospect_id,
        opportunity_type_id=opportunity_type_id,
        beneficiary_id=beneficiary_id,
        current_status=current_status,
    )


def _make_interview_technique() -> PrepareTechnique:
    """Create an interview_preparation PrepareTechnique."""
    return PrepareTechnique(
        id="interview_preparation",
        service_class="InterviewPrepService",
        description="Generates interview prep pack on Interview state entry",
        trigger="state_entry",
        trigger_state="Interview",
        inputs=["opportunity_description", "tailored_cv"],
        outputs=["interview_prep_pack"],
    )


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_repo():
    """Mock PipelineRepository."""
    repo = MagicMock()
    repo.update_pipeline_record = AsyncMock()
    return repo


@pytest.fixture
def mock_publisher():
    """Mock EventPublisher."""
    publisher = MagicMock()
    publisher.publish = AsyncMock(return_value=1)
    return publisher


@pytest.fixture
def mock_schema_registry():
    """Mock SchemaRegistry with configurable state_entry_techniques."""
    schema = MagicMock()
    schema.get_state_entry_techniques = MagicMock(return_value=[])
    return schema


@pytest.fixture
def mock_redis_pool():
    """Mock ARQ Redis pool."""
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    return pool


@pytest.fixture
def pipeline_manager(mock_repo, mock_publisher, mock_schema_registry, mock_redis_pool):
    """Create a PipelineManager with all mocked dependencies."""
    return PipelineManager(
        repository=mock_repo,
        publisher=mock_publisher,
        gate_service=None,
        schema_registry=mock_schema_registry,
        redis_pool=mock_redis_pool,
    )


# ─── STATE-ENTRY DISPATCH TESTS ──────────────────────────────────────────────


class TestInterviewStateEntryEnqueuesJob:
    """Test that Interview state entry enqueues interview_prep job."""

    @pytest.mark.asyncio
    async def test_interview_state_entry_enqueues_job(
        self, pipeline_manager, mock_schema_registry, mock_redis_pool
    ):
        """WHEN transitioning to Interview state and schema returns interview_preparation
        technique, THEN enqueue_job is called with 'process_interview_prep'."""
        record = _make_record(current_status="Applied")
        technique = _make_interview_technique()
        mock_schema_registry.get_state_entry_techniques.return_value = [technique]

        result = await pipeline_manager._transition(record, "Interview")

        assert result.result == PipelineTransitionResult.ADVANCED
        mock_schema_registry.get_state_entry_techniques.assert_called_once_with(
            opportunity_type_id="job_site",
            state="Interview",
        )
        mock_redis_pool.enqueue_job.assert_called_once_with(
            "process_interview_prep",
            "rec-001",
        )


class TestNonInterviewStateDoesNotEnqueue:
    """Test that non-Interview state entry does not enqueue job."""

    @pytest.mark.asyncio
    async def test_non_interview_state_entry_does_not_enqueue(
        self, pipeline_manager, mock_schema_registry, mock_redis_pool
    ):
        """WHEN transitioning to 'Applied' state and schema returns empty list,
        THEN enqueue_job is NOT called."""
        record = _make_record(current_status="Sent")
        mock_schema_registry.get_state_entry_techniques.return_value = []

        result = await pipeline_manager._transition(record, "Applied")

        assert result.result == PipelineTransitionResult.ADVANCED
        mock_schema_registry.get_state_entry_techniques.assert_called_once_with(
            opportunity_type_id="job_site",
            state="Applied",
        )
        mock_redis_pool.enqueue_job.assert_not_called()


class TestDispatchIsNonBlocking:
    """Test that dispatch is non-blocking (pipeline transition completes immediately)."""

    @pytest.mark.asyncio
    async def test_dispatch_is_non_blocking(
        self, pipeline_manager, mock_schema_registry, mock_redis_pool
    ):
        """WHEN transitioning to Interview, _transition returns ADVANCED immediately
        even though enqueue is called — the transition result does not depend on
        the enqueue outcome."""
        record = _make_record(current_status="Applied")
        technique = _make_interview_technique()
        mock_schema_registry.get_state_entry_techniques.return_value = [technique]

        result = await pipeline_manager._transition(record, "Interview")

        # The transition returns ADVANCED (not blocked by dispatch)
        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.new_status == "Interview"
        assert result.previous_status == "Applied"
        # Enqueue was called but _transition didn't await generation
        mock_redis_pool.enqueue_job.assert_called_once()


class TestTypeWithoutStateEntryTechniques:
    """Test opportunity type without interview_preparation technique does not dispatch."""

    @pytest.mark.asyncio
    async def test_type_without_state_entry_techniques_does_not_dispatch(
        self, pipeline_manager, mock_schema_registry, mock_redis_pool
    ):
        """WHEN using cold_outreach_consultant type with no state_entry_techniques
        configured for this state, THEN no enqueue occurs."""
        record = _make_record(
            opportunity_type_id="cold_outreach_consultant",
            current_status="Applied",
        )
        mock_schema_registry.get_state_entry_techniques.return_value = []

        result = await pipeline_manager._transition(record, "Interview")

        assert result.result == PipelineTransitionResult.ADVANCED
        mock_redis_pool.enqueue_job.assert_not_called()


class TestDispatchHandlesRedisErrorGracefully:
    """Test that _dispatch handles redis errors without propagating."""

    @pytest.mark.asyncio
    async def test_dispatch_handles_redis_error_gracefully(
        self, pipeline_manager, mock_schema_registry, mock_redis_pool
    ):
        """WHEN enqueue_job raises an exception, _dispatch does NOT propagate
        the error — the transition still completes successfully."""
        record = _make_record(current_status="Applied")
        technique = _make_interview_technique()
        mock_schema_registry.get_state_entry_techniques.return_value = [technique]
        mock_redis_pool.enqueue_job.side_effect = Exception("Redis connection lost")

        result = await pipeline_manager._transition(record, "Interview")

        # Transition still succeeds despite Redis failure
        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.new_status == "Interview"
        mock_redis_pool.enqueue_job.assert_called_once()


class TestDispatchWithoutSchemaRegistry:
    """Test PipelineManager with schema=None is a no-op for dispatch."""

    @pytest.mark.asyncio
    async def test_dispatch_without_schema_registry_is_noop(
        self, mock_repo, mock_publisher, mock_redis_pool
    ):
        """WHEN PipelineManager has schema_registry=None, _dispatch_state_entry_techniques
        returns immediately without error."""
        manager = PipelineManager(
            repository=mock_repo,
            publisher=mock_publisher,
            gate_service=None,
            schema_registry=None,
            redis_pool=mock_redis_pool,
        )
        record = _make_record(current_status="Applied")

        result = await manager._transition(record, "Interview")

        assert result.result == PipelineTransitionResult.ADVANCED
        # No enqueue because schema is None — cannot look up techniques
        mock_redis_pool.enqueue_job.assert_not_called()


class TestDispatchWithoutRedisPool:
    """Test PipelineManager with redis_pool=None logs warning."""

    @pytest.mark.asyncio
    async def test_dispatch_without_redis_pool_logs_warning(
        self, mock_repo, mock_publisher, mock_schema_registry
    ):
        """WHEN PipelineManager has redis_pool=None but schema returns techniques,
        a warning is logged and no error is raised."""
        technique = _make_interview_technique()
        mock_schema_registry.get_state_entry_techniques.return_value = [technique]

        manager = PipelineManager(
            repository=mock_repo,
            publisher=mock_publisher,
            gate_service=None,
            schema_registry=mock_schema_registry,
            redis_pool=None,
        )
        record = _make_record(current_status="Applied")

        with patch("app.core.pipeline_manager.logger") as mock_logger:
            result = await manager._transition(record, "Interview")

        assert result.result == PipelineTransitionResult.ADVANCED
        # Should have logged a warning about missing redis_pool
        mock_logger.warning.assert_called()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "redis_pool" in warning_msg.lower() or "enqueue" in warning_msg.lower()
