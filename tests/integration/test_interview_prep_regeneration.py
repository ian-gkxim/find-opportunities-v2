"""Integration tests for Interview Prep on-demand regeneration via API.

Tests the regenerate_pack flow:
- POST regenerate → new pack created with fresh context → old pack superseded
- History record created with trigger_reason="manual_regenerate"
- New pack returned on subsequent GET

Requirements: 3.2
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.interview_prep_models import (
    GenerationContext,
    Interview_Prep_Pack,
    PackStatus,
    STAR_Talking_Point,
)
from app.core.interview_prep_service import InterviewPrepService


# ─── FIXTURES / HELPERS ───────────────────────────────────────────────────────


def _make_star_talking_point(competency: str = "Technical Leadership") -> STAR_Talking_Point:
    """Create a valid STAR talking point for testing."""
    return STAR_Talking_Point(
        competency=competency,
        question=f"Tell me about your experience with {competency}.",
        situation="At previous company, faced a complex technical challenge.",
        task="Needed to lead migration of legacy systems.",
        action="Led team of 4 through strangler-fig pattern migration.",
        result="Reduced response times by 95%, zero downtime.",
        source_asset_refs=["resume", "consultant_profiles"],
        is_gap_handled=False,
        gap_note=None,
    )


def _make_existing_pack(pipeline_record_id: str = "pipeline-001") -> Interview_Prep_Pack:
    """Create a mock existing pack that will be superseded."""
    return Interview_Prep_Pack(
        id=str(uuid.uuid4()),
        pipeline_record_id=pipeline_record_id,
        beneficiary_id="beneficiary-001",
        opportunity_type_id="job_site",
        likely_questions=[f"Question {i}" for i in range(10)],
        star_talking_points=[_make_star_talking_point(f"Competency {i}") for i in range(5)],
        company_briefing="A company briefing about the prospect.",
        questions_to_ask=["Q1?", "Q2?", "Q3?", "Q4?"],
        status=PackStatus.READY,
        omission_notes=[],
        grounding_flags=[],
        generation_duration_ms=5000,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _make_valid_llm_response() -> str:
    """Create a valid LLM response JSON for pack generation."""
    return json.dumps({
        "likely_questions": [f"New question {i}" for i in range(10)],
        "star_talking_points": [
            {
                "competency": f"Competency {i}",
                "question": f"Tell me about competency {i}",
                "situation": "At a previous role...",
                "task": "The task was to...",
                "action": "I took the action of...",
                "result": "This resulted in...",
                "source_asset_refs": ["resume"],
                "is_gap_handled": False,
                "gap_note": None,
            }
            for i in range(5)
        ],
        "company_briefing": "This is a new company briefing synthesized from enrichment data.",
        "questions_to_ask": ["New Q1?", "New Q2?", "New Q3?", "New Q4?"],
    })


def _make_pipeline_record():
    """Create a mock pipeline record."""
    record = MagicMock()
    record.prospect_id = "prospect-001"
    record.beneficiary_id = "beneficiary-001"
    record.opportunity_type_id = "job_site"
    return record


def _make_prospect():
    """Create a mock prospect."""
    prospect = MagicMock()
    prospect.description = "Senior Python Engineer role requiring microservices expertise."
    return prospect


def _make_db_repo_mock(existing_pack: Interview_Prep_Pack | None = None):
    """Create a mocked InterviewPrepRepository with standard behavior."""
    db = MagicMock()
    db.get_pack = AsyncMock(return_value=existing_pack)
    db.save_pack = AsyncMock()
    db.update_pack_status = AsyncMock()
    db.supersede_pack = AsyncMock()
    db.save_history = AsyncMock()
    db.get_pipeline_record = AsyncMock(return_value=_make_pipeline_record())
    db.get_prospect = AsyncMock(return_value=_make_prospect())
    db.get_submitted_materials = AsyncMock(return_value={
        "tailored_cv": "A tailored CV for the role.",
        "tailored_cover_letter": "A tailored cover letter.",
    })
    db.get_enrichment_record = AsyncMock(return_value={
        "industry": "Technology",
        "employee_count": "500-1000",
        "tech_stack": ["Python", "AWS", "Kubernetes"],
        "headquarters": "London, UK",
    })
    db.get_intent_signals = AsyncMock(return_value=[
        {"type": "hiring_ml_engineers"},
    ])
    db.get_profile_assets = AsyncMock(return_value={
        "resume": "10 years Python experience, microservices, AWS.",
        "consultant_profiles": "Technical lead with distributed systems expertise.",
    })
    db.get_star_examples = AsyncMock(return_value=[])
    return db


def _make_grounding_verifier_mock(all_grounded: bool = True):
    """Create a mocked GroundingVerifier that passes all claims."""
    verifier = MagicMock()
    grounding_result = MagicMock()
    grounding_result.grounding_report = MagicMock()

    if all_grounded:
        grounding_result.grounding_report.claims = []
    else:
        claim = MagicMock()
        claim.grounding_status = "ungrounded"
        grounding_result.grounding_report.claims = [claim]

    verifier.verify_material = AsyncMock(return_value=grounding_result)
    return verifier


def _make_llm_router_mock():
    """Create a mocked LLM_Router that returns valid pack JSON."""
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=_make_valid_llm_response())
    return llm


def _make_schema_registry_mock():
    """Create a mocked SchemaRegistry."""
    schema = MagicMock()
    return schema


def _make_event_publisher_mock():
    """Create a mocked EventPublisher."""
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    return publisher


# ─── TASK 13.3: On-demand regeneration via API ────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_pack_creates_new_pack_with_different_id():
    """POST regenerate → new pack created with fresh context → old pack superseded.

    Verifies that regenerate_pack produces a new pack with a different ID
    from the existing one, using freshly assembled context.

    Requirements: 3.2
    """
    # Arrange
    existing_pack = _make_existing_pack("pipeline-001")
    old_pack_id = existing_pack.id

    db_repo = _make_db_repo_mock(existing_pack=existing_pack)
    llm_router = _make_llm_router_mock()
    grounding_verifier = _make_grounding_verifier_mock(all_grounded=True)
    schema_registry = _make_schema_registry_mock()
    event_publisher = _make_event_publisher_mock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # Act
    new_pack = await service.regenerate_pack("pipeline-001")

    # Assert: new pack has a different ID from the old one
    assert new_pack.id != old_pack_id

    # Assert: new pack has the same pipeline_record_id
    assert new_pack.pipeline_record_id == "pipeline-001"

    # Assert: new pack has a valid status (ready or ready_with_flags)
    assert new_pack.status in (PackStatus.READY, PackStatus.READY_WITH_FLAGS)

    # Assert: DB.supersede_pack was called linking old to new
    db_repo.supersede_pack.assert_called_once_with(old_pack_id, new_pack.id)


@pytest.mark.asyncio
async def test_regenerate_pack_creates_history_record_with_manual_trigger():
    """Verify: history record created with trigger_reason="manual_regenerate".

    Requirements: 3.2
    """
    # Arrange
    existing_pack = _make_existing_pack("pipeline-001")

    db_repo = _make_db_repo_mock(existing_pack=existing_pack)
    llm_router = _make_llm_router_mock()
    grounding_verifier = _make_grounding_verifier_mock(all_grounded=True)
    schema_registry = _make_schema_registry_mock()
    event_publisher = _make_event_publisher_mock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # Act
    new_pack = await service.regenerate_pack("pipeline-001")

    # Assert: save_history was called with trigger_reason="manual_regenerate"
    db_repo.save_history.assert_called_once()
    call_kwargs = db_repo.save_history.call_args[1]
    assert call_kwargs["pack_id"] == new_pack.id
    assert call_kwargs["trigger_reason"] == "manual_regenerate"
    assert "context_hash" in call_kwargs
    assert len(call_kwargs["context_hash"]) == 64  # SHA-256 hex digest


@pytest.mark.asyncio
async def test_regenerate_pack_new_pack_returned_on_subsequent_get():
    """Verify: new pack returned on subsequent GET.

    After regeneration, the DB should have the new pack stored,
    and subsequent calls to get_pack should return the new pack.

    Requirements: 3.2
    """
    # Arrange
    existing_pack = _make_existing_pack("pipeline-001")

    db_repo = _make_db_repo_mock(existing_pack=existing_pack)
    llm_router = _make_llm_router_mock()
    grounding_verifier = _make_grounding_verifier_mock(all_grounded=True)
    schema_registry = _make_schema_registry_mock()
    event_publisher = _make_event_publisher_mock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # Act
    new_pack = await service.regenerate_pack("pipeline-001")

    # Assert: save_pack was called with the new pack (at least once for
    # the initial generating status and once for the final status)
    save_calls = db_repo.save_pack.call_args_list
    assert len(save_calls) >= 1

    # The last save_pack call should contain the final pack
    final_saved_pack = save_calls[-1][0][0]
    assert final_saved_pack.id == new_pack.id
    assert final_saved_pack.pipeline_record_id == "pipeline-001"
    assert final_saved_pack.status in (PackStatus.READY, PackStatus.READY_WITH_FLAGS)

    # Assert: the new pack contains the regenerated content from the LLM
    assert len(new_pack.likely_questions) >= 8
    assert len(new_pack.star_talking_points) == 5
    assert new_pack.company_briefing != ""
    assert len(new_pack.questions_to_ask) >= 3


@pytest.mark.asyncio
async def test_regenerate_pack_supersedes_old_pack():
    """Verify DB.supersede_pack was called linking old to new.

    The old pack should be marked as superseded with a reference to
    the new pack's ID.

    Requirements: 3.2
    """
    # Arrange
    existing_pack = _make_existing_pack("pipeline-001")
    old_pack_id = existing_pack.id

    db_repo = _make_db_repo_mock(existing_pack=existing_pack)
    llm_router = _make_llm_router_mock()
    grounding_verifier = _make_grounding_verifier_mock(all_grounded=True)
    schema_registry = _make_schema_registry_mock()
    event_publisher = _make_event_publisher_mock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # Act
    new_pack = await service.regenerate_pack("pipeline-001")

    # Assert: supersede_pack was called with (old_id, new_id)
    db_repo.supersede_pack.assert_called_once_with(old_pack_id, new_pack.id)

    # Assert: the old and new pack IDs are different
    assert old_pack_id != new_pack.id


@pytest.mark.asyncio
async def test_regenerate_pack_without_existing_pack_skips_supersede():
    """When no existing pack exists, supersede_pack should not be called.

    This handles the edge case where regenerate is called but no prior
    pack exists (e.g., initial generation failed and user retries).

    Requirements: 3.2
    """
    # Arrange: no existing pack
    db_repo = _make_db_repo_mock(existing_pack=None)
    llm_router = _make_llm_router_mock()
    grounding_verifier = _make_grounding_verifier_mock(all_grounded=True)
    schema_registry = _make_schema_registry_mock()
    event_publisher = _make_event_publisher_mock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # Act
    new_pack = await service.regenerate_pack("pipeline-001")

    # Assert: supersede_pack NOT called (no old pack to supersede)
    db_repo.supersede_pack.assert_not_called()

    # Assert: history record is still created
    db_repo.save_history.assert_called_once()
    call_kwargs = db_repo.save_history.call_args[1]
    assert call_kwargs["trigger_reason"] == "manual_regenerate"

    # Assert: new pack is valid
    assert new_pack.status in (PackStatus.READY, PackStatus.READY_WITH_FLAGS)


@pytest.mark.asyncio
async def test_regenerate_pack_uses_fresh_context():
    """Regeneration reassembles context which may include new profile data.

    Verifies that assemble_context is called during regeneration,
    ensuring any profile updates since the original generation are captured.

    Requirements: 3.2
    """
    # Arrange
    existing_pack = _make_existing_pack("pipeline-001")

    db_repo = _make_db_repo_mock(existing_pack=existing_pack)
    llm_router = _make_llm_router_mock()
    grounding_verifier = _make_grounding_verifier_mock(all_grounded=True)
    schema_registry = _make_schema_registry_mock()
    event_publisher = _make_event_publisher_mock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # Act
    new_pack = await service.regenerate_pack("pipeline-001")

    # Assert: context was freshly assembled (DB queries were made)
    db_repo.get_pipeline_record.assert_called_with("pipeline-001")
    db_repo.get_profile_assets.assert_called()
    db_repo.get_enrichment_record.assert_called()

    # Assert: LLM was called for generation (fresh generation, not cached)
    llm_router.generate.assert_called()

    # Assert: the new pack has fresh timestamps
    assert new_pack.created_at > existing_pack.created_at
