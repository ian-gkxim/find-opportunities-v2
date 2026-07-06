"""Unit tests for SchemaRegistry — validates loading, validation, parsing, and query API.

Tests cover Requirements 12.1–12.7: Schema-driven architecture retention.
"""

from pathlib import Path

import pytest
import yaml

from app.core.errors import SchemaValidationError
from app.core.schema_registry import (
    Beneficiary,
    OpportunityType,
    SchemaRegistry,
    Stage,
    Technique,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────


def _minimal_schema() -> dict:
    """Return a minimal valid schema dict for testing."""
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
        ],
        "outreach_techniques": [
            {
                "id": "manual_apply",
                "service_class": "ManualOutreachService",
                "description": "Manual application",
            },
        ],
    }


@pytest.fixture
def valid_schema_path(tmp_path: Path) -> Path:
    """Write a minimal valid schema to a temp file and return the path."""
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(yaml.dump(_minimal_schema()), encoding="utf-8")
    return schema_file


@pytest.fixture
def registry(valid_schema_path: Path) -> SchemaRegistry:
    """Return a SchemaRegistry loaded from a valid minimal schema."""
    return SchemaRegistry(valid_schema_path)


# ─── Loading Tests ────────────────────────────────────────────────────────────


class TestLoading:
    def test_loads_valid_schema(self, registry: SchemaRegistry) -> None:
        """A valid YAML schema loads without error."""
        assert registry is not None
        assert len(registry.stages) == 2
        assert len(registry.beneficiaries) == 1
        assert len(registry.opportunity_types) == 1

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError if the YAML file does not exist."""
        with pytest.raises(SchemaValidationError, match="not found"):
            SchemaRegistry(tmp_path / "nonexistent.yaml")

    def test_raises_on_invalid_yaml(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError if YAML is malformed."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{not: valid: yaml: [", encoding="utf-8")
        with pytest.raises(SchemaValidationError, match="Invalid YAML"):
            SchemaRegistry(bad_file)

    def test_raises_on_non_mapping_root(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError if YAML root is a list, not mapping."""
        bad_file = tmp_path / "list.yaml"
        bad_file.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(SchemaValidationError, match="mapping"):
            SchemaRegistry(bad_file)


# ─── Validation Tests ─────────────────────────────────────────────────────────


class TestValidation:
    def test_missing_top_level_key(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError with entity_id when a top-level key is missing."""
        schema = _minimal_schema()
        del schema["beneficiaries"]
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="beneficiaries") as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "beneficiaries"

    def test_missing_beneficiary_field(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError when a beneficiary is missing a required field."""
        schema = _minimal_schema()
        del schema["beneficiaries"][0]["offerings_asset"]
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="offerings_asset"):
            SchemaRegistry(schema_file)

    def test_empty_baseline_assets(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError when beneficiary has empty baseline_assets."""
        schema = _minimal_schema()
        schema["beneficiaries"][0]["baseline_assets"] = []
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="baseline_assets"):
            SchemaRegistry(schema_file)

    def test_missing_technique_field(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError when a technique is missing service_class."""
        schema = _minimal_schema()
        del schema["find_techniques"][0]["service_class"]
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="service_class"):
            SchemaRegistry(schema_file)

    def test_empty_field_value(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError when a required field has empty string."""
        schema = _minimal_schema()
        schema["beneficiaries"][0]["label"] = "   "
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="empty value"):
            SchemaRegistry(schema_file)


# ─── Cross-Reference Validation Tests ─────────────────────────────────────────


class TestCrossReferenceValidation:
    def test_invalid_beneficiary_reference(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError referencing the opportunity type id."""
        schema = _minimal_schema()
        schema["opportunity_types"][0]["beneficiaries"] = ["nonexistent"]
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="nonexistent") as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "job_site"

    def test_invalid_find_technique_reference(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError for unknown find_technique."""
        schema = _minimal_schema()
        schema["opportunity_types"][0]["find_technique"] = "unknown_tech"
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="unknown_tech") as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "job_site"

    def test_invalid_prepare_technique_reference(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError for unknown prepare_technique."""
        schema = _minimal_schema()
        schema["opportunity_types"][0]["prepare_technique"] = "bad_prep"
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="bad_prep") as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "job_site"

    def test_invalid_outreach_technique_reference(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError for unknown outreach_technique."""
        schema = _minimal_schema()
        schema["opportunity_types"][0]["outreach_technique"] = "bad_outreach"
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="bad_outreach") as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "job_site"

    def test_empty_pipeline_states(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError when opportunity type has no pipeline states."""
        schema = _minimal_schema()
        schema["opportunity_types"][0]["pipeline_states"] = []
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="no pipeline states") as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "job_site"


# ─── Parsing Tests ────────────────────────────────────────────────────────────


class TestParsing:
    def test_beneficiary_dataclass(self, registry: SchemaRegistry) -> None:
        """Beneficiaries are parsed into Beneficiary dataclass instances."""
        assert len(registry.beneficiaries) == 1
        b = registry.beneficiaries[0]
        assert isinstance(b, Beneficiary)
        assert b.id == "consultant"
        assert b.label == "Consultant"
        assert b.baseline_assets == ["resume"]

    def test_opportunity_type_dataclass(self, registry: SchemaRegistry) -> None:
        """OpportunityTypes are parsed into OpportunityType dataclass instances."""
        assert len(registry.opportunity_types) == 1
        ot = registry.opportunity_types[0]
        assert isinstance(ot, OpportunityType)
        assert ot.id == "job_site"
        assert ot.beneficiaries == ["consultant"]
        assert ot.pipeline_states == ["Applied", "Interview", "Offer"]

    def test_technique_dataclass(self, registry: SchemaRegistry) -> None:
        """Techniques are parsed into Technique dataclass instances."""
        assert len(registry.find_techniques) == 1
        t = registry.find_techniques[0]
        assert isinstance(t, Technique)
        assert t.id == "adzuna_discovery"
        assert t.service_class == "AdzunaDiscoveryService"

    def test_technique_with_inputs_outputs(self, tmp_path: Path) -> None:
        """Techniques with inputs/outputs are parsed correctly."""
        schema = _minimal_schema()
        schema["prepare_techniques"][0]["inputs"] = ["resume", "instructions"]
        schema["prepare_techniques"][0]["outputs"] = ["tailored_cv"]
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        reg = SchemaRegistry(schema_file)
        t = reg.prepare_techniques[0]
        assert t.inputs == ["resume", "instructions"]
        assert t.outputs == ["tailored_cv"]

    def test_stage_dataclass(self, registry: SchemaRegistry) -> None:
        """Stages are parsed into Stage dataclass instances."""
        assert len(registry.stages) == 2
        s = registry.stages[0]
        assert isinstance(s, Stage)
        assert s.id == "understand"
        assert s.label == "Understand Us"


# ─── Query API Tests ──────────────────────────────────────────────────────────


class TestQueryAPI:
    def test_get_beneficiary_found(self, registry: SchemaRegistry) -> None:
        """get_beneficiary returns the matching beneficiary."""
        b = registry.get_beneficiary("consultant")
        assert b is not None
        assert b.id == "consultant"

    def test_get_beneficiary_not_found(self, registry: SchemaRegistry) -> None:
        """get_beneficiary returns None for unknown id."""
        assert registry.get_beneficiary("nonexistent") is None

    def test_get_opportunity_types_for_beneficiary(
        self, registry: SchemaRegistry
    ) -> None:
        """Returns opportunity types that include the beneficiary."""
        results = registry.get_opportunity_types_for_beneficiary("consultant")
        assert len(results) == 1
        assert results[0].id == "job_site"

    def test_get_opportunity_types_for_unknown_beneficiary(
        self, registry: SchemaRegistry
    ) -> None:
        """Returns empty list for unknown beneficiary."""
        assert registry.get_opportunity_types_for_beneficiary("unknown") == []

    def test_get_pipeline_states(self, registry: SchemaRegistry) -> None:
        """Returns pipeline states for a known opportunity type."""
        states = registry.get_pipeline_states("job_site")
        assert states == ["Applied", "Interview", "Offer"]

    def test_get_pipeline_states_unknown(self, registry: SchemaRegistry) -> None:
        """Returns empty list for unknown opportunity type."""
        assert registry.get_pipeline_states("nonexistent") == []


# ─── Navigation Derivation Tests ──────────────────────────────────────────────


class TestNavigation:
    def test_derive_navigation_structure(self, registry: SchemaRegistry) -> None:
        """derive_navigation returns a dict keyed by stage id."""
        nav = registry.derive_navigation()
        assert "understand" in nav
        assert "find" in nav
        assert nav["understand"]["label"] == "Understand Us"

    def test_navigation_sub_tabs(self, registry: SchemaRegistry) -> None:
        """Each stage has sub-tabs derived from beneficiaries."""
        nav = registry.derive_navigation()
        sub_tabs = nav["understand"]["sub_tabs"]
        assert len(sub_tabs) == 1
        assert sub_tabs[0]["beneficiary_id"] == "consultant"
        assert sub_tabs[0]["label"] == "Consultant"

    def test_navigation_includes_opportunity_types(
        self, registry: SchemaRegistry
    ) -> None:
        """Sub-tabs include their relevant opportunity types."""
        nav = registry.derive_navigation()
        sub_tabs = nav["find"]["sub_tabs"]
        opp_types = sub_tabs[0]["opportunity_types"]
        assert len(opp_types) == 1
        assert opp_types[0]["id"] == "job_site"
        assert opp_types[0]["pipeline_states"] == ["Applied", "Interview", "Offer"]

    def test_navigation_with_multiple_beneficiaries(self, tmp_path: Path) -> None:
        """Navigation includes sub-tabs for each beneficiary."""
        schema = _minimal_schema()
        schema["beneficiaries"].append(
            {
                "id": "team",
                "label": "Team",
                "description": "Firm",
                "baseline_assets": ["company_profile"],
                "offerings_asset": "docs",
                "offerings_label": "Docs",
                "search_criteria_asset": "criteria",
            }
        )
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        reg = SchemaRegistry(schema_file)
        nav = reg.derive_navigation()
        sub_tabs = nav["understand"]["sub_tabs"]
        assert len(sub_tabs) == 2
        assert sub_tabs[0]["beneficiary_id"] == "consultant"
        assert sub_tabs[1]["beneficiary_id"] == "team"


# ─── Integration Test with Real Schema ────────────────────────────────────────


class TestRealSchema:
    """Validate that the actual config/schema.yaml loads successfully."""

    def test_loads_real_schema(self) -> None:
        """The production schema at config/schema.yaml passes all validation."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        assert len(registry.beneficiaries) >= 2
        assert len(registry.opportunity_types) >= 3
        assert len(registry.stages) >= 3

    def test_real_schema_navigation(self) -> None:
        """The production schema produces a valid navigation structure."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        nav = registry.derive_navigation()
        assert len(nav) == len(registry.stages)
        for stage_id, stage_nav in nav.items():
            assert "label" in stage_nav
            assert "sub_tabs" in stage_nav
            assert len(stage_nav["sub_tabs"]) == len(registry.beneficiaries)
