"""Integration tests for PersonalizationEngine ↔ ContentSelector wiring.

Tests the full integration path: PersonalizationEngine invokes ContentSelector
when material exceeds a length constraint declared in Schema_Registry,
skips when no constraint exists, and records cuts in reasoning_log.

Requirements: 3.1, 3.2, 3.3
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from app.core.content_selector import ConstraintType, LengthConstraint
from app.core.personalization_engine import (
    EnrichmentData,
    PersonalizationEngine,
)
from app.core.schema_registry import SchemaRegistry


# ─── HELPERS ──────────────────────────────────────────────────────────────────


class FakeLLMRouter:
    """Fake LLM router that returns controllable content for integration testing."""

    def __init__(self, response: str):
        self._response = response
        self.call_count = 0

    async def generate_content(
        self, prompt: str, context: dict, material_type: str
    ) -> str:
        self.call_count += 1
        return self._response


def _make_schema_registry_with_constraint(
    material_type: str, max_words: int
) -> MagicMock:
    """Create a mock SchemaRegistry that returns a tight LengthConstraint."""
    mock_registry = MagicMock()
    mock_registry.get_length_constraint.return_value = LengthConstraint(
        constraint_type=ConstraintType.MAX_WORDS,
        max_value=max_words,
    )
    return mock_registry


def _make_schema_registry_without_constraint() -> MagicMock:
    """Create a mock SchemaRegistry where get_length_constraint returns None."""
    mock_registry = MagicMock()
    mock_registry.get_length_constraint.return_value = None
    return mock_registry


def _make_enrichment() -> EnrichmentData:
    """Create enrichment data with keywords that allow relevance scoring."""
    return EnrichmentData(
        industry="fintech",
        tech_stack=["python", "react", "kubernetes"],
        company_size=200,
        recent_funding=None,
        intent_signals=["cloud migration", "devops tooling"],
        hooks=[],
    )


# ─── TEST: PersonalizationEngine invokes ContentSelector when exceeds constraint


@pytest.mark.asyncio
async def test_invokes_content_selector_when_exceeds_constraint():
    """PersonalizationEngine applies content selection when material exceeds constraint.

    Setup:
    - Schema_Registry returns a tight constraint (max 5 words).
    - LLM returns content that clearly exceeds 5 words.

    Assert:
    - Returned content is shorter than original LLM output.
    - Content has been trimmed to satisfy the constraint.

    Requirements: 3.2
    """
    # Arrange: LLM returns content with ~30 words (well over 5 word limit)
    long_content = (
        "- Experienced python developer with kubernetes expertise\n"
        "- Led cloud migration projects for fintech companies\n"
        "- Built react applications with modern architecture\n"
        "- Managed devops tooling across multiple teams\n"
        "- Delivered scalable solutions for enterprise clients"
    )
    fake_llm = FakeLLMRouter(response=long_content)

    # Schema registry with a very tight constraint (max 5 words)
    schema_registry = _make_schema_registry_with_constraint("cv", max_words=15)

    engine = PersonalizationEngine(
        llm_router=fake_llm,
        schema_registry=schema_registry,
    )

    enrichment = _make_enrichment()

    # Act
    result = await engine.generate_materials(
        enrichment=enrichment,
        beneficiary_id="consultant",
        material_type="cv",
        contact_seniority="director",
    )

    # Assert: content has been trimmed
    original_word_count = len(long_content.split())
    result_word_count = len(result.content.split())
    assert result_word_count < original_word_count, (
        f"Expected content to be trimmed: original={original_word_count} words, "
        f"result={result_word_count} words"
    )
    # The trimmed content should respect the constraint
    assert result_word_count <= 15, (
        f"Result should be within 15 word constraint, got {result_word_count}"
    )


# ─── TEST: PersonalizationEngine skips when no constraint declared


@pytest.mark.asyncio
async def test_skips_content_selection_when_no_constraint():
    """PersonalizationEngine passes content through unchanged when no constraint.

    Setup:
    - Schema_Registry.get_length_constraint() returns None.
    - LLM returns long content.

    Assert:
    - Content passes through unchanged.
    - reasoning_log has no "content_selection" entry.

    Requirements: 3.3
    """
    # Arrange: LLM returns content
    original_content = (
        "This is a comprehensive cover letter with many words. "
        "It discusses the fintech industry and python development. "
        "The candidate has extensive kubernetes experience."
    )
    fake_llm = FakeLLMRouter(response=original_content)

    # Schema registry returns None for constraint
    schema_registry = _make_schema_registry_without_constraint()

    engine = PersonalizationEngine(
        llm_router=fake_llm,
        schema_registry=schema_registry,
    )

    enrichment = _make_enrichment()

    # Act
    result = await engine.generate_materials(
        enrichment=enrichment,
        beneficiary_id="consultant",
        material_type="cover_letter",
        contact_seniority="director",
    )

    # Assert: content passes through unchanged
    assert result.content == original_content

    # Assert: reasoning_log has no "content_selection" entry
    content_selection_entries = [
        entry for entry in engine.reasoning_log
        if entry.get("action") == "content_selection"
    ]
    assert len(content_selection_entries) == 0, (
        "Expected no content_selection entries in reasoning_log when no constraint declared"
    )


# ─── TEST: reasoning_log records cuts with scores


@pytest.mark.asyncio
async def test_reasoning_log_records_cuts_with_scores():
    """reasoning_log contains structured cut data when content selection is applied.

    Setup:
    - Schema_Registry returns tight constraint.
    - LLM returns content exceeding constraint.

    Assert:
    - reasoning_log has entry with action="content_selection".
    - Entry contains "cuts" list with unit_id, composite_score, text_preview.
    - Entry contains "original_length" and "final_length".

    Requirements: 3.2
    """
    # Arrange: LLM returns content that exceeds a 10-word constraint
    long_content = (
        "- Expert python developer with deep fintech knowledge\n"
        "- Led kubernetes deployments across multiple cloud providers\n"
        "- Built react frontends for financial trading platforms\n"
        "- Drove cloud migration initiatives for enterprise banking"
    )
    fake_llm = FakeLLMRouter(response=long_content)

    # Tight constraint: max 10 words
    schema_registry = _make_schema_registry_with_constraint("cv", max_words=10)

    engine = PersonalizationEngine(
        llm_router=fake_llm,
        schema_registry=schema_registry,
    )

    enrichment = _make_enrichment()

    # Act
    result = await engine.generate_materials(
        enrichment=enrichment,
        beneficiary_id="consultant",
        material_type="cv",
        contact_seniority="director",
    )

    # Assert: reasoning_log has a content_selection entry
    content_selection_entries = [
        entry for entry in engine.reasoning_log
        if entry.get("action") == "content_selection"
    ]
    assert len(content_selection_entries) == 1, (
        "Expected exactly one content_selection entry in reasoning_log"
    )

    log_entry = content_selection_entries[0]

    # Assert: entry has required fields
    assert log_entry["action"] == "content_selection"
    assert "original_length" in log_entry
    assert "final_length" in log_entry
    assert log_entry["original_length"] > log_entry["final_length"]

    # Assert: cuts list exists and has structured entries
    assert "cuts" in log_entry
    assert len(log_entry["cuts"]) > 0, "Expected at least one cut"

    for cut in log_entry["cuts"]:
        assert "unit_id" in cut, "Each cut must have unit_id"
        assert "composite_score" in cut, "Each cut must have composite_score"
        assert "text_preview" in cut, "Each cut must have text_preview"
        assert isinstance(cut["composite_score"], int)
        assert isinstance(cut["text_preview"], str)
        assert len(cut["text_preview"]) <= 80  # Preview is capped at 80 chars

    # Assert: final_length respects constraint
    assert log_entry["final_length"] <= 10


# ─── TEST: Schema_Registry loads length_constraints from real YAML


def test_schema_registry_loads_length_constraints_from_yaml():
    """Schema_Registry correctly parses length_constraints from YAML.

    Creates a temporary YAML with length_constraints defined on a prepare
    technique, loads it into a real SchemaRegistry, and verifies the
    constraint is accessible via get_length_constraint().

    Requirements: 3.1
    """
    # Arrange: build a minimal valid schema YAML with length_constraints
    schema_content = {
        "schema_version": "2.0",
        "stages": [
            {
                "id": "pipeline",
                "label": "Pipeline",
                "description": "Test stage",
            }
        ],
        "beneficiaries": [
            {
                "id": "consultant",
                "label": "Consultant",
                "description": "Test beneficiary",
                "baseline_assets": ["resume"],
                "offerings_asset": "profiles",
                "offerings_label": "Offerings",
                "search_criteria_asset": "criteria",
            }
        ],
        "opportunity_types": [
            {
                "id": "job_site",
                "label": "Job Sites",
                "beneficiaries": ["consultant"],
                "source_asset": "job_sites",
                "source_label": "Job Sites",
                "find_technique": "test_find",
                "find_label": "Find",
                "prepare_technique": "cv_and_cover_letter",
                "outreach_technique": "manual_apply",
                "pipeline_states": ["Personalise"],
            }
        ],
        "find_techniques": [
            {
                "id": "test_find",
                "service_class": "TestFindService",
                "description": "Test find technique",
            }
        ],
        "prepare_techniques": [
            {
                "id": "cv_and_cover_letter",
                "service_class": "CVGeneratorService",
                "description": "Generates tailored CV and cover letter",
                "inputs": ["resume"],
                "outputs": ["tailored_cv", "tailored_cover_letter"],
                "length_constraints": {
                    "tailored_cv": {"max_words": 800},
                    "tailored_cover_letter": {"max_characters": 2000},
                },
            }
        ],
        "outreach_techniques": [
            {
                "id": "manual_apply",
                "service_class": "ManualOutreachService",
                "description": "Manual application",
            }
        ],
    }

    # Write to a temporary YAML file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as tmp:
        yaml.dump(schema_content, tmp, default_flow_style=False)
        tmp_path = Path(tmp.name)

    try:
        # Act: load the schema
        registry = SchemaRegistry(tmp_path)

        # Assert: tailored_cv has max_words=800 constraint
        cv_constraint = registry.get_length_constraint("tailored_cv")
        assert cv_constraint is not None
        assert cv_constraint.constraint_type == ConstraintType.MAX_WORDS
        assert cv_constraint.max_value == 800

        # Assert: tailored_cover_letter has max_characters=2000 constraint
        cl_constraint = registry.get_length_constraint("tailored_cover_letter")
        assert cl_constraint is not None
        assert cl_constraint.constraint_type == ConstraintType.MAX_CHARACTERS
        assert cl_constraint.max_value == 2000

        # Assert: nonexistent material type returns None
        none_constraint = registry.get_length_constraint("nonexistent")
        assert none_constraint is None

    finally:
        tmp_path.unlink()
