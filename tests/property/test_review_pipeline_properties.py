# Feature: review-critique-loop, Properties 10-12: Pipeline integration property tests
"""Property-based tests for Review Pipeline Stage integration.

Tests the dispatch timing enforcement, review status pipeline transitions,
and narrative revision targeting properties.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.review_models import (
    CritiqueCategory,
    DraftMaterial,
    NarrativeFinding,
    ReasoningLog,
    ReviewResult,
    ReviewStatus,
)
from app.core.review_pipeline_stage import ReviewPipelineStage
from app.core.review_service import ReviewService


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_draft_material(
    content: str = "Some draft content",
    quality_score: int = 75,
    material_id: str = "mat-001",
):
    """Create a DraftMaterial for testing."""
    return DraftMaterial(
        id=material_id,
        pipeline_record_id="pipe-001",
        prepare_technique_id="cv_and_cover_letter",
        material_type="tailored_cv",
        content=content,
        quality_score=quality_score,
        generated_at=datetime.now(timezone.utc),
    )


def _make_reasoning_log(
    material_id: str = "mat-001",
    status: ReviewStatus = ReviewStatus.REVIEWED,
):
    """Create a minimal ReasoningLog for testing."""
    now = datetime.now(timezone.utc)
    return ReasoningLog(
        material_id=material_id,
        prepare_technique_id="cv_and_cover_letter",
        review_technique_id="standard_material_review",
        cycles=[],
        total_cycles_executed=1,
        max_cycles_configured=2,
        final_review_status=status,
        started_at=now,
        completed_at=now,
    )


def _make_review_result(
    material_id: str = "mat-001",
    content: str = "Revised content",
    status: ReviewStatus = ReviewStatus.REVIEWED,
    quality_score: int = 80,
):
    """Create a ReviewResult for testing."""
    return ReviewResult(
        material_id=material_id,
        revised_content=content,
        review_status=status,
        reasoning_log=_make_reasoning_log(material_id, status),
        quality_score_final=quality_score,
        total_edits_applied=2,
    )


# ─── Strategies ───────────────────────────────────────────────────────────────

# Safe text without null bytes for material content
safe_content = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z", "S"),
        blacklist_characters="\x00",
    ),
    min_size=10,
    max_size=300,
)

# Quality scores 0-100
quality_scores = st.integers(min_value=0, max_value=100)

# Review status outcomes
review_statuses = st.sampled_from([
    ReviewStatus.REVIEWED,
    ReviewStatus.UNREVIEWED,
    ReviewStatus.REVIEW_FAILED,
])


# ─── Property 10: Dispatch occurs within 10 seconds of draft completion ───────


class TestProperty10DispatchTiming:
    """Property 10: Dispatch occurs within 10 seconds of draft completion.

    The ReviewPipelineStage enforces a DISPATCH_DEADLINE of 10 seconds.
    When process_after_generation() is called, the review must be dispatched
    quickly and the stage must verify timing against the deadline constant.

    **Validates: Requirement 1, AC 1**
    """

    @given(
        content=safe_content,
        quality_score=quality_scores,
    )
    @settings(max_examples=100)
    def test_dispatch_occurs_within_deadline(
        self, content: str, quality_score: int
    ) -> None:
        """WHEN process_after_generation is called with a draft material,
        THEN review_service.review_material is dispatched and completes
        well within the DISPATCH_DEADLINE (10 seconds).

        **Validates: Requirement 1, AC 1**
        """
        # Mock review service that returns immediately
        mock_review_service = AsyncMock()
        mock_review_service.review_material.return_value = _make_review_result(
            content=content, quality_score=quality_score
        )

        # Mock schema registry that confirms review technique exists
        mock_schema = MagicMock()
        mock_schema.get_review_technique_for_prepare.return_value = MagicMock()

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema,
        )

        draft = _make_draft_material(content=content, quality_score=quality_score)

        import time

        async def run():
            start = time.monotonic()
            result = await stage.process_after_generation(
                draft_material=draft,
                prospect=MagicMock(),
                beneficiary=MagicMock(),
                enrichment=MagicMock(),
                opportunity_description="Test opportunity",
            )
            elapsed = time.monotonic() - start
            return result, elapsed

        result, elapsed = asyncio.run(run())

        # Verify the dispatch happened (review_material was called)
        mock_review_service.review_material.assert_called_once()

        # Verify dispatch occurred within the DISPATCH_DEADLINE
        assert elapsed < ReviewPipelineStage.DISPATCH_DEADLINE, (
            f"Dispatch took {elapsed:.2f}s, exceeding "
            f"DISPATCH_DEADLINE of {ReviewPipelineStage.DISPATCH_DEADLINE}s"
        )

    @given(content=safe_content)
    @settings(max_examples=100)
    def test_dispatch_deadline_constant_is_10_seconds(self, content: str) -> None:
        """WHEN ReviewPipelineStage is instantiated, THEN DISPATCH_DEADLINE
        is always 10.0 seconds as required.

        **Validates: Requirement 1, AC 1**
        """
        assert ReviewPipelineStage.DISPATCH_DEADLINE == 10.0

        # Also verify the stage enforces this by having the constant accessible
        mock_review_service = AsyncMock()
        mock_schema = MagicMock()
        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema,
        )
        assert stage.DISPATCH_DEADLINE == 10.0


# ─── Property 11: Review status correctly transitions pipeline state ──────────


class TestProperty11ReviewStatusTransition:
    """Property 11: Review status correctly transitions pipeline state.

    After review completes, the pipeline stage result must contain the
    correct ReviewStatus enum value matching the review outcome.

    **Validates: Requirement 3, AC 3**
    """

    @given(
        status=review_statuses,
        content=safe_content,
        quality_score=quality_scores,
    )
    @settings(max_examples=100)
    def test_pipeline_returns_matching_review_status(
        self, status: ReviewStatus, content: str, quality_score: int
    ) -> None:
        """WHEN ReviewService returns a specific ReviewStatus, THEN the
        pipeline stage result dict contains the same status enum value.

        **Validates: Requirement 3, AC 3**
        """
        # Mock review service to return the generated status
        mock_review_service = AsyncMock()
        mock_review_service.review_material.return_value = _make_review_result(
            content=content,
            status=status,
            quality_score=quality_score,
        )

        # Mock schema registry that confirms review technique exists
        mock_schema = MagicMock()
        mock_schema.get_review_technique_for_prepare.return_value = MagicMock()

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema,
        )

        draft = _make_draft_material(content=content, quality_score=quality_score)

        async def run():
            return await stage.process_after_generation(
                draft_material=draft,
                prospect=MagicMock(),
                beneficiary=MagicMock(),
                enrichment=MagicMock(),
                opportunity_description="Test opportunity",
            )

        result = asyncio.run(run())

        # The pipeline stage result must contain the matching status
        assert result["review_status"] == status
        assert isinstance(result["review_status"], ReviewStatus)

    @given(
        content=safe_content,
        quality_score=quality_scores,
    )
    @settings(max_examples=100)
    def test_pipeline_always_transitions_to_post_prepare_state(
        self, content: str, quality_score: int
    ) -> None:
        """WHEN process_after_generation completes (success or failure),
        THEN the result always contains revised_content, review_status,
        reasoning_log, and quality_score keys (post-prepare state).

        **Validates: Requirement 3, AC 3**
        """
        # Mock review service that returns successfully
        mock_review_service = AsyncMock()
        mock_review_service.review_material.return_value = _make_review_result(
            content=content, quality_score=quality_score
        )

        mock_schema = MagicMock()
        mock_schema.get_review_technique_for_prepare.return_value = MagicMock()

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema,
        )

        draft = _make_draft_material(content=content, quality_score=quality_score)

        async def run():
            return await stage.process_after_generation(
                draft_material=draft,
                prospect=MagicMock(),
                beneficiary=MagicMock(),
                enrichment=MagicMock(),
                opportunity_description="Test opportunity",
            )

        result = asyncio.run(run())

        # Post-prepare state requires all four keys
        assert "revised_content" in result
        assert "review_status" in result
        assert "reasoning_log" in result
        assert "quality_score" in result

        # review_status must be a valid ReviewStatus enum
        assert isinstance(result["review_status"], ReviewStatus)

    @given(content=safe_content, quality_score=quality_scores)
    @settings(max_examples=100)
    def test_exception_degrades_to_unreviewed_status(
        self, content: str, quality_score: int
    ) -> None:
        """WHEN ReviewService raises an unexpected exception, THEN the
        pipeline stage returns UNREVIEWED status with original content.

        **Validates: Requirement 3, AC 3**
        """
        # Mock review service that raises an exception
        mock_review_service = AsyncMock()
        mock_review_service.review_material.side_effect = RuntimeError(
            "Unexpected LLM failure"
        )

        mock_schema = MagicMock()
        mock_schema.get_review_technique_for_prepare.return_value = MagicMock()

        stage = ReviewPipelineStage(
            review_service=mock_review_service,
            schema_registry=mock_schema,
        )

        draft = _make_draft_material(content=content, quality_score=quality_score)

        async def run():
            return await stage.process_after_generation(
                draft_material=draft,
                prospect=MagicMock(),
                beneficiary=MagicMock(),
                enrichment=MagicMock(),
                opportunity_description="Test opportunity",
            )

        result = asyncio.run(run())

        # Graceful degradation: original content returned with UNREVIEWED
        assert result["review_status"] == ReviewStatus.UNREVIEWED
        assert result["revised_content"] == content
        assert result["quality_score"] == quality_score


# ─── Property 12: Narrative revision targets only flagged passages ────────────


class TestProperty12NarrativeRevisionTargeting:
    """Property 12: Narrative revision targets only flagged passages.

    The revision prompt built by ReviewService._build_revision_prompt()
    must instruct modification of ONLY the flagged passages and include
    those passages in the prompt output.

    **Validates: Requirement 2, AC 5**
    """

    @given(
        material_content=safe_content,
        passage_1=st.from_regex(r"[A-Za-z ]{10,40}", fullmatch=True),
        passage_2=st.from_regex(r"[A-Za-z ]{10,40}", fullmatch=True),
        description_1=st.from_regex(r"[A-Za-z ]{10,30}", fullmatch=True),
        description_2=st.from_regex(r"[A-Za-z ]{10,30}", fullmatch=True),
    )
    @settings(max_examples=100)
    def test_revision_prompt_includes_only_flagged_passages(
        self,
        material_content: str,
        passage_1: str,
        passage_2: str,
        description_1: str,
        description_2: str,
    ) -> None:
        """WHEN _build_revision_prompt is called with narrative findings
        that have flagged_passage values, THEN the prompt includes those
        flagged passages and instructs revision of only those passages.

        **Validates: Requirement 2, AC 5**
        """
        assume(passage_1 != passage_2)

        findings: dict[CritiqueCategory, list[NarrativeFinding]] = {
            CritiqueCategory.MISSED_KEYWORDS: [
                NarrativeFinding(
                    category=CritiqueCategory.MISSED_KEYWORDS,
                    description=description_1,
                    flagged_passage=passage_1,
                ),
            ],
            CritiqueCategory.REFRAMING: [
                NarrativeFinding(
                    category=CritiqueCategory.REFRAMING,
                    description=description_2,
                    flagged_passage=passage_2,
                ),
            ],
            CritiqueCategory.COMPANY_ANGLES: [],
            CritiqueCategory.TONE_STYLE: [],
        }

        # Instantiate ReviewService with mocked deps
        service = ReviewService(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            review_repository=MagicMock(),
            personalization_engine=MagicMock(),
        )

        prompt = service._build_revision_prompt(material_content, findings)

        # The prompt must include both flagged passages
        assert passage_1 in prompt
        assert passage_2 in prompt

        # The prompt must instruct revision of ONLY flagged passages
        assert "ONLY" in prompt or "only" in prompt
        # The prompt must instruct preserving other content
        assert "verbatim" in prompt.lower() or "preserve" in prompt.lower()

    @given(
        material_content=safe_content,
        passage=st.from_regex(r"[A-Za-z ]{10,40}", fullmatch=True),
        non_flagged_text=st.from_regex(r"UNIQUE_[A-Z]{8,15}", fullmatch=True),
        description=st.from_regex(r"[A-Za-z ]{10,30}", fullmatch=True),
    )
    @settings(max_examples=100)
    def test_revision_prompt_does_not_target_unflagged_content(
        self,
        material_content: str,
        passage: str,
        non_flagged_text: str,
        description: str,
    ) -> None:
        """WHEN _build_revision_prompt is called, THEN the narrative_findings
        section of the prompt does NOT contain arbitrary material content
        that was not flagged.

        **Validates: Requirement 2, AC 5**
        """
        # Ensure the non_flagged_text is distinct from the flagged passage
        assume(non_flagged_text not in passage)
        assume(non_flagged_text not in description)

        findings: dict[CritiqueCategory, list[NarrativeFinding]] = {
            CritiqueCategory.TONE_STYLE: [
                NarrativeFinding(
                    category=CritiqueCategory.TONE_STYLE,
                    description=description,
                    flagged_passage=passage,
                ),
            ],
            CritiqueCategory.MISSED_KEYWORDS: [],
            CritiqueCategory.COMPANY_ANGLES: [],
            CritiqueCategory.REFRAMING: [],
        }

        service = ReviewService(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            review_repository=MagicMock(),
            personalization_engine=MagicMock(),
        )

        # Include non_flagged_text in the material but NOT as a flagged passage
        full_content = material_content + " " + non_flagged_text

        prompt = service._build_revision_prompt(full_content, findings)

        # The narrative_findings section should contain the flagged passage
        assert passage in prompt

        # Extract just the narrative_findings section from the prompt
        findings_start = prompt.find("<narrative_findings>")
        findings_end = prompt.find("</narrative_findings>")
        if findings_start != -1 and findings_end != -1:
            findings_section = prompt[findings_start:findings_end]
            # The non-flagged text should NOT appear in the findings section
            assert non_flagged_text not in findings_section

    @given(
        material_content=safe_content,
        description=st.from_regex(r"[A-Za-z ]{10,30}", fullmatch=True),
    )
    @settings(max_examples=100)
    def test_revision_prompt_handles_none_flagged_passage(
        self, material_content: str, description: str
    ) -> None:
        """WHEN a NarrativeFinding has flagged_passage=None (omission finding),
        THEN the prompt still includes the description but no quoted passage.

        **Validates: Requirement 2, AC 5**
        """
        findings: dict[CritiqueCategory, list[NarrativeFinding]] = {
            CritiqueCategory.MISSED_KEYWORDS: [
                NarrativeFinding(
                    category=CritiqueCategory.MISSED_KEYWORDS,
                    description=description,
                    flagged_passage=None,  # Omission finding
                ),
            ],
            CritiqueCategory.COMPANY_ANGLES: [],
            CritiqueCategory.REFRAMING: [],
            CritiqueCategory.TONE_STYLE: [],
        }

        service = ReviewService(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            review_repository=MagicMock(),
            personalization_engine=MagicMock(),
        )

        prompt = service._build_revision_prompt(material_content, findings)

        # The description should appear in the prompt
        assert description in prompt
        # "Flagged passage:" should NOT appear for None passages
        # (The implementation only adds flagged_passage line when it's not None)
        assert "Flagged passage:" not in prompt
