"""Unit tests for app.core.review_models domain models.

Validates enum membership, string values, dataclass instantiation,
CritiqueResponse category completeness, and exception class hierarchy.

Requirements: 1.4, 2.1
"""

from datetime import datetime, timezone

import pytest

from app.core.errors import BaseServiceError
from app.core.review_models import (
    CritiqueCategory,
    CritiqueParseError,
    CritiqueResponse,
    CycleLog,
    DraftMaterial,
    EditOutcome,
    EditReason,
    EditSkipReason,
    NarrativeFinding,
    ReasoningLog,
    ReviewLLMError,
    ReviewResult,
    ReviewStatus,
    ReviewTimeoutError,
    StructuredEdit,
)

# ─── ENUM TESTS ──────────────────────────────────────────────────────────────


class TestReviewStatus:
    """ReviewStatus enum: 3 values with correct string representations."""

    def test_has_three_members(self):
        assert len(ReviewStatus) == 3

    def test_reviewed_value(self):
        assert ReviewStatus.REVIEWED == "reviewed"
        assert ReviewStatus.REVIEWED.value == "reviewed"

    def test_unreviewed_value(self):
        assert ReviewStatus.UNREVIEWED == "unreviewed"
        assert ReviewStatus.UNREVIEWED.value == "unreviewed"

    def test_review_failed_value(self):
        assert ReviewStatus.REVIEW_FAILED == "review_failed"
        assert ReviewStatus.REVIEW_FAILED.value == "review_failed"

    def test_is_str_enum(self):
        """ReviewStatus members are usable as plain strings."""
        assert isinstance(ReviewStatus.REVIEWED, str)


class TestEditReason:
    """EditReason enum: 4 values with correct string representations."""

    def test_has_four_members(self):
        assert len(EditReason) == 4

    def test_keyword_match_value(self):
        assert EditReason.KEYWORD_MATCH == "keyword_match"

    def test_company_angle_value(self):
        assert EditReason.COMPANY_ANGLE == "company_angle"

    def test_reframing_value(self):
        assert EditReason.REFRAMING == "reframing"

    def test_style_value(self):
        assert EditReason.STYLE == "style"

    def test_is_str_enum(self):
        assert isinstance(EditReason.KEYWORD_MATCH, str)


class TestEditSkipReason:
    """EditSkipReason enum: 2 values."""

    def test_has_two_members(self):
        assert len(EditSkipReason) == 2

    def test_ambiguous_or_stale_target_value(self):
        assert EditSkipReason.AMBIGUOUS_OR_STALE_TARGET == "ambiguous_or_stale_target"

    def test_ungrounded_suggestion_value(self):
        assert EditSkipReason.UNGROUNDED_SUGGESTION == "ungrounded_suggestion"

    def test_is_str_enum(self):
        assert isinstance(EditSkipReason.AMBIGUOUS_OR_STALE_TARGET, str)


class TestCritiqueCategory:
    """CritiqueCategory enum: 4 fixed categories the reviewer must report on."""

    def test_has_four_members(self):
        assert len(CritiqueCategory) == 4

    def test_missed_keywords_value(self):
        assert CritiqueCategory.MISSED_KEYWORDS == "missed_keywords"

    def test_company_angles_value(self):
        assert CritiqueCategory.COMPANY_ANGLES == "company_angles"

    def test_reframing_value(self):
        assert CritiqueCategory.REFRAMING == "reframing"

    def test_tone_style_value(self):
        assert CritiqueCategory.TONE_STYLE == "tone_style"

    def test_is_str_enum(self):
        assert isinstance(CritiqueCategory.MISSED_KEYWORDS, str)


# ─── DATACLASS TESTS ─────────────────────────────────────────────────────────


class TestStructuredEdit:
    """StructuredEdit dataclass instantiation."""

    def test_valid_instantiation(self):
        edit = StructuredEdit(
            target_material_id="mat-001",
            old_string="generic phrasing here",
            new_string="specific company-focused phrasing",
            reason=EditReason.COMPANY_ANGLE,
            category=CritiqueCategory.COMPANY_ANGLES,
        )
        assert edit.target_material_id == "mat-001"
        assert edit.old_string == "generic phrasing here"
        assert edit.new_string == "specific company-focused phrasing"
        assert edit.reason == EditReason.COMPANY_ANGLE
        assert edit.category == CritiqueCategory.COMPANY_ANGLES

    def test_all_reason_category_combinations(self):
        """Each EditReason can pair with any CritiqueCategory."""
        edit = StructuredEdit(
            target_material_id="mat-002",
            old_string="old",
            new_string="new",
            reason=EditReason.STYLE,
            category=CritiqueCategory.TONE_STYLE,
        )
        assert edit.reason == EditReason.STYLE
        assert edit.category == CritiqueCategory.TONE_STYLE


class TestNarrativeFinding:
    """NarrativeFinding dataclass instantiation."""

    def test_valid_instantiation_with_passage(self):
        finding = NarrativeFinding(
            category=CritiqueCategory.REFRAMING,
            description="The phrase is too passive",
            flagged_passage="we have experience in",
        )
        assert finding.category == CritiqueCategory.REFRAMING
        assert finding.description == "The phrase is too passive"
        assert finding.flagged_passage == "we have experience in"

    def test_valid_instantiation_without_passage(self):
        """flagged_passage is None for omission findings."""
        finding = NarrativeFinding(
            category=CritiqueCategory.MISSED_KEYWORDS,
            description="The draft omits the keyword 'cloud migration'",
        )
        assert finding.flagged_passage is None

    def test_flagged_passage_defaults_to_none(self):
        finding = NarrativeFinding(
            category=CritiqueCategory.COMPANY_ANGLES,
            description="Missing mention of recent acquisition",
        )
        assert finding.flagged_passage is None


class TestCritiqueResponse:
    """CritiqueResponse dataclass — requires all four category keys."""

    def _make_complete_response(self) -> CritiqueResponse:
        """Helper to build a valid CritiqueResponse with all categories."""
        return CritiqueResponse(
            structured_edits=[
                StructuredEdit(
                    target_material_id="mat-001",
                    old_string="old text",
                    new_string="new text",
                    reason=EditReason.KEYWORD_MATCH,
                    category=CritiqueCategory.MISSED_KEYWORDS,
                )
            ],
            narrative_findings={
                CritiqueCategory.MISSED_KEYWORDS: [
                    NarrativeFinding(
                        category=CritiqueCategory.MISSED_KEYWORDS,
                        description="Missing keyword: AI",
                    )
                ],
                CritiqueCategory.COMPANY_ANGLES: [],
                CritiqueCategory.REFRAMING: [],
                CritiqueCategory.TONE_STYLE: [],
            },
        )

    def test_valid_instantiation_all_categories_present(self):
        response = self._make_complete_response()
        assert len(response.structured_edits) == 1
        assert len(response.narrative_findings) == 4
        # All four categories present
        for cat in CritiqueCategory:
            assert cat in response.narrative_findings

    def test_empty_edits_and_all_empty_findings(self):
        """Valid response with no edits and no findings (all empty lists)."""
        response = CritiqueResponse(
            structured_edits=[],
            narrative_findings={
                CritiqueCategory.MISSED_KEYWORDS: [],
                CritiqueCategory.COMPANY_ANGLES: [],
                CritiqueCategory.REFRAMING: [],
                CritiqueCategory.TONE_STYLE: [],
            },
        )
        assert response.structured_edits == []
        for cat in CritiqueCategory:
            assert response.narrative_findings[cat] == []

    def test_missing_category_key_detectable(self):
        """A CritiqueResponse with missing category keys can be detected."""
        incomplete_findings = {
            CritiqueCategory.MISSED_KEYWORDS: [],
            CritiqueCategory.COMPANY_ANGLES: [],
            # Missing REFRAMING and TONE_STYLE
        }
        response = CritiqueResponse(
            structured_edits=[],
            narrative_findings=incomplete_findings,
        )
        # Detection: check all four keys are present
        missing_keys = [
            cat for cat in CritiqueCategory if cat not in response.narrative_findings
        ]
        assert len(missing_keys) == 2
        assert CritiqueCategory.REFRAMING in missing_keys
        assert CritiqueCategory.TONE_STYLE in missing_keys

    def test_single_missing_category_detected(self):
        """A single missing category key is detectable."""
        findings = {
            CritiqueCategory.MISSED_KEYWORDS: [],
            CritiqueCategory.COMPANY_ANGLES: [],
            CritiqueCategory.REFRAMING: [],
            # Missing TONE_STYLE
        }
        response = CritiqueResponse(
            structured_edits=[],
            narrative_findings=findings,
        )
        missing = [cat for cat in CritiqueCategory if cat not in response.narrative_findings]
        assert missing == [CritiqueCategory.TONE_STYLE]


class TestEditOutcome:
    """EditOutcome dataclass instantiation."""

    def test_applied_edit(self):
        edit = StructuredEdit(
            target_material_id="mat-001",
            old_string="old",
            new_string="new",
            reason=EditReason.REFRAMING,
            category=CritiqueCategory.REFRAMING,
        )
        outcome = EditOutcome(edit=edit, applied=True)
        assert outcome.applied is True
        assert outcome.skip_reason is None

    def test_skipped_edit(self):
        edit = StructuredEdit(
            target_material_id="mat-001",
            old_string="not found",
            new_string="replacement",
            reason=EditReason.STYLE,
            category=CritiqueCategory.TONE_STYLE,
        )
        outcome = EditOutcome(
            edit=edit,
            applied=False,
            skip_reason=EditSkipReason.AMBIGUOUS_OR_STALE_TARGET,
        )
        assert outcome.applied is False
        assert outcome.skip_reason == EditSkipReason.AMBIGUOUS_OR_STALE_TARGET

    def test_discarded_edit(self):
        edit = StructuredEdit(
            target_material_id="mat-001",
            old_string="existing text",
            new_string="ungrounded claim",
            reason=EditReason.KEYWORD_MATCH,
            category=CritiqueCategory.MISSED_KEYWORDS,
        )
        outcome = EditOutcome(
            edit=edit,
            applied=False,
            skip_reason=EditSkipReason.UNGROUNDED_SUGGESTION,
        )
        assert outcome.applied is False
        assert outcome.skip_reason == EditSkipReason.UNGROUNDED_SUGGESTION


class TestCycleLog:
    """CycleLog dataclass instantiation."""

    def test_valid_instantiation(self):
        log = CycleLog(
            cycle_number=1,
            edits_applied=3,
            edits_skipped=1,
            edits_discarded=0,
            narrative_findings_by_category={
                CritiqueCategory.MISSED_KEYWORDS: 2,
                CritiqueCategory.COMPANY_ANGLES: 1,
                CritiqueCategory.REFRAMING: 0,
                CritiqueCategory.TONE_STYLE: 0,
            },
            quality_score_before=65,
            quality_score_after=78,
            duration_ms=4500,
        )
        assert log.cycle_number == 1
        assert log.edits_applied == 3
        assert log.edits_skipped == 1
        assert log.edits_discarded == 0
        assert log.quality_score_before == 65
        assert log.quality_score_after == 78
        assert log.duration_ms == 4500
        assert log.skipped_edits == []
        assert log.discarded_edits == []


class TestDraftMaterial:
    """DraftMaterial dataclass — all fields populated."""

    def test_valid_instantiation_all_fields(self):
        now = datetime.now(tz=timezone.utc)
        material = DraftMaterial(
            id="550e8400-e29b-41d4-a716-446655440000",
            pipeline_record_id="rec-001",
            prepare_technique_id="cv_and_cover_letter",
            material_type="tailored_cv",
            content="Dear Hiring Manager, I am writing to express...",
            quality_score=72,
            generated_at=now,
        )
        assert material.id == "550e8400-e29b-41d4-a716-446655440000"
        assert material.pipeline_record_id == "rec-001"
        assert material.prepare_technique_id == "cv_and_cover_letter"
        assert material.material_type == "tailored_cv"
        assert material.content == "Dear Hiring Manager, I am writing to express..."
        assert material.quality_score == 72
        assert material.generated_at == now

    def test_all_material_types(self):
        """DraftMaterial supports all four material types."""
        now = datetime.now(tz=timezone.utc)
        for material_type in ("tailored_cv", "tailored_cover_letter", "draft_email", "proposal"):
            material = DraftMaterial(
                id="id-1",
                pipeline_record_id="rec-1",
                prepare_technique_id="technique-1",
                material_type=material_type,
                content="content",
                quality_score=50,
                generated_at=now,
            )
            assert material.material_type == material_type


class TestReasoningLog:
    """ReasoningLog dataclass instantiation."""

    def test_valid_instantiation(self):
        started = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        completed = datetime(2024, 1, 1, 12, 0, 5, tzinfo=timezone.utc)
        cycle = CycleLog(
            cycle_number=1,
            edits_applied=2,
            edits_skipped=0,
            edits_discarded=1,
            narrative_findings_by_category={
                CritiqueCategory.MISSED_KEYWORDS: 1,
                CritiqueCategory.COMPANY_ANGLES: 0,
                CritiqueCategory.REFRAMING: 0,
                CritiqueCategory.TONE_STYLE: 1,
            },
            quality_score_before=60,
            quality_score_after=75,
            duration_ms=3200,
        )
        log = ReasoningLog(
            material_id="mat-001",
            prepare_technique_id="cv_and_cover_letter",
            review_technique_id="standard_material_review",
            cycles=[cycle],
            total_cycles_executed=1,
            max_cycles_configured=2,
            final_review_status=ReviewStatus.REVIEWED,
            started_at=started,
            completed_at=completed,
        )
        assert log.material_id == "mat-001"
        assert log.total_cycles_executed == 1
        assert log.max_cycles_configured == 2
        assert log.final_review_status == ReviewStatus.REVIEWED
        assert len(log.cycles) == 1


class TestReviewResult:
    """ReviewResult dataclass instantiation."""

    def test_valid_instantiation(self):
        started = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        completed = datetime(2024, 1, 1, 12, 0, 5, tzinfo=timezone.utc)
        reasoning_log = ReasoningLog(
            material_id="mat-001",
            prepare_technique_id="cv_and_cover_letter",
            review_technique_id="standard_material_review",
            cycles=[],
            total_cycles_executed=1,
            max_cycles_configured=2,
            final_review_status=ReviewStatus.REVIEWED,
            started_at=started,
            completed_at=completed,
        )
        result = ReviewResult(
            material_id="mat-001",
            revised_content="Improved content here",
            review_status=ReviewStatus.REVIEWED,
            reasoning_log=reasoning_log,
            quality_score_final=85,
            total_edits_applied=4,
        )
        assert result.material_id == "mat-001"
        assert result.revised_content == "Improved content here"
        assert result.review_status == ReviewStatus.REVIEWED
        assert result.quality_score_final == 85
        assert result.total_edits_applied == 4


# ─── EXCEPTION CLASS TESTS ───────────────────────────────────────────────────


class TestReviewLLMError:
    """ReviewLLMError exception class."""

    def test_stores_material_id_and_attempts(self):
        err = ReviewLLMError(
            message="LLM critique failed",
            material_id="mat-123",
            attempts=3,
        )
        assert err.material_id == "mat-123"
        assert err.attempts == 3
        assert err.message == "LLM critique failed"

    def test_inherits_base_service_error(self):
        err = ReviewLLMError(
            message="failed",
            material_id="mat-001",
            attempts=2,
        )
        assert isinstance(err, BaseServiceError)
        assert isinstance(err, Exception)

    def test_service_is_llm_critique(self):
        err = ReviewLLMError(
            message="timeout",
            material_id="mat-001",
            attempts=1,
        )
        assert err.service == "llm_critique"

    def test_entity_id_is_material_id(self):
        err = ReviewLLMError(
            message="error",
            material_id="mat-456",
            attempts=2,
        )
        assert err.entity_id == "mat-456"


class TestReviewTimeoutError:
    """ReviewTimeoutError — inherits from ReviewLLMError."""

    def test_inherits_review_llm_error(self):
        err = ReviewTimeoutError(
            message="Critique exceeded 60s",
            material_id="mat-789",
            attempts=3,
        )
        assert isinstance(err, ReviewLLMError)
        assert isinstance(err, BaseServiceError)

    def test_stores_material_id_and_attempts(self):
        err = ReviewTimeoutError(
            message="timeout",
            material_id="mat-100",
            attempts=2,
        )
        assert err.material_id == "mat-100"
        assert err.attempts == 2

    def test_catchable_as_review_llm_error(self):
        err = ReviewTimeoutError(
            message="timed out",
            material_id="mat-001",
            attempts=3,
        )
        with pytest.raises(ReviewLLMError):
            raise err


class TestCritiqueParseError:
    """CritiqueParseError — inherits from ReviewLLMError."""

    def test_inherits_review_llm_error(self):
        err = CritiqueParseError(
            message="Invalid JSON in critique response",
            material_id="mat-200",
            attempts=1,
        )
        assert isinstance(err, ReviewLLMError)
        assert isinstance(err, BaseServiceError)

    def test_stores_material_id_and_attempts(self):
        err = CritiqueParseError(
            message="parse error",
            material_id="mat-300",
            attempts=2,
        )
        assert err.material_id == "mat-300"
        assert err.attempts == 2

    def test_catchable_as_review_llm_error(self):
        err = CritiqueParseError(
            message="bad json",
            material_id="mat-001",
            attempts=1,
        )
        with pytest.raises(ReviewLLMError):
            raise err


class TestExceptionHierarchy:
    """Verify the full exception hierarchy for review errors."""

    @pytest.mark.parametrize(
        "error_class",
        [ReviewLLMError, ReviewTimeoutError, CritiqueParseError],
    )
    def test_all_catchable_as_base_service_error(self, error_class):
        err = error_class(
            message="test error",
            material_id="mat-001",
            attempts=1,
        )
        with pytest.raises(BaseServiceError):
            raise err

    def test_timeout_is_subclass_of_review_llm_error(self):
        assert issubclass(ReviewTimeoutError, ReviewLLMError)

    def test_parse_error_is_subclass_of_review_llm_error(self):
        assert issubclass(CritiqueParseError, ReviewLLMError)

    def test_review_llm_error_is_subclass_of_base_service_error(self):
        assert issubclass(ReviewLLMError, BaseServiceError)
