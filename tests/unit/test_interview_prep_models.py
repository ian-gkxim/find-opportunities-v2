"""Unit tests for app.core.interview_prep_models domain models.

Validates enum membership, string values, dataclass instantiation,
default field values, and exception class hierarchy.

Requirements: 2.1
"""

from datetime import datetime, timezone

import pytest

from app.core.interview_prep_models import (
    ContextAssemblyError,
    DeadlineExceededError,
    GapHandlingStrategy,
    GenerationContext,
    GenerationTimeoutError,
    Interview_Prep_Pack,
    InterviewPrepError,
    PackStatus,
    PackValidationError,
    STAR_Talking_Point,
)


# ─── ENUM TESTS ──────────────────────────────────────────────────────────────


class TestPackStatus:
    """PackStatus enum: 5 values with correct string representations."""

    def test_has_five_members(self):
        assert len(PackStatus) == 5

    def test_generating_value(self):
        assert PackStatus.GENERATING == "generating"
        assert PackStatus.GENERATING.value == "generating"

    def test_grounding_value(self):
        assert PackStatus.GROUNDING == "grounding"
        assert PackStatus.GROUNDING.value == "grounding"

    def test_ready_value(self):
        assert PackStatus.READY == "ready"
        assert PackStatus.READY.value == "ready"

    def test_ready_with_flags_value(self):
        assert PackStatus.READY_WITH_FLAGS == "ready_with_flags"
        assert PackStatus.READY_WITH_FLAGS.value == "ready_with_flags"

    def test_failed_value(self):
        assert PackStatus.FAILED == "failed"
        assert PackStatus.FAILED.value == "failed"

    def test_is_str_enum(self):
        """PackStatus members are usable as plain strings."""
        assert isinstance(PackStatus.GENERATING, str)


class TestGapHandlingStrategy:
    """GapHandlingStrategy enum: 3 values with correct string representations."""

    def test_has_three_members(self):
        assert len(GapHandlingStrategy) == 3

    def test_adjacent_experience_value(self):
        assert GapHandlingStrategy.ADJACENT_EXPERIENCE == "adjacent_experience"
        assert GapHandlingStrategy.ADJACENT_EXPERIENCE.value == "adjacent_experience"

    def test_transferable_skill_value(self):
        assert GapHandlingStrategy.TRANSFERABLE_SKILL == "transferable_skill"
        assert GapHandlingStrategy.TRANSFERABLE_SKILL.value == "transferable_skill"

    def test_learning_trajectory_value(self):
        assert GapHandlingStrategy.LEARNING_TRAJECTORY == "learning_trajectory"
        assert GapHandlingStrategy.LEARNING_TRAJECTORY.value == "learning_trajectory"

    def test_is_str_enum(self):
        """GapHandlingStrategy members are usable as plain strings."""
        assert isinstance(GapHandlingStrategy.ADJACENT_EXPERIENCE, str)


# ─── DATACLASS TESTS ─────────────────────────────────────────────────────────


class TestSTARTalkingPoint:
    """STAR_Talking_Point dataclass instantiation and defaults."""

    def test_valid_instantiation_all_fields(self):
        point = STAR_Talking_Point(
            competency="Project Management",
            question="Tell me about a time you managed a complex project",
            situation="Led a 12-person cross-functional team at Acme Corp",
            task="Deliver the platform migration within 6 months",
            action="Implemented agile ceremonies and daily standups",
            result="Delivered 2 weeks early with 98% uptime during cutover",
            source_asset_refs=["asset-001", "asset-002"],
            is_gap_handled=True,
            gap_note="Adjacent project coordination experience applies",
        )
        assert point.competency == "Project Management"
        assert point.question == "Tell me about a time you managed a complex project"
        assert point.situation == "Led a 12-person cross-functional team at Acme Corp"
        assert point.task == "Deliver the platform migration within 6 months"
        assert point.action == "Implemented agile ceremonies and daily standups"
        assert point.result == "Delivered 2 weeks early with 98% uptime during cutover"
        assert point.source_asset_refs == ["asset-001", "asset-002"]
        assert point.is_gap_handled is True
        assert point.gap_note == "Adjacent project coordination experience applies"

    def test_defaults_is_gap_handled_false(self):
        point = STAR_Talking_Point(
            competency="Python Development",
            question="Describe your Python experience",
            situation="Backend developer at StartupX",
            task="Build a high-throughput data pipeline",
            action="Designed async pipeline using asyncio and Redis",
            result="Processed 10M events/day with <100ms latency",
            source_asset_refs=["asset-010"],
        )
        assert point.is_gap_handled is False

    def test_defaults_gap_note_none(self):
        point = STAR_Talking_Point(
            competency="Python Development",
            question="Describe your Python experience",
            situation="Backend developer at StartupX",
            task="Build a high-throughput data pipeline",
            action="Designed async pipeline using asyncio and Redis",
            result="Processed 10M events/day with <100ms latency",
            source_asset_refs=["asset-010"],
        )
        assert point.gap_note is None


class TestInterviewPrepPack:
    """Interview_Prep_Pack dataclass instantiation and defaults."""

    def _make_star_point(self) -> STAR_Talking_Point:
        return STAR_Talking_Point(
            competency="Leadership",
            question="Tell me about leading a team",
            situation="Engineering lead at Corp",
            task="Scale team from 4 to 12",
            action="Structured hiring and onboarding",
            result="Team doubled velocity in 6 months",
            source_asset_refs=["asset-100"],
        )

    def test_valid_instantiation_all_required_fields(self):
        now = datetime.now(tz=timezone.utc)
        star_points = [self._make_star_point() for _ in range(5)]
        pack = Interview_Prep_Pack(
            id="pack-001",
            pipeline_record_id="rec-001",
            beneficiary_id="ben-001",
            opportunity_type_id="job_site",
            likely_questions=["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"],
            star_talking_points=star_points,
            company_briefing="A brief about the company.",
            questions_to_ask=["Ask1", "Ask2", "Ask3"],
            status=PackStatus.READY,
            created_at=now,
            updated_at=now,
        )
        assert pack.id == "pack-001"
        assert pack.pipeline_record_id == "rec-001"
        assert pack.beneficiary_id == "ben-001"
        assert pack.opportunity_type_id == "job_site"
        assert len(pack.likely_questions) == 8
        assert len(pack.star_talking_points) == 5
        assert pack.company_briefing == "A brief about the company."
        assert len(pack.questions_to_ask) == 3
        assert pack.status == PackStatus.READY

    def test_defaults_omission_notes_empty_list(self):
        now = datetime.now(tz=timezone.utc)
        pack = Interview_Prep_Pack(
            id="pack-002",
            pipeline_record_id="rec-002",
            beneficiary_id="ben-002",
            opportunity_type_id="company",
            likely_questions=["Q1"] * 10,
            star_talking_points=[self._make_star_point()] * 5,
            company_briefing="Briefing text.",
            questions_to_ask=["A1", "A2", "A3"],
            status=PackStatus.GENERATING,
            created_at=now,
            updated_at=now,
        )
        assert pack.omission_notes == []

    def test_defaults_grounding_flags_empty_list(self):
        now = datetime.now(tz=timezone.utc)
        pack = Interview_Prep_Pack(
            id="pack-003",
            pipeline_record_id="rec-003",
            beneficiary_id="ben-003",
            opportunity_type_id="job_site",
            likely_questions=["Q1"] * 8,
            star_talking_points=[self._make_star_point()] * 5,
            company_briefing="Briefing.",
            questions_to_ask=["A1", "A2", "A3"],
            status=PackStatus.GROUNDING,
            created_at=now,
            updated_at=now,
        )
        assert pack.grounding_flags == []

    def test_defaults_generation_duration_ms_zero(self):
        now = datetime.now(tz=timezone.utc)
        pack = Interview_Prep_Pack(
            id="pack-004",
            pipeline_record_id="rec-004",
            beneficiary_id="ben-004",
            opportunity_type_id="job_site",
            likely_questions=["Q1"] * 8,
            star_talking_points=[self._make_star_point()] * 5,
            company_briefing="Brief.",
            questions_to_ask=["A1", "A2", "A3"],
            status=PackStatus.READY,
            created_at=now,
            updated_at=now,
        )
        assert pack.generation_duration_ms == 0


class TestGenerationContext:
    """GenerationContext dataclass with optional None fields."""

    def test_valid_instantiation_with_all_fields(self):
        ctx = GenerationContext(
            opportunity_description="Senior Python developer needed",
            tailored_cv="My tailored CV content",
            tailored_cover_letter="My cover letter content",
            enrichment_record={"company": "Acme", "industry": "Tech"},
            intent_signals=[{"type": "hiring_surge"}],
            profile_assets={"asset-001": "Resume content"},
            star_examples=[{"competency": "leadership", "narrative": "Led team"}],
            opportunity_type_id="job_site",
            beneficiary_id="ben-001",
        )
        assert ctx.opportunity_description == "Senior Python developer needed"
        assert ctx.tailored_cv == "My tailored CV content"
        assert ctx.tailored_cover_letter == "My cover letter content"
        assert ctx.enrichment_record == {"company": "Acme", "industry": "Tech"}
        assert ctx.intent_signals == [{"type": "hiring_surge"}]
        assert ctx.profile_assets == {"asset-001": "Resume content"}
        assert ctx.star_examples == [{"competency": "leadership", "narrative": "Led team"}]
        assert ctx.opportunity_type_id == "job_site"
        assert ctx.beneficiary_id == "ben-001"

    def test_none_optional_fields(self):
        """tailored_cv, tailored_cover_letter, and star_examples can be None."""
        ctx = GenerationContext(
            opportunity_description="Data engineer role",
            tailored_cv=None,
            tailored_cover_letter=None,
            enrichment_record={"company": "BigCo"},
            intent_signals=[],
            profile_assets={"asset-010": "Profile content"},
            star_examples=None,
            opportunity_type_id="company",
            beneficiary_id="ben-002",
        )
        assert ctx.tailored_cv is None
        assert ctx.tailored_cover_letter is None
        assert ctx.star_examples is None


# ─── EXCEPTION CLASS TESTS ───────────────────────────────────────────────────


class TestInterviewPrepError:
    """InterviewPrepError base exception carries pipeline_record_id and retryable."""

    def test_stores_pipeline_record_id(self):
        err = InterviewPrepError(
            "Generation failed",
            pipeline_record_id="rec-500",
        )
        assert err.pipeline_record_id == "rec-500"

    def test_stores_retryable_default_true(self):
        err = InterviewPrepError(
            "Some error",
            pipeline_record_id="rec-501",
        )
        assert err.retryable is True

    def test_stores_retryable_explicit_false(self):
        err = InterviewPrepError(
            "Fatal error",
            pipeline_record_id="rec-502",
            retryable=False,
        )
        assert err.retryable is False

    def test_stores_message(self):
        err = InterviewPrepError(
            "Something went wrong",
            pipeline_record_id="rec-503",
        )
        assert err.message == "Something went wrong"

    def test_inherits_exception(self):
        err = InterviewPrepError(
            "error",
            pipeline_record_id="rec-504",
        )
        assert isinstance(err, Exception)

    def test_catchable_as_exception(self):
        with pytest.raises(InterviewPrepError):
            raise InterviewPrepError("fail", pipeline_record_id="rec-505")


class TestGenerationTimeoutError:
    """GenerationTimeoutError has timeout_seconds attribute."""

    def test_has_timeout_seconds_default(self):
        err = GenerationTimeoutError(
            pipeline_record_id="rec-600",
        )
        assert err.timeout_seconds == 90.0

    def test_has_timeout_seconds_custom(self):
        err = GenerationTimeoutError(
            pipeline_record_id="rec-601",
            timeout_seconds=45.0,
        )
        assert err.timeout_seconds == 45.0

    def test_inherits_interview_prep_error(self):
        err = GenerationTimeoutError(
            pipeline_record_id="rec-602",
        )
        assert isinstance(err, InterviewPrepError)
        assert isinstance(err, Exception)

    def test_retryable_by_default(self):
        err = GenerationTimeoutError(
            pipeline_record_id="rec-603",
        )
        assert err.retryable is True


class TestDeadlineExceededError:
    """DeadlineExceededError is not retryable by default."""

    def test_not_retryable_by_default(self):
        err = DeadlineExceededError(
            pipeline_record_id="rec-700",
        )
        assert err.retryable is False

    def test_has_deadline_seconds(self):
        err = DeadlineExceededError(
            pipeline_record_id="rec-701",
        )
        assert err.deadline_seconds == 120.0

    def test_inherits_interview_prep_error(self):
        err = DeadlineExceededError(
            pipeline_record_id="rec-702",
        )
        assert isinstance(err, InterviewPrepError)

    def test_carries_pipeline_record_id(self):
        err = DeadlineExceededError(
            pipeline_record_id="rec-703",
        )
        assert err.pipeline_record_id == "rec-703"


class TestPackValidationError:
    """PackValidationError carries validation_errors list."""

    def test_carries_validation_errors(self):
        err = PackValidationError(
            pipeline_record_id="rec-800",
            validation_errors=["Too few questions", "Briefing too long"],
        )
        assert err.validation_errors == ["Too few questions", "Briefing too long"]

    def test_validation_errors_empty_list(self):
        err = PackValidationError(
            pipeline_record_id="rec-801",
            validation_errors=[],
        )
        assert err.validation_errors == []

    def test_inherits_interview_prep_error(self):
        err = PackValidationError(
            pipeline_record_id="rec-802",
            validation_errors=["error"],
        )
        assert isinstance(err, InterviewPrepError)

    def test_retryable_by_default(self):
        err = PackValidationError(
            pipeline_record_id="rec-803",
            validation_errors=["some issue"],
        )
        assert err.retryable is True


class TestContextAssemblyError:
    """ContextAssemblyError carries missing_inputs list and is not retryable."""

    def test_carries_missing_inputs(self):
        err = ContextAssemblyError(
            pipeline_record_id="rec-900",
            missing_inputs=["opportunity_description", "profile_assets"],
        )
        assert err.missing_inputs == ["opportunity_description", "profile_assets"]

    def test_missing_inputs_defaults_to_empty(self):
        err = ContextAssemblyError(
            pipeline_record_id="rec-901",
        )
        assert err.missing_inputs == []

    def test_not_retryable_by_default(self):
        err = ContextAssemblyError(
            pipeline_record_id="rec-902",
        )
        assert err.retryable is False

    def test_inherits_interview_prep_error(self):
        err = ContextAssemblyError(
            pipeline_record_id="rec-903",
        )
        assert isinstance(err, InterviewPrepError)

    def test_carries_pipeline_record_id(self):
        err = ContextAssemblyError(
            pipeline_record_id="rec-904",
            missing_inputs=["enrichment_record"],
        )
        assert err.pipeline_record_id == "rec-904"
