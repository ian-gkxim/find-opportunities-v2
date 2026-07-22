"""Unit tests for SchemaRegistry — validates loading, validation, parsing, and query API.

Tests cover Requirements 12.1–12.7: Schema-driven architecture retention.
"""

from pathlib import Path

import pytest
import yaml

from app.core.errors import SchemaValidationError
from app.core.schema_registry import (
    Beneficiary,
    GroundingTechnique,
    OpportunityType,
    PrepareTechnique,
    ReviewTechnique,
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

    def test_invalid_review_technique_reference(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError when prepare_technique references unknown review_technique."""
        schema = _minimal_schema()
        schema["prepare_techniques"][0]["review_technique"] = "nonexistent_review"
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(
            SchemaValidationError, match="nonexistent_review"
        ) as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "cv_gen"

    def test_valid_review_technique_reference(self, tmp_path: Path) -> None:
        """No error when prepare_technique references a declared review_technique."""
        schema = _minimal_schema()
        schema["review_techniques"] = [
            {
                "id": "standard_review",
                "service_class": "ReviewService",
                "description": "Standard review",
                "critique_categories": ["missed_keywords"],
                "max_review_cycles": 2,
            }
        ]
        schema["prepare_techniques"][0]["review_technique"] = "standard_review"
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.prepare_techniques[0].review_technique == "standard_review"

    def test_review_technique_reference_absent_is_valid(self, tmp_path: Path) -> None:
        """No error when prepare_technique has no review_technique field."""
        schema = _minimal_schema()
        # No review_technique field on the prepare_technique — should be fine
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.prepare_techniques[0].review_technique is None

    def test_review_technique_reference_with_no_review_section(self, tmp_path: Path) -> None:
        """Raises error when review_technique is set but review_techniques section is absent."""
        schema = _minimal_schema()
        schema["prepare_techniques"][0]["review_technique"] = "some_review"
        # No review_techniques section in the schema
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(
            SchemaValidationError, match="some_review"
        ) as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "cv_gen"


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


# ─── Review Technique Parsing Tests ───────────────────────────────────────────


class TestReviewTechniqueParsing:
    """Tests for Schema_Registry review technique parsing.

    Validates: Requirements 4.1, 4.2
    """

    def test_real_schema_produces_review_technique_instances(self) -> None:
        """Loading the real config/schema.yaml produces ReviewTechnique instances
        for standard_material_review and email_review."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        assert len(registry.review_techniques) == 2
        ids = {rt.id for rt in registry.review_techniques}
        assert "standard_material_review" in ids
        assert "email_review" in ids
        for rt in registry.review_techniques:
            assert isinstance(rt, ReviewTechnique)

    def test_get_review_technique_returns_correct_fields(self) -> None:
        """get_review_technique('standard_material_review') returns a ReviewTechnique
        with max_review_cycles=2 and 4 critique_categories."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        rt = registry.get_review_technique("standard_material_review")
        assert rt is not None
        assert isinstance(rt, ReviewTechnique)
        assert rt.id == "standard_material_review"
        assert rt.service_class == "ReviewService"
        assert rt.max_review_cycles == 2
        assert len(rt.critique_categories) == 4
        assert set(rt.critique_categories) == {
            "missed_keywords",
            "company_angles",
            "reframing",
            "tone_style",
        }

    def test_email_review_technique_fields(self) -> None:
        """email_review has max_review_cycles=1 and all 4 critique categories."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        rt = registry.get_review_technique("email_review")
        assert rt is not None
        assert isinstance(rt, ReviewTechnique)
        assert rt.id == "email_review"
        assert rt.service_class == "ReviewService"
        assert rt.max_review_cycles == 1
        assert len(rt.critique_categories) == 4
        assert set(rt.critique_categories) == {
            "missed_keywords",
            "company_angles",
            "reframing",
            "tone_style",
        }

    def test_get_review_technique_nonexistent_returns_none(self) -> None:
        """get_review_technique('nonexistent') returns None."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        assert registry.get_review_technique("nonexistent") is None

    def test_get_review_technique_for_prepare_cv_and_cover_letter(self) -> None:
        """get_review_technique_for_prepare('cv_and_cover_letter') returns
        the standard_material_review technique."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        rt = registry.get_review_technique_for_prepare("cv_and_cover_letter")
        assert rt is not None
        assert rt.id == "standard_material_review"

    def test_get_review_technique_for_prepare_cold_email(self) -> None:
        """get_review_technique_for_prepare('cold_email_composition') returns
        the email_review technique."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        rt = registry.get_review_technique_for_prepare("cold_email_composition")
        assert rt is not None
        assert rt.id == "email_review"

    def test_get_review_technique_for_prepare_nonexistent(self) -> None:
        """get_review_technique_for_prepare('nonexistent') returns None."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        assert registry.get_review_technique_for_prepare("nonexistent") is None

    def test_schema_without_review_techniques_section(self, tmp_path: Path) -> None:
        """A schema with NO review_techniques section loads successfully
        with an empty review_techniques list."""
        schema = _minimal_schema()
        # Ensure no review_techniques key exists
        assert "review_techniques" not in schema
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.review_techniques == []
        # Any lookup should return None
        assert registry.get_review_technique_for_prepare("cv_gen") is None

    def test_prepare_technique_without_review_technique_field(self, tmp_path: Path) -> None:
        """Prepare techniques without a review_technique field have
        review_technique = None."""
        schema = _minimal_schema()
        # The minimal schema's prepare_technique has no review_technique field
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        pt = registry.prepare_techniques[0]
        assert isinstance(pt, PrepareTechnique)
        assert pt.review_technique is None
        # Also confirm the lookup returns None
        assert registry.get_review_technique_for_prepare("cv_gen") is None

    def test_prepare_techniques_are_dataclass_instances_with_review_field(self) -> None:
        """Real schema prepare_techniques are PrepareTechnique instances with
        the review_technique field correctly populated."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        # All prepare_techniques should be PrepareTechnique instances
        for pt in registry.prepare_techniques:
            assert isinstance(pt, PrepareTechnique)
            assert hasattr(pt, "review_technique")

        # Verify specific wiring
        cv_pt = next(p for p in registry.prepare_techniques if p.id == "cv_and_cover_letter")
        assert cv_pt.review_technique == "standard_material_review"

        email_pt = next(p for p in registry.prepare_techniques if p.id == "cold_email_composition")
        assert email_pt.review_technique == "email_review"

        proposal_pt = next(p for p in registry.prepare_techniques if p.id == "proposal_composition")
        assert proposal_pt.review_technique == "standard_material_review"



# ─── Grounding Technique Tests ────────────────────────────────────────────────


def _minimal_schema_with_grounding() -> dict:
    """Return a minimal valid schema dict with grounding_techniques for testing."""
    schema = _minimal_schema()
    schema["grounding_techniques"] = [
        {
            "id": "standard_grounding",
            "service_class": "GroundingVerifier",
            "description": "Extract and verify factual claims against profile assets",
            "claim_categories": [
                "skill_technology",
                "achievement_outcome",
                "quantified_metric",
                "credential_certification",
                "named_client_employer",
                "experience_duration",
            ],
            "extraction_timeout_seconds": 60,
            "verification_timeout_seconds": 30,
            "max_retries": 2,
        }
    ]
    return schema


class TestGroundingTechniqueValidation:
    """Tests for grounding_technique reference validation on prepare_techniques.

    Validates: Requirements 1.1, 1.2
    """

    def test_invalid_grounding_technique_reference(self, tmp_path: Path) -> None:
        """Raises SchemaValidationError when prepare_technique references unknown grounding_technique."""
        schema = _minimal_schema()
        schema["prepare_techniques"][0]["grounding_technique"] = "nonexistent_grounding"
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(
            SchemaValidationError, match="nonexistent_grounding"
        ) as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "cv_gen"

    def test_valid_grounding_technique_reference(self, tmp_path: Path) -> None:
        """No error when prepare_technique references a declared grounding_technique."""
        schema = _minimal_schema_with_grounding()
        schema["prepare_techniques"][0]["grounding_technique"] = "standard_grounding"
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.prepare_techniques[0].grounding_technique == "standard_grounding"

    def test_grounding_technique_reference_absent_is_valid(self, tmp_path: Path) -> None:
        """No error when prepare_technique has no grounding_technique field."""
        schema = _minimal_schema()
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.prepare_techniques[0].grounding_technique is None

    def test_grounding_technique_reference_with_no_grounding_section(
        self, tmp_path: Path
    ) -> None:
        """Raises error when grounding_technique is set but grounding_techniques section is absent."""
        schema = _minimal_schema()
        schema["prepare_techniques"][0]["grounding_technique"] = "some_grounding"
        # No grounding_techniques section in the schema
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(
            SchemaValidationError, match="some_grounding"
        ) as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "cv_gen"


class TestGroundingTechniqueParsing:
    """Tests for GroundingTechnique dataclass parsing.

    Validates: Requirements 1.1, 1.2
    """

    def test_parses_grounding_techniques(self, tmp_path: Path) -> None:
        """Grounding techniques are parsed into GroundingTechnique dataclass instances."""
        schema = _minimal_schema_with_grounding()
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert len(registry.grounding_techniques) == 1
        gt = registry.grounding_techniques[0]
        assert isinstance(gt, GroundingTechnique)
        assert gt.id == "standard_grounding"
        assert gt.service_class == "GroundingVerifier"
        assert gt.description == "Extract and verify factual claims against profile assets"
        assert gt.claim_categories == [
            "skill_technology",
            "achievement_outcome",
            "quantified_metric",
            "credential_certification",
            "named_client_employer",
            "experience_duration",
        ]
        assert gt.extraction_timeout_seconds == 60
        assert gt.verification_timeout_seconds == 30
        assert gt.max_retries == 2

    def test_grounding_technique_defaults(self, tmp_path: Path) -> None:
        """GroundingTechnique uses default values for optional timeout/retry fields."""
        schema = _minimal_schema()
        schema["grounding_techniques"] = [
            {
                "id": "minimal_grounding",
                "service_class": "GroundingVerifier",
                "description": "Minimal grounding technique",
            }
        ]
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        gt = registry.grounding_techniques[0]
        assert gt.extraction_timeout_seconds == 60
        assert gt.verification_timeout_seconds == 30
        assert gt.max_retries == 2
        assert gt.claim_categories == []

    def test_no_grounding_techniques_section(self, tmp_path: Path) -> None:
        """A schema with NO grounding_techniques section loads with empty list."""
        schema = _minimal_schema()
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.grounding_techniques == []

    def test_prepare_technique_has_grounding_technique_field(self, tmp_path: Path) -> None:
        """PrepareTechnique instances include the grounding_technique field."""
        schema = _minimal_schema_with_grounding()
        schema["prepare_techniques"][0]["grounding_technique"] = "standard_grounding"
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        pt = registry.prepare_techniques[0]
        assert isinstance(pt, PrepareTechnique)
        assert pt.grounding_technique == "standard_grounding"


# ─── Voice Asset Placement Validation Tests ───────────────────────────────────


def _schema_with_two_beneficiaries() -> dict:
    """Return a valid schema with both consultant and team beneficiaries."""
    schema = _minimal_schema()
    schema["beneficiaries"].append(
        {
            "id": "team",
            "label": "Team",
            "description": "GKIM as a firm",
            "baseline_assets": ["company_profile"],
            "offerings_asset": "company_documents",
            "offerings_label": "Offerings",
            "search_criteria_asset": "project_search_criteria",
        }
    )
    return schema


class TestVoiceAssetPlacementValidation:
    """Tests for Schema_Registry voice asset placement validation.

    Validates: Requirements 1.1
    """

    def test_brand_voice_on_consultant_raises(self, tmp_path: Path) -> None:
        """brand_voice declared on a consultant beneficiary raises SchemaValidationError."""
        schema = _schema_with_two_beneficiaries()
        schema["beneficiaries"][0]["baseline_assets"].append("brand_voice")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="brand_voice") as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "consultant"

    def test_writing_style_on_team_raises(self, tmp_path: Path) -> None:
        """writing_style declared on team beneficiary raises SchemaValidationError."""
        schema = _schema_with_two_beneficiaries()
        schema["beneficiaries"][1]["baseline_assets"].append("writing_style")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(SchemaValidationError, match="consultant-only") as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "team"

    def test_behavioral_profile_without_writing_style_raises(self, tmp_path: Path) -> None:
        """behavioral_profile declared without writing_style raises SchemaValidationError."""
        schema = _schema_with_two_beneficiaries()
        schema["beneficiaries"][0]["baseline_assets"].append("behavioral_profile")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        with pytest.raises(
            SchemaValidationError, match="behavioral_profile.*without writing_style"
        ) as exc_info:
            SchemaRegistry(schema_file)
        assert exc_info.value.entity_id == "consultant"

    def test_writing_style_and_behavioral_profile_on_consultant_valid(
        self, tmp_path: Path
    ) -> None:
        """writing_style + behavioral_profile on consultant passes validation."""
        schema = _schema_with_two_beneficiaries()
        schema["beneficiaries"][0]["baseline_assets"].extend(
            ["writing_style", "behavioral_profile"]
        )
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        b = registry.get_beneficiary("consultant")
        assert b is not None
        assert "writing_style" in b.baseline_assets
        assert "behavioral_profile" in b.baseline_assets

    def test_brand_voice_on_team_valid(self, tmp_path: Path) -> None:
        """brand_voice on team beneficiary passes validation."""
        schema = _schema_with_two_beneficiaries()
        schema["beneficiaries"][1]["baseline_assets"].append("brand_voice")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        b = registry.get_beneficiary("team")
        assert b is not None
        assert "brand_voice" in b.baseline_assets

    def test_writing_style_only_on_consultant_valid(self, tmp_path: Path) -> None:
        """Only writing_style on consultant (no behavioral_profile) passes validation."""
        schema = _schema_with_two_beneficiaries()
        schema["beneficiaries"][0]["baseline_assets"].append("writing_style")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        b = registry.get_beneficiary("consultant")
        assert b is not None
        assert "writing_style" in b.baseline_assets
        assert "behavioral_profile" not in b.baseline_assets


class TestGroundingTechniqueLookup:
    """Tests for grounding technique lookup methods.

    Validates: Requirements 1.1, 1.2
    """

    def test_get_grounding_technique_found(self, tmp_path: Path) -> None:
        """get_grounding_technique returns the matching GroundingTechnique."""
        schema = _minimal_schema_with_grounding()
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        gt = registry.get_grounding_technique("standard_grounding")
        assert gt is not None
        assert gt.id == "standard_grounding"
        assert isinstance(gt, GroundingTechnique)

    def test_get_grounding_technique_not_found(self, tmp_path: Path) -> None:
        """get_grounding_technique returns None for unknown id."""
        schema = _minimal_schema_with_grounding()
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.get_grounding_technique("nonexistent") is None

    def test_get_grounding_technique_for_prepare_found(self, tmp_path: Path) -> None:
        """get_grounding_technique_for_prepare returns the linked GroundingTechnique."""
        schema = _minimal_schema_with_grounding()
        schema["prepare_techniques"][0]["grounding_technique"] = "standard_grounding"
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        gt = registry.get_grounding_technique_for_prepare("cv_gen")
        assert gt is not None
        assert gt.id == "standard_grounding"

    def test_get_grounding_technique_for_prepare_no_grounding(self, tmp_path: Path) -> None:
        """get_grounding_technique_for_prepare returns None when no grounding_technique is set."""
        schema = _minimal_schema()
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.get_grounding_technique_for_prepare("cv_gen") is None

    def test_get_grounding_technique_for_prepare_nonexistent_prepare(self, tmp_path: Path) -> None:
        """get_grounding_technique_for_prepare returns None for unknown prepare_technique_id."""
        schema = _minimal_schema_with_grounding()
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.get_grounding_technique_for_prepare("nonexistent") is None


# ─── Length Constraint Parsing Tests ──────────────────────────────────────────


class TestLengthConstraintParsing:
    """Tests for Schema_Registry length_constraints parsing.

    Validates: Requirements 3.1
    """

    def test_parses_max_words_constraint(self, tmp_path: Path) -> None:
        """Parses length_constraints with max_words from prepare technique."""
        schema = _minimal_schema()
        schema["prepare_techniques"][0]["outputs"] = ["tailored_cv"]
        schema["prepare_techniques"][0]["length_constraints"] = {
            "tailored_cv": {"max_words": 800}
        }
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        constraint = registry.get_length_constraint("tailored_cv")
        assert constraint is not None
        assert constraint.constraint_type.value == "max_words"
        assert constraint.max_value == 800

    def test_parses_max_characters_constraint(self, tmp_path: Path) -> None:
        """Parses length_constraints with max_characters from prepare technique."""
        schema = _minimal_schema()
        schema["prepare_techniques"][0]["outputs"] = ["draft_email"]
        schema["prepare_techniques"][0]["length_constraints"] = {
            "draft_email": {"max_characters": 2000}
        }
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        constraint = registry.get_length_constraint("draft_email")
        assert constraint is not None
        assert constraint.constraint_type.value == "max_characters"
        assert constraint.max_value == 2000

    def test_parses_max_units_constraint(self, tmp_path: Path) -> None:
        """Parses length_constraints with max_units from prepare technique."""
        schema = _minimal_schema()
        schema["prepare_techniques"][0]["outputs"] = ["skills_list"]
        schema["prepare_techniques"][0]["length_constraints"] = {
            "skills_list": {"max_units": 10}
        }
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        constraint = registry.get_length_constraint("skills_list")
        assert constraint is not None
        assert constraint.constraint_type.value == "max_units"
        assert constraint.max_value == 10

    def test_parses_multiple_constraints_on_one_technique(self, tmp_path: Path) -> None:
        """Parses multiple length_constraints from a single prepare technique."""
        schema = _minimal_schema()
        schema["prepare_techniques"][0]["outputs"] = ["tailored_cv", "tailored_cover_letter"]
        schema["prepare_techniques"][0]["length_constraints"] = {
            "tailored_cv": {"max_words": 800},
            "tailored_cover_letter": {"max_words": 400},
        }
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)

        cv_constraint = registry.get_length_constraint("tailored_cv")
        assert cv_constraint is not None
        assert cv_constraint.max_value == 800

        cl_constraint = registry.get_length_constraint("tailored_cover_letter")
        assert cl_constraint is not None
        assert cl_constraint.max_value == 400

    def test_no_length_constraints_returns_none(self, registry: SchemaRegistry) -> None:
        """get_length_constraint returns None when no constraints are declared."""
        assert registry.get_length_constraint("tailored_cv") is None
        assert registry.get_length_constraint("nonexistent") is None

    def test_missing_length_constraints_field_is_handled(self, tmp_path: Path) -> None:
        """A prepare technique without length_constraints field loads successfully."""
        schema = _minimal_schema()
        # No length_constraints field — should be fine
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.get_length_constraint("anything") is None

    def test_empty_length_constraints_mapping_is_handled(self, tmp_path: Path) -> None:
        """A prepare technique with an empty length_constraints mapping loads fine."""
        schema = _minimal_schema()
        schema["prepare_techniques"][0]["length_constraints"] = {}
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)
        assert registry.get_length_constraint("anything") is None

    def test_constraints_from_multiple_prepare_techniques(self, tmp_path: Path) -> None:
        """Length constraints from multiple prepare techniques are all accessible."""
        schema = _minimal_schema()
        # Add a second prepare technique
        schema["prepare_techniques"].append({
            "id": "email_gen",
            "service_class": "EmailService",
            "description": "Email generation",
            "outputs": ["draft_email"],
            "length_constraints": {
                "draft_email": {"max_words": 250}
            },
        })
        # Add constraint to first technique
        schema["prepare_techniques"][0]["outputs"] = ["tailored_cv"]
        schema["prepare_techniques"][0]["length_constraints"] = {
            "tailored_cv": {"max_words": 800}
        }
        # Update opportunity type to reference the new technique
        schema["opportunity_types"].append({
            "id": "cold_outreach",
            "label": "Cold Outreach",
            "beneficiaries": ["consultant"],
            "source_asset": "criteria",
            "source_label": "Criteria",
            "find_technique": "adzuna_discovery",
            "find_label": "From Outreach",
            "prepare_technique": "email_gen",
            "outreach_technique": "manual_apply",
            "pipeline_states": ["Drafted", "Sent"],
        })
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        registry = SchemaRegistry(schema_file)

        cv_constraint = registry.get_length_constraint("tailored_cv")
        assert cv_constraint is not None
        assert cv_constraint.max_value == 800

        email_constraint = registry.get_length_constraint("draft_email")
        assert email_constraint is not None
        assert email_constraint.max_value == 250

    def test_real_schema_no_constraints_currently(self) -> None:
        """The current production schema has no length_constraints (graceful handling)."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        # Currently no length_constraints in the real schema
        assert registry.get_length_constraint("tailored_cv") is None
        assert registry.get_length_constraint("draft_email") is None
