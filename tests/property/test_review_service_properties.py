# Feature: review-critique-loop, Properties 1-8: Review_Service property tests
"""Property-based tests for Review_Service core logic.

Tests the structured edit application, ungrounded filtering, cycle bounds,
category completeness, batch concurrency, graceful degradation, quality
score recomputation, and fresh context exclusion properties.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.review_models import (
    CritiqueCategory,
    CritiqueResponse,
    CycleLog,
    DraftMaterial,
    EditOutcome,
    EditReason,
    EditSkipReason,
    NarrativeFinding,
    ReviewLLMError,
    ReviewResult,
    ReviewStatus,
    StructuredEdit,
)
from app.core.review_service import ReviewService


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_service(
    llm_router=None, schema_registry=None, review_repository=None,
    personalization_engine=None,
):
    """Create a ReviewService with mocked dependencies."""
    return ReviewService(
        llm_router=llm_router or MagicMock(),
        schema_registry=schema_registry or MagicMock(),
        review_repository=review_repository or MagicMock(),
        personalization_engine=personalization_engine or MagicMock(),
    )


def _make_draft_material(content: str = "Some draft content", quality_score: int = 75):
    """Create a DraftMaterial for testing."""
    return DraftMaterial(
        id="mat-001",
        pipeline_record_id="pipe-001",
        prepare_technique_id="cv_and_cover_letter",
        material_type="tailored_cv",
        content=content,
        quality_score=quality_score,
        generated_at=datetime.now(timezone.utc),
    )


def _make_critique_response(edits=None, findings=None):
    """Create a valid CritiqueResponse dict for mocking LLM returns."""
    return {
        "structured_edits": edits or [],
        "narrative_findings": findings or {
            "missed_keywords": [],
            "company_angles": [],
            "reframing": [],
            "tone_style": [],
        },
    }


# ─── Strategies ───────────────────────────────────────────────────────────────

# Printable text without null bytes
safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z", "S"),
                           blacklist_characters="\x00"),
    min_size=1, max_size=200,
)

# Words for asset sets (alphanumeric, 4-15 chars)
asset_word = st.from_regex(r"[a-z]{4,15}", fullmatch=True)


# ─── Property 1: Structured edit applies iff old_string matches exactly once ──


class TestProperty1EditApplication:
    """Property 1: Structured edit applies if and only if old_string matches exactly once.

    **Validates: Requirement 2, AC 3**
    """

    @given(
        prefix=st.text(min_size=0, max_size=50),
        target=st.text(min_size=1, max_size=30),
        suffix=st.text(min_size=0, max_size=50),
        replacement=st.text(min_size=1, max_size=30),
    )
    @settings(max_examples=100)
    def test_exactly_one_match_applies_edit(
        self, prefix: str, target: str, suffix: str, replacement: str
    ) -> None:
        """WHEN old_string occurs exactly once in material, THEN the edit is applied.

        **Validates: Requirement 2, AC 3**
        """
        # Ensure target appears exactly once in material
        material = prefix + target + suffix
        assume(material.count(target) == 1)
        assume(target != replacement)

        service = _make_service()
        edit = StructuredEdit(
            target_material_id="mat-001",
            old_string=target,
            new_string=replacement,
            reason=EditReason.KEYWORD_MATCH,
            category=CritiqueCategory.MISSED_KEYWORDS,
        )

        # Use empty beneficiary_assets so grounding check passes (no ungrounded filter)
        revised, outcomes = service._apply_structured_edits(material, [edit], set())

        assert len(outcomes) == 1
        assert outcomes[0].applied is True
        assert outcomes[0].skip_reason is None
        # The replacement must appear in the revised text
        assert replacement in revised


    @given(
        base_text=st.text(min_size=5, max_size=100),
        old_string=st.text(min_size=1, max_size=20),
    )
    @settings(max_examples=100)
    def test_zero_matches_skips_with_ambiguous(
        self, base_text: str, old_string: str
    ) -> None:
        """WHEN old_string occurs zero times in material, THEN edit is skipped
        with AMBIGUOUS_OR_STALE_TARGET.

        **Validates: Requirement 2, AC 3**
        """
        # Ensure old_string does NOT appear in base_text
        assume(old_string not in base_text)

        service = _make_service()
        edit = StructuredEdit(
            target_material_id="mat-001",
            old_string=old_string,
            new_string="replacement",
            reason=EditReason.REFRAMING,
            category=CritiqueCategory.REFRAMING,
        )

        revised, outcomes = service._apply_structured_edits(base_text, [edit], set())

        assert len(outcomes) == 1
        assert outcomes[0].applied is False
        assert outcomes[0].skip_reason == EditSkipReason.AMBIGUOUS_OR_STALE_TARGET
        assert revised == base_text  # Text unchanged

    @given(
        target=st.text(min_size=1, max_size=15),
        filler=st.text(min_size=1, max_size=20),
    )
    @settings(max_examples=100)
    def test_multiple_matches_skips_with_ambiguous(
        self, target: str, filler: str
    ) -> None:
        """WHEN old_string occurs more than once in material, THEN edit is skipped
        with AMBIGUOUS_OR_STALE_TARGET.

        **Validates: Requirement 2, AC 3**
        """
        # Build text with target appearing at least twice
        material = target + filler + target
        assume(material.count(target) >= 2)

        service = _make_service()
        edit = StructuredEdit(
            target_material_id="mat-001",
            old_string=target,
            new_string="replacement",
            reason=EditReason.STYLE,
            category=CritiqueCategory.TONE_STYLE,
        )

        revised, outcomes = service._apply_structured_edits(material, [edit], set())

        assert len(outcomes) == 1
        assert outcomes[0].applied is False
        assert outcomes[0].skip_reason == EditSkipReason.AMBIGUOUS_OR_STALE_TARGET
        assert revised == material  # Text unchanged


# ─── Property 2: Ungrounded suggestions are always discarded ─────────────────


class TestProperty2UngroundedFiltering:
    """Property 2: Ungrounded suggestions are always discarded.

    **Validates: Requirement 2, AC 4**
    """

    @given(
        material=st.text(min_size=10, max_size=100),
        old_word=st.from_regex(r"[a-z]{4,10}", fullmatch=True),
        ungrounded_word=st.from_regex(r"[a-z]{5,12}", fullmatch=True),
        asset_words=st.lists(
            st.from_regex(r"[a-z]{4,12}", fullmatch=True),
            min_size=1, max_size=5, unique=True,
        ),
    )
    @settings(max_examples=100)
    def test_ungrounded_edits_are_discarded(
        self, material: str, old_word: str, ungrounded_word: str,
        asset_words: list[str],
    ) -> None:
        """WHEN a structured edit introduces content not present in beneficiary
        assets, THEN the edit is discarded with UNGROUNDED_SUGGESTION.

        **Validates: Requirement 2, AC 4**
        """
        # Ensure old_word appears exactly once in material
        material_with_target = material + " " + old_word + " end."
        assume(material_with_target.count(old_word) == 1)

        # Ensure ungrounded_word is NOT in any asset and NOT in old_word
        assume(ungrounded_word not in old_word)
        assume(ungrounded_word not in material_with_target)
        for asset in asset_words:
            assume(ungrounded_word not in asset)

        beneficiary_assets = set(asset_words)

        service = _make_service()
        edit = StructuredEdit(
            target_material_id="mat-001",
            old_string=old_word,
            new_string=f"introduced {ungrounded_word} here",
            reason=EditReason.COMPANY_ANGLE,
            category=CritiqueCategory.COMPANY_ANGLES,
        )

        revised, outcomes = service._apply_structured_edits(
            material_with_target, [edit], beneficiary_assets
        )

        assert len(outcomes) == 1
        assert outcomes[0].applied is False
        assert outcomes[0].skip_reason == EditSkipReason.UNGROUNDED_SUGGESTION
        assert revised == material_with_target  # Text unchanged


    @given(
        material=st.text(min_size=10, max_size=100),
        old_word=st.from_regex(r"[a-z]{4,10}", fullmatch=True),
        grounded_word=st.from_regex(r"[a-z]{5,12}", fullmatch=True),
    )
    @settings(max_examples=100)
    def test_grounded_edits_are_applied(
        self, material: str, old_word: str, grounded_word: str
    ) -> None:
        """WHEN a structured edit introduces content present in beneficiary
        assets, THEN the edit is applied (not discarded).

        **Validates: Requirement 2, AC 4**
        """
        # Build material with old_word appearing exactly once
        material_with_target = material + " " + old_word + " end."
        assume(material_with_target.count(old_word) == 1)
        assume(grounded_word not in old_word)
        assume(old_word not in grounded_word)

        # The new_string uses ONLY the grounded_word (no other significant words)
        # The asset set contains the grounded word so it passes grounding check
        beneficiary_assets = {grounded_word}

        service = _make_service()
        edit = StructuredEdit(
            target_material_id="mat-001",
            old_string=old_word,
            new_string=grounded_word,
            reason=EditReason.KEYWORD_MATCH,
            category=CritiqueCategory.MISSED_KEYWORDS,
        )

        revised, outcomes = service._apply_structured_edits(
            material_with_target, [edit], beneficiary_assets
        )

        assert len(outcomes) == 1
        assert outcomes[0].applied is True
        assert outcomes[0].skip_reason is None


# ─── Property 3: Review cycles bounded by schema configuration ────────────────


class TestProperty3CycleBounds:
    """Property 3: Review cycles bounded by schema configuration.

    **Validates: Requirement 3, AC 1**
    """

    @given(max_cycles=st.integers(min_value=1, max_value=3))
    @settings(max_examples=100)
    def test_cycles_never_exceed_max(self, max_cycles: int) -> None:
        """WHEN max_review_cycles is configured, THEN total cycles executed
        never exceeds that value and never exceeds 3.

        **Validates: Requirement 3, AC 1**
        """
        # Mock schema registry to return a review technique with max_cycles
        mock_schema = MagicMock()
        mock_review_technique = MagicMock()
        mock_review_technique.max_review_cycles = max_cycles
        mock_review_technique.critique_categories = [
            "missed_keywords", "company_angles", "reframing", "tone_style"
        ]
        mock_review_technique.id = "test_review"
        mock_schema.get_review_technique_for_prepare.return_value = mock_review_technique

        # Mock LLM router to return valid critique responses
        mock_llm = AsyncMock()
        mock_llm.dispatch_critique.return_value = _make_critique_response()
        mock_llm.dispatch_revision.return_value = "revised text"

        # Mock repository
        mock_db = AsyncMock()

        service = _make_service(
            llm_router=mock_llm,
            schema_registry=mock_schema,
            review_repository=mock_db,
        )

        draft = _make_draft_material(content="This is test content for review.")
        mock_beneficiary = {"profile_assets": {"skills": ["python", "consulting"]}}

        result = asyncio.run(service.review_material(
            draft_material=draft,
            prospect=MagicMock(),
            beneficiary=mock_beneficiary,
            enrichment={"firmographics": {}, "technographics": {}, "intent_signals": [], "contact_seniority": ""},
            opportunity_description="Test opportunity",
        ))

        assert result.reasoning_log.total_cycles_executed <= max_cycles
        assert result.reasoning_log.total_cycles_executed <= 3
        assert result.reasoning_log.max_cycles_configured == max_cycles


# ─── Property 4: All four critique categories are always present ──────────────


class TestProperty4CategoryCompleteness:
    """Property 4: All four critique categories are always present in response.

    **Validates: Requirement 1, AC 4**
    """

    @given(
        missed_count=st.integers(min_value=0, max_value=5),
        angles_count=st.integers(min_value=0, max_value=5),
        reframing_count=st.integers(min_value=0, max_value=5),
        tone_count=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=100)
    def test_all_four_categories_present(
        self, missed_count: int, angles_count: int,
        reframing_count: int, tone_count: int,
    ) -> None:
        """WHEN a CritiqueResponse is constructed, THEN narrative_findings
        always contains all four CritiqueCategory keys.

        **Validates: Requirement 1, AC 4**
        """
        # Build a CritiqueResponse with random number of findings per category
        findings: dict[CritiqueCategory, list[NarrativeFinding]] = {
            CritiqueCategory.MISSED_KEYWORDS: [
                NarrativeFinding(
                    category=CritiqueCategory.MISSED_KEYWORDS,
                    description=f"Finding {i}",
                )
                for i in range(missed_count)
            ],
            CritiqueCategory.COMPANY_ANGLES: [
                NarrativeFinding(
                    category=CritiqueCategory.COMPANY_ANGLES,
                    description=f"Finding {i}",
                )
                for i in range(angles_count)
            ],
            CritiqueCategory.REFRAMING: [
                NarrativeFinding(
                    category=CritiqueCategory.REFRAMING,
                    description=f"Finding {i}",
                )
                for i in range(reframing_count)
            ],
            CritiqueCategory.TONE_STYLE: [
                NarrativeFinding(
                    category=CritiqueCategory.TONE_STYLE,
                    description=f"Finding {i}",
                )
                for i in range(tone_count)
            ],
        }

        response = CritiqueResponse(
            structured_edits=[],
            narrative_findings=findings,
        )

        # Verify all four categories are present
        required_categories = set(CritiqueCategory)
        present_categories = set(response.narrative_findings.keys())
        assert required_categories == present_categories
        assert len(response.narrative_findings) == 4


# ─── Property 5: Batch concurrency never exceeds 3 ───────────────────────────


class TestProperty5BatchConcurrency:
    """Property 5: Batch concurrency never exceeds 3 concurrent critiques.

    **Validates: Requirement 3, AC 5**
    """

    @given(batch_size=st.integers(min_value=1, max_value=10))
    @settings(max_examples=100)
    def test_peak_concurrency_never_exceeds_three(self, batch_size: int) -> None:
        """WHEN a batch of N materials is queued for review, THEN at no point
        do more than 3 critiques execute concurrently.

        **Validates: Requirement 3, AC 5**
        """
        peak_concurrency = 0
        current_concurrency = 0
        lock = asyncio.Lock()

        async def mock_dispatch_critique(prompt, timeout=60.0):
            nonlocal peak_concurrency, current_concurrency
            async with lock:
                current_concurrency += 1
                peak_concurrency = max(peak_concurrency, current_concurrency)
            # Simulate brief LLM work
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrency -= 1
            return _make_critique_response()

        async def mock_dispatch_revision(prompt, timeout=60.0):
            return "revised"

        # Setup mocks
        mock_schema = MagicMock()
        mock_review_technique = MagicMock()
        mock_review_technique.max_review_cycles = 1
        mock_review_technique.critique_categories = [
            "missed_keywords", "company_angles", "reframing", "tone_style"
        ]
        mock_review_technique.id = "test_review"
        mock_schema.get_review_technique_for_prepare.return_value = mock_review_technique

        mock_llm = AsyncMock()
        mock_llm.dispatch_critique.side_effect = mock_dispatch_critique
        mock_llm.dispatch_revision.side_effect = mock_dispatch_revision

        mock_db = AsyncMock()

        service = _make_service(
            llm_router=mock_llm,
            schema_registry=mock_schema,
            review_repository=mock_db,
        )

        materials = [
            _make_draft_material(content=f"Content for material {i}")
            for i in range(batch_size)
        ]
        mock_beneficiary = {"profile_assets": {"skills": ["python"]}}

        async def run_batch():
            return await service.review_batch(
                materials=materials,
                prospect=MagicMock(),
                beneficiary=mock_beneficiary,
                enrichment={"firmographics": {}, "technographics": {}, "intent_signals": [], "contact_seniority": ""},
                opportunity_description="Test opportunity",
            )

        asyncio.run(run_batch())

        assert peak_concurrency <= ReviewService.BATCH_CONCURRENCY
        assert peak_concurrency <= 3


# ─── Property 6: Failed critique degrades gracefully to "unreviewed" ──────────


class TestProperty6GracefulDegradation:
    """Property 6: Failed critique degrades gracefully to "unreviewed".

    **Validates: Requirement 1, AC 5**
    """

    @given(
        failure_type=st.sampled_from(["timeout", "error", "malformed_json"]),
        content=st.text(min_size=10, max_size=100),
    )
    @settings(max_examples=100)
    def test_llm_failure_results_in_unreviewed(
        self, failure_type: str, content: str,
    ) -> None:
        """WHEN all LLM critique attempts fail, THEN material is marked
        "unreviewed" and proceeds.

        **Validates: Requirement 1, AC 5**
        """
        # Mock schema registry
        mock_schema = MagicMock()
        mock_review_technique = MagicMock()
        mock_review_technique.max_review_cycles = 1
        mock_review_technique.critique_categories = [
            "missed_keywords", "company_angles", "reframing", "tone_style"
        ]
        mock_review_technique.id = "test_review"
        mock_schema.get_review_technique_for_prepare.return_value = mock_review_technique

        # Mock LLM to always fail based on failure_type
        mock_llm = AsyncMock()
        if failure_type == "timeout":
            mock_llm.dispatch_critique.side_effect = TimeoutError("LLM timeout")
        elif failure_type == "error":
            mock_llm.dispatch_critique.side_effect = RuntimeError("API 500 error")
        else:  # malformed_json
            mock_llm.dispatch_critique.return_value = {"invalid": "structure"}

        mock_db = AsyncMock()
        mock_db.mark_unreviewed = AsyncMock()

        service = _make_service(
            llm_router=mock_llm,
            schema_registry=mock_schema,
            review_repository=mock_db,
        )

        draft = _make_draft_material(content=content)
        mock_beneficiary = {"profile_assets": {"skills": ["python"]}}

        result = asyncio.run(service.review_material(
            draft_material=draft,
            prospect=MagicMock(),
            beneficiary=mock_beneficiary,
            enrichment={"firmographics": {}, "technographics": {}, "intent_signals": [], "contact_seniority": ""},
            opportunity_description="Test opportunity",
        ))

        assert result.review_status == ReviewStatus.UNREVIEWED
        # Material content should revert to original on failure
        assert result.revised_content == content


# ─── Property 7: Quality score is recomputed after each cycle ─────────────────


class TestProperty7QualityScoreRecomputation:
    """Property 7: Quality score is recomputed after each cycle.

    **Validates: Requirement 3, AC 2**
    """

    @given(
        initial_score=st.integers(min_value=0, max_value=100),
        max_cycles=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=100)
    def test_cycle_log_records_before_and_after_scores(
        self, initial_score: int, max_cycles: int,
    ) -> None:
        """WHEN a review cycle completes, THEN CycleLog records
        quality_score_before and quality_score_after with recomputed values.

        **Validates: Requirement 3, AC 2**
        """
        # Mock schema registry
        mock_schema = MagicMock()
        mock_review_technique = MagicMock()
        mock_review_technique.max_review_cycles = max_cycles
        mock_review_technique.critique_categories = [
            "missed_keywords", "company_angles", "reframing", "tone_style"
        ]
        mock_review_technique.id = "test_review"
        mock_schema.get_review_technique_for_prepare.return_value = mock_review_technique

        # Mock LLM to return valid critique with no edits (simpler)
        mock_llm = AsyncMock()
        mock_llm.dispatch_critique.return_value = _make_critique_response()
        mock_llm.dispatch_revision.return_value = "revised text"

        mock_db = AsyncMock()

        service = _make_service(
            llm_router=mock_llm,
            schema_registry=mock_schema,
            review_repository=mock_db,
        )

        draft = _make_draft_material(
            content="This is a test material.\n\nWith multiple paragraphs.",
            quality_score=initial_score,
        )
        mock_beneficiary = {"profile_assets": {"skills": ["python"]}}

        result = asyncio.run(service.review_material(
            draft_material=draft,
            prospect=MagicMock(),
            beneficiary=mock_beneficiary,
            enrichment={"firmographics": {}, "technographics": {}, "intent_signals": [], "contact_seniority": ""},
            opportunity_description="Test opportunity",
        ))

        # Every cycle must have quality_score_before and quality_score_after
        assert len(result.reasoning_log.cycles) == max_cycles
        for i, cycle_log in enumerate(result.reasoning_log.cycles):
            assert 0 <= cycle_log.quality_score_before <= 100
            assert 0 <= cycle_log.quality_score_after <= 100
            # First cycle's before should be the initial score
            if i == 0:
                assert cycle_log.quality_score_before == initial_score
            # Each subsequent cycle's before should equal previous cycle's after
            if i > 0:
                prev_cycle = result.reasoning_log.cycles[i - 1]
                assert cycle_log.quality_score_before == prev_cycle.quality_score_after


# ─── Property 8: Fresh context excludes drafting pass artifacts ───────────────


class TestProperty8FreshContextExclusion:
    """Property 8: Fresh context excludes drafting pass artifacts.

    **Validates: Requirement 1, AC 2**
    """

    @given(
        conversation_suffix=st.from_regex(r"[A-Z][a-z]{8,20}", fullmatch=True),
        template_suffix=st.from_regex(r"[A-Z][a-z]{8,20}", fullmatch=True),
        reasoning_suffix=st.from_regex(r"[A-Z][a-z]{8,20}", fullmatch=True),
    )
    @settings(max_examples=100)
    def test_prompt_excludes_drafting_artifacts(
        self, conversation_suffix: str, template_suffix: str,
        reasoning_suffix: str,
    ) -> None:
        """WHEN _build_fresh_context_prompt is called, THEN the resulting prompt
        never contains drafting conversation, prompt template, or reasoning chain.

        **Validates: Requirement 1, AC 2**
        """
        # Use unique prefixes that will never appear in the prompt template
        drafting_conversation = f"DRAFTCONV_{conversation_suffix}_XYZZY"
        prompt_template = f"TMPLPROMPT_{template_suffix}_XYZZY"
        reasoning_chain = f"REASONING_{reasoning_suffix}_XYZZY"

        material_text = "This is a simple draft material for testing."
        opportunity = "Software engineering role at TechCorp"

        service = _make_service()

        # Create enrichment with drafting artifacts in non-standard fields
        enrichment = {
            "firmographics": {"company": "TestCorp"},
            "technographics": {"stack": ["python"]},
            "intent_signals": [],
            "contact_seniority": "senior",
            # These should NOT appear because they're not part of the
            # expected enrichment fields that get extracted
            "drafting_conversation": drafting_conversation,
            "prompt_template": prompt_template,
            "reasoning_chain": reasoning_chain,
        }

        beneficiary = {
            "profile_assets": {
                "skills": ["python", "consulting"],
            },
        }

        categories = list(CritiqueCategory)

        prompt = service._build_fresh_context_prompt(
            material_text=material_text,
            opportunity_description=opportunity,
            enrichment=enrichment,
            beneficiary=beneficiary,
            categories=categories,
        )

        # The prompt should contain the material and opportunity
        assert material_text in prompt
        assert opportunity in prompt

        # The prompt should NOT contain drafting artifacts
        # _build_fresh_context_prompt extracts only firmographics,
        # technographics, intent_signals, contact_seniority
        assert drafting_conversation not in prompt
        assert prompt_template not in prompt
        assert reasoning_chain not in prompt
