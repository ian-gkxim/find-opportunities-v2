# Feature: outbound-validation-gate, Property 5: Schema config resolution with defaults
"""Property-based tests for SchemaRegistry.get_validation_rules() resolution.

Tests that the schema registry correctly resolves validation rule configurations:
- Techniques WITH validation_rules → returns list[ValidationRuleConfig]
- Techniques WITHOUT validation_rules → returns None
- Unknown technique IDs → returns None
- Severity overrides are correctly mapped to RuleSeverity enum

**Validates: Requirements 3.1, 3.3**
"""

from __future__ import annotations

from dataclasses import field
from unittest.mock import MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.outbound_validator import (
    ASYNC_RULES,
    BUILT_IN_RULES,
    RuleSeverity,
    ValidationRuleConfig,
)
from app.core.schema_registry import (
    SchemaRegistry,
    Technique,
    ValidationRuleDeclaration,
)


# ─── Constants ────────────────────────────────────────────────────────────────

ALL_KNOWN_RULE_IDS: list[str] = list(BUILT_IN_RULES.keys()) + list(ASYNC_RULES.keys())

VALID_SEVERITIES: list[str] = ["blocking", "warning"]


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for valid technique IDs (alphanumeric with underscores)
technique_id_st = st.from_regex(r"[a-z][a-z0-9_]{2,30}", fullmatch=True)

# Strategy for a valid rule_id drawn from known built-in rules
valid_rule_id_st = st.sampled_from(ALL_KNOWN_RULE_IDS)

# Strategy for optional severity override (None means use default)
severity_st = st.one_of(st.none(), st.sampled_from(VALID_SEVERITIES))

# Strategy for simple rule params (keep it lightweight)
params_st = st.fixed_dictionaries({}, optional={
    "min_length": st.integers(min_value=10, max_value=200),
    "max_length": st.integers(min_value=500, max_value=10000),
    "required": st.booleans(),
    "enabled": st.booleans(),
})

# Strategy for a single ValidationRuleDeclaration
validation_rule_declaration_st = st.builds(
    ValidationRuleDeclaration,
    rule_id=valid_rule_id_st,
    severity=severity_st,
    params=params_st,
)

# Strategy for a non-empty list of ValidationRuleDeclarations
validation_rules_list_st = st.lists(
    validation_rule_declaration_st, min_size=1, max_size=9
)


def _build_registry_with_techniques(
    techniques: list[Technique],
) -> SchemaRegistry:
    """Build a mock SchemaRegistry with the given outreach_techniques list.

    Bypasses YAML loading and validation to directly test get_validation_rules().
    """
    registry = object.__new__(SchemaRegistry)
    registry.outreach_techniques = techniques
    return registry


@st.composite
def technique_with_rules_st(draw) -> Technique:
    """Generate a Technique that HAS validation_rules configured."""
    tid = draw(technique_id_st)
    rules = draw(validation_rules_list_st)
    return Technique(
        id=tid,
        service_class="TestService",
        description="Test technique",
        inputs=[],
        outputs=[],
        validation_rules=rules,
    )


@st.composite
def technique_without_rules_st(draw) -> Technique:
    """Generate a Technique that has NO validation_rules (empty list)."""
    tid = draw(technique_id_st)
    return Technique(
        id=tid,
        service_class="TestService",
        description="Test technique without rules",
        inputs=[],
        outputs=[],
        validation_rules=[],
    )


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestProperty5SchemaConfigResolutionWithDefaults:
    """Property 5: Schema config resolution with defaults.

    **Validates: Requirements 3.1, 3.3**

    Key invariants:
    - Technique with validation_rules → returns list[ValidationRuleConfig] (non-None)
    - Technique with no validation_rules → returns None
    - Unknown technique_id → returns None
    - Severity overrides are correctly mapped to RuleSeverity enum
    """

    @given(technique=technique_with_rules_st())
    @settings(max_examples=200)
    def test_configured_technique_returns_list(
        self,
        technique: Technique,
    ) -> None:
        """WHEN a technique has validation_rules configured, THEN
        get_validation_rules() returns a non-None list of ValidationRuleConfig.

        **Validates: Requirements 3.1**
        """
        registry = _build_registry_with_techniques([technique])

        result = registry.get_validation_rules(technique.id)

        assert result is not None, (
            f"Expected non-None result for technique '{technique.id}' "
            f"which has {len(technique.validation_rules)} validation rules"
        )
        assert isinstance(result, list)
        assert len(result) == len(technique.validation_rules), (
            f"Expected {len(technique.validation_rules)} configs, got {len(result)}"
        )

    @given(technique=technique_with_rules_st())
    @settings(max_examples=200)
    def test_configured_technique_rule_ids_match(
        self,
        technique: Technique,
    ) -> None:
        """WHEN a technique has validation_rules configured, THEN each returned
        ValidationRuleConfig has the correct rule_id matching the declaration.

        **Validates: Requirements 3.1**
        """
        registry = _build_registry_with_techniques([technique])

        result = registry.get_validation_rules(technique.id)
        assert result is not None

        for config, decl in zip(result, technique.validation_rules):
            assert config.rule_id == decl.rule_id, (
                f"Rule ID mismatch: config={config.rule_id}, decl={decl.rule_id}"
            )

    @given(technique=technique_without_rules_st())
    @settings(max_examples=200)
    def test_unconfigured_technique_returns_none(
        self,
        technique: Technique,
    ) -> None:
        """WHEN a technique has no validation_rules (empty list), THEN
        get_validation_rules() returns None.

        **Validates: Requirements 3.3**
        """
        registry = _build_registry_with_techniques([technique])

        result = registry.get_validation_rules(technique.id)

        assert result is None, (
            f"Expected None for technique '{technique.id}' with no validation_rules, "
            f"but got {result}"
        )

    @given(
        technique=technique_with_rules_st(),
        unknown_id=technique_id_st,
    )
    @settings(max_examples=200)
    def test_unknown_technique_returns_none(
        self,
        technique: Technique,
        unknown_id: str,
    ) -> None:
        """WHEN the technique_id is not present in the registry, THEN
        get_validation_rules() returns None.

        **Validates: Requirements 3.3**
        """
        # Ensure the unknown_id doesn't accidentally match the technique
        assume(unknown_id != technique.id)

        registry = _build_registry_with_techniques([technique])

        result = registry.get_validation_rules(unknown_id)

        assert result is None, (
            f"Expected None for unknown technique '{unknown_id}', but got {result}"
        )

    @given(technique=technique_with_rules_st())
    @settings(max_examples=200)
    def test_severity_overrides_mapped_to_enum(
        self,
        technique: Technique,
    ) -> None:
        """WHEN a validation_rule declaration has a severity override, THEN
        the returned ValidationRuleConfig.severity is the corresponding
        RuleSeverity enum value. When severity is None, config.severity is None.

        **Validates: Requirements 3.1**
        """
        registry = _build_registry_with_techniques([technique])

        result = registry.get_validation_rules(technique.id)
        assert result is not None

        for config, decl in zip(result, technique.validation_rules):
            if decl.severity is None:
                assert config.severity is None, (
                    f"Expected None severity for rule '{config.rule_id}' "
                    f"but got {config.severity}"
                )
            elif decl.severity == "blocking":
                assert config.severity == RuleSeverity.BLOCKING, (
                    f"Expected BLOCKING for rule '{config.rule_id}' "
                    f"but got {config.severity}"
                )
            elif decl.severity == "warning":
                assert config.severity == RuleSeverity.WARNING, (
                    f"Expected WARNING for rule '{config.rule_id}' "
                    f"but got {config.severity}"
                )
            else:
                # Should not happen with our strategy, but guard against it
                raise AssertionError(
                    f"Unexpected severity value: {decl.severity!r}"
                )

    @given(technique=technique_with_rules_st())
    @settings(max_examples=200)
    def test_params_are_correctly_passed_through(
        self,
        technique: Technique,
    ) -> None:
        """WHEN a validation_rule declaration has params, THEN the returned
        ValidationRuleConfig.params contains the same key-value pairs.

        **Validates: Requirements 3.1**
        """
        registry = _build_registry_with_techniques([technique])

        result = registry.get_validation_rules(technique.id)
        assert result is not None

        for config, decl in zip(result, technique.validation_rules):
            assert config.params == decl.params, (
                f"Params mismatch for rule '{config.rule_id}': "
                f"config={config.params}, decl={decl.params}"
            )
