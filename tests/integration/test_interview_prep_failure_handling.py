"""Integration test for failure handling and non-blocking guarantee.

Verifies that when the LLM_Router times out on all attempts:
1. PipelineManager transitions to Interview state (ADVANCED) immediately
2. process_interview_prep returns {"status": "failed", "pack_id": None}
3. DB.update_pack_status is called with FAILED
4. Pipeline transition is NOT blocked by generation failure

Requirements: 1.1, 3.3
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.interview_prep_models import PackStatus
from app.core.pipeline_manager import PipelineManager, PipelineTransitionResult
from app.workers.interview_prep_worker import process_interview_prep


# ─── FIXTURES / HELPERS ───────────────────────────────────────────────────────


def _make_pipeline_record_data():
    """Create a mock PipelineRecordData in a state ready to transition to Interview."""
    record = MagicMock()
    record.id = "pipeline-record-001"
    record.beneficiary_id = "beneficiary-001"
    record.opportunity_type_id = "job_site"
    record.prospect_id = "prospect-001"
    record.current_status = "Submitted"
    return record


def _make_schema_registry_with_interview_technique():
    """Create a mock SchemaRegistry that returns interview_preparation technique."""
    technique = MagicMock()
    technique.id = "interview_preparation"
    technique.trigger = "state_entry"
    technique.trigger_state = "Interview"

    schema = MagicMock()
    schema.get_state_entry_techniques.return_value = [technique]
    # For pipeline validation
    schema.get_pipeline_states.return_value = [
        "New", "Contacted", "Submitted", "Interview", "Offer", "Placed"
    ]
    return schema


def _make_llm_router_always_timeout():
    """Create an LLM_Router mock that always times out.

    Raises asyncio.TimeoutError to simulate the wait_for timeout in the service.
    """
    llm_router = MagicMock()

    async def _timeout_generate(*args, **kwargs):
        raise asyncio.TimeoutError("LLM generation timed out")

    llm_router.generate = _timeout_generate
    return llm_router


def _make_db_repo_mock():
    """Create a mock InterviewPrepRepository with required async methods."""
    db = MagicMock()
    db.save_pack = AsyncMock()
    db.update_pack_status = AsyncMock()
    db.get_pack = AsyncMock(return_value=None)
    db.get_failed_packs = AsyncMock(return_value=[])

    # Context assembly mocks
    record = MagicMock()
    record.prospect_id = "prospect-001"
    record.beneficiary_id = "beneficiary-001"
    record.opportunity_type_id = "job_site"
    db.get_pipeline_record = AsyncMock(return_value=record)

    prospect = MagicMock()
    prospect.description = "Senior Python Engineer with ML experience needed."
    db.get_prospect = AsyncMock(return_value=prospect)

    db.get_submitted_materials = AsyncMock(return_value={
        "tailored_cv": "My CV content",
        "tailored_cover_letter": "My cover letter content",
    })
    db.get_enrichment_record = AsyncMock(return_value={
        "industry": "Technology",
        "employee_count": "500",
        "tech_stack": ["Python", "AWS"],
        "headquarters": "London",
    })
    db.get_intent_signals = AsyncMock(return_value=[])
    db.get_profile_assets = AsyncMock(return_value={"resume": "My resume content"})
    db.get_star_examples = AsyncMock(return_value=[])

    return db


def _make_worker_ctx_with_timeout_llm():
    """Build an ARQ worker context dict with an LLM that always times out."""
    return {
        "session_factory": MagicMock(),
        "llm_router": _make_llm_router_always_timeout(),
        "schema_registry": MagicMock(),
        "grounding_verifier": MagicMock(),
        "event_publisher": MagicMock(),
    }


# ─── TEST: Pipeline transition is ADVANCED and non-blocking ───────────────────


@pytest.mark.asyncio
async def test_pipeline_transition_to_interview_is_not_blocked_by_prep():
    """WHEN PipelineManager transitions a record to Interview state,
    THEN the transition result is ADVANCED immediately, regardless of
    whether interview_prep generation succeeds or fails.

    The prep generation is dispatched as a non-blocking enqueue operation.

    Requirements: 1.1, 3.3
    """
    # Arrange
    schema = _make_schema_registry_with_interview_technique()
    redis_pool = MagicMock()
    redis_pool.enqueue_job = AsyncMock()

    repo = MagicMock()
    repo.get_pipeline_record = AsyncMock(return_value=_make_pipeline_record_data())
    repo.update_pipeline_record_status = AsyncMock()

    publisher = MagicMock()
    publisher.publish = AsyncMock()

    manager = PipelineManager(
        repository=repo,
        publisher=publisher,
        schema_registry=schema,
        redis_pool=redis_pool,
    )

    record = _make_pipeline_record_data()

    # Act — perform the transition
    # _transition calls repo.update_pipeline_record and _broadcast_pipeline_update internally
    repo.update_pipeline_record = AsyncMock()
    with patch.object(manager, "_broadcast_pipeline_update", new_callable=AsyncMock):
        transition = await manager._transition(record, "Interview")

    # Assert — transition result is ADVANCED (pipeline not blocked)
    assert transition.result == PipelineTransitionResult.ADVANCED
    assert transition.new_status == "Interview"

    # Assert — interview prep job was enqueued (non-blocking dispatch)
    redis_pool.enqueue_job.assert_called_once_with(
        "process_interview_prep",
        record.id,
    )


# ─── TEST: Worker returns failed status after LLM timeout ─────────────────────


@pytest.mark.asyncio
async def test_process_interview_prep_returns_failed_on_timeout():
    """WHEN the LLM_Router times out on all generation attempts,
    THEN process_interview_prep returns {"status": "failed", "pack_id": None}.

    Requirements: 1.1, 3.3
    """
    # Arrange — build service with mocked dependencies
    db_repo = _make_db_repo_mock()
    llm_router = _make_llm_router_always_timeout()
    event_publisher = MagicMock()
    event_publisher.publish = AsyncMock()

    ctx = {
        "session_factory": MagicMock(),
        "llm_router": llm_router,
        "schema_registry": MagicMock(),
        "grounding_verifier": MagicMock(),
        "event_publisher": event_publisher,
    }

    # Patch _build_service to inject our mocked service
    from app.core.interview_prep_service import InterviewPrepService

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=MagicMock(),
        schema_registry=MagicMock(),
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    with patch(
        "app.workers.interview_prep_worker._build_service",
        return_value=service,
    ):
        # Act
        result = await process_interview_prep(ctx, "pipeline-record-001")

    # Assert — worker reports failure
    assert result["status"] == "failed"
    assert result["pack_id"] is None


# ─── TEST: DB.update_pack_status called with FAILED ───────────────────────────


@pytest.mark.asyncio
async def test_db_update_pack_status_called_with_failed_on_timeout():
    """WHEN generation fails after retries due to LLM timeout,
    THEN DB.update_pack_status is called with PackStatus.FAILED.

    Requirements: 1.1, 3.3
    """
    # Arrange
    db_repo = _make_db_repo_mock()
    llm_router = _make_llm_router_always_timeout()
    event_publisher = MagicMock()
    event_publisher.publish = AsyncMock()

    from app.core.interview_prep_service import InterviewPrepService

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=MagicMock(),
        schema_registry=MagicMock(),
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    with patch(
        "app.workers.interview_prep_worker._build_service",
        return_value=service,
    ):
        # Act
        result = await process_interview_prep({}, "pipeline-record-001")

    # Assert — status is failed
    assert result["status"] == "failed"

    # Assert — update_pack_status was called with FAILED
    db_repo.update_pack_status.assert_called()
    # Get the last call (the final failure status update)
    calls = db_repo.update_pack_status.call_args_list
    # At least one call should set FAILED status
    failed_calls = [
        c for c in calls
        if len(c.args) >= 2 and c.args[1] == PackStatus.FAILED
    ]
    assert len(failed_calls) >= 1, (
        f"Expected at least one call to update_pack_status with FAILED, "
        f"got calls: {calls}"
    )


# ─── TEST: Combined flow - transition ADVANCED while prep fails ───────────────


@pytest.mark.asyncio
async def test_transition_advanced_and_prep_fails_independently():
    """Integration: PipelineManager transitions to Interview (ADVANCED),
    then separately process_interview_prep is called and fails.

    This proves the pipeline transition completes without waiting for
    the interview prep generation outcome.

    Requirements: 1.1, 3.3
    """
    # --- Part 1: Transition completes immediately ---
    schema = _make_schema_registry_with_interview_technique()
    redis_pool = MagicMock()
    redis_pool.enqueue_job = AsyncMock()

    repo = MagicMock()
    repo.get_pipeline_record = AsyncMock(return_value=_make_pipeline_record_data())
    repo.update_pipeline_record_status = AsyncMock()

    publisher = MagicMock()
    publisher.publish = AsyncMock()

    manager = PipelineManager(
        repository=repo,
        publisher=publisher,
        schema_registry=schema,
        redis_pool=redis_pool,
    )

    record = _make_pipeline_record_data()

    repo.update_pipeline_record = AsyncMock()
    with patch.object(manager, "_broadcast_pipeline_update", new_callable=AsyncMock):
        transition = await manager._transition(record, "Interview")

    # Pipeline transition succeeds regardless
    assert transition.result == PipelineTransitionResult.ADVANCED

    # --- Part 2: Worker fails independently ---
    db_repo = _make_db_repo_mock()
    llm_router = _make_llm_router_always_timeout()
    event_publisher = MagicMock()
    event_publisher.publish = AsyncMock()

    from app.core.interview_prep_service import InterviewPrepService

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=MagicMock(),
        schema_registry=MagicMock(),
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    with patch(
        "app.workers.interview_prep_worker._build_service",
        return_value=service,
    ):
        worker_result = await process_interview_prep({}, "pipeline-record-001")

    # Worker reports failure
    assert worker_result["status"] == "failed"
    assert worker_result["pack_id"] is None

    # But the transition was already ADVANCED — non-blocking guarantee holds
    assert transition.result == PipelineTransitionResult.ADVANCED
    assert transition.new_status == "Interview"
