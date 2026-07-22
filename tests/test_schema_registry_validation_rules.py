"""Unit tests for Schema Registry validation_rules parsing.

Tests requirements 3.1 and 3.2:
- 3.1: Schema_Registry supports a validation_rules declaration per outreach technique
- 3.2: Schema_Registry validates declared rule ids at startup
"""

from pathlib import Path

import pytest
import yaml

from app.core.errors import SchemaValidationError
from app.core.outbound_validator import RuleSeverity, ValidationRuleConfig
from app.core.schema_registry import (
    SchemaRegistry,
    Technique,
    ValidationRuleDeclaration,
)


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _minimal_schema_with_validation_rules() -> dict:
    """Return a minimal valid schema with validation_rules on an outreach technique."""
    return {
        "stages": [
            {"id": "find", "label": "Find", "description": "Find stage"},
        ],
        "beneficiaries": [
            {
                "id": "consultant",
                "label": "Consultant",
                "description": "Consultant",
                "baseline_assets": ["resume"],
                "offerings_asset": "profiles",
                "offerings_label": "Offerings",
                "search_criteria_asset": "search_criteria",
            },
        ],
        "opportunity_types": [
            {
                "id": "job",
                "label": "Jobs",
                "beneficiaries": ["consultant"],
                "source_asset": "jobs",
                "source_label": "Jobs",
                "find_technique": "search",
                "find_label": "Search",
                "prepare_technique": "prep",
                "outreach_technique": "email_outreach",
                "pipeline_states": ["Applied"],
            },
        ],
        "find_techniques": [
            {
                "id": "search",
                "service_class": "SearchService",
                "description": "Search",
            },
        ],
        "prepare_techniques": [
            {
                "id": "prep",
                "service_class": "PrepService",
                "description": "Prep",
            },
        ],
        "outreach_techniques": [
            {
                "id": "email_outreach",
                "service_class": "EmailService",
                "description": "Email outreach",
                "validation_rules": [
                    {"rule_id": "unreplaced_tokens"},
                    {"rule_id": "empty_subject"},
                    {
                        "rule_id": "missing_signature",
                        "params": {"required": True},
                    },
                    {
                        "rule_id": "length_bounds",
                        "severity": "warning",
                        "params": {"min_length": 100, "max_length": 3000},
                    },
                ],
            },
        ],
    }


def _minimal_schema_without_validation_rules() -> dict:
    """Return a minimal valid schema where outreach technique has no validation_rules."""
    return {
        "stages": [
            {"id": "find", "label": "Find", "description": "Find stage"},
        ],
        "beneficiaries": [
            {
                "id": "consultant",
                "label": "Consultant",
                "description": "Consultant",
                "baseline_assets": ["resume"],
                "offerings_asset": "profiles",
                "offerings_label": "Offerings",
                "search_criteria_asset": "search_criteria",
            },
        ],
        "opportunity_types": [
            {
                "id": "job",
                "label": "Jobs",
                "beneficiaries": ["consultant"],
                "source_asset": "jobs",
                "source_label": "Jobs",
                "find_technique": "search",
                "find_label": "Search",
                "prepare_technique": "prep",
                "outreach_technique": "basic_outreach",
                "pipeline_states": ["Applied"],
            },
        ],
        "find_techniques": [
            {
                "id": "search",
                "service_class": "SearchService",
                "description": "Search",
            },
        ],
        "prepare_techniques": [
            {
                "id": "prep",
                "service_class": "PrepService",
                "description": "Prep",
            },
        ],
        "outreach_techniques": [
            {
                "id": "basic_outreach",
                "service_class": "BasicService",
                "description": "Basic outreach",
            },
        ],
    }


def _write_schema(tmp_path: Path, schema: dict) -> Path:
    """Write a schema dict to a temp file and return the path."""
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(yaml.dump(schema), encoding="utf-8")
    return schema_file


# ─── TEST: Valid YAML produces correct ValidationRuleDeclaration instances ────


class TestValidYAMLParsing:
    """Test that valid YAML with validation_rules produces correct dataclass instances."""

    def test_technique_has_validation_rules_list(self, tmp_path: Path) -> None:
        """When a technique has validation_rules, parsed Technique has matching list."""
        schema = _minimal_schema_with_validation_rules()
        registry = SchemaRegistry(_write_schema(tmp_path, schema))

        technique = next(
            t for t in registry.outreach_techniques if t.id == "email_outreach"
        )
        assert isinstance(technique, Technique)
        assert len(technique.validation_rules) == 4

    def test_validation_rule_declaration_fields(self, tmp_path: Path) -> None:
        """Each ValidationRuleDeclaration has correct rule_id, severity, and params."""
        schema = _minimal_schema_with_validation_rules()
        registry = SchemaRegistry(_write_schema(tmp_path, schema))

        technique = next(
            t for t in registry.outreach_techniques if t.id == "email_outreach"
        )
        rules = technique.validation_rules

        # First rule: no severity or params
        assert rules[0].rule_id == "unreplaced_tokens"
        assert rules[0].severity is None
        assert rules[0].params == {}

        # Second rule: no severity or params
        assert rules[1].rule_id == "empty_subject"
        assert rules[1].severity is None
        assert rules[1].params == {}

        # Third rule: has params, no severity
        assert rules[2].rule_id == "missing_signature"
        assert rules[2].severity is None
        assert rules[2].params == {"required": True}

        # Fourth rule: has severity and params
        assert rules[3].rule_id == "length_bounds"
        assert rules[3].severity == "warning"
        assert rules[3].params == {"min_length": 100, "max_length": 3000}

    def test_validation_rule_declarations_are_frozen(self, tmp_path: Path) -> None:
        """ValidationRuleDeclaration instances are frozen dataclasses."""
        schema = _minimal_schema_with_validation_rules()
        registry = SchemaRegistry(_write_schema(tmp_path, schema))

        technique = next(
            t for t in registry.outreach_techniques if t.id == "email_outreach"
        )
        decl = technique.validation_rules[0]
        assert isinstance(decl, ValidationRuleDeclaration)

        with pytest.raises(Exception):  # FrozenInstanceError
            decl.rule_id = "something_else"  # type: ignore[misc]


# ─── TEST: Missing validation_rules field defaults to empty list ──────────────


class TestMissingValidationRulesField:
    """Test that techniques without validation_rules get an empty list."""

    def test_no_validation_rules_key_gives_empty_list(self, tmp_path: Path) -> None:
        """When technique has no validation_rules key, Technique.validation_rules is []."""
        schema = _minimal_schema_without_validation_rules()
        registry = SchemaRegistry(_write_schema(tmp_path, schema))

        technique = next(
            t for t in registry.outreach_techniques if t.id == "basic_outreach"
        )
        assert technique.validation_rules == []

    def test_empty_validation_rules_gives_empty_list(self, tmp_path: Path) -> None:
        """When validation_rules is an empty list in YAML, parsed list is empty."""
        schema = _minimal_schema_without_validation_rules()
        schema["outreach_techniques"][0]["validation_rules"] = []
        registry = SchemaRegistry(_write_schema(tmp_path, schema))

        technique = next(
            t for t in registry.outreach_techniques if t.id == "basic_outreach"
        )
        assert technique.validation_rules == []


# ─── TEST: get_validation_rules returns correct configs with severity overrides


class TestGetValidationRules:
    """Test get_validation_rules() returns proper ValidationRuleConfig instances."""

    def test_returns_validation_rule_configs(self, tmp_path: Path) -> None:
        """get_validation_rules returns list of ValidationRuleConfig for configured technique."""
        schema = _minimal_schema_with_validation_rules()
        registry = SchemaRegistry(_write_schema(tmp_path, schema))

        configs = registry.get_validation_rules("email_outreach")
        assert configs is not None
        assert len(configs) == 4
        assert all(isinstance(c, ValidationRuleConfig) for c in configs)

    def test_severity_mapped_to_enum(self, tmp_path: Path) -> None:
        """Severity strings are mapped to RuleSeverity enum values."""
        schema = _minimal_schema_with_validation_rules()
        registry = SchemaRegistry(_write_schema(tmp_path, schema))

        configs = registry.get_validation_rules("email_outreach")
        assert configs is not None

        # Rule with no severity override → None (use default)
        assert configs[0].severity is None
        assert configs[0].rule_id == "unreplaced_tokens"

        # Rule with severity: warning → RuleSeverity.WARNING
        length_config = configs[3]
        assert length_config.rule_id == "length_bounds"
        assert length_config.severity == RuleSeverity.WARNING

    def test_params_passed_through(self, tmp_path: Path) -> None:
        """Params from YAML are passed through to ValidationRuleConfig."""
        schema = _minimal_schema_with_validation_rules()
        registry = SchemaRegistry(_write_schema(tmp_path, schema))

        configs = registry.get_validation_rules("email_outreach")
        assert configs is not None

        # missing_signature has params
        sig_config = configs[2]
        assert sig_config.rule_id == "missing_signature"
        assert sig_config.params == {"required": True}

        # length_bounds has params
        length_config = configs[3]
        assert length_config.params == {"min_length": 100, "max_length": 3000}

    def test_returns_none_for_unknown_technique(self, tmp_path: Path) -> None:
        """get_validation_rules returns None for unknown technique_id."""
        schema = _minimal_schema_with_validation_rules()
        registry = SchemaRegistry(_write_schema(tmp_path, schema))

        result = registry.get_validation_rules("nonexistent_technique")
        assert result is None

    def test_returns_none_for_technique_without_rules(self, tmp_path: Path) -> None:
        """get_validation_rules returns None when technique has no validation_rules."""
        schema = _minimal_schema_without_validation_rules()
        registry = SchemaRegistry(_write_schema(tmp_path, schema))

        result = registry.get_validation_rules("basic_outreach")
        assert result is None


# ─── TEST: Startup validation errors ─────────────────────────────────────────


class TestStartupValidation:
    """Test that invalid rule_ids and severities raise SchemaValidationError at startup."""

    def test_unknown_rule_id_raises_error(self, tmp_path: Path) -> None:
        """Unknown rule_id in validation_rules raises SchemaValidationError."""
        schema = _minimal_schema_without_validation_rules()
        schema["outreach_techniques"][0]["validation_rules"] = [
            {"rule_id": "totally_fake_rule"},
        ]

        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaRegistry(_write_schema(tmp_path, schema))

        assert "unknown validation rule" in str(exc_info.value).lower()
        assert "totally_fake_rule" in str(exc_info.value)

    def test_invalid_severity_raises_error(self, tmp_path: Path) -> None:
        """Invalid severity value in validation_rules raises SchemaValidationError."""
        schema = _minimal_schema_without_validation_rules()
        schema["outreach_techniques"][0]["validation_rules"] = [
            {"rule_id": "unreplaced_tokens", "severity": "critical"},
        ]

        with pytest.raises(SchemaValidationError) as exc_info:
            SchemaRegistry(_write_schema(tmp_path, schema))

        assert "invalid severity" in str(exc_info.value).lower()
        assert "critical" in str(exc_info.value)

    def test_valid_severities_do_not_raise(self, tmp_path: Path) -> None:
        """Valid severity values (blocking, warning) do not raise errors."""
        schema = _minimal_schema_without_validation_rules()
        schema["outreach_techniques"][0]["validation_rules"] = [
            {"rule_id": "unreplaced_tokens", "severity": "blocking"},
            {"rule_id": "empty_subject", "severity": "warning"},
        ]

        # Should not raise
        registry = SchemaRegistry(_write_schema(tmp_path, schema))
        technique = next(
            t for t in registry.outreach_techniques if t.id == "basic_outreach"
        )
        assert len(technique.validation_rules) == 2


# ─── TEST: Real schema integration ───────────────────────────────────────────


class TestRealSchemaValidationRules:
    """Verify the real config/schema.yaml has validation_rules on lemlist_sequence."""

    def test_lemlist_sequence_has_validation_rules(self) -> None:
        """The production schema's lemlist_sequence technique has validation_rules."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        technique = next(
            (t for t in registry.outreach_techniques if t.id == "lemlist_sequence"),
            None,
        )
        assert technique is not None
        assert len(technique.validation_rules) > 0

    def test_lemlist_sequence_get_validation_rules(self) -> None:
        """get_validation_rules for lemlist_sequence returns configs with correct rule_ids."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        configs = registry.get_validation_rules("lemlist_sequence")
        assert configs is not None
        assert len(configs) > 0

        rule_ids = [c.rule_id for c in configs]
        assert "unreplaced_tokens" in rule_ids
        assert "empty_subject" in rule_ids
        assert "length_bounds" in rule_ids

    def test_lemlist_sequence_length_bounds_has_warning_severity(self) -> None:
        """The length_bounds rule on lemlist_sequence has WARNING severity override."""
        schema_path = Path("config/schema.yaml")
        if not schema_path.exists():
            pytest.skip("config/schema.yaml not present")

        registry = SchemaRegistry(schema_path)
        configs = registry.get_validation_rules("lemlist_sequence")
        assert configs is not None

        length_config = next(c for c in configs if c.rule_id == "length_bounds")
        assert length_config.severity == RuleSeverity.WARNING
        assert length_config.params["min_length"] == 100
        assert length_config.params["max_length"] == 3000
