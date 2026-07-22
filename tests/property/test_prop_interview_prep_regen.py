# Feature: interview-prep-technique, Property 4: Grounding verification with single regeneration
"""Property-based test for grounding verification with single regeneration.

Mock Grounding_Verifier to return varying claim statuses (all grounded,
some ungrounded, all ungrounded). Verify:
- Exactly one regeneration attempt when ungrounded claims found
- No further regeneration after single attempt
- Remaining flags surfaced in grounding_flags

**Validates: Requirements 2.3**
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.interview_prep_models import (
    GenerationContext,
    Interview_Prep_Pack,
    PackStatus,
    STAR_Talking_Point,
)
from app.core.interview_prep_service import InterviewPrepService
from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingReport,
    GroundingResult,
    GroundingStatus,
    MaterialGroundingStatus,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_star_points(count: int = 5) -> list[STAR_Talking_Point]:
    """Build a list of STAR talking points for testing."""
    return [
        STAR_Talking_Point(
            competency=f"Competency {i}",
            question=f"Tell me about your experience with competency {i}",
            situation=f"At company X I worked on situation {i}",
            task=f"I needed to accomplish task {i}",
            action=f"I took action {i} to resolve the problem",
            result=f"This resulted in result {i} with measurable outcomes",
            source_asset_refs=["resume"],
            is_gap_handled=False,
            gap_note=None,
        )
        for i in range(count)
    ]


def _make_pack(star_points: list[STAR_Talking_Point] | None = None) -> Interview_Prep_Pack:
    """Build a valid Interview_Prep_Pack for testing."""
    now = datetime.now(tz=timezone.utc)
    return Interview_Prep_Pack(
        id="pack-001",
        pipeline_record_id="pipeline-record-001",
        beneficiary_id="ben-001",
        opportunity_type_id="job_site",
        likely_questions=[f"Question {i}" for i in range(10)],
        star_talking_points=star_points or _make_star_points(),
        company_briefing="A brief company overview for the interview.",
        questions_to_ask=[f"Ask question {i}" for i in range(4)],
        status=PackStatus.GROUNDING,
        omission_notes=[],
        grounding_flags=[],
        created_at=now,
        updated_at=now,
    )


def _make_context() -> GenerationContext:
    """Build a minimal GenerationContext for testing."""
    return GenerationContext(
        opportunity_description="Senior engineer role at TechCo.",
        tailored_cv="Experienced engineer with 10 years.",
        tailored_cover_letter="Cover letter content.",
        enrichment_record={
            "industry": "Technology",
            "employee_count": "500",
            "tech_stack": ["Python", "AWS"],
            "headquarters": "London",
        },
        intent_signals=[{"type": "hiring_signal"}],
        profile_assets={"resume": "10 years of Python engineering experience."},
        star_examples=None,
        opportunity_type_id="job_site",
        beneficiary_id="ben-001",
    )


def _make_grounding_result(
    num_ungrounded: int,
    total_claims: int = 5,
) -> GroundingResult:
    """Build a GroundingResult with the specified number of ungrounded claims.

    Creates `total_claims` claims, with the first `num_ungrounded` being ungrounded
    and the rest grounded.
    """
    claims = []
    for i in range(total_claims):
        status = GroundingStatus.UNGROUNDED if i < num_ungrounded else GroundingStatus.GROUNDED
        claims.append(
            Claim(
                id=f"claim-{i}",
                material_id="interview_prep_pack-001",
                category=ClaimCategory.ACHIEVEMENT_OUTCOME,
                claim_text=f"I took action {i} to resolve the problem",
                source_span=f"I took action {i} to resolve the problem",
                source_span_start=0,
                source_span_end=50,
                grounding_status=status,
                source_pointer=None,
                discrepancy=None,
                is_prospect_side=False,
            )
        )

    grounded_count = total_claims - num_ungrounded
    ungrounded_count = num_ungrounded
    material_status = (
        MaterialGroundingStatus.GROUNDING_VERIFIED
        if num_ungrounded == 0
        else MaterialGroundingStatus.GROUNDING_BLOCKED
    )

    now = datetime.now(tz=timezone.utc)
    report = GroundingReport(
        id="report-001",
        material_id="interview_prep_pack-001",
        pipeline_record_id="pipeline-record-001",
        claims=claims,
        total_claims=total_claims,
        grounded_count=grounded_count,
        partially_grounded_count=0,
        ungrounded_count=ungrounded_count,
        material_grounding_status=material_status,
        extraction_duration_ms=100,
        verification_duration_ms=200,
        created_at=now,
        updated_at=now,
    )

    return GroundingResult(
        material_id="interview_prep_pack-001",
        material_grounding_status=material_status,
        grounding_report=report,
        blocked_states=[],
        requires_action=num_ungrounded > 0,
    )


def _make_regenerated_points_json(count: int) -> str:
    """Build a JSON response for regenerated STAR talking points."""
    points = [
        {
            "competency": f"Regenerated Competency {i}",
            "question": f"Regenerated question {i}",
            "situation": f"Regenerated situation {i}",
            "task": f"Regenerated task {i}",
            "action": f"Regenerated action {i}",
            "result": f"Regenerated result {i}",
            "source_asset_refs": ["resume"],
            "is_gap_handled": False,
            "gap_note": None,
        }
        for i in range(count)
    ]
    return json.dumps({"star_talking_points": points})


def _make_service() -> tuple[InterviewPrepService, AsyncMock, AsyncMock]:
    """Create an InterviewPrepService with mocked dependencies.

    Returns (service, llm_mock, grounding_mock).
    """
    llm_mock = AsyncMock()
    grounding_mock = AsyncMock()
    schema_mock = MagicMock()
    db_mock = AsyncMock()
    publisher_mock = AsyncMock()

    service = InterviewPrepService(
        llm_router=llm_mock,
        grounding_verifier=grounding_mock,
        schema_registry=schema_mock,
        db_repo=db_mock,
        event_publisher=publisher_mock,
    )

    return service, llm_mock, grounding_mock


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestGroundingSingleRegenerationProperty:
    """Property 4: Grounding verification with single regeneration."""

    @given(
        num_ungrounded_claims=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_no_regeneration_when_all_grounded(
        self, num_ungrounded_claims: int
    ) -> None:
        """WHEN all claims are grounded (num_ungrounded=0), THEN LLM.generate is
        NOT called for regeneration and grounding_flags is empty.

        **Validates: Requirements 2.3**
        """
        # Only test the "all grounded" case
        if num_ungrounded_claims != 0:
            return

        service, llm_mock, grounding_mock = _make_service()
        pack = _make_pack()
        context = _make_context()

        # Mock grounding verifier to return all grounded
        grounding_mock.verify_material = AsyncMock(
            return_value=_make_grounding_result(num_ungrounded=0)
        )

        updated_pack, remaining_flags = await service._ground_talking_points(
            pack, context
        )

        # LLM should NOT be called for regeneration
        llm_mock.generate.assert_not_called()
        # No grounding flags
        assert remaining_flags == []

    @given(
        num_ungrounded_claims=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_single_regeneration_when_ungrounded_found(
        self, num_ungrounded_claims: int
    ) -> None:
        """WHEN some claims are ungrounded (num_ungrounded >= 1), THEN
        LLM.generate is called exactly once for regeneration and
        verify_material is called exactly 2 times (initial + re-verify).

        **Validates: Requirements 2.3**
        """
        service, llm_mock, grounding_mock = _make_service()
        pack = _make_pack()
        context = _make_context()

        # First call: initial grounding returns ungrounded claims
        initial_result = _make_grounding_result(num_ungrounded=num_ungrounded_claims)
        # Second call: re-verification after regeneration returns all grounded
        reverify_result = _make_grounding_result(num_ungrounded=0)

        grounding_mock.verify_material = AsyncMock(
            side_effect=[initial_result, reverify_result]
        )

        # Mock LLM to return valid regenerated points
        llm_mock.generate = AsyncMock(
            return_value=_make_regenerated_points_json(num_ungrounded_claims)
        )

        updated_pack, remaining_flags = await service._ground_talking_points(
            pack, context
        )

        # LLM.generate called exactly once for regeneration
        assert llm_mock.generate.call_count == 1
        # verify_material called exactly 2 times (initial + re-verify)
        assert grounding_mock.verify_material.call_count == 2

    @given(
        num_ungrounded_claims=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_remaining_flags_surfaced_after_single_regen(
        self, num_ungrounded_claims: int
    ) -> None:
        """AFTER single regeneration, any remaining ungrounded claims appear
        in grounding_flags rather than triggering further regeneration.

        **Validates: Requirements 2.3**
        """
        service, llm_mock, grounding_mock = _make_service()
        pack = _make_pack()
        context = _make_context()

        # First call: initial grounding returns ungrounded claims
        initial_result = _make_grounding_result(num_ungrounded=num_ungrounded_claims)

        # Second call: re-verification still finds some ungrounded
        # (simulate partial improvement: leave 1 ungrounded remaining)
        remaining_ungrounded = min(num_ungrounded_claims, 1)
        reverify_result = _make_grounding_result(num_ungrounded=remaining_ungrounded)

        grounding_mock.verify_material = AsyncMock(
            side_effect=[initial_result, reverify_result]
        )

        # Mock LLM to return valid regenerated points
        llm_mock.generate = AsyncMock(
            return_value=_make_regenerated_points_json(num_ungrounded_claims)
        )

        updated_pack, remaining_flags = await service._ground_talking_points(
            pack, context
        )

        # LLM.generate called exactly once — no further regeneration
        assert llm_mock.generate.call_count == 1
        # verify_material called exactly 2 times — no further verification loops
        assert grounding_mock.verify_material.call_count == 2
        # Remaining flags are surfaced in grounding_flags
        assert len(remaining_flags) == remaining_ungrounded
        # Each flag corresponds to the claim text from the re-verify result
        for flag in remaining_flags:
            assert isinstance(flag, str)
            assert len(flag) > 0
