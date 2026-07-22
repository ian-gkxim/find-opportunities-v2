# Feature: interview-prep-technique, Property 1: Pack structural invariants
"""Property-based tests for Interview_Prep_Pack structural validation.

Generates random Interview_Prep_Packs with varying counts and content lengths.
Verifies: _validate_pack_structure returns empty errors iff counts and word
limits are within bounds.

**Validates: Requirements 2.1**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.interview_prep_models import (
    Interview_Prep_Pack,
    PackStatus,
    STAR_Talking_Point,
)
from app.core.interview_prep_service import InterviewPrepService


# ─── Constants (mirroring service constraints) ────────────────────────────────

MIN_QUESTIONS = InterviewPrepService.MIN_QUESTIONS  # 8
MAX_QUESTIONS = InterviewPrepService.MAX_QUESTIONS  # 15
STAR_COUNT = InterviewPrepService.STAR_COUNT  # 5
MAX_BRIEFING_WORDS = InterviewPrepService.MAX_BRIEFING_WORDS  # 400
MIN_QUESTIONS_TO_ASK = InterviewPrepService.MIN_QUESTIONS_TO_ASK  # 3
MAX_QUESTIONS_TO_ASK = InterviewPrepService.MAX_QUESTIONS_TO_ASK  # 6


# ─── Strategies ───────────────────────────────────────────────────────────────

_word = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),  # a-z
    min_size=3,
    max_size=10,
)

_question_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        min_codepoint=32,
        max_codepoint=126,
    ),
    min_size=5,
    max_size=80,
)

# Source asset refs: list of 0+ asset IDs
_source_asset_refs = st.lists(
    st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
        min_size=3,
        max_size=15,
    ),
    min_size=0,
    max_size=4,
)


@st.composite
def star_talking_point_strategy(draw: st.DrawFn) -> STAR_Talking_Point:
    """Generate a random STAR_Talking_Point with varying source_asset_refs."""
    return STAR_Talking_Point(
        competency=draw(_word),
        question=draw(_question_text),
        situation=draw(_question_text),
        task=draw(_question_text),
        action=draw(_question_text),
        result=draw(_question_text),
        source_asset_refs=draw(_source_asset_refs),
        is_gap_handled=False,
        gap_note=None,
    )


@st.composite
def company_briefing_strategy(draw: st.DrawFn, max_words: int = 600) -> str:
    """Generate a company briefing with 0 to max_words words."""
    word_count = draw(st.integers(min_value=0, max_value=max_words))
    words = draw(st.lists(_word, min_size=word_count, max_size=word_count))
    return " ".join(words)


@st.composite
def interview_prep_pack_strategy(draw: st.DrawFn) -> Interview_Prep_Pack:
    """Generate a random Interview_Prep_Pack with varying counts and content.

    Ranges:
    - likely_questions: 0-20 entries
    - star_talking_points: 0-10 STAR_Talking_Point instances
    - company_briefing: 0-600 words
    - questions_to_ask: 0-10 entries
    """
    likely_questions_count = draw(st.integers(min_value=0, max_value=20))
    star_count = draw(st.integers(min_value=0, max_value=10))
    questions_to_ask_count = draw(st.integers(min_value=0, max_value=10))

    likely_questions = draw(
        st.lists(_question_text, min_size=likely_questions_count, max_size=likely_questions_count)
    )
    star_talking_points = draw(
        st.lists(star_talking_point_strategy(), min_size=star_count, max_size=star_count)
    )
    company_briefing = draw(company_briefing_strategy())
    questions_to_ask = draw(
        st.lists(_question_text, min_size=questions_to_ask_count, max_size=questions_to_ask_count)
    )

    now = datetime.now(tz=timezone.utc)
    return Interview_Prep_Pack(
        id=str(uuid.uuid4()),
        pipeline_record_id="pipeline-001",
        beneficiary_id="beneficiary-001",
        opportunity_type_id="job_site",
        likely_questions=likely_questions,
        star_talking_points=star_talking_points,
        company_briefing=company_briefing,
        questions_to_ask=questions_to_ask,
        status=PackStatus.READY,
        omission_notes=[],
        grounding_flags=[],
        generation_duration_ms=1000,
        created_at=now,
        updated_at=now,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _create_service() -> InterviewPrepService:
    """Create an InterviewPrepService instance without __init__ dependencies.

    Uses __new__ to bypass constructor since we only need _validate_pack_structure
    which accesses class constants, not instance dependencies.
    """
    service = InterviewPrepService.__new__(InterviewPrepService)
    return service


def _pack_is_within_bounds(pack: Interview_Prep_Pack) -> bool:
    """Check whether a pack satisfies all structural constraints.

    Mirrors the logic in _validate_pack_structure:
    - likely_questions count in [8, 15]
    - star_talking_points count == 5
    - company_briefing word count <= 400
    - questions_to_ask count in [3, 6]
    - All STAR points have at least one source_asset_ref
    """
    if not (MIN_QUESTIONS <= len(pack.likely_questions) <= MAX_QUESTIONS):
        return False
    if len(pack.star_talking_points) != STAR_COUNT:
        return False
    briefing_words = len(pack.company_briefing.split())
    if briefing_words > MAX_BRIEFING_WORDS:
        return False
    if not (MIN_QUESTIONS_TO_ASK <= len(pack.questions_to_ask) <= MAX_QUESTIONS_TO_ASK):
        return False
    for tp in pack.star_talking_points:
        if not tp.source_asset_refs:
            return False
    return True


# ─── Property 1: Pack structural invariants ───────────────────────────────────


class TestProperty1PackStructuralInvariants:
    """Property 1: Pack structural invariants.

    For any successfully generated Interview_Prep_Pack, _validate_pack_structure
    returns empty errors iff counts and word limits are within bounds.

    **Validates: Requirements 2.1**
    """

    @given(pack=interview_prep_pack_strategy())
    @settings(max_examples=200)
    def test_valid_pack_returns_empty_errors(
        self,
        pack: Interview_Prep_Pack,
    ) -> None:
        """FOR ANY pack where all structural constraints are satisfied,
        _validate_pack_structure SHALL return an empty list.

        **Validates: Requirements 2.1**
        """
        service = _create_service()

        if _pack_is_within_bounds(pack):
            errors = service._validate_pack_structure(pack)
            assert errors == [], (
                f"Pack is within bounds but got validation errors: {errors}\n"
                f"likely_questions={len(pack.likely_questions)}, "
                f"star_talking_points={len(pack.star_talking_points)}, "
                f"briefing_words={len(pack.company_briefing.split())}, "
                f"questions_to_ask={len(pack.questions_to_ask)}"
            )

    @given(pack=interview_prep_pack_strategy())
    @settings(max_examples=200)
    def test_invalid_pack_returns_non_empty_errors(
        self,
        pack: Interview_Prep_Pack,
    ) -> None:
        """FOR ANY pack where ANY structural constraint is violated,
        _validate_pack_structure SHALL return a non-empty list.

        **Validates: Requirements 2.1**
        """
        service = _create_service()

        if not _pack_is_within_bounds(pack):
            errors = service._validate_pack_structure(pack)
            assert len(errors) > 0, (
                f"Pack violates constraints but got no validation errors.\n"
                f"likely_questions={len(pack.likely_questions)}, "
                f"star_talking_points={len(pack.star_talking_points)}, "
                f"briefing_words={len(pack.company_briefing.split())}, "
                f"questions_to_ask={len(pack.questions_to_ask)}, "
                f"star_refs={[len(tp.source_asset_refs) for tp in pack.star_talking_points]}"
            )
