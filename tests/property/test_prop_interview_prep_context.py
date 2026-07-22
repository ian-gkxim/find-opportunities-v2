# Feature: interview-prep-technique, Property 2: Context assembly completeness and graceful degradation
"""Property-based tests for Interview_Prep_Service context assembly.

Generates random pipeline records with varying presence/absence of CV,
cover letter, enrichment, and profile assets. Verifies:
- Context includes all available sources
- omission_notes populated for each missing material
- Generation proceeds without submitted materials

**Validates: Requirements 1.2, 1.3**
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.interview_prep_models import GenerationContext
from app.core.interview_prep_service import InterviewPrepService


# ─── Lightweight stubs for db_repo return values ──────────────────────────────


@dataclass
class FakePipelineRecord:
    """Minimal pipeline record returned by db_repo.get_pipeline_record."""

    id: str
    prospect_id: str
    beneficiary_id: str
    opportunity_type_id: str


@dataclass
class FakeProspect:
    """Minimal prospect returned by db_repo.get_prospect."""

    description: str


# ─── Strategies ───────────────────────────────────────────────────────────────

_printable_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        min_codepoint=32,
        max_codepoint=126,
    ),
    min_size=5,
    max_size=100,
)

# Whether the submitted CV exists for this pipeline record
has_cv_st = st.booleans()

# Whether the submitted cover letter exists for this pipeline record
has_cover_letter_st = st.booleans()

# Number of profile assets (always at least 1 — required)
profile_asset_count_st = st.integers(min_value=1, max_value=5)


@st.composite
def context_config_strategy(draw: st.DrawFn) -> dict:
    """Generate a random configuration for context assembly inputs."""
    has_cv = draw(has_cv_st)
    has_cover_letter = draw(has_cover_letter_st)
    profile_asset_count = draw(profile_asset_count_st)

    # Generate profile asset contents
    profile_assets = {}
    for i in range(profile_asset_count):
        asset_id = f"asset_{i}"
        profile_assets[asset_id] = draw(_printable_text)

    # Generate CV text if present
    cv_text = draw(_printable_text) if has_cv else None

    # Generate cover letter text if present
    cover_letter_text = draw(_printable_text) if has_cover_letter else None

    # Opportunity description (always present — required)
    opportunity_description = draw(_printable_text)

    return {
        "has_cv": has_cv,
        "has_cover_letter": has_cover_letter,
        "cv_text": cv_text,
        "cover_letter_text": cover_letter_text,
        "profile_assets": profile_assets,
        "profile_asset_count": profile_asset_count,
        "opportunity_description": opportunity_description,
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _create_service_with_mocked_db(config: dict) -> InterviewPrepService:
    """Create an InterviewPrepService with db_repo mocked per config.

    The db_repo returns data based on the generated configuration:
    - Pipeline record always exists
    - Prospect always has an opportunity description
    - Enrichment record always present
    - Submitted materials present/absent based on config
    - Profile assets with the configured count
    """
    mock_llm = MagicMock()
    mock_grounding = MagicMock()
    mock_schema = MagicMock()
    mock_publisher = MagicMock()

    mock_db = MagicMock()

    # Pipeline record — always found
    pipeline_record = FakePipelineRecord(
        id="pipeline-001",
        prospect_id="prospect-001",
        beneficiary_id="beneficiary-001",
        opportunity_type_id="job_site",
    )
    mock_db.get_pipeline_record = AsyncMock(return_value=pipeline_record)

    # Prospect — always has description
    prospect = FakeProspect(description=config["opportunity_description"])
    mock_db.get_prospect = AsyncMock(return_value=prospect)

    # Submitted materials — presence depends on config
    submitted_materials = {}
    if config["has_cv"]:
        submitted_materials["tailored_cv"] = config["cv_text"]
    if config["has_cover_letter"]:
        submitted_materials["tailored_cover_letter"] = config["cover_letter_text"]

    # Return the dict (empty dict if neither present, but still truthy for empty dict)
    # The service checks submitted.get(...) so we need the dict
    mock_db.get_submitted_materials = AsyncMock(
        return_value=submitted_materials if submitted_materials else {}
    )

    # Enrichment record — always present
    enrichment_record = {
        "industry": "Technology",
        "employee_count": 500,
        "tech_stack": ["Python", "PostgreSQL"],
        "headquarters": "Copenhagen",
    }
    mock_db.get_enrichment_record = AsyncMock(return_value=enrichment_record)

    # Intent signals
    mock_db.get_intent_signals = AsyncMock(return_value=[{"type": "hiring"}])

    # Profile assets — always at least 1
    mock_db.get_profile_assets = AsyncMock(return_value=config["profile_assets"])

    # STAR examples — optional, always return some
    mock_db.get_star_examples = AsyncMock(return_value=[{"example": "data"}])

    service = InterviewPrepService(
        llm_router=mock_llm,
        grounding_verifier=mock_grounding,
        schema_registry=mock_schema,
        db_repo=mock_db,
        event_publisher=mock_publisher,
    )
    return service


# ─── Property 2: Context assembly completeness and graceful degradation ───────


class TestProperty2ContextAssemblyCompleteness:
    """Property 2: Context assembly completeness and graceful degradation.

    For any pipeline record in Interview state, the assembled GenerationContext
    SHALL include all available data sources. For any pipeline record where
    submitted materials are unavailable, the service SHALL still produce a
    context and the omission_notes SHALL contain an entry for each missing material.

    **Validates: Requirements 1.2, 1.3**
    """

    @given(config=context_config_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_cv_available_included_in_context(
        self,
        config: dict,
    ) -> None:
        """FOR ANY pipeline record where a submitted CV is available,
        the assembled context SHALL have a non-None tailored_cv.

        **Validates: Requirements 1.2**
        """
        service = _create_service_with_mocked_db(config)
        context = await service.assemble_context("pipeline-001")

        if config["has_cv"]:
            assert context.tailored_cv is not None, (
                "CV is available but context.tailored_cv is None"
            )
            assert context.tailored_cv == config["cv_text"], (
                "CV text in context does not match submitted CV"
            )

    @given(config=context_config_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_missing_cv_produces_omission_note(
        self,
        config: dict,
    ) -> None:
        """FOR ANY pipeline record where the submitted CV is unavailable,
        omission_notes SHALL contain a note about the missing CV.

        **Validates: Requirements 1.3**
        """
        service = _create_service_with_mocked_db(config)
        context = await service.assemble_context("pipeline-001")

        if not config["has_cv"]:
            assert context.tailored_cv is None, (
                "CV is not available but context.tailored_cv is not None"
            )
            # Check omission_notes on the service (stored in _omission_notes)
            assert any("CV" in note or "cv" in note.lower() for note in service._omission_notes), (
                f"Missing CV but no CV omission note found in: {service._omission_notes}"
            )

    @given(config=context_config_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_missing_cover_letter_produces_omission_note(
        self,
        config: dict,
    ) -> None:
        """FOR ANY pipeline record where the submitted cover letter is unavailable,
        omission_notes SHALL contain a note about the missing cover letter.

        **Validates: Requirements 1.3**
        """
        service = _create_service_with_mocked_db(config)
        context = await service.assemble_context("pipeline-001")

        if not config["has_cover_letter"]:
            assert context.tailored_cover_letter is None, (
                "Cover letter is not available but context.tailored_cover_letter is not None"
            )
            assert any(
                "cover letter" in note.lower() for note in service._omission_notes
            ), (
                f"Missing cover letter but no cover letter omission note found in: "
                f"{service._omission_notes}"
            )

    @given(config=context_config_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_profile_assets_always_present_with_at_least_one_entry(
        self,
        config: dict,
    ) -> None:
        """FOR ANY pipeline record, the assembled context SHALL always
        have profile_assets with at least 1 entry.

        **Validates: Requirements 1.2**
        """
        service = _create_service_with_mocked_db(config)
        context = await service.assemble_context("pipeline-001")

        assert context.profile_assets is not None, (
            "profile_assets is None"
        )
        assert len(context.profile_assets) >= 1, (
            f"profile_assets has {len(context.profile_assets)} entries, expected >= 1"
        )
        assert len(context.profile_assets) == config["profile_asset_count"], (
            f"Expected {config['profile_asset_count']} profile assets, "
            f"got {len(context.profile_assets)}"
        )

    @given(config=context_config_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_opportunity_description_always_non_empty(
        self,
        config: dict,
    ) -> None:
        """FOR ANY pipeline record, the assembled context SHALL always
        have a non-empty opportunity_description.

        **Validates: Requirements 1.2**
        """
        service = _create_service_with_mocked_db(config)
        context = await service.assemble_context("pipeline-001")

        assert context.opportunity_description is not None, (
            "opportunity_description is None"
        )
        assert len(context.opportunity_description) > 0, (
            "opportunity_description is empty"
        )
        assert context.opportunity_description == config["opportunity_description"], (
            "opportunity_description does not match the prospect description"
        )

    @given(config=context_config_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_enrichment_record_always_present(
        self,
        config: dict,
    ) -> None:
        """FOR ANY pipeline record, the assembled context SHALL always
        have a non-None enrichment_record.

        **Validates: Requirements 1.2**
        """
        service = _create_service_with_mocked_db(config)
        context = await service.assemble_context("pipeline-001")

        assert context.enrichment_record is not None, (
            "enrichment_record is None — assembly should always include it"
        )
