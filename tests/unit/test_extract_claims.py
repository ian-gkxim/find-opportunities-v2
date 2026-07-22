"""Unit tests for GroundingVerifier.extract_claims().

Validates LLM dispatch, retry logic (3 total attempts with exponential backoff),
JSON parsing into Claim objects, source_span validation, and error handling.

Requirements: 1.1, 1.2, 1.3, 1.4
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import APITimeoutError
from app.core.grounding_errors import ExtractionError
from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingVerifier,
)


# ─── FIXTURES ─────────────────────────────────────────────────────────────────

SAMPLE_MATERIAL = (
    "John has 10 years of experience in Python development. "
    "He led a cloud migration project at Acme Corp that reduced costs by 40%."
)


def _make_valid_claims_response() -> list[dict]:
    """Build a valid LLM response matching the extraction schema."""
    return [
        {
            "claim_text": "10 years of experience in Python development",
            "category": "experience_duration",
            "source_span": "10 years of experience in Python development",
            "source_span_start": 9,
            "source_span_end": 53,
            "is_prospect_side": False,
        },
        {
            "claim_text": "Led a cloud migration project at Acme Corp",
            "category": "achievement_outcome",
            "source_span": "led a cloud migration project at Acme Corp",
            "source_span_start": 55,
            "source_span_end": 98,
            "is_prospect_side": False,
        },
        {
            "claim_text": "Reduced costs by 40%",
            "category": "quantified_metric",
            "source_span": "reduced costs by 40%",
            "source_span_start": 99,
            "source_span_end": 119,
            "is_prospect_side": False,
        },
    ]


@pytest.fixture
def mock_llm_router():
    """Create a mock LLM router with dispatch_extraction method."""
    router = MagicMock()
    router.dispatch_extraction = AsyncMock(return_value=_make_valid_claims_response())
    return router


@pytest.fixture
def verifier(mock_llm_router):
    """Create a GroundingVerifier instance with mocked dependencies."""
    return GroundingVerifier(
        llm_router=mock_llm_router,
        schema_registry=MagicMock(),
        db_repo=MagicMock(),
        personalization_engine=MagicMock(),
    )


# ─── HAPPY PATH TESTS ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_claims_returns_claim_objects(verifier, mock_llm_router):
    """Extract claims returns properly constructed Claim objects."""
    claims = await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    assert len(claims) == 3
    assert all(isinstance(c, Claim) for c in claims)
    assert all(c.material_id == "mat-001" for c in claims)
    assert all(c.grounding_status is None for c in claims)


@pytest.mark.asyncio
async def test_extract_claims_sets_correct_categories(verifier):
    """Claims have the correct ClaimCategory enum values."""
    claims = await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    categories = [c.category for c in claims]
    assert ClaimCategory.EXPERIENCE_DURATION in categories
    assert ClaimCategory.ACHIEVEMENT_OUTCOME in categories
    assert ClaimCategory.QUANTIFIED_METRIC in categories


@pytest.mark.asyncio
async def test_extract_claims_calls_dispatch_with_correct_params(verifier, mock_llm_router):
    """dispatch_extraction is called with the formatted prompt and 60s timeout."""
    await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    mock_llm_router.dispatch_extraction.assert_called_once()
    call_args = mock_llm_router.dispatch_extraction.call_args
    assert call_args.kwargs.get("timeout") == 60.0
    # Prompt should contain the material text
    prompt_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("prompt", "")
    assert SAMPLE_MATERIAL in prompt_arg


@pytest.mark.asyncio
async def test_extract_claims_assigns_unique_uuids(verifier):
    """Each claim receives a unique UUID."""
    claims = await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    ids = [c.id for c in claims]
    assert len(set(ids)) == len(ids)  # all unique


# ─── RETRY LOGIC TESTS ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.core.grounding_verifier.asyncio.sleep", new_callable=AsyncMock)
async def test_retries_on_json_decode_error(mock_sleep, mock_llm_router):
    """Retries on json.JSONDecodeError up to MAX_RETRIES and succeeds."""
    mock_llm_router.dispatch_extraction = AsyncMock(
        side_effect=[
            json.JSONDecodeError("Expecting value", "", 0),
            _make_valid_claims_response(),
        ]
    )
    verifier = GroundingVerifier(
        llm_router=mock_llm_router,
        schema_registry=MagicMock(),
        db_repo=MagicMock(),
        personalization_engine=MagicMock(),
    )

    claims = await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    assert len(claims) == 3
    assert mock_llm_router.dispatch_extraction.call_count == 2
    mock_sleep.assert_called_once_with(1)  # first backoff = 2^0 = 1


@pytest.mark.asyncio
@patch("app.core.grounding_verifier.asyncio.sleep", new_callable=AsyncMock)
async def test_retries_on_api_timeout_error(mock_sleep, mock_llm_router):
    """Retries on APITimeoutError and succeeds on third attempt."""
    mock_llm_router.dispatch_extraction = AsyncMock(
        side_effect=[
            APITimeoutError("timeout", service="llm", timeout_seconds=60.0),
            APITimeoutError("timeout", service="llm", timeout_seconds=60.0),
            _make_valid_claims_response(),
        ]
    )
    verifier = GroundingVerifier(
        llm_router=mock_llm_router,
        schema_registry=MagicMock(),
        db_repo=MagicMock(),
        personalization_engine=MagicMock(),
    )

    claims = await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    assert len(claims) == 3
    assert mock_llm_router.dispatch_extraction.call_count == 3
    # Backoff calls: 2^0=1, 2^1=2
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1)
    mock_sleep.assert_any_call(2)


@pytest.mark.asyncio
@patch("app.core.grounding_verifier.asyncio.sleep", new_callable=AsyncMock)
async def test_raises_extraction_error_after_all_retries_exhausted(mock_sleep, mock_llm_router):
    """Raises ExtractionError after 3 failed attempts."""
    mock_llm_router.dispatch_extraction = AsyncMock(
        side_effect=json.JSONDecodeError("Expecting value", "", 0)
    )
    verifier = GroundingVerifier(
        llm_router=mock_llm_router,
        schema_registry=MagicMock(),
        db_repo=MagicMock(),
        personalization_engine=MagicMock(),
    )

    with pytest.raises(ExtractionError) as exc_info:
        await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    assert exc_info.value.material_id == "mat-001"
    assert exc_info.value.attempts == 3
    assert mock_llm_router.dispatch_extraction.call_count == 3


@pytest.mark.asyncio
@patch("app.core.grounding_verifier.asyncio.sleep", new_callable=AsyncMock)
async def test_mixed_errors_retry_then_fail(mock_sleep, mock_llm_router):
    """Mix of timeout and parse errors exhausts retries correctly."""
    mock_llm_router.dispatch_extraction = AsyncMock(
        side_effect=[
            APITimeoutError("timeout", service="llm", timeout_seconds=60.0),
            json.JSONDecodeError("bad", "", 0),
            APITimeoutError("timeout", service="llm", timeout_seconds=60.0),
        ]
    )
    verifier = GroundingVerifier(
        llm_router=mock_llm_router,
        schema_registry=MagicMock(),
        db_repo=MagicMock(),
        personalization_engine=MagicMock(),
    )

    with pytest.raises(ExtractionError) as exc_info:
        await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    assert exc_info.value.attempts == 3


# ─── SOURCE SPAN VALIDATION TESTS ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skips_claims_with_invalid_source_span(mock_llm_router):
    """Claims with source_span not in material_text are skipped."""
    response = [
        {
            "claim_text": "Valid claim",
            "category": "skill_technology",
            "source_span": "10 years of experience in Python development",
            "source_span_start": 9,
            "source_span_end": 53,
            "is_prospect_side": False,
        },
        {
            "claim_text": "Invalid span claim",
            "category": "achievement_outcome",
            "source_span": "this text does not exist in the material",
            "source_span_start": 0,
            "source_span_end": 40,
            "is_prospect_side": False,
        },
    ]
    mock_llm_router.dispatch_extraction = AsyncMock(return_value=response)
    verifier = GroundingVerifier(
        llm_router=mock_llm_router,
        schema_registry=MagicMock(),
        db_repo=MagicMock(),
        personalization_engine=MagicMock(),
    )

    claims = await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    assert len(claims) == 1
    assert claims[0].claim_text == "Valid claim"


@pytest.mark.asyncio
async def test_skips_claims_with_invalid_category(mock_llm_router):
    """Claims with unrecognized category values are skipped."""
    response = [
        {
            "claim_text": "Valid claim",
            "category": "skill_technology",
            "source_span": "Python development",
            "source_span_start": 0,
            "source_span_end": 18,
            "is_prospect_side": False,
        },
        {
            "claim_text": "Bad category",
            "category": "nonexistent_category",
            "source_span": "cloud migration",
            "source_span_start": 0,
            "source_span_end": 15,
            "is_prospect_side": False,
        },
    ]
    mock_llm_router.dispatch_extraction = AsyncMock(return_value=response)
    verifier = GroundingVerifier(
        llm_router=mock_llm_router,
        schema_registry=MagicMock(),
        db_repo=MagicMock(),
        personalization_engine=MagicMock(),
    )

    claims = await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    assert len(claims) == 1
    assert claims[0].category == ClaimCategory.SKILL_TECHNOLOGY


@pytest.mark.asyncio
async def test_handles_dict_response_with_claims_key(mock_llm_router):
    """Handles LLM response wrapped in a dict with 'claims' key."""
    mock_llm_router.dispatch_extraction = AsyncMock(
        return_value={"claims": _make_valid_claims_response()}
    )
    verifier = GroundingVerifier(
        llm_router=mock_llm_router,
        schema_registry=MagicMock(),
        db_repo=MagicMock(),
        personalization_engine=MagicMock(),
    )

    claims = await verifier.extract_claims(SAMPLE_MATERIAL, "mat-001")

    assert len(claims) == 3
