"""Unit tests for Schema_Registry state-entry extensions.

Tests cover Requirement 3.1: Schema_Registry supports declaring interview_preparation
prepare technique attachable to opportunity types with Interview state, triggered on
state entry rather than at material-preparation time.
"""

from pathlib import Path

import pytest
import yaml

from app.core.errors import SchemaValidationError
from app.core.schema_registry import PrepareTechnique, SchemaRegistry


# ─── Helpers ──────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REAL_SCHEMA_PATH = _PROJECT_ROOT / "config" / "schema.yaml"


def _minimal_schema_with_state_entry() -> dict:
    """Return a minimal valid schema with state_entry_techniques configured."""
    return {
        "stages": [
            {"id": "understand", "label": "Understand Us", "description": "Desc"},
            {"id": "find", "label": "Find", "description": "Desc"},
        ],
        "beneficiaries": [
            {
                "id": "consultant",
                "label": "Consultant",
                "description": "Individual consultant",
                "baseline_assets": ["resume"],
                "offerings_asset": "profiles",
                "offerings_label": "Offerings",
                "search_criteria_asset": "search_criteria",
            },
        ],
        "opportunity_types": [
            {
                "id": "job_site",
                "label": "Job Sites",
                "beneficiaries": ["consultant"],
                "source_asset": "job_sites",
                "source_label": "Job Sites",
                "find_technique": "adzuna_discovery",
                "find_label": "From Jobs",
                "prepare_technique": "cv_gen",
                "outreach_technique": "manual_apply",
                "pipeline_states": ["Applied", "Interview", "Offer"],
                "state_entry_techniques": ["interview_preparation"],
            },
        ],
        "find_techniques": [
            {
                "id": "adzuna_discovery",
                "service_class": "AdzunaDiscoveryService",
                "description": "Adzuna search",
            },
        ],
        "prepare_techniques": [
            {
                "id": "cv_gen",
                "service_class": "CVGeneratorService",
                "description": "CV generation",
            },
            {
                "id": "interview_preparation",
                "service_class": "InterviewPrepService",
                "description": "Generates interview prep pack on Interview state entry",
                "trigger": "state_entry",
                "trigger_state": "Interview",
                "inputs": ["opportunity_description", "tailored_cv"],
                "outputs": ["interview_prep_pack"],
            },
        ],
        "outreach_techniques": [
            {
                "id": "manual_apply",
                "service_class": "ManualOutreachService",
                "description": "Manual application",
            },
        ],
    }


def _write_schema(tmp_path: Path, schema: dict) -> Path:
    """Write schema dict to YAML file and return its path."""
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(yaml.dump(schema), encoding="utf-8")
    return schema_file


# ─── Tests using real config/schema.yaml ──────────────────────────────────────


class TestGetStateEntryTechniquesReal:
    """Tests that use the real config/schema.yaml to verify state-entry technique lookups."""

    @pytest.fixture
    def registry(self) -> SchemaRegistry:
        if not _REAL_SCHEMA_PATH.exists():
            pytest.skip("config/schema.yaml not present")
        return SchemaRegistry(_REAL_SCHEMA_PATH)

    def test_get_state_entry_techniques_returns_interview_preparation_for_job_site(
        self, registry: SchemaRegistry
    ) -> None:
        """get_state_entry_techniques returns interview_preparation for job_site Interview state."""
        techniques = registry.get_state_entry_techniques("job_site", "Interview")
        assert len(techniques) == 1
        assert techniques[0].id == "interview_preparation"

    def test_get_state_entry_techniques_returns_interview_preparation_for_company(
        self, registry: SchemaRegistry
    ) -> None:
        """get_state_entry_techniques returns interview_preparation for company Interview state."""
        techniques = registry.get_state_entry_techniques("company", "Interview")
        assert len(techniques) == 1
        assert techniques[0].id == "interview_preparation"

    def test_get_state_entry_techniques_returns_empty_for_non_interview_state(
        self, registry: SchemaRegistry
    ) -> None:
        """get_state_entry_techniques returns empty list for a state without techniques."""
        techniques = registry.get_state_entry_techniques("job_site", "Applied")
        assert techniques == []

    def test_get_state_entry_techniques_returns_empty_for_type_without_state_entry(
        self, registry: SchemaRegistry
    ) -> None:
        """get_state_entry_techniques returns empty list for type with no state_entry_techniques."""
        techniques = registry.get_state_entry_techniques(
            "cold_outreach_consultant", "Drafted"
        )
        assert techniques == []

    def test_get_state_entry_techniques_returns_empty_for_unknown_type(
        self, registry: SchemaRegistry
    ) -> None:
        """get_state_entry_techniques returns empty list for unknown opportunity type."""
        techniques = registry.get_state_entry_techniques(
            "nonexistent_type", "Interview"
        )
        assert techniques == []

    def test_prepare_technique_has_trigger_fields(
        self, registry: SchemaRegistry
    ) -> None:
        """interview_preparation prepare technique has trigger and trigger_state fields set."""
        techniques = registry.get_state_entry_techniques("job_site", "Interview")
        assert len(techniques) == 1
        tech = techniques[0]
        assert isinstance(tech, PrepareTechnique)
        assert tech.trigger == "state_entry"
        assert tech.trigger_state == "Interview"

    def test_existing_prepare_techniques_default_to_material_preparation(
        self, registry: SchemaRegistry
    ) -> None:
        """Existing prepare techniques (e.g. cv_and_cover_letter) default to material_preparation."""
        cv_tech = next(
            (t for t in registry.prepare_techniques if t.id == "cv_and_cover_letter"),
            None,
        )
        assert cv_tech is not None
        assert cv_tech.trigger == "material_preparation"
        assert cv_tech.trigger_state is None


# ─── Tests for validation using tmp schemas ───────────────────────────────────


class TestStateEntryValidation:
    """Tests that invalid state-entry technique configurations are rejected."""

    def test_validation_rejects_trigger_state_not_in_pipeline_states(
        self, tmp_path: Path
    ) -> None:
        """SchemaRegistry rejects when trigger_state is not in opportunity type's pipeline_states."""
        schema = _minimal_schema_with_state_entry()
        # Remove "Interview" from pipeline_states so trigger_state becomes invalid
        schema["opportunity_types"][0]["pipeline_states"] = [
            "Applied",
            "Offer",
            "Rejected",
        ]

        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaRegistry(_write_schema(tmp_path, schema))

        assert "trigger_state" in str(exc_info.value)
        assert "Interview" in str(exc_info.value)

    def test_validation_rejects_unknown_state_entry_technique(
        self, tmp_path: Path
    ) -> None:
        """SchemaRegistry rejects when state_entry_techniques references non-existent technique."""
        schema = _minimal_schema_with_state_entry()
        # Reference a technique that doesn't exist
        schema["opportunity_types"][0]["state_entry_techniques"] = [
            "nonexistent_technique"
        ]

        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaRegistry(_write_schema(tmp_path, schema))

        assert "nonexistent_technique" in str(exc_info.value)
