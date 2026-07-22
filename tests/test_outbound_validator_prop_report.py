# Feature: outbound-validation-gate, Property 2: Report completeness
"""Property-based tests for OutboundValidator.validate() report completeness.

Generates random subsets of BUILT_IN_RULES keys as the rule configs, mocks
SchemaRegistry to return those configs, and asserts:
- len(report.results) == len(configs)  — every configured rule produces exactly one result
- set(r.rule_id for r in report.results) == set(c.rule_id for c in configs) — all rule_ids match

**Validates: Requirements 1.1, 1.4**
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.outbound_validator import (
    BUILT_IN_RULES,
    Material,
    OutboundValidator,
    ValidationContext,
    ValidationRuleConfig,
)


# ─── Constants ────────────────────────────────────────────────────────────────

ALL_SYNC_RULE_IDS: list[str] = list(BUILT_IN_RULES.keys())


# ─── Strategies ───────────────────────────────────────────────────────────────

# Generate non-empty subsets of BUILT_IN_RULES keys as configurations
rule_subset_st = st.lists(
    st.sampled_from(ALL_SYNC_RULE_IDS),
    min_size=1,
    max_size=len(ALL_SYNC_RULE_IDS),
    unique=True,
)


def _make_configs(rule_ids: list[str]) -> list[ValidationRuleConfig]:
    """Convert a list of rule_id strings into ValidationRuleConfig objects."""
    return [ValidationRuleConfig(rule_id=rid) for rid in rule_ids]


def _make_validator(configs: list[ValidationRuleConfig]) -> OutboundValidator:
    """Build an OutboundValidator with a mocked SchemaRegistry and repository."""
    mock_schema = MagicMock()
    mock_schema.get_validation_rules.return_value = configs

    mock_pipeline = MagicMock()
    mock_db = AsyncMock()
    mock_db.save_validation_report = AsyncMock(return_value="mock-id")

    return OutboundValidator(
        schema_registry=mock_schema,
        pipeline_manager=mock_pipeline,
        db_repo=mock_db,
    )


def _make_simple_material() -> Material:
    """Create a simple material that won't trip any rules unexpectedly."""
    return Material(
        subject="Test Subject",
        body="Hello World. This is a simple test body with enough characters to pass.",
        signature="Best regards, Test",
        personalization_fields={},
    )


def _make_context() -> ValidationContext:
    """Create a simple validation context."""
    return ValidationContext(
        pipeline_record_id="test-pipeline-123",
        contact_first_name="Test",
        contact_last_name="User",
        outreach_technique="test_technique",
        material_type="email",
        required_fields=[],
    )


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestProperty2ReportCompleteness:
    """Property 2: Report completeness.

    Every configured rule produces exactly one result in the report, and the
    set of rule_ids in the report matches the configured set exactly.

    **Validates: Requirements 1.1, 1.4**
    """

    @given(rule_ids=rule_subset_st)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_report_result_count_matches_config_count(
        self,
        rule_ids: list[str],
    ) -> None:
        """WHEN a random subset of BUILT_IN_RULES is configured, THEN
        validate() produces a report with exactly len(configs) results.

        **Validates: Requirements 1.1, 1.4**
        """
        configs = _make_configs(rule_ids)
        validator = _make_validator(configs)
        material = _make_simple_material()
        context = _make_context()

        report = await validator.validate(material, context)

        assert len(report.results) == len(configs), (
            f"Expected {len(configs)} results for configs {rule_ids}, "
            f"got {len(report.results)} results with rule_ids "
            f"{[r.rule_id for r in report.results]}"
        )

    @given(rule_ids=rule_subset_st)
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_report_rule_ids_match_configured_set(
        self,
        rule_ids: list[str],
    ) -> None:
        """WHEN a random subset of BUILT_IN_RULES is configured, THEN the
        set of rule_ids in the report matches the configured set exactly.

        **Validates: Requirements 1.1, 1.4**
        """
        configs = _make_configs(rule_ids)
        validator = _make_validator(configs)
        material = _make_simple_material()
        context = _make_context()

        report = await validator.validate(material, context)

        result_rule_ids = {r.rule_id for r in report.results}
        config_rule_ids = {c.rule_id for c in configs}

        assert result_rule_ids == config_rule_ids, (
            f"Rule ID mismatch.\n"
            f"  Configured: {sorted(config_rule_ids)}\n"
            f"  Got in report: {sorted(result_rule_ids)}\n"
            f"  Missing from report: {sorted(config_rule_ids - result_rule_ids)}\n"
            f"  Extra in report: {sorted(result_rule_ids - config_rule_ids)}"
        )
