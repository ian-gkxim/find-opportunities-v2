"""Unit tests for InterviewPrepService.assemble_context().

Validates context assembly logic including:
- Loading pipeline record, prospect, submitted materials, enrichment,
  profile assets, and STAR examples
- Graceful degradation when submitted materials are unavailable
- ContextAssemblyError raised when required inputs are missing

Requirements: 1.2, 1.3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.interview_prep_models import (
    ContextAssemblyError,
    GenerationContext,
)
from app.core.interview_prep_service import InterviewPrepService


# ─── FAKE DATA OBJECTS ────────────────────────────────────────────────────────


@dataclass
class FakePipelineRecord:
    id: str = "rec-001"
    prospect_id: str = "prospect-001"
    beneficiary_id: str = "ben-001"
    opportunity_type_id: str = "job_site"


@dataclass
class FakeProspect:
    id: str = "prospect-001"
    description: str = "Senior Python developer needed for fintech startup"


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    """Create a mock InterviewPrepRepository with default happy-path responses."""
    db = AsyncMock()
    db.get_pipeline_record.return_value = FakePipelineRecord()
    db.get_prospect.return_value = FakeProspect()
    db.get_submitted_materials.return_value = {
        "tailored_cv": "Tailored CV content for the role",
        "tailored_cover_letter": "Cover letter content",
    }
    db.get_enrichment_record.return_value = {
        "company": "FinTechCo",
        "industry": "Financial Technology",
        "tech_stack": ["Python", "PostgreSQL", "Kafka"],
    }
    db.get_intent_signals.return_value = [
        {"type": "hiring_surge", "confidence": 0.85}
    ]
    db.get_profile_assets.return_value = {
        "resume": "Full resume content here",
        "consultant_profiles": "Profile content here",
    }
    db.get_star_examples.return_value = [
        {"competency": "leadership", "narrative": "Led a team of 8"}
    ]
    return db


@pytest.fixture
def service(mock_db):
    """Create an InterviewPrepService instance with mocked dependencies."""
    return InterviewPrepService(
        llm_router=MagicMock(),
        grounding_verifier=MagicMock(),
        schema_registry=MagicMock(),
        db_repo=mock_db,
        event_publisher=MagicMock(),
    )


# ─── HAPPY PATH TESTS ────────────────────────────────────────────────────────


class TestAssembleContextHappyPath:
    """Tests for successful context assembly with all data available."""

    @pytest.mark.asyncio
    async def test_returns_generation_context(self, service, mock_db):
        ctx = await service.assemble_context("rec-001")
        assert isinstance(ctx, GenerationContext)

    @pytest.mark.asyncio
    async def test_opportunity_description_loaded(self, service, mock_db):
        ctx = await service.assemble_context("rec-001")
        assert ctx.opportunity_description == "Senior Python developer needed for fintech startup"

    @pytest.mark.asyncio
    async def test_tailored_cv_loaded(self, service, mock_db):
        ctx = await service.assemble_context("rec-001")
        assert ctx.tailored_cv == "Tailored CV content for the role"

    @pytest.mark.asyncio
    async def test_tailored_cover_letter_loaded(self, service, mock_db):
        ctx = await service.assemble_context("rec-001")
        assert ctx.tailored_cover_letter == "Cover letter content"

    @pytest.mark.asyncio
    async def test_enrichment_record_loaded(self, service, mock_db):
        ctx = await service.assemble_context("rec-001")
        assert ctx.enrichment_record == {
            "company": "FinTechCo",
            "industry": "Financial Technology",
            "tech_stack": ["Python", "PostgreSQL", "Kafka"],
        }

    @pytest.mark.asyncio
    async def test_intent_signals_loaded(self, service, mock_db):
        ctx = await service.assemble_context("rec-001")
        assert ctx.intent_signals == [{"type": "hiring_surge", "confidence": 0.85}]

    @pytest.mark.asyncio
    async def test_profile_assets_loaded(self, service, mock_db):
        ctx = await service.assemble_context("rec-001")
        assert ctx.profile_assets == {
            "resume": "Full resume content here",
            "consultant_profiles": "Profile content here",
        }

    @pytest.mark.asyncio
    async def test_star_examples_loaded(self, service, mock_db):
        ctx = await service.assemble_context("rec-001")
        assert ctx.star_examples == [
            {"competency": "leadership", "narrative": "Led a team of 8"}
        ]

    @pytest.mark.asyncio
    async def test_opportunity_type_id_set(self, service, mock_db):
        ctx = await service.assemble_context("rec-001")
        assert ctx.opportunity_type_id == "job_site"

    @pytest.mark.asyncio
    async def test_beneficiary_id_set(self, service, mock_db):
        ctx = await service.assemble_context("rec-001")
        assert ctx.beneficiary_id == "ben-001"

    @pytest.mark.asyncio
    async def test_no_omission_notes_when_all_materials_present(self, service, mock_db):
        await service.assemble_context("rec-001")
        assert service._omission_notes == []


# ─── GRACEFUL DEGRADATION TESTS ──────────────────────────────────────────────


class TestAssembleContextGracefulDegradation:
    """Tests for graceful degradation when submitted materials are unavailable."""

    @pytest.mark.asyncio
    async def test_no_submitted_materials_still_returns_context(self, service, mock_db):
        mock_db.get_submitted_materials.return_value = None
        ctx = await service.assemble_context("rec-001")
        assert isinstance(ctx, GenerationContext)
        assert ctx.tailored_cv is None
        assert ctx.tailored_cover_letter is None

    @pytest.mark.asyncio
    async def test_omission_notes_for_missing_cv(self, service, mock_db):
        mock_db.get_submitted_materials.return_value = {
            "tailored_cv": None,
            "tailored_cover_letter": "Cover letter content",
        }
        await service.assemble_context("rec-001")
        assert any("CV" in note for note in service._omission_notes)

    @pytest.mark.asyncio
    async def test_omission_notes_for_missing_cover_letter(self, service, mock_db):
        mock_db.get_submitted_materials.return_value = {
            "tailored_cv": "CV content",
            "tailored_cover_letter": None,
        }
        await service.assemble_context("rec-001")
        assert any("cover letter" in note for note in service._omission_notes)

    @pytest.mark.asyncio
    async def test_omission_notes_for_both_missing(self, service, mock_db):
        mock_db.get_submitted_materials.return_value = None
        await service.assemble_context("rec-001")
        assert len(service._omission_notes) == 2

    @pytest.mark.asyncio
    async def test_no_star_examples_returns_none(self, service, mock_db):
        mock_db.get_star_examples.return_value = None
        ctx = await service.assemble_context("rec-001")
        assert ctx.star_examples is None

    @pytest.mark.asyncio
    async def test_no_intent_signals_returns_empty_list(self, service, mock_db):
        mock_db.get_intent_signals.return_value = None
        ctx = await service.assemble_context("rec-001")
        assert ctx.intent_signals == []


# ─── ERROR CASES ──────────────────────────────────────────────────────────────


class TestAssembleContextErrors:
    """Tests for ContextAssemblyError when required inputs are missing."""

    @pytest.mark.asyncio
    async def test_raises_when_pipeline_record_not_found(self, service, mock_db):
        mock_db.get_pipeline_record.return_value = None
        with pytest.raises(ContextAssemblyError) as exc_info:
            await service.assemble_context("rec-missing")
        assert "pipeline_record" in exc_info.value.missing_inputs

    @pytest.mark.asyncio
    async def test_raises_when_opportunity_description_empty(self, service, mock_db):
        mock_db.get_prospect.return_value = FakeProspect(description="")
        with pytest.raises(ContextAssemblyError) as exc_info:
            await service.assemble_context("rec-001")
        assert "opportunity_description" in exc_info.value.missing_inputs

    @pytest.mark.asyncio
    async def test_raises_when_prospect_not_found(self, service, mock_db):
        mock_db.get_prospect.return_value = None
        with pytest.raises(ContextAssemblyError) as exc_info:
            await service.assemble_context("rec-001")
        assert "opportunity_description" in exc_info.value.missing_inputs

    @pytest.mark.asyncio
    async def test_raises_when_enrichment_record_missing(self, service, mock_db):
        mock_db.get_enrichment_record.return_value = None
        with pytest.raises(ContextAssemblyError) as exc_info:
            await service.assemble_context("rec-001")
        assert "enrichment_record" in exc_info.value.missing_inputs

    @pytest.mark.asyncio
    async def test_raises_when_profile_assets_empty(self, service, mock_db):
        mock_db.get_profile_assets.return_value = {}
        with pytest.raises(ContextAssemblyError) as exc_info:
            await service.assemble_context("rec-001")
        assert "profile_assets" in exc_info.value.missing_inputs

    @pytest.mark.asyncio
    async def test_raises_when_profile_assets_none(self, service, mock_db):
        mock_db.get_profile_assets.return_value = None
        with pytest.raises(ContextAssemblyError) as exc_info:
            await service.assemble_context("rec-001")
        assert "profile_assets" in exc_info.value.missing_inputs

    @pytest.mark.asyncio
    async def test_error_not_retryable(self, service, mock_db):
        mock_db.get_pipeline_record.return_value = None
        with pytest.raises(ContextAssemblyError) as exc_info:
            await service.assemble_context("rec-001")
        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_error_carries_pipeline_record_id(self, service, mock_db):
        mock_db.get_enrichment_record.return_value = None
        with pytest.raises(ContextAssemblyError) as exc_info:
            await service.assemble_context("rec-001")
        assert exc_info.value.pipeline_record_id == "rec-001"
