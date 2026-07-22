"""Unit tests for InterviewPrepService._generate_via_llm() method.

Tests prompt building, LLM dispatch with timeout, JSON parsing, pack construction,
structural validation, and retry logic.

Requirements: 1.1, 2.1
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.interview_prep_models import (
    GenerationContext,
    Interview_Prep_Pack,
    PackStatus,
    STAR_Talking_Point,
    InterviewPrepError,
    GenerationTimeoutError,
    PackValidationError,
)
from app.core.interview_prep_service import InterviewPrepService


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


def _make_valid_llm_response() -> str:
    """Return a valid JSON response matching the expected pack structure."""
    return json.dumps({
        "likely_questions": [
            f"Question {i}" for i in range(10)
        ],
        "star_talking_points": [
            {
                "competency": f"Competency {i}",
                "question": f"Tell me about {i}",
                "situation": f"At company X, situation {i}",
                "task": f"I needed to do task {i}",
                "action": f"I did action {i}",
                "result": f"Result was outcome {i}",
                "source_asset_refs": ["resume"],
                "is_gap_handled": False,
                "gap_note": None,
            }
            for i in range(5)
        ],
        "company_briefing": "A mid-size tech company focused on SaaS products.",
        "questions_to_ask": [
            "What's the team structure?",
            "How do you handle deployments?",
            "What's the roadmap for next quarter?",
        ],
    })


def _make_context() -> GenerationContext:
    """Return a valid GenerationContext for testing."""
    return GenerationContext(
        opportunity_description="Senior Python developer role at TechCo.",
        tailored_cv="My tailored CV content.",
        tailored_cover_letter="My tailored cover letter.",
        enrichment_record={
            "industry": "Technology",
            "employee_count": "500",
            "tech_stack": ["Python", "PostgreSQL", "Redis"],
            "headquarters": "London, UK",
        },
        intent_signals=[
            {"type": "hiring_surge"},
            {"type": "expansion"},
        ],
        profile_assets={
            "resume": "10 years Python experience...",
            "consultant_profiles": "Led teams of 5+ engineers...",
        },
        star_examples=None,
        opportunity_type_id="job_site",
        beneficiary_id="ben-123",
    )


def _make_service(llm_response=None) -> InterviewPrepService:
    """Create an InterviewPrepService with mocked dependencies."""
    llm_router = MagicMock()
    if llm_response is not None:
        llm_router.generate = AsyncMock(return_value=llm_response)
    else:
        llm_router.generate = AsyncMock(return_value=_make_valid_llm_response())

    grounding_verifier = MagicMock()
    schema_registry = MagicMock()
    db_repo = MagicMock()
    event_publisher = MagicMock()

    return InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )


# ─── TESTS: SUCCESSFUL GENERATION ────────────────────────────────────────────


class TestGenerateViaLlmSuccess:
    """Tests for successful _generate_via_llm execution."""

    @pytest.mark.asyncio
    async def test_returns_interview_prep_pack(self):
        service = _make_service()
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert isinstance(result, Interview_Prep_Pack)

    @pytest.mark.asyncio
    async def test_pack_has_correct_beneficiary_id(self):
        service = _make_service()
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert result.beneficiary_id == "ben-123"

    @pytest.mark.asyncio
    async def test_pack_has_correct_opportunity_type_id(self):
        service = _make_service()
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert result.opportunity_type_id == "job_site"

    @pytest.mark.asyncio
    async def test_pack_has_generating_status(self):
        service = _make_service()
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert result.status == PackStatus.GENERATING

    @pytest.mark.asyncio
    async def test_pack_has_correct_likely_questions_count(self):
        service = _make_service()
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert len(result.likely_questions) == 10

    @pytest.mark.asyncio
    async def test_pack_has_correct_star_count(self):
        service = _make_service()
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert len(result.star_talking_points) == 5

    @pytest.mark.asyncio
    async def test_pack_has_correct_questions_to_ask_count(self):
        service = _make_service()
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert len(result.questions_to_ask) == 3

    @pytest.mark.asyncio
    async def test_star_points_have_correct_structure(self):
        service = _make_service()
        context = _make_context()
        result = await service._generate_via_llm(context)
        for point in result.star_talking_points:
            assert isinstance(point, STAR_Talking_Point)
            assert point.competency
            assert point.question
            assert point.situation
            assert point.source_asset_refs

    @pytest.mark.asyncio
    async def test_llm_called_with_generation_evaluation_type(self):
        service = _make_service()
        context = _make_context()
        await service._generate_via_llm(context)
        call_kwargs = service._llm.generate.call_args[1]
        assert call_kwargs["evaluation_type"] == "generation"

    @pytest.mark.asyncio
    async def test_prompt_contains_opportunity_description(self):
        service = _make_service()
        context = _make_context()
        await service._generate_via_llm(context)
        call_kwargs = service._llm.generate.call_args[1]
        assert "Senior Python developer role at TechCo" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_profile_assets(self):
        service = _make_service()
        context = _make_context()
        await service._generate_via_llm(context)
        call_kwargs = service._llm.generate.call_args[1]
        assert "10 years Python experience" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_submitted_cv(self):
        service = _make_service()
        context = _make_context()
        await service._generate_via_llm(context)
        call_kwargs = service._llm.generate.call_args[1]
        assert "My tailored CV content" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_enrichment_data(self):
        service = _make_service()
        context = _make_context()
        await service._generate_via_llm(context)
        call_kwargs = service._llm.generate.call_args[1]
        prompt = call_kwargs["prompt"]
        assert "Technology" in prompt
        assert "500" in prompt
        assert "Python" in prompt
        assert "London, UK" in prompt


# ─── TESTS: TIMEOUT AND RETRY ────────────────────────────────────────────────


class TestGenerateViaLlmTimeout:
    """Tests for timeout and retry behavior."""

    @pytest.mark.asyncio
    async def test_raises_generation_timeout_after_retries_exhausted(self):
        service = _make_service()
        # Make generate always timeout
        service._llm.generate = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        context = _make_context()
        with pytest.raises(GenerationTimeoutError):
            await service._generate_via_llm(context)

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self):
        service = _make_service()
        # First call times out, second succeeds
        service._llm.generate = AsyncMock(
            side_effect=[
                asyncio.TimeoutError(),
                _make_valid_llm_response(),
            ]
        )
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert isinstance(result, Interview_Prep_Pack)
        assert service._llm.generate.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_llm_error(self):
        service = _make_service()
        # First call errors, second succeeds
        service._llm.generate = AsyncMock(
            side_effect=[
                RuntimeError("LLM unavailable"),
                _make_valid_llm_response(),
            ]
        )
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert isinstance(result, Interview_Prep_Pack)
        assert service._llm.generate.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_interview_prep_error_after_max_retries_on_llm_error(self):
        service = _make_service()
        service._llm.generate = AsyncMock(
            side_effect=RuntimeError("LLM unavailable")
        )
        context = _make_context()
        with pytest.raises(InterviewPrepError, match="LLM generation failed"):
            await service._generate_via_llm(context)
        # MAX_RETRIES + 1 attempts total
        assert service._llm.generate.call_count == 3


# ─── TESTS: JSON PARSING ─────────────────────────────────────────────────────


class TestGenerateViaLlmParsing:
    """Tests for JSON parsing and error handling."""

    @pytest.mark.asyncio
    async def test_raises_on_invalid_json(self):
        service = _make_service(llm_response="not valid json {{{")
        context = _make_context()
        with pytest.raises(InterviewPrepError, match="Failed to parse LLM response"):
            await service._generate_via_llm(context)

    @pytest.mark.asyncio
    async def test_handles_dict_response_with_content_key(self):
        valid_json = _make_valid_llm_response()
        service = _make_service(llm_response={"content": valid_json})
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert isinstance(result, Interview_Prep_Pack)

    @pytest.mark.asyncio
    async def test_handles_dict_response_with_text_key(self):
        valid_json = _make_valid_llm_response()
        service = _make_service(llm_response={"text": valid_json})
        context = _make_context()
        result = await service._generate_via_llm(context)
        assert isinstance(result, Interview_Prep_Pack)


# ─── TESTS: PACK VALIDATION ──────────────────────────────────────────────────


class TestGenerateViaLlmValidation:
    """Tests for pack structural validation within _generate_via_llm."""

    @pytest.mark.asyncio
    async def test_raises_pack_validation_error_on_too_few_questions(self):
        bad_response = json.dumps({
            "likely_questions": ["Q1", "Q2"],  # fewer than 8
            "star_talking_points": [
                {
                    "competency": f"C{i}",
                    "question": f"Q{i}",
                    "situation": f"S{i}",
                    "task": f"T{i}",
                    "action": f"A{i}",
                    "result": f"R{i}",
                    "source_asset_refs": ["resume"],
                    "is_gap_handled": False,
                    "gap_note": None,
                }
                for i in range(5)
            ],
            "company_briefing": "Brief.",
            "questions_to_ask": ["Q1", "Q2", "Q3"],
        })
        service = _make_service(llm_response=bad_response)
        context = _make_context()
        with pytest.raises(PackValidationError):
            await service._generate_via_llm(context)

    @pytest.mark.asyncio
    async def test_raises_pack_validation_error_on_wrong_star_count(self):
        bad_response = json.dumps({
            "likely_questions": [f"Q{i}" for i in range(10)],
            "star_talking_points": [
                {
                    "competency": "C1",
                    "question": "Q1",
                    "situation": "S1",
                    "task": "T1",
                    "action": "A1",
                    "result": "R1",
                    "source_asset_refs": ["resume"],
                    "is_gap_handled": False,
                    "gap_note": None,
                }
            ],  # only 1 instead of 5
            "company_briefing": "Brief.",
            "questions_to_ask": ["Q1", "Q2", "Q3"],
        })
        service = _make_service(llm_response=bad_response)
        context = _make_context()
        with pytest.raises(PackValidationError):
            await service._generate_via_llm(context)


# ─── TESTS: CONTEXT WITHOUT OPTIONAL FIELDS ──────────────────────────────────


class TestGenerateViaLlmContextVariations:
    """Tests for handling different context configurations."""

    @pytest.mark.asyncio
    async def test_works_without_submitted_cv(self):
        service = _make_service()
        context = _make_context()
        context.tailored_cv = None
        result = await service._generate_via_llm(context)
        assert isinstance(result, Interview_Prep_Pack)

    @pytest.mark.asyncio
    async def test_works_without_submitted_cover_letter(self):
        service = _make_service()
        context = _make_context()
        context.tailored_cover_letter = None
        result = await service._generate_via_llm(context)
        assert isinstance(result, Interview_Prep_Pack)

    @pytest.mark.asyncio
    async def test_works_with_empty_intent_signals(self):
        service = _make_service()
        context = _make_context()
        context.intent_signals = []
        await service._generate_via_llm(context)
        call_kwargs = service._llm.generate.call_args[1]
        assert "None identified" in call_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_works_with_object_enrichment_record(self):
        """Test that enrichment_record as an object (not dict) works."""
        service = _make_service()
        context = _make_context()

        # Replace dict with an object with attributes
        enrichment_obj = MagicMock()
        enrichment_obj.industry = "Finance"
        enrichment_obj.employee_count = "1000"
        enrichment_obj.tech_stack = ["Java", "Kafka"]
        enrichment_obj.headquarters = "New York, US"
        context.enrichment_record = enrichment_obj

        result = await service._generate_via_llm(context)
        assert isinstance(result, Interview_Prep_Pack)
        call_kwargs = service._llm.generate.call_args[1]
        assert "Finance" in call_kwargs["prompt"]
