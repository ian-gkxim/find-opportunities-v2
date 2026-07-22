"""Integration test for Interview Prep graceful degradation (missing materials).

Verifies that when submitted CV and cover letter are unavailable, the
Interview_Prep_Service still generates a valid pack from profile assets alone,
with omission_notes populated documenting the missing materials.

Requirements: 1.3
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


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_valid_llm_pack_response() -> str:
    """Return a valid JSON response from the LLM for pack generation."""
    return json.dumps(
        {
            "likely_questions": [
                "Tell me about your experience with Python.",
                "How do you approach system design?",
                "Describe a challenging debugging scenario.",
                "How do you handle tight deadlines?",
                "What is your experience with cloud platforms?",
                "Describe your testing methodology.",
                "How do you collaborate with cross-functional teams?",
                "What is your experience with CI/CD pipelines?",
                "How do you prioritize competing tasks?",
                "Describe a time you mentored a junior developer.",
            ],
            "star_talking_points": [
                {
                    "competency": "Technical Leadership",
                    "question": "Tell me about leading a technical project.",
                    "situation": "Led migration of monolith to microservices at previous company.",
                    "task": "Reduce response times and improve scalability.",
                    "action": "Designed strangler-fig migration plan, led team of 4.",
                    "result": "Reduced p95 from 4s to 200ms over 3 months.",
                    "source_asset_refs": ["resume"],
                    "is_gap_handled": False,
                    "gap_note": None,
                },
                {
                    "competency": "Problem Solving",
                    "question": "Describe a complex debugging scenario.",
                    "situation": "Production outage affecting 10k users due to memory leak.",
                    "task": "Identify root cause and fix within SLA.",
                    "action": "Used heap profiling to identify unbounded cache growth.",
                    "result": "Fixed within 2 hours, implemented monitoring to prevent recurrence.",
                    "source_asset_refs": ["consultant_profiles"],
                    "is_gap_handled": False,
                    "gap_note": None,
                },
                {
                    "competency": "Cloud Architecture",
                    "question": "What is your cloud platform experience?",
                    "situation": "Tasked with migrating on-premise infrastructure to AWS.",
                    "task": "Design cost-effective cloud architecture.",
                    "action": "Architected multi-AZ deployment with auto-scaling.",
                    "result": "40% cost reduction, 99.95% uptime achieved.",
                    "source_asset_refs": ["resume", "consultant_profiles"],
                    "is_gap_handled": False,
                    "gap_note": None,
                },
                {
                    "competency": "Team Collaboration",
                    "question": "How do you work with cross-functional teams?",
                    "situation": "Joined project mid-sprint with unclear requirements.",
                    "task": "Align engineering and product on deliverables.",
                    "action": "Facilitated daily syncs, created shared requirements doc.",
                    "result": "Delivered on time with full team alignment.",
                    "source_asset_refs": ["consultant_profiles"],
                    "is_gap_handled": False,
                    "gap_note": None,
                },
                {
                    "competency": "Machine Learning",
                    "question": "Describe your ML deployment experience.",
                    "situation": "No direct ML deployment experience, but built supporting infrastructure.",
                    "task": "Support ML team with scalable data pipelines.",
                    "action": "Designed Kafka streaming pipelines with schema validation.",
                    "result": "Enabled ML team to reduce feature freshness from 24h to 5min.",
                    "source_asset_refs": ["consultant_profiles"],
                    "is_gap_handled": True,
                    "gap_note": "Adjacent experience: data pipeline architecture supporting ML workflows.",
                },
            ],
            "company_briefing": (
                "Acme Corp is a mid-size technology company specialising in enterprise SaaS. "
                "They employ approximately 500 people and are headquartered in London. "
                "Their technology stack includes Python, AWS, and Kubernetes. "
                "Recent intent signals suggest they are expanding their engineering team."
            ),
            "questions_to_ask": [
                "What does the team's deployment cadence look like?",
                "How does the engineering team collaborate with product?",
                "What are the biggest technical challenges you're facing this quarter?",
                "How do you approach technical debt management?",
            ],
        }
    )


def _make_grounding_result_all_grounded():
    """Create a mock GroundingResult where all claims are grounded."""
    result = MagicMock()
    result.grounding_report = MagicMock()
    result.grounding_report.claims = []  # No claims = all grounded
    return result


def _make_pipeline_record():
    """Create a mock pipeline record."""
    record = MagicMock()
    record.prospect_id = "prospect-001"
    record.beneficiary_id = "beneficiary-001"
    record.opportunity_type_id = "job_site"
    return record


def _make_prospect():
    """Create a mock prospect with opportunity description."""
    prospect = MagicMock()
    prospect.description = (
        "Senior Software Engineer role. Requirements: Python, cloud architecture, "
        "team leadership, CI/CD experience. Responsibilities include designing "
        "scalable systems, mentoring junior engineers, and driving technical decisions."
    )
    return prospect


def _make_enrichment_record():
    """Create a mock enrichment record."""
    return {
        "industry": "Technology",
        "employee_count": "500",
        "tech_stack": ["Python", "AWS", "Kubernetes"],
        "intent_signals": [{"type": "hiring_expansion"}],
        "headquarters": "London, UK",
    }


def _make_profile_assets():
    """Create mock profile assets (always available per preconditions)."""
    return {
        "resume": (
            "Senior Software Engineer with 8 years of experience. "
            "Led migration of monolith to microservices. "
            "Expertise in Python, AWS, system design."
        ),
        "consultant_profiles": (
            "Specialises in cloud architecture and technical leadership. "
            "Experience with Kafka streaming pipelines, team mentoring, "
            "and production incident management."
        ),
    }


def _make_db_repo_mock(*, submitted_materials_available: bool = False):
    """Create a mocked DB repository.

    Args:
        submitted_materials_available: If False, get_submitted_materials returns None
            to simulate missing CV/cover letter.
    """
    db = MagicMock()
    db.get_pipeline_record = AsyncMock(return_value=_make_pipeline_record())
    db.get_prospect = AsyncMock(return_value=_make_prospect())

    if submitted_materials_available:
        db.get_submitted_materials = AsyncMock(
            return_value={
                "tailored_cv": "My tailored CV content...",
                "tailored_cover_letter": "My cover letter content...",
            }
        )
    else:
        # Simulate missing submitted materials (graceful degradation scenario)
        db.get_submitted_materials = AsyncMock(return_value=None)

    db.get_enrichment_record = AsyncMock(return_value=_make_enrichment_record())
    db.get_intent_signals = AsyncMock(
        return_value=[{"type": "hiring_expansion"}]
    )
    db.get_profile_assets = AsyncMock(return_value=_make_profile_assets())
    db.get_star_examples = AsyncMock(return_value=None)
    db.save_pack = AsyncMock()
    db.update_pack_status = AsyncMock()
    return db


# ─── INTEGRATION TESTS ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graceful_degradation_generates_pack_without_submitted_materials():
    """Pack is generated successfully from profile-only when CV/cover letter are missing.

    Creates a scenario where get_submitted_materials returns None (no CV or
    cover letter submitted), and verifies the service still produces a valid
    pack with status=ready and omission_notes documenting what was missing.

    Requirements: 1.3
    """
    # Arrange
    llm_router = MagicMock()
    llm_router.generate = AsyncMock(return_value=_make_valid_llm_pack_response())

    grounding_verifier = MagicMock()
    grounding_verifier.verify_material = AsyncMock(
        return_value=_make_grounding_result_all_grounded()
    )

    schema_registry = MagicMock()
    db_repo = _make_db_repo_mock(submitted_materials_available=False)
    event_publisher = MagicMock()
    event_publisher.publish = AsyncMock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # Act
    pack = await service.generate_pack(pipeline_record_id="pipeline-001")

    # Assert: pack generated successfully with status=ready
    assert pack.status == PackStatus.READY

    # Assert: omission_notes populated for both missing CV and cover letter
    assert len(pack.omission_notes) == 2
    cv_note = next(
        (n for n in pack.omission_notes if "CV" in n or "cv" in n.lower()), None
    )
    cover_letter_note = next(
        (n for n in pack.omission_notes if "cover letter" in n.lower()), None
    )
    assert cv_note is not None, (
        f"Expected omission note about missing CV, got: {pack.omission_notes}"
    )
    assert cover_letter_note is not None, (
        f"Expected omission note about missing cover letter, got: {pack.omission_notes}"
    )

    # Assert: pack has valid content (generated from profile-only)
    assert len(pack.likely_questions) >= 8
    assert len(pack.star_talking_points) == 5
    assert len(pack.company_briefing) > 0
    assert len(pack.questions_to_ask) >= 3

    # Assert: pack was persisted
    assert db_repo.save_pack.call_count >= 1

    # Assert: notification was sent
    event_publisher.publish.assert_called()


@pytest.mark.asyncio
async def test_graceful_degradation_omission_notes_content():
    """Omission notes contain meaningful descriptions of what is missing.

    Verifies that each omission note clearly describes which material is
    unavailable and that the service is proceeding with profile assets only.

    Requirements: 1.3
    """
    # Arrange
    llm_router = MagicMock()
    llm_router.generate = AsyncMock(return_value=_make_valid_llm_pack_response())

    grounding_verifier = MagicMock()
    grounding_verifier.verify_material = AsyncMock(
        return_value=_make_grounding_result_all_grounded()
    )

    schema_registry = MagicMock()
    db_repo = _make_db_repo_mock(submitted_materials_available=False)
    event_publisher = MagicMock()
    event_publisher.publish = AsyncMock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # Act
    pack = await service.generate_pack(pipeline_record_id="pipeline-001")

    # Assert: omission notes mention "profile" to indicate fallback
    for note in pack.omission_notes:
        assert "profile" in note.lower(), (
            f"Omission note should reference profile fallback: {note}"
        )

    # Assert: one note is about CV, one about cover letter
    notes_lower = [n.lower() for n in pack.omission_notes]
    assert any("cv" in n for n in notes_lower), (
        f"Expected a note about missing CV in: {pack.omission_notes}"
    )
    assert any("cover letter" in n for n in notes_lower), (
        f"Expected a note about missing cover letter in: {pack.omission_notes}"
    )


@pytest.mark.asyncio
async def test_graceful_degradation_llm_called_without_submitted_materials():
    """LLM generation proceeds without submitted materials section when missing.

    Verifies that the LLM is called and the prompt does NOT include CV/cover
    letter content (since they're unavailable), but generation succeeds.

    Requirements: 1.3
    """
    # Arrange
    llm_router = MagicMock()
    llm_router.generate = AsyncMock(return_value=_make_valid_llm_pack_response())

    grounding_verifier = MagicMock()
    grounding_verifier.verify_material = AsyncMock(
        return_value=_make_grounding_result_all_grounded()
    )

    schema_registry = MagicMock()
    db_repo = _make_db_repo_mock(submitted_materials_available=False)
    event_publisher = MagicMock()
    event_publisher.publish = AsyncMock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # Act
    pack = await service.generate_pack(pipeline_record_id="pipeline-001")

    # Assert: LLM was still called (generation proceeded)
    llm_router.generate.assert_called()

    # Assert: the prompt passed to LLM does NOT contain CV/cover letter content
    call_kwargs = llm_router.generate.call_args
    prompt_text = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0] if call_kwargs.args else ""
    if not prompt_text and call_kwargs.kwargs:
        prompt_text = call_kwargs.kwargs.get("prompt", "")

    # The submitted materials section should be empty when materials are missing
    assert "SUBMITTED CV:" not in prompt_text
    assert "SUBMITTED COVER LETTER:" not in prompt_text

    # Assert: pack is still valid
    assert pack.status == PackStatus.READY
    assert len(pack.likely_questions) >= 8


@pytest.mark.asyncio
async def test_graceful_degradation_grounding_still_runs():
    """Grounding verification still runs on packs generated from profile-only.

    Even without submitted materials, STAR talking points must still pass
    through the Grounding_Verifier to ensure they're traceable to profile assets.

    Requirements: 1.3
    """
    # Arrange
    llm_router = MagicMock()
    llm_router.generate = AsyncMock(return_value=_make_valid_llm_pack_response())

    grounding_verifier = MagicMock()
    grounding_verifier.verify_material = AsyncMock(
        return_value=_make_grounding_result_all_grounded()
    )

    schema_registry = MagicMock()
    db_repo = _make_db_repo_mock(submitted_materials_available=False)
    event_publisher = MagicMock()
    event_publisher.publish = AsyncMock()

    service = InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )

    # Act
    pack = await service.generate_pack(pipeline_record_id="pipeline-001")

    # Assert: grounding verifier was called (claims still verified)
    grounding_verifier.verify_material.assert_called_once()

    # Assert: pack reached READY status (grounding passed)
    assert pack.status == PackStatus.READY
    assert pack.grounding_flags == []
