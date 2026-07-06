"""Schema integration tests — verifies production config/schema.yaml loading and validation.

Tests that the SchemaRegistry correctly loads, validates, and parses the
production schema, that navigation is correctly derived, and that all
cross-references are valid.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7
"""

from pathlib import Path

import pytest

from app.core.errors import SchemaValidationError
from app.core.schema_registry import (
    Beneficiary,
    OpportunityType,
    SchemaRegistry,
    Stage,
    Technique,
)


# Path to the production schema.yaml
SCHEMA_PATH = Path(__file__).parent.parent.parent / "config" / "schema.yaml"


# ─── Test: Loading production schema ──────────────────────────────────────────


class TestSchemaLoading:
    """Tests that the production schema.yaml loads successfully."""

    def test_production_schema_loads_without_error(self):
        """The production config/schema.yaml can be loaded and parsed."""
        registry = SchemaRegistry(SCHEMA_PATH)
        assert registry is not None

    def test_schema_has_required_collections(self):
        """Registry exposes all expected typed collections after loading."""
        registry = SchemaRegistry(SCHEMA_PATH)

        assert hasattr(registry, "stages")
        assert hasattr(registry, "beneficiaries")
        assert hasattr(registry, "opportunity_types")
        assert hasattr(registry, "find_techniques")
        assert hasattr(registry, "prepare_techniques")
        assert hasattr(registry, "outreach_techniques")


    def test_schema_types_are_correct(self):
        """All parsed entities are proper typed dataclass instances."""
        registry = SchemaRegistry(SCHEMA_PATH)

        assert all(isinstance(s, Stage) for s in registry.stages)
        assert all(isinstance(b, Beneficiary) for b in registry.beneficiaries)
        assert all(isinstance(ot, OpportunityType) for ot in registry.opportunity_types)
        assert all(isinstance(t, Technique) for t in registry.find_techniques)
        assert all(isinstance(t, Technique) for t in registry.prepare_techniques)
        assert all(isinstance(t, Technique) for t in registry.outreach_techniques)


# ─── Test: SchemaRegistry validates and parses ────────────────────────────────


class TestSchemaValidation:
    """Tests that SchemaRegistry validation works on the production schema."""

    def test_all_beneficiaries_have_required_fields(self):
        """Each beneficiary has id, label, description, baseline_assets, etc."""
        registry = SchemaRegistry(SCHEMA_PATH)

        for ben in registry.beneficiaries:
            assert ben.id, f"Beneficiary missing id"
            assert ben.label, f"Beneficiary {ben.id} missing label"
            assert ben.description, f"Beneficiary {ben.id} missing description"
            assert len(ben.baseline_assets) >= 1, (
                f"Beneficiary {ben.id} needs at least one baseline_assets"
            )
            assert ben.offerings_asset, f"Beneficiary {ben.id} missing offerings_asset"
            assert ben.offerings_label, f"Beneficiary {ben.id} missing offerings_label"
            assert ben.search_criteria_asset, (
                f"Beneficiary {ben.id} missing search_criteria_asset"
            )

    def test_all_techniques_have_required_fields(self):
        """Each technique (find, prepare, outreach) has id, service_class, description."""
        registry = SchemaRegistry(SCHEMA_PATH)

        all_techniques = (
            registry.find_techniques
            + registry.prepare_techniques
            + registry.outreach_techniques
        )
        for tech in all_techniques:
            assert tech.id, "Technique missing id"
            assert tech.service_class, f"Technique {tech.id} missing service_class"
            assert tech.description, f"Technique {tech.id} missing description"

    def test_all_opportunity_types_have_pipeline_states(self):
        """Every opportunity type declares at least one pipeline state."""
        registry = SchemaRegistry(SCHEMA_PATH)

        for ot in registry.opportunity_types:
            assert len(ot.pipeline_states) >= 1, (
                f"OpportunityType {ot.id} has no pipeline states"
            )

    def test_all_stages_have_required_fields(self):
        """Each stage has id, label, and description."""
        registry = SchemaRegistry(SCHEMA_PATH)

        for stage in registry.stages:
            assert stage.id, "Stage missing id"
            assert stage.label, f"Stage {stage.id} missing label"
            assert stage.description, f"Stage {stage.id} missing description"


# ─── Test: Cross-references are valid ─────────────────────────────────────────


class TestSchemaCrossReferences:
    """Tests that all cross-references in the schema are valid."""

    def test_opportunity_types_reference_valid_beneficiaries(self):
        """Each opportunity type references only declared beneficiary ids."""
        registry = SchemaRegistry(SCHEMA_PATH)
        beneficiary_ids = {b.id for b in registry.beneficiaries}

        for ot in registry.opportunity_types:
            for ben_id in ot.beneficiaries:
                assert ben_id in beneficiary_ids, (
                    f"OpportunityType {ot.id} references unknown "
                    f"beneficiary '{ben_id}'"
                )

    def test_opportunity_types_reference_valid_find_techniques(self):
        """Each opportunity type references a declared find technique."""
        registry = SchemaRegistry(SCHEMA_PATH)
        find_ids = {t.id for t in registry.find_techniques}

        for ot in registry.opportunity_types:
            assert ot.find_technique in find_ids, (
                f"OpportunityType {ot.id} references unknown "
                f"find_technique '{ot.find_technique}'"
            )

    def test_opportunity_types_reference_valid_prepare_techniques(self):
        """Each opportunity type references a declared prepare technique."""
        registry = SchemaRegistry(SCHEMA_PATH)
        prepare_ids = {t.id for t in registry.prepare_techniques}

        for ot in registry.opportunity_types:
            assert ot.prepare_technique in prepare_ids, (
                f"OpportunityType {ot.id} references unknown "
                f"prepare_technique '{ot.prepare_technique}'"
            )

    def test_opportunity_types_reference_valid_outreach_techniques(self):
        """Each opportunity type references a declared outreach technique."""
        registry = SchemaRegistry(SCHEMA_PATH)
        outreach_ids = {t.id for t in registry.outreach_techniques}

        for ot in registry.opportunity_types:
            assert ot.outreach_technique in outreach_ids, (
                f"OpportunityType {ot.id} references unknown "
                f"outreach_technique '{ot.outreach_technique}'"
            )

    def test_no_duplicate_ids_across_entities(self):
        """All entity ids within their category are unique."""
        registry = SchemaRegistry(SCHEMA_PATH)

        # Beneficiary ids
        ben_ids = [b.id for b in registry.beneficiaries]
        assert len(ben_ids) == len(set(ben_ids)), "Duplicate beneficiary ids found"

        # Opportunity type ids
        ot_ids = [ot.id for ot in registry.opportunity_types]
        assert len(ot_ids) == len(set(ot_ids)), "Duplicate opportunity_type ids found"

        # Stage ids
        stage_ids = [s.id for s in registry.stages]
        assert len(stage_ids) == len(set(stage_ids)), "Duplicate stage ids found"

        # Technique ids (within each category)
        find_ids = [t.id for t in registry.find_techniques]
        assert len(find_ids) == len(set(find_ids)), "Duplicate find_technique ids"

        prepare_ids = [t.id for t in registry.prepare_techniques]
        assert len(prepare_ids) == len(set(prepare_ids)), "Duplicate prepare_technique ids"

        outreach_ids = [t.id for t in registry.outreach_techniques]
        assert len(outreach_ids) == len(set(outreach_ids)), "Duplicate outreach_technique ids"


# ─── Test: Navigation structure derivation ────────────────────────────────────


class TestNavigationDerivation:
    """Tests that navigation structure is correctly derived from schema."""

    def test_navigation_has_all_stages(self):
        """Derived navigation includes an entry for every stage."""
        registry = SchemaRegistry(SCHEMA_PATH)
        nav = registry.derive_navigation()

        for stage in registry.stages:
            assert stage.id in nav, f"Stage '{stage.id}' missing from navigation"

    def test_navigation_stage_labels_match(self):
        """Navigation stage labels match the declared stage labels."""
        registry = SchemaRegistry(SCHEMA_PATH)
        nav = registry.derive_navigation()

        for stage in registry.stages:
            assert nav[stage.id]["label"] == stage.label

    def test_navigation_sub_tabs_contain_beneficiaries(self):
        """Each stage's sub_tabs include entries for each beneficiary."""
        registry = SchemaRegistry(SCHEMA_PATH)
        nav = registry.derive_navigation()

        beneficiary_ids = {b.id for b in registry.beneficiaries}

        for stage in registry.stages:
            sub_tabs = nav[stage.id]["sub_tabs"]
            sub_tab_ben_ids = {st["beneficiary_id"] for st in sub_tabs}
            assert sub_tab_ben_ids == beneficiary_ids, (
                f"Stage '{stage.id}' sub_tabs don't cover all beneficiaries"
            )

    def test_navigation_sub_tabs_have_opportunity_types(self):
        """Sub-tabs include opportunity types for the correct beneficiary."""
        registry = SchemaRegistry(SCHEMA_PATH)
        nav = registry.derive_navigation()

        for stage in registry.stages:
            for sub_tab in nav[stage.id]["sub_tabs"]:
                ben_id = sub_tab["beneficiary_id"]
                opp_types = sub_tab["opportunity_types"]

                # All listed opportunity types should include this beneficiary
                for ot in opp_types:
                    full_ot = next(
                        o for o in registry.opportunity_types if o.id == ot["id"]
                    )
                    assert ben_id in full_ot.beneficiaries, (
                        f"OpportunityType {ot['id']} listed under beneficiary "
                        f"'{ben_id}' but doesn't declare that beneficiary"
                    )

    def test_navigation_opportunity_types_include_pipeline_states(self):
        """Opportunity types in navigation include their pipeline states."""
        registry = SchemaRegistry(SCHEMA_PATH)
        nav = registry.derive_navigation()

        for stage in registry.stages:
            for sub_tab in nav[stage.id]["sub_tabs"]:
                for ot_nav in sub_tab["opportunity_types"]:
                    full_ot = next(
                        o for o in registry.opportunity_types
                        if o.id == ot_nav["id"]
                    )
                    assert ot_nav["pipeline_states"] == full_ot.pipeline_states


# ─── Test: Schema lookup methods ─────────────────────────────────────────────


class TestSchemaLookups:
    """Tests for SchemaRegistry lookup methods."""

    def test_get_beneficiary_by_id(self):
        """get_beneficiary returns the correct beneficiary or None."""
        registry = SchemaRegistry(SCHEMA_PATH)

        consultant = registry.get_beneficiary("consultant")
        assert consultant is not None
        assert consultant.label == "Consultant"

        team = registry.get_beneficiary("team")
        assert team is not None
        assert team.label == "Team"

        unknown = registry.get_beneficiary("nonexistent")
        assert unknown is None

    def test_get_opportunity_types_for_beneficiary(self):
        """Returns opportunity types that include the given beneficiary."""
        registry = SchemaRegistry(SCHEMA_PATH)

        consultant_types = registry.get_opportunity_types_for_beneficiary("consultant")
        assert len(consultant_types) >= 1
        for ot in consultant_types:
            assert "consultant" in ot.beneficiaries

        team_types = registry.get_opportunity_types_for_beneficiary("team")
        assert len(team_types) >= 1
        for ot in team_types:
            assert "team" in ot.beneficiaries

    def test_get_pipeline_states_for_opportunity_type(self):
        """Returns ordered pipeline states for a specific opportunity type."""
        registry = SchemaRegistry(SCHEMA_PATH)

        # Cold outreach consultant pipeline
        consultant_states = registry.get_pipeline_states("cold_outreach_consultant")
        assert consultant_states == [
            "Drafted", "Sent", "Replied", "Meeting Booked", "Converted"
        ]

        # Cold outreach team pipeline
        team_states = registry.get_pipeline_states("cold_outreach_team")
        assert team_states == [
            "Drafted", "Sent", "Replied", "Proposal Requested", "Won", "Lost"
        ]

        # Unknown type returns empty list
        assert registry.get_pipeline_states("nonexistent") == []


# ─── Test: Schema validation rejects invalid schemas ──────────────────────────


class TestSchemaValidationRejectsInvalid:
    """Tests that SchemaRegistry rejects invalid schema configurations."""

    def test_rejects_missing_top_level_key(self, tmp_path):
        """Schema without required top-level key raises SchemaValidationError."""
        invalid_schema = tmp_path / "invalid.yaml"
        invalid_schema.write_text(
            """
stages:
  - id: understand
    label: "Understand"
    description: "Test"
beneficiaries:
  - id: consultant
    label: "Consultant"
    description: "Test"
    baseline_assets: [resume]
    offerings_asset: profiles
    offerings_label: "Offerings"
    search_criteria_asset: criteria
opportunity_types: []
find_techniques: []
prepare_techniques: []
# Missing outreach_techniques
"""
        )

        with pytest.raises(SchemaValidationError, match="outreach_techniques"):
            SchemaRegistry(invalid_schema)

    def test_rejects_invalid_beneficiary_reference(self, tmp_path):
        """Schema with invalid beneficiary cross-reference raises error."""
        invalid_schema = tmp_path / "invalid_ref.yaml"
        invalid_schema.write_text(
            """
stages:
  - id: find
    label: "Find"
    description: "Test"
beneficiaries:
  - id: consultant
    label: "Consultant"
    description: "Test"
    baseline_assets: [resume]
    offerings_asset: profiles
    offerings_label: "Offerings"
    search_criteria_asset: criteria
opportunity_types:
  - id: job_site
    label: "Job Sites"
    beneficiaries: [nonexistent_beneficiary]
    source_asset: sites
    source_label: "Sites"
    find_technique: adzuna
    find_label: "Find"
    prepare_technique: cv_gen
    outreach_technique: manual
    pipeline_states: [Applied]
find_techniques:
  - id: adzuna
    service_class: AdzunaService
    description: "Adzuna discovery"
prepare_techniques:
  - id: cv_gen
    service_class: CVService
    description: "CV generation"
outreach_techniques:
  - id: manual
    service_class: ManualService
    description: "Manual outreach"
"""
        )

        with pytest.raises(SchemaValidationError, match="nonexistent_beneficiary"):
            SchemaRegistry(invalid_schema)

    def test_rejects_opportunity_type_with_no_pipeline_states(self, tmp_path):
        """Schema where an opportunity type has empty pipeline_states raises error."""
        invalid_schema = tmp_path / "no_states.yaml"
        invalid_schema.write_text(
            """
stages:
  - id: find
    label: "Find"
    description: "Test"
beneficiaries:
  - id: consultant
    label: "Consultant"
    description: "Test"
    baseline_assets: [resume]
    offerings_asset: profiles
    offerings_label: "Offerings"
    search_criteria_asset: criteria
opportunity_types:
  - id: job_site
    label: "Job Sites"
    beneficiaries: [consultant]
    source_asset: sites
    source_label: "Sites"
    find_technique: adzuna
    find_label: "Find"
    prepare_technique: cv_gen
    outreach_technique: manual
    pipeline_states: []
find_techniques:
  - id: adzuna
    service_class: AdzunaService
    description: "Adzuna discovery"
prepare_techniques:
  - id: cv_gen
    service_class: CVService
    description: "CV generation"
outreach_techniques:
  - id: manual
    service_class: ManualService
    description: "Manual outreach"
"""
        )

        with pytest.raises(SchemaValidationError, match="no pipeline states"):
            SchemaRegistry(invalid_schema)

    def test_rejects_nonexistent_schema_file(self, tmp_path):
        """Loading a non-existent schema file raises SchemaValidationError."""
        with pytest.raises(SchemaValidationError, match="not found"):
            SchemaRegistry(tmp_path / "does_not_exist.yaml")
