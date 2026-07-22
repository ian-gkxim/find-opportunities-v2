"""Unit tests for ReviewService._dispatch_critique() and _parse_critique_response().

Validates retry logic (3 total attempts), JSON parsing into CritiqueResponse,
parse failure handling, and proper error raising after all retries exhausted.

Requirements: 1.1, 1.5
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.review_models import (
    CritiqueCategory,
    CritiqueParseError,
    CritiqueResponse,
    EditReason,
    ReviewLLMError,
    StructuredEdit,
)
from app.core.review_service import ReviewService


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


def _make_valid_raw_response() -> dict:
    """Build a valid raw JSON response matching the CritiqueResponse schema."""
    return {
        "structured_edits": [
            {
                "target_material_id": "mat-001",
                "old_string": "generic phrasing",
                "new_string": "specific company-focused phrasing",
                "reason": "keyword_match",
                "category": "missed_keywords",
            }
        ],
        "narrative_findings": {
            "missed_keywords": [
                {
                    "description": "Missing keyword: cloud migration",
                    "flagged_passage": "we provide services",
                }
            ],
            "company_angles": [],
            "reframing": [],
            "tone_style": [],
        },
    }


def _make_service(llm_mock: AsyncMock | None = None) -> ReviewService:
    """Create a ReviewService instance with mocked dependencies."""
    llm = llm_mock or AsyncMock()
    schema = MagicMock()
    db = MagicMock()
    personalization = MagicMock()
    return ReviewService(
        llm_router=llm,
        schema_registry=schema,
        review_repository=db,
        personalization_engine=personalization,
    )


# ─── _parse_critique_response TESTS ──────────────────────────────────────────


class TestParseCritiqueResponse:
    """Tests for _parse_critique_response helper method."""

    def test_parses_valid_response(self):
        service = _make_service()
        raw = _make_valid_raw_response()

        result = service._parse_critique_response(raw, material_id="mat-001")

        assert isinstance(result, CritiqueResponse)
        assert len(result.structured_edits) == 1
        assert result.structured_edits[0].old_string == "generic phrasing"
        assert result.structured_edits[0].new_string == "specific company-focused phrasing"
        assert result.structured_edits[0].reason == EditReason.KEYWORD_MATCH
        assert result.structured_edits[0].category == CritiqueCategory.MISSED_KEYWORDS

    def test_parses_narrative_findings_all_categories(self):
        service = _make_service()
        raw = _make_valid_raw_response()

        result = service._parse_critique_response(raw, material_id="mat-001")

        # All four categories present
        for cat in CritiqueCategory:
            assert cat in result.narrative_findings

        # missed_keywords has one finding
        assert len(result.narrative_findings[CritiqueCategory.MISSED_KEYWORDS]) == 1
        finding = result.narrative_findings[CritiqueCategory.MISSED_KEYWORDS][0]
        assert finding.category == CritiqueCategory.MISSED_KEYWORDS
        assert finding.description == "Missing keyword: cloud migration"
        assert finding.flagged_passage == "we provide services"

    def test_parses_empty_edits_and_findings(self):
        service = _make_service()
        raw = {
            "structured_edits": [],
            "narrative_findings": {
                "missed_keywords": [],
                "company_angles": [],
                "reframing": [],
                "tone_style": [],
            },
        }

        result = service._parse_critique_response(raw, material_id="mat-001")

        assert result.structured_edits == []
        for cat in CritiqueCategory:
            assert result.narrative_findings[cat] == []

    def test_raises_on_missing_structured_edits(self):
        service = _make_service()
        raw = {
            "narrative_findings": {
                "missed_keywords": [],
                "company_angles": [],
                "reframing": [],
                "tone_style": [],
            }
        }

        with pytest.raises(CritiqueParseError, match="structured_edits"):
            service._parse_critique_response(raw, material_id="mat-001")

    def test_raises_on_invalid_structured_edits_type(self):
        service = _make_service()
        raw = {
            "structured_edits": "not a list",
            "narrative_findings": {
                "missed_keywords": [],
                "company_angles": [],
                "reframing": [],
                "tone_style": [],
            },
        }

        with pytest.raises(CritiqueParseError, match="structured_edits"):
            service._parse_critique_response(raw, material_id="mat-001")

    def test_raises_on_missing_narrative_findings(self):
        service = _make_service()
        raw = {"structured_edits": []}

        with pytest.raises(CritiqueParseError, match="narrative_findings"):
            service._parse_critique_response(raw, material_id="mat-001")

    def test_raises_on_invalid_narrative_findings_type(self):
        service = _make_service()
        raw = {
            "structured_edits": [],
            "narrative_findings": "not a dict",
        }

        with pytest.raises(CritiqueParseError, match="narrative_findings"):
            service._parse_critique_response(raw, material_id="mat-001")

    def test_raises_on_missing_category_keys(self):
        service = _make_service()
        raw = {
            "structured_edits": [],
            "narrative_findings": {
                "missed_keywords": [],
                "company_angles": [],
                # Missing reframing and tone_style
            },
        }

        with pytest.raises(CritiqueParseError, match="missing required categories"):
            service._parse_critique_response(raw, material_id="mat-001")

    def test_raises_on_invalid_edit_reason(self):
        service = _make_service()
        raw = {
            "structured_edits": [
                {
                    "target_material_id": "mat-001",
                    "old_string": "text",
                    "new_string": "new text",
                    "reason": "invalid_reason",
                    "category": "missed_keywords",
                }
            ],
            "narrative_findings": {
                "missed_keywords": [],
                "company_angles": [],
                "reframing": [],
                "tone_style": [],
            },
        }

        with pytest.raises(CritiqueParseError, match="Failed to parse"):
            service._parse_critique_response(raw, material_id="mat-001")

    def test_raises_on_missing_edit_field(self):
        service = _make_service()
        raw = {
            "structured_edits": [
                {
                    "target_material_id": "mat-001",
                    "old_string": "text",
                    # Missing new_string, reason, category
                }
            ],
            "narrative_findings": {
                "missed_keywords": [],
                "company_angles": [],
                "reframing": [],
                "tone_style": [],
            },
        }

        with pytest.raises(CritiqueParseError, match="Failed to parse"):
            service._parse_critique_response(raw, material_id="mat-001")

    def test_narrative_finding_with_null_flagged_passage(self):
        service = _make_service()
        raw = {
            "structured_edits": [],
            "narrative_findings": {
                "missed_keywords": [
                    {
                        "description": "Missing keyword about omission",
                        "flagged_passage": None,
                    }
                ],
                "company_angles": [],
                "reframing": [],
                "tone_style": [],
            },
        }

        result = service._parse_critique_response(raw, material_id="mat-001")

        finding = result.narrative_findings[CritiqueCategory.MISSED_KEYWORDS][0]
        assert finding.flagged_passage is None

    def test_material_id_propagated_to_error(self):
        service = _make_service()
        raw = {"structured_edits": "bad"}

        with pytest.raises(CritiqueParseError) as exc_info:
            service._parse_critique_response(raw, material_id="mat-xyz")

        assert exc_info.value.material_id == "mat-xyz"


# ─── _dispatch_critique TESTS ────────────────────────────────────────────────


class TestDispatchCritique:
    """Tests for _dispatch_critique retry logic and error handling."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        llm_mock = AsyncMock()
        llm_mock.dispatch_critique = AsyncMock(return_value=_make_valid_raw_response())
        service = _make_service(llm_mock)

        result = await service._dispatch_critique(
            material_text="Some draft text",
            opportunity_description="Senior Dev role",
            enrichment={},
            beneficiary={},
            categories=list(CritiqueCategory),
            material_id="mat-001",
        )

        assert isinstance(result, CritiqueResponse)
        assert llm_mock.dispatch_critique.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_timeout_then_succeeds(self):
        """LLM times out on first call, succeeds on second."""
        llm_mock = AsyncMock()
        llm_mock.dispatch_critique = AsyncMock(
            side_effect=[
                TimeoutError("LLM timeout"),
                _make_valid_raw_response(),
            ]
        )
        service = _make_service(llm_mock)

        result = await service._dispatch_critique(
            material_text="Draft",
            opportunity_description="Role",
            enrichment={},
            beneficiary={},
            categories=list(CritiqueCategory),
            material_id="mat-001",
        )

        assert isinstance(result, CritiqueResponse)
        assert llm_mock.dispatch_critique.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_parse_failure_then_succeeds(self):
        """LLM returns malformed JSON on first call, valid on second."""
        llm_mock = AsyncMock()
        llm_mock.dispatch_critique = AsyncMock(
            side_effect=[
                {"bad": "response"},  # Missing required fields
                _make_valid_raw_response(),
            ]
        )
        service = _make_service(llm_mock)

        result = await service._dispatch_critique(
            material_text="Draft",
            opportunity_description="Role",
            enrichment={},
            beneficiary={},
            categories=list(CritiqueCategory),
            material_id="mat-001",
        )

        assert isinstance(result, CritiqueResponse)
        assert llm_mock.dispatch_critique.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self):
        """After 3 total attempts (1 + 2 retries), raises ReviewLLMError."""
        llm_mock = AsyncMock()
        llm_mock.dispatch_critique = AsyncMock(
            side_effect=TimeoutError("LLM timeout")
        )
        service = _make_service(llm_mock)

        with pytest.raises(ReviewLLMError) as exc_info:
            await service._dispatch_critique(
                material_text="Draft",
                opportunity_description="Role",
                enrichment={},
                beneficiary={},
                categories=list(CritiqueCategory),
                material_id="mat-fail",
            )

        assert exc_info.value.material_id == "mat-fail"
        assert exc_info.value.attempts == 3
        assert llm_mock.dispatch_critique.call_count == 3

    @pytest.mark.asyncio
    async def test_parse_failures_count_toward_retry_limit(self):
        """All 3 attempts return unparseable responses → raises ReviewLLMError."""
        llm_mock = AsyncMock()
        # Return responses that will fail parsing (missing categories)
        bad_response = {
            "structured_edits": [],
            "narrative_findings": {"missed_keywords": []},  # Missing 3 categories
        }
        llm_mock.dispatch_critique = AsyncMock(return_value=bad_response)
        service = _make_service(llm_mock)

        with pytest.raises(ReviewLLMError) as exc_info:
            await service._dispatch_critique(
                material_text="Draft",
                opportunity_description="Role",
                enrichment={},
                beneficiary={},
                categories=list(CritiqueCategory),
                material_id="mat-parse-fail",
            )

        assert exc_info.value.attempts == 3
        assert llm_mock.dispatch_critique.call_count == 3

    @pytest.mark.asyncio
    async def test_mixed_errors_exhaust_retries(self):
        """Mix of timeout and parse failure — all count toward limit."""
        llm_mock = AsyncMock()
        llm_mock.dispatch_critique = AsyncMock(
            side_effect=[
                TimeoutError("timeout"),
                {"structured_edits": "not_a_list"},  # Parse failure
                RuntimeError("API error"),
            ]
        )
        service = _make_service(llm_mock)

        with pytest.raises(ReviewLLMError) as exc_info:
            await service._dispatch_critique(
                material_text="Draft",
                opportunity_description="Role",
                enrichment={},
                beneficiary={},
                categories=list(CritiqueCategory),
                material_id="mat-mixed",
            )

        assert exc_info.value.attempts == 3
        assert llm_mock.dispatch_critique.call_count == 3

    @pytest.mark.asyncio
    async def test_success_on_third_attempt(self):
        """Fails twice, succeeds on third (final) attempt."""
        llm_mock = AsyncMock()
        llm_mock.dispatch_critique = AsyncMock(
            side_effect=[
                TimeoutError("timeout"),
                RuntimeError("API error"),
                _make_valid_raw_response(),
            ]
        )
        service = _make_service(llm_mock)

        result = await service._dispatch_critique(
            material_text="Draft",
            opportunity_description="Role",
            enrichment={},
            beneficiary={},
            categories=list(CritiqueCategory),
            material_id="mat-001",
        )

        assert isinstance(result, CritiqueResponse)
        assert llm_mock.dispatch_critique.call_count == 3

    @pytest.mark.asyncio
    async def test_timeout_parameter_passed_to_llm(self):
        """Verifies the 60-second timeout is passed to dispatch_critique."""
        llm_mock = AsyncMock()
        llm_mock.dispatch_critique = AsyncMock(return_value=_make_valid_raw_response())
        service = _make_service(llm_mock)

        await service._dispatch_critique(
            material_text="Draft",
            opportunity_description="Role",
            enrichment={},
            beneficiary={},
            categories=list(CritiqueCategory),
            material_id="mat-001",
        )

        call_kwargs = llm_mock.dispatch_critique.call_args
        assert call_kwargs[1]["timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_error_message_contains_last_error(self):
        """The raised ReviewLLMError message references the last error."""
        llm_mock = AsyncMock()
        llm_mock.dispatch_critique = AsyncMock(
            side_effect=ValueError("specific error message")
        )
        service = _make_service(llm_mock)

        with pytest.raises(ReviewLLMError) as exc_info:
            await service._dispatch_critique(
                material_text="Draft",
                opportunity_description="Role",
                enrichment={},
                beneficiary={},
                categories=list(CritiqueCategory),
                material_id="mat-001",
            )

        assert "specific error message" in exc_info.value.message
        assert "3 attempts" in exc_info.value.message
