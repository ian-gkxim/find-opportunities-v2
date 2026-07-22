# Feature: outbound-validation-gate, Property 6: Unknown rule id rejection at startup
"""Property-based test for schema validation of validation_rules declarations.

Generates random rule_id strings that are NOT in `BUILT_IN_RULES | ASYNC_RULES`
keyset, and verifies that SchemaRegistry ALWAYS raises SchemaValidationError
with a descriptive error message during startup validation.

**Validates: Requirements 3.2**
"""

from pathlib import Path

import yaml
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.errors import SchemaValidationError
from app.core.outbound_validator import ASYNC_RULES, BUILT_IN_RULES
from app.core.schema_registry import SchemaRegistry


# ─── Known Rule IDs (excluded from generation) ───────────────────────────────

KNOWN_RULE_IDS = set(BUILT_IN_RULES.keys()) | set(ASYNC_RULES.keys())

# ─── Strategies ───────────────────────────────────────────────────────────────

# Generate identifier-like strings that could plausibly be rule_ids
unknown_rule_id_strategy = st.from_regex(r"[a-z][a-z0-9_]{2,30}", fullmatch=True).filter(
    lambda s: s not in KNOWN_RULE_IDS
)


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


class TestUnknownRuleIdRejection:
    """Property 6: Unknown rule id rejection at startup."""

    @given(unknown_rule_id=unknown_rule_id_strategy)
    @settings(max_examples=100)
    def test_unknown_rule_id_always_raises_schema_validation_error(
        self, unknown_rule_id: str, tmp_path_factory
    ) -> None:
        """WHEN an outreach technique declares a validation_rules entry with a rule_id
        that is NOT in BUILT_IN_RULES or ASYNC_RULES, THEN SchemaRegistry ALWAYS
        raises SchemaValidationError with a descriptive error message containing
        the unknown rule_id.

        **Validates: Requirements 3.2**
        """
        schema = _minimal_schema()

        # Add a validation_rules section with the unknown rule_id
        schema["outreach_techniques"][0]["validation_rules"] = [
            {"rule_id": unknown_rule_id},
        ]

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        # SchemaRegistry MUST raise SchemaValidationError
        try:
            SchemaRegistry(schema_file)
            raise AssertionError(
                f"SchemaRegistry accepted unknown validation rule '{unknown_rule_id}'"
            )
        except SchemaValidationError as exc:
            # Error message should mention the unknown rule_id
            assert unknown_rule_id in str(exc), (
                f"Expected unknown rule_id '{unknown_rule_id}' in error message, got: {exc}"
            )
            # entity_id should match the outreach technique that declared the bad rule
            assert exc.entity_id == "manual_apply", (
                f"Expected entity_id='manual_apply', got entity_id='{exc.entity_id}'"
            )

    @given(
        known_rule_id=st.sampled_from(sorted(KNOWN_RULE_IDS)),
    )
    @settings(max_examples=50)
    def test_known_rule_id_never_raises_schema_validation_error(
        self, known_rule_id: str, tmp_path_factory
    ) -> None:
        """WHEN an outreach technique declares a validation_rules entry with a rule_id
        that IS in BUILT_IN_RULES or ASYNC_RULES, THEN SchemaRegistry loads
        successfully without raising SchemaValidationError for that rule.

        **Validates: Requirements 3.2**
        """
        schema = _minimal_schema()

        # Add a validation_rules section with a known/valid rule_id
        schema["outreach_techniques"][0]["validation_rules"] = [
            {"rule_id": known_rule_id},
        ]

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        # Should load without SchemaValidationError
        registry = SchemaRegistry(schema_file)
        assert registry is not None
