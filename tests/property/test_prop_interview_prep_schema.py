# Feature: interview-prep-technique, Property 5: Schema validation — technique attachable only to types with Interview state
"""Property-based test for schema state-entry validation.

Generates random opportunity type configurations with and without the Interview
state in their pipeline_states, attaching an interview_preparation technique and
verifying that SchemaRegistry accepts only valid configurations.

**Validates: Requirements 3.1**
"""

from pathlib import Path

import yaml
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.schema_registry import SchemaRegistry
from app.core.errors import SchemaValidationError


# ─── Strategies ───────────────────────────────────────────────────────────────

# Generate valid identifier strings (lowercase + underscores, 3-20 chars)
identifier_strategy = st.from_regex(r"[a-z][a-z0-9_]{2,19}", fullmatch=True)

# Pipeline states that are NOT "Interview"
non_interview_states = st.sampled_from([
    "Applied", "Screening", "Offer", "Rejected", "Negotiation",
    "Onboarding", "Assessment", "Reference_Check", "Final_Round",
])


def _minimal_schema() -> dict:
    """Return a minimal valid schema dict for property testing."""
    return {
        "stages": [
            {"id": "find", "label": "Find", "description": "Find stage"},
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
                "pipeline_states": ["Applied", "Interview"],
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


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestSchemaStateEntryValidation:
    """Property 5: Schema validation — technique attachable only to types with Interview state."""

    @given(
        extra_states=st.lists(
            non_interview_states, min_size=0, max_size=4, unique=True
        ),
    )
    @settings(max_examples=100)
    def test_types_with_interview_state_accept_interview_preparation(
        self, extra_states: list[str], tmp_path_factory
    ) -> None:
        """WHEN an opportunity type has Interview in pipeline_states AND
        interview_preparation is declared as a state_entry technique with
        trigger_state=Interview, THEN SchemaRegistry loads without error.

        **Validates: Requirements 3.1**
        """
        schema = _minimal_schema()

        # Build pipeline_states that always include "Interview"
        pipeline_states = list(set(["Interview"] + extra_states))
        schema["opportunity_types"][0]["pipeline_states"] = pipeline_states

        # Add state_entry_techniques reference
        schema["opportunity_types"][0]["state_entry_techniques"] = ["interview_preparation"]

        # Add the interview_preparation prepare technique
        schema["prepare_techniques"].append({
            "id": "interview_preparation",
            "service_class": "InterviewPrepService",
            "description": "Interview preparation pack generation",
            "trigger": "state_entry",
            "trigger_state": "Interview",
        })

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        # Should load without error
        registry = SchemaRegistry(schema_file)
        assert any(
            t.id == "interview_preparation" for t in registry.prepare_techniques
        )

    @given(
        states=st.lists(
            non_interview_states, min_size=1, max_size=5, unique=True
        ),
    )
    @settings(max_examples=100)
    def test_types_without_interview_state_reject_interview_preparation(
        self, states: list[str], tmp_path_factory
    ) -> None:
        """WHEN an opportunity type does NOT have Interview in pipeline_states
        AND interview_preparation with trigger_state=Interview is attached as
        a state_entry_technique, THEN SchemaRegistry raises SchemaValidationError.

        **Validates: Requirements 3.1**
        """
        # Ensure "Interview" is never in our states
        assume("Interview" not in states)

        schema = _minimal_schema()

        # Pipeline states without Interview
        schema["opportunity_types"][0]["pipeline_states"] = states

        # Add state_entry_techniques reference
        schema["opportunity_types"][0]["state_entry_techniques"] = ["interview_preparation"]

        # Add the interview_preparation prepare technique
        schema["prepare_techniques"].append({
            "id": "interview_preparation",
            "service_class": "InterviewPrepService",
            "description": "Interview preparation pack generation",
            "trigger": "state_entry",
            "trigger_state": "Interview",
        })

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        # SchemaRegistry MUST raise SchemaValidationError
        try:
            SchemaRegistry(schema_file)
            raise AssertionError(
                f"SchemaRegistry accepted interview_preparation on type without "
                f"Interview state. pipeline_states={states}"
            )
        except SchemaValidationError as exc:
            # entity_id should be the opportunity type that has the bad config
            assert exc.entity_id == "job_site", (
                f"Expected entity_id='job_site', got entity_id='{exc.entity_id}'"
            )
            # Error should mention trigger_state or Interview
            assert "Interview" in str(exc), (
                f"Expected 'Interview' in error message, got: {exc}"
            )

    @given(
        fake_technique_id=identifier_strategy,
        extra_states=st.lists(
            non_interview_states, min_size=0, max_size=3, unique=True
        ),
    )
    @settings(max_examples=100)
    def test_unknown_state_entry_technique_reference_always_raises(
        self, fake_technique_id: str, extra_states: list[str], tmp_path_factory
    ) -> None:
        """WHEN an opportunity type's state_entry_techniques references a
        technique id NOT declared in prepare_techniques, THEN SchemaRegistry
        ALWAYS raises SchemaValidationError.

        **Validates: Requirements 3.1**
        """
        # Ensure the fake technique is not one of our declared prepare techniques
        assume(fake_technique_id not in ("cv_gen", "interview_preparation"))

        schema = _minimal_schema()

        # Include Interview in pipeline_states (valid setup otherwise)
        pipeline_states = list(set(["Interview"] + extra_states))
        schema["opportunity_types"][0]["pipeline_states"] = pipeline_states

        # Reference a non-existent technique in state_entry_techniques
        schema["opportunity_types"][0]["state_entry_techniques"] = [fake_technique_id]

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        # SchemaRegistry MUST raise SchemaValidationError
        try:
            SchemaRegistry(schema_file)
            raise AssertionError(
                f"SchemaRegistry accepted unknown state_entry_technique '{fake_technique_id}'"
            )
        except SchemaValidationError as exc:
            # entity_id should be the opportunity type
            assert exc.entity_id == "job_site", (
                f"Expected entity_id='job_site', got entity_id='{exc.entity_id}'"
            )
            # Error should mention the fake technique id
            assert fake_technique_id in str(exc), (
                f"Expected '{fake_technique_id}' in error message, got: {exc}"
            )
