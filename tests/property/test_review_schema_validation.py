# Feature: review-critique-loop, Property 9: Schema validation rejects dangling review_technique references
"""Property-based test for schema cross-reference validation.

Generates random schema YAML configurations with valid and invalid
review_technique references, verifying that the SchemaRegistry ALWAYS
rejects dangling references with SchemaValidationError containing the
correct entity_id.

**Validates: Requirements 4, AC 3**
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


@st.composite
def review_technique_entry(draw, technique_id=None):
    """Generate a valid review_technique entry dict."""
    tid = technique_id or draw(identifier_strategy)
    return {
        "id": tid,
        "service_class": "ReviewService",
        "description": draw(st.text(min_size=3, max_size=40)),
        "critique_categories": draw(
            st.lists(
                st.sampled_from(["missed_keywords", "company_angles", "reframing", "tone_style"]),
                min_size=1,
                max_size=4,
                unique=True,
            )
        ),
        "max_review_cycles": draw(st.integers(min_value=1, max_value=3)),
    }


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestSchemaReviewTechniqueValidation:
    """Property 9: Schema validation rejects dangling review_technique references."""

    @given(
        valid_review_ids=st.lists(
            identifier_strategy, min_size=1, max_size=5, unique=True
        ),
        invalid_ref=identifier_strategy,
    )
    @settings(max_examples=100)
    def test_invalid_review_technique_reference_always_raises(
        self, valid_review_ids: list[str], invalid_ref: str, tmp_path_factory
    ) -> None:
        """WHEN a prepare_technique references a review_technique id that is NOT
        declared in the review_techniques section, THEN SchemaRegistry ALWAYS
        raises SchemaValidationError with entity_id matching the prepare_technique id.

        **Validates: Requirement 4, AC 3**
        """
        # Ensure the invalid reference is truly not in the valid set
        assume(invalid_ref not in valid_review_ids)

        schema = _minimal_schema()

        # Add valid review_techniques section
        schema["review_techniques"] = [
            {
                "id": rid,
                "service_class": "ReviewService",
                "description": f"Review technique {rid}",
                "critique_categories": ["missed_keywords"],
                "max_review_cycles": 1,
            }
            for rid in valid_review_ids
        ]

        # Set the prepare_technique to reference an invalid (dangling) id
        schema["prepare_techniques"][0]["review_technique"] = invalid_ref

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        # SchemaRegistry MUST raise SchemaValidationError
        try:
            SchemaRegistry(schema_file)
            # If we get here, the test fails — dangling ref was not rejected
            raise AssertionError(
                f"SchemaRegistry accepted dangling review_technique reference '{invalid_ref}'"
            )
        except SchemaValidationError as exc:
            # entity_id must match the prepare_technique id that has the bad reference
            assert exc.entity_id == "cv_gen", (
                f"Expected entity_id='cv_gen', got entity_id='{exc.entity_id}'"
            )
            # Error message should mention the invalid reference
            assert invalid_ref in str(exc), (
                f"Expected invalid ref '{invalid_ref}' in error message, got: {exc}"
            )

    @given(
        valid_review_ids=st.lists(
            identifier_strategy, min_size=1, max_size=5, unique=True
        ),
    )
    @settings(max_examples=100)
    def test_valid_review_technique_reference_never_raises(
        self, valid_review_ids: list[str], tmp_path_factory
    ) -> None:
        """WHEN a prepare_technique references a review_technique id that IS
        declared in the review_techniques section, THEN SchemaRegistry loads
        successfully without raising SchemaValidationError.

        **Validates: Requirement 4, AC 3**
        """
        schema = _minimal_schema()

        # Pick the first valid id as the reference
        chosen_ref = valid_review_ids[0]

        # Add review_techniques section with all valid ids
        schema["review_techniques"] = [
            {
                "id": rid,
                "service_class": "ReviewService",
                "description": f"Review technique {rid}",
                "critique_categories": ["missed_keywords", "company_angles"],
                "max_review_cycles": 2,
            }
            for rid in valid_review_ids
        ]

        # Set prepare_technique to reference a valid review technique
        schema["prepare_techniques"][0]["review_technique"] = chosen_ref

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        # Should load without error
        registry = SchemaRegistry(schema_file)
        assert registry.prepare_techniques[0].review_technique == chosen_ref
