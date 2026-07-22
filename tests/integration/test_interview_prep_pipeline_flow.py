"""End-to-end integration test for Interview Prep pipeline flow.

Exercises the full flow: pipeline transition to Interview → ARQ job enqueued →
InterviewPrepService.generate_pack called → pack stored → WebSocket notification sent.

Uses mocked external dependencies (LLM, DB, Redis) to isolate the pipeline logic.

Requirements: 1.1, 2.1, 3.1
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.interview_prep_models import (
    Interview_Prep_Pack,
    PackStatus,
    STAR_Talking_Point,
)
from app.core.interview_prep_service import InterviewPrepService
from app.core.pipeline_manager import (
    PipelineManager,
    PipelineRecordData,
    PipelineTransitionResult,
)
from app.core.schema_registry import PrepareTechnique
from app.workers.interview_prep_worker import process_interview_prep


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_valid_pack_json() -> str:
    """Return a valid Interview_Prep_Pack JSON that the mocked LLM returns."""
    return json.dumps({
        "likely_questions": [
            "Tell me about your experience with distributed systems.",
            "How do you handle conflict in a team?",
            "Describe a time you optimized a complex pipeline.",
            "What is your approach to testing microservices?",
            "How do you stay current with emerging technologies?",
            "Tell me about a project where you led a team.",
            "What strategies do you use for debugging production issues?",
            "How do you prioritize technical debt vs new features?",
            "Describe your experience with CI/CD pipelines.",
            "What is your approach to code reviews?",
        ],
        "star_talking_points": [
            {
                "competency": "Distributed Systems",
                "question": "Tell me about your experience with distributed systems.",
                "situation": "At TechCorp, our monolith was hitting scaling limits.",
                "task": "I was tasked with decomposing the system into microservices.",
                "action": "Designed event-driven architecture with Kafka and deployed on Kubernetes.",
                "result": "Reduced latency by 60% and enabled independent scaling.",
                "source_asset_refs": ["resume-001"],
                "is_gap_handled": False,
                "gap_note": None,
            },
            {
                "competency": "Team Leadership",
                "question": "Tell me about a project where you led a team.",
                "situation": "Led a cross-functional team of 8 engineers on a platform migration.",
                "task": "Deliver the migration within 3 months with zero downtime.",
                "action": "Established sprint cadence, daily standups, and canary deployments.",
                "result": "Completed migration 2 weeks ahead of schedule with 99.9% uptime.",
                "source_asset_refs": ["profile-002"],
                "is_gap_handled": False,
                "gap_note": None,
            },
            {
                "competency": "Performance Optimization",
                "question": "Describe a time you optimized a complex pipeline.",
                "situation": "Data pipeline was taking 4 hours to process daily batch.",
                "task": "Reduce processing time to under 1 hour.",
                "action": "Rewrote ETL logic using parallel processing and query optimization.",
                "result": "Processing time reduced to 45 minutes.",
                "source_asset_refs": ["resume-001", "profile-002"],
                "is_gap_handled": False,
                "gap_note": None,
            },
            {
                "competency": "Testing Strategy",
                "question": "What is your approach to testing microservices?",
                "situation": "Quality issues were slipping through to production.",
                "task": "Implement comprehensive testing strategy for the team.",
                "action": "Introduced contract testing, property-based testing, and chaos engineering.",
                "result": "Production incidents reduced by 75% over 6 months.",
                "source_asset_refs": ["profile-002"],
                "is_gap_handled": False,
                "gap_note": None,
            },
            {
                "competency": "CI/CD",
                "question": "Describe your experience with CI/CD pipelines.",
                "situation": "Deployments were manual and error-prone.",
                "task": "Automate the entire deployment pipeline.",
                "action": "Built GitHub Actions pipelines with automated testing and canary releases.",
                "result": "Deployment frequency increased from weekly to multiple times daily.",
                "source_asset_refs": ["resume-001"],
                "is_gap_handled": False,
                "gap_note": None,
            },
        ],
        "company_briefing": (
            "Acme Corp is a mid-size technology company focused on enterprise SaaS solutions. "
            "Founded in 2015, they serve Fortune 500 clients in the financial services sector. "
            "Their engineering team uses Python, Kubernetes, and event-driven architecture. "
            "Recent growth signals include Series C funding and expansion into the APAC market."
        ),
        "questions_to_ask": [
            "What does the team's development workflow look like day-to-day?",
            "How does the engineering team handle technical debt prioritization?",
            "What growth opportunities are available for senior engineers?",
            "Can you tell me more about the team structure and cross-functional collaboration?",
        ],
    })


def _make_pipeline_record(
    record_id: str = "rec-001",
    opportunity_type_id: str = "job_site",
    current_status: str = "Applied",
) -> PipelineRecordData:
    """Create a PipelineRecordData for testing."""
    return PipelineRecordData(
        id=record_id,
        prospect_id="prospect-001",
        opportunity_type_id=opportunity_type_id,
        beneficiary_id="ben-001",
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


def _make_mock_db_repo(record_id: str = "rec-001") -> MagicMock:
    """Create a mocked InterviewPrepRepository with all required methods."""
    repo = MagicMock()
    repo.save_pack = AsyncMock()
    repo.update_pack_status = AsyncMock()
    repo.get_pack = AsyncMock(return_value=None)
    repo.get_pipeline_record = AsyncMock(return_value=MagicMock(
        id=record_id,
        prospect_id="prospect-001",
        opportunity_type_id="job_site",
        beneficiary_id="ben-001",
    ))
    repo.get_prospect = AsyncMock(return_value=MagicMock(
        description="Senior Python Engineer at Acme Corp. "
                    "Requirements: distributed systems, team leadership, CI/CD."
    ))
    repo.get_submitted_materials = AsyncMock(return_value={
        "tailored_cv": "Experienced engineer with 10 years in distributed systems.",
        "tailored_cover_letter": "I am excited to apply for this role at Acme Corp.",
    })
    repo.get_enrichment_record = AsyncMock(return_value={
        "industry": "Technology",
        "employee_count": "500-1000",
        "tech_stack": ["Python", "Kubernetes", "Kafka"],
        "headquarters": "San Francisco, CA",
    })
    repo.get_intent_signals = AsyncMock(return_value=[
        {"type": "hiring_surge"},
        {"type": "funding_round"},
    ])
    repo.get_profile_assets = AsyncMock(return_value={
        "resume-001": "10 years experience in distributed systems and microservices.",
        "profile-002": "Led cross-functional teams, established CI/CD pipelines.",
    })
    repo.get_star_examples = AsyncMock(return_value=[])
    return repo


def _make_mock_grounding_verifier(all_grounded: bool = True) -> MagicMock:
    """Create a mocked GroundingVerifier that returns all claims as grounded."""
    verifier = MagicMock()
    result = MagicMock()
    result.grounding_report.claims = []
    if not all_grounded:
        claim = MagicMock()
        claim.grounding_status = "ungrounded"
        claim.claim_text = "fabricated claim"
        result.grounding_report.claims = [claim]
    verifier.verify_material = AsyncMock(return_value=result)
    return verifier


def _make_mock_event_publisher() -> MagicMock:
    """Create a mocked EventPublisher."""
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    return publisher


# ─── INTEGRATION TEST: FULL PIPELINE FLOW ────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_transition_to_interview_enqueues_arq_job():
    """Pipeline transition to Interview state → ARQ job enqueued.

    Verifies the PipelineManager dispatches state-entry techniques when
    transitioning to Interview, resulting in enqueue_job being called.

    Requirements: 1.1, 3.1
    """
    # Arrange: PipelineManager with mocked dependencies
    mock_repo = MagicMock()
    mock_repo.update_pipeline_record = AsyncMock()

    mock_publisher = MagicMock()
    mock_publisher.publish = AsyncMock(return_value=1)

    mock_schema = MagicMock()
    technique = _make_interview_technique()
    mock_schema.get_state_entry_techniques = MagicMock(return_value=[technique])

    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock()

    manager = PipelineManager(
        repository=mock_repo,
        publisher=mock_publisher,
        gate_service=None,
        schema_registry=mock_schema,
        redis_pool=mock_redis,
    )

    record = _make_pipeline_record(current_status="Applied")

    # Act: transition to Interview
    result = await manager._transition(record, "Interview")

    # Assert: transition succeeds
    assert result.result == PipelineTransitionResult.ADVANCED
    assert result.new_status == "Interview"

    # Assert: enqueue_job was called for the interview prep worker
    mock_redis.enqueue_job.assert_called_once_with(
        "process_interview_prep",
        "rec-001",
    )


@pytest.mark.asyncio
async def test_worker_calls_service_generate_pack():
    """ARQ worker process_interview_prep calls InterviewPrepService.generate_pack.

    Verifies that the worker constructs the service and invokes generate_pack
    with the pipeline_record_id.

    Requirements: 1.1, 2.1
    """
    # Arrange: mock the service's generate_pack
    now = datetime.now(tz=timezone.utc)
    expected_pack = Interview_Prep_Pack(
        id="pack-001",
        pipeline_record_id="rec-001",
        beneficiary_id="ben-001",
        opportunity_type_id="job_site",
        likely_questions=["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"],
        star_talking_points=[],
        company_briefing="Acme Corp briefing.",
        questions_to_ask=["Ask1", "Ask2", "Ask3"],
        status=PackStatus.READY,
        created_at=now,
        updated_at=now,
    )

    mock_service = MagicMock(spec=InterviewPrepService)
    mock_service.generate_pack = AsyncMock(return_value=expected_pack)

    # Patch _build_service to return our mock service
    with patch(
        "app.workers.interview_prep_worker._build_service",
        return_value=mock_service,
    ):
        ctx = {}  # ARQ context (not used since we patch _build_service)
        result = await process_interview_prep(ctx, "rec-001")

    # Assert: generate_pack was called with the correct pipeline_record_id
    mock_service.generate_pack.assert_called_once_with("rec-001")

    # Assert: result contains ready status and pack_id
    assert result["status"] == "ready"
    assert result["pack_id"] == "pack-001"


@pytest.mark.asyncio
async def test_service_generate_pack_stores_pack_and_sends_notification():
    """InterviewPrepService.generate_pack stores pack in DB and sends WebSocket notification.

    Mocks the LLM_Router to return valid pack JSON. Verifies that:
    - The pack is saved to the database with status=ready
    - A WebSocket notification is published with pack_ready event

    Requirements: 1.1, 2.1, 3.1
    """
    # Arrange: mock LLM router to return valid pack JSON
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_make_valid_pack_json())

    mock_grounding = _make_mock_grounding_verifier(all_grounded=True)
    mock_schema = MagicMock()
    mock_db_repo = _make_mock_db_repo()
    mock_publisher = _make_mock_event_publisher()

    service = InterviewPrepService(
        llm_router=mock_llm,
        grounding_verifier=mock_grounding,
        schema_registry=mock_schema,
        db_repo=mock_db_repo,
        event_publisher=mock_publisher,
    )

    # Act: generate the pack
    pack = await service.generate_pack("rec-001")

    # Assert: pack returned with ready status
    assert pack.status == PackStatus.READY
    assert pack.pipeline_record_id == "rec-001"
    assert pack.beneficiary_id == "ben-001"
    assert len(pack.likely_questions) == 10
    assert len(pack.star_talking_points) == 5
    assert len(pack.questions_to_ask) == 4
    assert pack.company_briefing != ""

    # Assert: pack was saved to database (save_pack called at least twice:
    # once for initial generating status, once for final ready status)
    assert mock_db_repo.save_pack.call_count >= 2

    # Verify the final save has status=ready
    final_save_call = mock_db_repo.save_pack.call_args_list[-1]
    final_pack = final_save_call[0][0]
    assert final_pack.status == PackStatus.READY

    # Assert: WebSocket notification was published
    mock_publisher.publish.assert_called_once()
    publish_call = mock_publisher.publish.call_args
    assert publish_call.kwargs["event"] == "pack_ready"
    assert publish_call.kwargs["data"]["pipeline_record_id"] == "rec-001"
    assert publish_call.kwargs["data"]["pack_id"] == pack.id
    assert publish_call.kwargs["data"]["status"] == "ready"
    assert publish_call.kwargs["data"]["has_flags"] is False


@pytest.mark.asyncio
async def test_end_to_end_pipeline_transition_through_worker_to_notification():
    """Full end-to-end: transition → enqueue → worker → service → pack stored → notification.

    Integrates the PipelineManager transition, then manually invokes the worker
    (simulating ARQ dispatch), and verifies the complete chain.

    Requirements: 1.1, 2.1, 3.1
    """
    # ─── Step 1: Pipeline transition enqueues the job ─────────────────────
    mock_repo = MagicMock()
    mock_repo.update_pipeline_record = AsyncMock()

    mock_pipeline_publisher = MagicMock()
    mock_pipeline_publisher.publish = AsyncMock(return_value=1)

    mock_schema = MagicMock()
    technique = _make_interview_technique()
    mock_schema.get_state_entry_techniques = MagicMock(return_value=[technique])

    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock()

    manager = PipelineManager(
        repository=mock_repo,
        publisher=mock_pipeline_publisher,
        gate_service=None,
        schema_registry=mock_schema,
        redis_pool=mock_redis,
    )

    record = _make_pipeline_record(current_status="Applied")

    # Transition to Interview
    transition_result = await manager._transition(record, "Interview")
    assert transition_result.result == PipelineTransitionResult.ADVANCED
    assert transition_result.new_status == "Interview"

    # Verify job was enqueued
    mock_redis.enqueue_job.assert_called_once_with(
        "process_interview_prep",
        "rec-001",
    )

    # ─── Step 2: Worker invokes service.generate_pack ─────────────────────
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=_make_valid_pack_json())

    mock_grounding = _make_mock_grounding_verifier(all_grounded=True)
    mock_db_repo = _make_mock_db_repo()
    mock_notification_publisher = _make_mock_event_publisher()

    service = InterviewPrepService(
        llm_router=mock_llm,
        grounding_verifier=mock_grounding,
        schema_registry=mock_schema,
        db_repo=mock_db_repo,
        event_publisher=mock_notification_publisher,
    )

    # Simulate what the worker does: call service.generate_pack
    pack = await service.generate_pack("rec-001")

    # ─── Step 3: Verify complete chain results ────────────────────────────

    # Pack is stored with ready status
    assert pack.status == PackStatus.READY
    assert pack.pipeline_record_id == "rec-001"
    assert pack.beneficiary_id == "ben-001"

    # Pack has correct structural content
    assert len(pack.likely_questions) == 10
    assert len(pack.star_talking_points) == 5
    assert all(
        isinstance(tp, STAR_Talking_Point) for tp in pack.star_talking_points
    )
    assert len(pack.questions_to_ask) == 4
    assert pack.company_briefing != ""
    assert pack.generation_duration_ms >= 0

    # Database was called to persist the pack
    assert mock_db_repo.save_pack.call_count >= 2

    # WebSocket notification was sent
    mock_notification_publisher.publish.assert_called_once()
    notification = mock_notification_publisher.publish.call_args
    assert notification.kwargs["event"] == "pack_ready"
    assert notification.kwargs["data"]["status"] == "ready"
    assert notification.kwargs["data"]["has_flags"] is False

    # LLM was called for generation
    mock_llm.generate.assert_called()

    # Grounding verifier was called for STAR points
    mock_grounding.verify_material.assert_called_once()
