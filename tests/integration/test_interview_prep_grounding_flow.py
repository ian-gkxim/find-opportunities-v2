"""Integration test for Interview Prep grounding flow with regeneration.

Tests the full grounding verification pipeline within InterviewPrepService:
LLM generation → Grounding_Verifier flags ungrounded claims →
single regeneration with exclusion constraint → re-verification →
remaining flags stored in grounding_flags with status=ready_with_flags.

Requirements: 2.2, 2.3
"""

from __future__ import annotations

import json
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
from app.core.interview_prep_models import (
    GenerationContext,
    Interview_Prep_Pack,
    PackStatus,
    STAR_Talking_Point,
)
from app.core.interview_prep_service import InterviewPrepService


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_valid_pack_json(fabricated_claim_in_point_index: int = 2) -> str:
    """Return a valid pack JSON where one STAR point contains a fabricated claim.

    The point at `fabricated_claim_in_point_index` includes text that the
    grounding verifier will flag as ungrounded (e.g. "led a team of 50 engineers"
    when the profile only evidences teams of 5).
    """
    star_points = []
    for i in range(5):
        if i == fabricated_claim_in_point_index:
            # This point contains a fabricated claim
            star_points.append({
                "competency": "Technical Leadership",
                "question": "Tell me about leading large teams",
                "situation": "At MegaCorp I led a team of 50 engineers on a platform rewrite",
                "task": "Needed to migrate a monolith to microservices",
                "action": "I coordinated 50 engineers across 8 squads",
                "result": "Delivered 3 months early saving $2M in contractor costs",
                "source_asset_refs": ["resume"],
                "is_gap_handled": False,
                "gap_note": None,
            })
        else:
            star_points.append({
                "competency": f"Competency {i}",
                "question": f"Tell me about competency {i}",
                "situation": f"At company Y, I was responsible for area {i}",
                "task": f"I needed to deliver outcome {i}",
                "action": f"I implemented solution {i} using Python",
                "result": f"Achieved measurable result {i}",
                "source_asset_refs": ["resume", "consultant_profiles"],
                "is_gap_handled": False,
                "gap_note": None,
            })

    return json.dumps({
        "likely_questions": [f"Question {i}" for i in range(10)],
        "star_talking_points": star_points,
        "company_briefing": "A growing SaaS company in the fintech space.",
        "questions_to_ask": [
            "What's the team structure?",
            "How do you handle deployments?",
            "What's the growth roadmap?",
        ],
    })


def _make_regenerated_points_json() -> str:
    """Return regenerated talking points that replace the flagged one.

    The regenerated point is grounded but still has a minor remaining flag.
    """
    return json.dumps([{
        "competency": "Technical Leadership",
        "question": "Tell me about leading large teams",
        "situation": "At company Y I led a team of 5 engineers on a backend rewrite",
        "task": "Needed to migrate key services to a new architecture",
        "action": "I coordinated the team through weekly architecture reviews",
        "result": "Delivered on schedule with 99.9% uptime maintained",
        "source_asset_refs": ["resume"],
        "is_gap_handled": False,
        "gap_note": None,
    }])


def _make_grounding_result_with_ungrounded_claims(
    material_id: str,
) -> GroundingResult:
    """Create a GroundingResult with one ungrounded claim (fabricated team size)."""
    now = datetime.now(tz=timezone.utc)
    ungrounded_claim = Claim(
        id="claim-001",
        material_id=material_id,
        category=ClaimCategory.QUANTIFIED_METRIC,
        claim_text="led a team of 50 engineers",
        source_span="led a team of 50 engineers on a platform rewrite",
        source_span_start=0,
        source_span_end=48,
        grounding_status=GroundingStatus.UNGROUNDED,
        source_pointer=None,
        discrepancy="Profile evidences teams of 5, not 50",
        is_prospect_side=False,
    )
    grounded_claim = Claim(
        id="claim-002",
        material_id=material_id,
        category=ClaimCategory.SKILL_TECHNOLOGY,
        claim_text="implemented solution using Python",
        source_span="implemented solution using Python",
        source_span_start=100,
        source_span_end=132,
        grounding_status=GroundingStatus.GROUNDED,
        source_pointer=None,
        discrepancy=None,
        is_prospect_side=False,
    )

    report = GroundingReport(
        id="report-001",
        material_id=material_id,
        pipeline_record_id="pipeline-001",
        claims=[ungrounded_claim, grounded_claim],
        total_claims=2,
        grounded_count=1,
        partially_grounded_count=0,
        ungrounded_count=1,
        material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
        extraction_duration_ms=150,
        verification_duration_ms=80,
        created_at=now,
        updated_at=now,
    )

    return GroundingResult(
        material_id=material_id,
        material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
        grounding_report=report,
        blocked_states=["Approve"],
        requires_action=True,
    )


def _make_grounding_result_with_remaining_flag(
    material_id: str,
) -> GroundingResult:
    """Create a GroundingResult for re-verification with one remaining flag.

    After regeneration, the re-verification still finds a minor ungrounded
    claim (e.g. "99.9% uptime" not directly evidenced in profile).
    """
    now = datetime.now(tz=timezone.utc)
    remaining_claim = Claim(
        id="claim-003",
        material_id=material_id,
        category=ClaimCategory.QUANTIFIED_METRIC,
        claim_text="99.9% uptime maintained",
        source_span="99.9% uptime maintained",
        source_span_start=0,
        source_span_end=22,
        grounding_status=GroundingStatus.UNGROUNDED,
        source_pointer=None,
        discrepancy="Specific uptime metric not evidenced in profile",
        is_prospect_side=False,
    )

    report = GroundingReport(
        id="report-002",
        material_id=material_id,
        pipeline_record_id="pipeline-001",
        claims=[remaining_claim],
        total_claims=1,
        grounded_count=0,
        partially_grounded_count=0,
        ungrounded_count=1,
        material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
        extraction_duration_ms=100,
        verification_duration_ms=50,
        created_at=now,
        updated_at=now,
    )

    return GroundingResult(
        material_id=material_id,
        material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
        grounding_report=report,
        blocked_states=[],
        requires_action=True,
    )


def _make_generation_context() -> GenerationContext:
    """Create a valid GenerationContext for the integration test."""
    return GenerationContext(
        opportunity_description="Senior Python developer at FinCo.",
        tailored_cv="10 years experience with Python and PostgreSQL.",
        tailored_cover_letter="I am excited about this opportunity.",
        enrichment_record={
            "industry": "Fintech",
            "employee_count": "200",
            "tech_stack": ["Python", "PostgreSQL", "Kafka"],
            "headquarters": "London, UK",
        },
        intent_signals=[{"type": "hiring_surge"}],
        profile_assets={
            "resume": "Led a team of 5 engineers. 10 years Python experience.",
            "consultant_profiles": "Backend specialist with PostgreSQL expertise.",
        },
        star_examples=None,
        opportunity_type_id="job_site",
        beneficiary_id="ben-456",
    )


def _make_pipeline_record():
    """Create a mock pipeline record for the DB."""
    record = MagicMock()
    record.prospect_id = "prospect-001"
    record.opportunity_type_id = "job_site"
    record.beneficiary_id = "ben-456"
    return record


def _make_prospect():
    """Create a mock prospect."""
    prospect = MagicMock()
    prospect.description = "Senior Python developer at FinCo."
    return prospect


# ─── INTEGRATION TEST: GROUNDING FLOW WITH REGENERATION ───────────────────────


@pytest.mark.asyncio
async def test_grounding_flow_regeneration_triggered_and_remaining_flags_stored():
    """Full grounding flow: generate → verify → regenerate once → re-verify → flags stored.

    Exercises the complete grounding pipeline within InterviewPrepService:
    1. LLM generates a pack with a fabricated STAR claim (team of 50)
    2. Grounding_Verifier flags the fabricated claim as ungrounded
    3. Service triggers single regeneration with exclusion constraint
    4. Re-verification finds a remaining minor flag (uptime metric)
    5. Final pack has status=ready_with_flags with grounding_flags populated

    Requirements: 2.2, 2.3
    """
    # ─── Arrange ──────────────────────────────────────────────────────────

    # Mock LLM Router: first call returns pack with fabricated claim,
    # second call (regeneration) returns fixed talking points
    llm_router = MagicMock()
    llm_router.generate = AsyncMock(
        side_effect=[
            _make_valid_pack_json(),          # Initial generation
            _make_regenerated_points_json(),   # Regeneration of flagged points
        ]
    )

    # Mock Grounding Verifier: first call flags ungrounded claims,
    # second call (re-verification) returns remaining flag
    grounding_verifier = MagicMock()
    grounding_verifier.verify_material = AsyncMock(
        side_effect=[
            # First verification: finds fabricated "team of 50" claim
            _make_grounding_result_with_ungrounded_claims(
                material_id="interview_prep_mock-pack-id"
            ),
            # Re-verification after regeneration: finds remaining "99.9% uptime" flag
            _make_grounding_result_with_remaining_flag(
                material_id="interview_prep_mock-pack-id_regen"
            ),
        ]
    )

    # Mock Schema Registry
    schema_registry = MagicMock()

    # Mock DB Repository
    db_repo = MagicMock()
    db_repo.get_pipeline_record = AsyncMock(return_value=_make_pipeline_record())
    db_repo.get_prospect = AsyncMock(return_value=_make_prospect())
    db_repo.get_submitted_materials = AsyncMock(return_value={
        "tailored_cv": "10 years experience with Python and PostgreSQL.",
        "tailored_cover_letter": "I am excited about this opportunity.",
    })
    db_repo.get_enrichment_record = AsyncMock(return_value={
        "industry": "Fintech",
        "employee_count": "200",
        "tech_stack": ["Python", "PostgreSQL", "Kafka"],
        "headquarters": "London, UK",
    })
    db_repo.get_intent_signals = AsyncMock(return_value=[{"type": "hiring_surge"}])
    db_repo.get_profile_assets = AsyncMock(return_value={
        "resume": "Led a team of 5 engineers. 10 years Python experience.",
        "consultant_profiles": "Backend specialist with PostgreSQL expertise.",
    })
    db_repo.get_star_examples = AsyncMock(return_value=None)
    db_repo.save_pack = AsyncMock()
    db_repo.update_pack_status = AsyncMock()

    # Mock Event Publisher
    event_publisher = MagicMock()
    event_publisher.publish = AsyncMock()

    # Create the service
    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # ─── Act ──────────────────────────────────────────────────────────────

    result = await service.generate_pack(pipeline_record_id="pipeline-001")

    # ─── Assert ───────────────────────────────────────────────────────────

    # 1. Final status should be ready_with_flags (remaining flags exist)
    assert result.status == PackStatus.READY_WITH_FLAGS

    # 2. Grounding flags should contain the remaining ungrounded claim text
    assert len(result.grounding_flags) > 0
    assert "99.9% uptime maintained" in result.grounding_flags

    # 3. LLM was called exactly twice: initial generation + one regeneration
    assert llm_router.generate.call_count == 2

    # 4. Grounding verifier called exactly twice: initial verify + re-verify
    assert grounding_verifier.verify_material.call_count == 2

    # 5. The regenerated talking point replaced the fabricated one
    # Point at index 2 (the fabricated one) should no longer mention "50 engineers"
    flagged_point = result.star_talking_points[2]
    assert "50 engineers" not in flagged_point.situation
    assert "50 engineers" not in flagged_point.action

    # 6. Pack has correct structure
    assert len(result.likely_questions) == 10
    assert len(result.star_talking_points) == 5
    assert result.pipeline_record_id == "pipeline-001"
    assert result.beneficiary_id == "ben-456"

    # 7. WebSocket notification was sent with has_flags=True
    event_publisher.publish.assert_called_once()
    publish_call = event_publisher.publish.call_args
    assert publish_call.kwargs["event"] == "pack_ready"
    assert publish_call.kwargs["data"]["has_flags"] is True
    assert publish_call.kwargs["data"]["status"] == "ready_with_flags"


@pytest.mark.asyncio
async def test_grounding_flow_all_grounded_returns_ready_status():
    """When all claims are grounded, pack gets status=ready with no flags.

    Verifies the happy path: Grounding_Verifier finds no ungrounded claims,
    so no regeneration is triggered and the pack is delivered cleanly.

    Requirements: 2.2, 2.3
    """
    # ─── Arrange ──────────────────────────────────────────────────────────

    llm_router = MagicMock()
    llm_router.generate = AsyncMock(return_value=_make_valid_pack_json())

    # All claims grounded — no ungrounded results
    now = datetime.now(tz=timezone.utc)
    all_grounded_result = GroundingResult(
        material_id="interview_prep_mock",
        material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
        grounding_report=GroundingReport(
            id="report-ok",
            material_id="interview_prep_mock",
            pipeline_record_id="pipeline-002",
            claims=[
                Claim(
                    id="claim-ok",
                    material_id="interview_prep_mock",
                    category=ClaimCategory.SKILL_TECHNOLOGY,
                    claim_text="10 years Python experience",
                    source_span="10 years Python experience",
                    source_span_start=0,
                    source_span_end=26,
                    grounding_status=GroundingStatus.GROUNDED,
                    source_pointer=None,
                    discrepancy=None,
                    is_prospect_side=False,
                )
            ],
            total_claims=1,
            grounded_count=1,
            partially_grounded_count=0,
            ungrounded_count=0,
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            extraction_duration_ms=100,
            verification_duration_ms=50,
            created_at=now,
            updated_at=now,
        ),
        blocked_states=[],
        requires_action=False,
    )

    grounding_verifier = MagicMock()
    grounding_verifier.verify_material = AsyncMock(return_value=all_grounded_result)

    db_repo = MagicMock()
    db_repo.get_pipeline_record = AsyncMock(return_value=_make_pipeline_record())
    db_repo.get_prospect = AsyncMock(return_value=_make_prospect())
    db_repo.get_submitted_materials = AsyncMock(return_value={
        "tailored_cv": "My CV content.",
        "tailored_cover_letter": "My cover letter.",
    })
    db_repo.get_enrichment_record = AsyncMock(return_value={
        "industry": "Fintech",
        "employee_count": "200",
        "tech_stack": ["Python", "PostgreSQL"],
        "headquarters": "London, UK",
    })
    db_repo.get_intent_signals = AsyncMock(return_value=[])
    db_repo.get_profile_assets = AsyncMock(return_value={
        "resume": "10 years Python experience. Led team of 5.",
    })
    db_repo.get_star_examples = AsyncMock(return_value=None)
    db_repo.save_pack = AsyncMock()
    db_repo.update_pack_status = AsyncMock()

    event_publisher = MagicMock()
    event_publisher.publish = AsyncMock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=MagicMock(),
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # ─── Act ──────────────────────────────────────────────────────────────

    result = await service.generate_pack(pipeline_record_id="pipeline-002")

    # ─── Assert ───────────────────────────────────────────────────────────

    # Status should be READY (no flags)
    assert result.status == PackStatus.READY

    # No grounding flags
    assert result.grounding_flags == []

    # LLM called only once (no regeneration needed)
    assert llm_router.generate.call_count == 1

    # Grounding verifier called only once (no re-verification needed)
    assert grounding_verifier.verify_material.call_count == 1

    # WebSocket notification sent with has_flags=False
    event_publisher.publish.assert_called_once()
    publish_call = event_publisher.publish.call_args
    assert publish_call.kwargs["data"]["has_flags"] is False
    assert publish_call.kwargs["data"]["status"] == "ready"
