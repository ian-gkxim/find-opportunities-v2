"""Integration tests for the Review Critique Loop pipeline.

Tests end-to-end flow through ReviewPipelineStage → ReviewService with
mocked LLM_Router, SchemaRegistry, and ReviewRepository.

Requirements: 1.1, 1.5, 3.3, 3.4, 3.5
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.review_models import (
    CritiqueCategory,
    DraftMaterial,
    ReasoningLog,
    ReviewResult,
    ReviewStatus,
)
from app.core.review_service import ReviewService
from app.core.review_pipeline_stage import ReviewPipelineStage


# ─── FIXTURES / HELPERS ───────────────────────────────────────────────────────


def _make_valid_critique_response_dict():
    """Return a valid CritiqueResponse dict that the LLM mock returns."""
    return {
        "structured_edits": [
            {
                "target_material_id": "mat-001",
                "old_string": "generic text",
                "new_string": "Python and machine learning",
                "reason": "keyword_match",
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


def _make_draft_material(material_id: str = "mat-001") -> DraftMaterial:
    """Create a test DraftMaterial instance."""
    return DraftMaterial(
        id=material_id,
        pipeline_record_id="pipeline-001",
        prepare_technique_id="cv_and_cover_letter",
        material_type="tailored_cv",
        content="This is generic text that needs improvement for the role.",
        quality_score=70,
        generated_at=datetime.now(timezone.utc),
    )


def _make_review_technique_mock():
    """Create a mock review technique configuration."""
    technique = MagicMock()
    technique.id = "standard_material_review"
    technique.max_review_cycles = 2
    technique.critique_categories = [
        "missed_keywords",
        "company_angles",
        "reframing",
        "tone_style",
    ]
    return technique


def _make_schema_registry_mock(has_review_technique: bool = True):
    """Create a mocked SchemaRegistry."""
    schema = MagicMock()
    if has_review_technique:
        schema.get_review_technique_for_prepare.return_value = (
            _make_review_technique_mock()
        )
    else:
        schema.get_review_technique_for_prepare.return_value = None
    return schema


def _make_review_repository_mock():
    """Create a mocked ReviewRepository."""
    repo = MagicMock()
    repo.save_reasoning_log = AsyncMock()
    repo.mark_unreviewed = AsyncMock()
    return repo


def _make_personalization_engine_mock():
    """Create a mocked PersonalizationEngine."""
    engine = MagicMock()
    return engine


def _make_prospect():
    return {"name": "Acme Corp", "contact": "John Doe"}


def _make_beneficiary():
    return {
        "profile_assets": {
            "skills": ["Python", "machine learning", "data engineering"],
            "achievements": ["Led team of 10", "Increased revenue by 30%"],
        }
    }


def _make_enrichment():
    return {
        "firmographics": {"industry": "Technology", "size": "500-1000"},
        "technographics": {"stack": ["Python", "AWS", "Kubernetes"]},
        "intent_signals": ["hiring ML engineers"],
        "contact_seniority": "VP",
    }


# ─── TASK 12.1: End-to-end pipeline flow ─────────────────────────────────────


@pytest.mark.asyncio
async def test_review_pipeline_end_to_end_reviewed_status():
    """PersonalizationEngine → ReviewService → pipeline state transition.

    Verifies that when a valid CritiqueResponse is returned by the LLM,
    the material proceeds with 'reviewed' status and reasoning_log is populated.

    Requirements: 1.1, 3.3
    """
    # Arrange: mock LLM router to return valid critique
    llm_router = MagicMock()
    llm_router.dispatch_critique = AsyncMock(
        return_value=_make_valid_critique_response_dict()
    )
    llm_router.dispatch_revision = AsyncMock(return_value=None)

    schema_registry = _make_schema_registry_mock(has_review_technique=True)
    review_repository = _make_review_repository_mock()
    personalization_engine = _make_personalization_engine_mock()

    review_service = ReviewService(
        llm_router=llm_router,
        schema_registry=schema_registry,
        review_repository=review_repository,
        personalization_engine=personalization_engine,
    )

    pipeline_stage = ReviewPipelineStage(
        review_service=review_service,
        schema_registry=schema_registry,
    )

    draft = _make_draft_material()
    prospect = _make_prospect()
    beneficiary = _make_beneficiary()
    enrichment = _make_enrichment()

    # Act: invoke the pipeline stage
    result = await pipeline_stage.process_after_generation(
        draft_material=draft,
        prospect=prospect,
        beneficiary=beneficiary,
        enrichment=enrichment,
        opportunity_description="Senior ML Engineer role at Acme Corp",
    )

    # Assert: material has "reviewed" status
    assert result["review_status"] == ReviewStatus.REVIEWED

    # Assert: reasoning_log is populated
    reasoning_log = result["reasoning_log"]
    assert reasoning_log is not None
    assert isinstance(reasoning_log, ReasoningLog)
    assert reasoning_log.material_id == "mat-001"
    assert reasoning_log.total_cycles_executed > 0
    assert reasoning_log.final_review_status == ReviewStatus.REVIEWED

    # Assert: revised_content differs from original (edit was applied)
    assert "Python and machine learning" in result["revised_content"]

    # Assert: reasoning_log was persisted
    review_repository.save_reasoning_log.assert_called_once()


@pytest.mark.asyncio
async def test_review_pipeline_skips_when_no_review_technique():
    """Pipeline skips review when schema has no review_technique configured.

    Verifies that with no review_technique, the draft passes through
    unchanged with REVIEWED status (trivial review — nothing to critique).

    Requirements: 1.1, 3.3
    """
    # Arrange: schema returns no review_technique
    schema_registry = _make_schema_registry_mock(has_review_technique=False)

    review_service = ReviewService(
        llm_router=MagicMock(),
        schema_registry=schema_registry,
        review_repository=_make_review_repository_mock(),
        personalization_engine=_make_personalization_engine_mock(),
    )

    pipeline_stage = ReviewPipelineStage(
        review_service=review_service,
        schema_registry=schema_registry,
    )

    draft = _make_draft_material()

    # Act
    result = await pipeline_stage.process_after_generation(
        draft_material=draft,
        prospect=_make_prospect(),
        beneficiary=_make_beneficiary(),
        enrichment=_make_enrichment(),
        opportunity_description="Role description",
    )

    # Assert: passes through with REVIEWED status (no review needed)
    assert result["review_status"] == ReviewStatus.REVIEWED
    assert result["revised_content"] == draft.content


# ─── TASK 12.2: Batch processing with concurrency ────────────────────────────


@pytest.mark.asyncio
async def test_batch_processing_respects_concurrency_limit():
    """Submit multiple materials for review with artificial delay.

    Verifies max 3 concurrent via timing: with 6 materials at 0.1s each
    and concurrency limit of 3, total time should be ≈0.2s (2 waves of 3).

    Requirements: 3.5
    """
    # Arrange: LLM with artificial delay
    async def mock_dispatch_with_delay(prompt, timeout=60.0):
        await asyncio.sleep(0.1)  # Simulate LLM latency
        return _make_valid_critique_response_dict()

    async def mock_revision_with_delay(prompt, timeout=60.0):
        await asyncio.sleep(0.01)
        return None

    llm_router = MagicMock()
    llm_router.dispatch_critique = AsyncMock(side_effect=mock_dispatch_with_delay)
    llm_router.dispatch_revision = AsyncMock(side_effect=mock_revision_with_delay)

    schema_registry = _make_schema_registry_mock(has_review_technique=True)
    # Set max_review_cycles to 1 so each material has exactly 1 critique call
    schema_registry.get_review_technique_for_prepare.return_value.max_review_cycles = 1

    review_repository = _make_review_repository_mock()
    personalization_engine = _make_personalization_engine_mock()

    review_service = ReviewService(
        llm_router=llm_router,
        schema_registry=schema_registry,
        review_repository=review_repository,
        personalization_engine=personalization_engine,
    )

    # Create 6 materials
    materials = [_make_draft_material(f"mat-{i:03d}") for i in range(6)]
    prospect = _make_prospect()
    beneficiary = _make_beneficiary()
    enrichment = _make_enrichment()

    # Act: measure total execution time
    start = time.monotonic()
    results = await review_service.review_batch(
        materials=materials,
        prospect=prospect,
        beneficiary=beneficiary,
        enrichment=enrichment,
        opportunity_description="Batch test role",
    )
    elapsed = time.monotonic() - start

    # Assert: all 6 materials processed
    assert len(results) == 6
    for r in results:
        assert r.review_status == ReviewStatus.REVIEWED

    # Assert: timing confirms concurrency limit of 3
    # With 6 items, concurrency 3, and 0.1s per item: expect ~0.2s (2 waves)
    # If fully serial it would take ~0.6s
    # If fully parallel (no limit) it would take ~0.1s
    # We allow some tolerance for test overhead
    assert elapsed >= 0.18, (
        f"Elapsed {elapsed:.3f}s is too fast — concurrency limit may not be enforced"
    )
    assert elapsed < 0.5, (
        f"Elapsed {elapsed:.3f}s is too slow — concurrency may be lower than 3"
    )


@pytest.mark.asyncio
async def test_batch_processing_9_materials_timing():
    """With 9 materials at 0.1s each and concurrency 3: expect ≈0.3s (3 waves).

    Requirements: 3.5
    """

    async def mock_dispatch_with_delay(prompt, timeout=60.0):
        await asyncio.sleep(0.1)
        return _make_valid_critique_response_dict()

    async def mock_revision_no_delay(prompt, timeout=60.0):
        return None

    llm_router = MagicMock()
    llm_router.dispatch_critique = AsyncMock(side_effect=mock_dispatch_with_delay)
    llm_router.dispatch_revision = AsyncMock(side_effect=mock_revision_no_delay)

    schema_registry = _make_schema_registry_mock(has_review_technique=True)
    schema_registry.get_review_technique_for_prepare.return_value.max_review_cycles = 1

    review_service = ReviewService(
        llm_router=llm_router,
        schema_registry=schema_registry,
        review_repository=_make_review_repository_mock(),
        personalization_engine=_make_personalization_engine_mock(),
    )

    materials = [_make_draft_material(f"mat-{i:03d}") for i in range(9)]

    start = time.monotonic()
    results = await review_service.review_batch(
        materials=materials,
        prospect=_make_prospect(),
        beneficiary=_make_beneficiary(),
        enrichment=_make_enrichment(),
        opportunity_description="Batch test 9 materials",
    )
    elapsed = time.monotonic() - start

    assert len(results) == 9
    for r in results:
        assert r.review_status == ReviewStatus.REVIEWED

    # 9 items / 3 concurrent = 3 waves × 0.1s = 0.3s minimum
    assert elapsed >= 0.27, (
        f"Elapsed {elapsed:.3f}s too fast — expected ≥0.27s for 3 waves"
    )
    assert elapsed < 0.6, (
        f"Elapsed {elapsed:.3f}s too slow — expected <0.6s with concurrency 3"
    )


# ─── TASK 12.3: Graceful degradation and Dashboard notification ───────────────


@pytest.mark.asyncio
async def test_graceful_degradation_on_llm_failure():
    """When LLM fails all attempts, material is marked 'unreviewed'.

    Verifies graceful degradation path: material gets UNREVIEWED status,
    original content preserved, and repository.mark_unreviewed() is called.

    Requirements: 1.5, 3.4
    """
    # Arrange: LLM that always fails
    llm_router = MagicMock()
    llm_router.dispatch_critique = AsyncMock(
        side_effect=Exception("LLM service unavailable")
    )

    schema_registry = _make_schema_registry_mock(has_review_technique=True)
    review_repository = _make_review_repository_mock()
    personalization_engine = _make_personalization_engine_mock()

    review_service = ReviewService(
        llm_router=llm_router,
        schema_registry=schema_registry,
        review_repository=review_repository,
        personalization_engine=personalization_engine,
    )

    pipeline_stage = ReviewPipelineStage(
        review_service=review_service,
        schema_registry=schema_registry,
    )

    draft = _make_draft_material()

    # Act
    result = await pipeline_stage.process_after_generation(
        draft_material=draft,
        prospect=_make_prospect(),
        beneficiary=_make_beneficiary(),
        enrichment=_make_enrichment(),
        opportunity_description="ML Engineer at Acme",
    )

    # Assert: material marked UNREVIEWED
    assert result["review_status"] == ReviewStatus.UNREVIEWED

    # Assert: original content preserved (reverted on failure)
    assert result["revised_content"] == draft.content

    # Assert: repository was notified of the unreviewed material
    review_repository.mark_unreviewed.assert_called_once_with("mat-001")


@pytest.mark.asyncio
async def test_graceful_degradation_reasoning_log_records_failure():
    """On total LLM failure, reasoning_log still captures partial telemetry.

    Verifies the reasoning_log is persisted with UNREVIEWED status even
    when all critique attempts fail.

    Requirements: 1.5, 3.4
    """
    # Arrange: LLM always fails
    llm_router = MagicMock()
    llm_router.dispatch_critique = AsyncMock(
        side_effect=Exception("Timeout after 60s")
    )

    schema_registry = _make_schema_registry_mock(has_review_technique=True)
    review_repository = _make_review_repository_mock()

    review_service = ReviewService(
        llm_router=llm_router,
        schema_registry=schema_registry,
        review_repository=review_repository,
        personalization_engine=_make_personalization_engine_mock(),
    )

    draft = _make_draft_material()

    # Act: call review_material directly for more detailed assertions
    result = await review_service.review_material(
        draft_material=draft,
        prospect=_make_prospect(),
        beneficiary=_make_beneficiary(),
        enrichment=_make_enrichment(),
        opportunity_description="Test opportunity",
    )

    # Assert: status is UNREVIEWED
    assert result.review_status == ReviewStatus.UNREVIEWED

    # Assert: reasoning_log was persisted
    review_repository.save_reasoning_log.assert_called_once()
    saved_log = review_repository.save_reasoning_log.call_args[0][0]
    assert saved_log.final_review_status == ReviewStatus.UNREVIEWED
    assert saved_log.material_id == "mat-001"
