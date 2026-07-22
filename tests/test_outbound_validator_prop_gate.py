# Feature: outbound-validation-gate, Property 1: Gate blocks iff blocking rule fails
"""Property-based tests for OutboundValidator.validate_and_send() gate logic.

Tests the core biconditional property:
    blocked == any(not r.passed and r.severity == BLOCKING for r in report.results)

Generates materials with varying rule configs and severity combinations to verify
that the gate blocks if and only if at least one blocking-severity rule fails.

**Validates: Requirements 1.2, 1.3**
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.outbound_validator import (
    BUILT_IN_RULES,
    Material,
    OutboundValidator,
    RuleSeverity,
    ValidationContext,
    ValidationRuleConfig,
)


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for severity: BLOCKING or WARNING
severity_st = st.sampled_from([RuleSeverity.BLOCKING, RuleSeverity.WARNING])

# Strategy to generate a material body that may or may not contain unreplaced tokens.
# We control token presence explicitly to know whether the unreplaced_tokens rule will fail.
TOKEN_EXAMPLES = ["{{first_name}}", "{company_name}", "[PLACEHOLDER]", "<INSERT_NAME>"]

safe_body_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"),
        blacklist_characters="{}<>[]",
    ),
    min_size=50,
    max_size=300,
)

body_with_token_st = st.builds(
    lambda prefix, token, suffix: prefix + " " + token + " " + suffix,
    prefix=safe_body_st,
    token=st.sampled_from(TOKEN_EXAMPLES),
    suffix=safe_body_st,
)


@st.composite
def rule_configs_st(draw):
    """Generate a list of ValidationRuleConfig with severity overrides.

    Uses only the 'unreplaced_tokens' rule since it's the easiest to control
    via generated material content. Combines with other rules at varying severities
    to exercise the biconditional gate logic.
    """
    # Always include unreplaced_tokens rule with a chosen severity
    token_severity = draw(severity_st)
    configs = [
        ValidationRuleConfig(
            rule_id="unreplaced_tokens",
            severity=token_severity,
            params={},
        )
    ]

    # Optionally include additional rules with various severities
    optional_rules = ["empty_subject", "missing_signature", "length_bounds"]
    included = draw(st.lists(
        st.sampled_from(optional_rules),
        min_size=0,
        max_size=3,
        unique=True,
    ))
    for rule_id in included:
        sev = draw(severity_st)
        params: dict = {}
        if rule_id == "missing_signature":
            # Control whether signature is required
            params["required"] = draw(st.booleans())
        if rule_id == "length_bounds":
            params["min_length"] = draw(st.integers(min_value=10, max_value=40))
            params["max_length"] = draw(st.integers(min_value=5000, max_value=10000))
        configs.append(
            ValidationRuleConfig(rule_id=rule_id, severity=sev, params=params)
        )

    return configs


@st.composite
def material_and_configs_st(draw):
    """Generate a (material, configs, context) tuple for the gate test.

    Controls whether the material has unreplaced tokens and combines with
    generated rule configs to exercise all blocking/passing scenarios.
    """
    has_tokens = draw(st.booleans())

    if has_tokens:
        body = draw(body_with_token_st)
    else:
        body = draw(safe_body_st)

    # Always provide a subject and signature to avoid those rules failing unexpectedly
    subject = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z"), blacklist_characters="{}<>[]"),
        min_size=5,
        max_size=50,
    ))
    signature = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z"), blacklist_characters="{}<>[]"),
        min_size=5,
        max_size=30,
    ))

    material = Material(
        subject=subject,
        body=body,
        signature=signature,
        personalization_fields={},
    )

    configs = draw(rule_configs_st())

    context = ValidationContext(
        pipeline_record_id="test-pipeline-001",
        contact_first_name="John",
        contact_last_name="Doe",
        outreach_technique="test_technique",
        material_type="email",
        required_fields=[],
    )

    return material, configs, context


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestProperty1GateBlocksIffBlockingRuleFails:
    """Property 1: Gate blocks iff blocking rule fails.

    **Validates: Requirements 1.2, 1.3**

    Core biconditional:
        gate_result.blocked == any(
            not r.passed and r.severity == BLOCKING
            for r in gate_result.report.results
        )

    - Requirement 1.2: If any blocking rule fails → block + transition
    - Requirement 1.3: If only warnings fail → permit submission
    """

    @given(data=material_and_configs_st())
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_blocked_iff_blocking_rule_failed(self, data):
        """FOR ANY material with any combination of rule configs and severities,
        the gate blocks if and only if at least one blocking-severity rule failed.

        **Validates: Requirements 1.2, 1.3**
        """
        material, configs, context = data

        # Mock dependencies
        mock_schema_registry = MagicMock()
        mock_schema_registry.get_validation_rules.return_value = configs

        mock_pipeline_manager = AsyncMock()
        mock_pipeline_manager.transition_to_validation_failed = AsyncMock()

        mock_db_repo = AsyncMock()
        mock_db_repo.save_validation_report = AsyncMock()

        mock_send_fn = AsyncMock(return_value={"status": "sent"})

        # Create the validator with mocked dependencies
        validator = OutboundValidator(
            schema_registry=mock_schema_registry,
            pipeline_manager=mock_pipeline_manager,
            db_repo=mock_db_repo,
        )

        # Execute validate_and_send
        gate_result = await validator.validate_and_send(
            material=material,
            context=context,
            send_fn=mock_send_fn,
        )

        # Compute expected blocking from the report results
        has_blocking_failure = any(
            not r.passed and r.severity == RuleSeverity.BLOCKING
            for r in gate_result.report.results
        )

        # CORE PROPERTY: blocked == any blocking rule failed
        assert gate_result.blocked == has_blocking_failure, (
            f"Gate blocked={gate_result.blocked} but expected "
            f"has_blocking_failure={has_blocking_failure}.\n"
            f"Results: {[(r.rule_id, r.passed, r.severity) for r in gate_result.report.results]}"
        )

    @given(data=material_and_configs_st())
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_send_fn_called_iff_not_blocked(self, data):
        """IF the gate does not block (no blocking failures), THEN send_fn is called.
        IF the gate blocks, THEN send_fn is NOT called.

        **Validates: Requirements 1.2, 1.3**
        """
        material, configs, context = data

        mock_schema_registry = MagicMock()
        mock_schema_registry.get_validation_rules.return_value = configs

        mock_pipeline_manager = AsyncMock()
        mock_pipeline_manager.transition_to_validation_failed = AsyncMock()

        mock_db_repo = AsyncMock()
        mock_db_repo.save_validation_report = AsyncMock()

        mock_send_fn = AsyncMock(return_value={"status": "sent"})

        validator = OutboundValidator(
            schema_registry=mock_schema_registry,
            pipeline_manager=mock_pipeline_manager,
            db_repo=mock_db_repo,
        )

        gate_result = await validator.validate_and_send(
            material=material,
            context=context,
            send_fn=mock_send_fn,
        )

        if gate_result.blocked:
            mock_send_fn.assert_not_called()
        else:
            mock_send_fn.assert_called_once()

    @given(data=material_and_configs_st())
    @settings(max_examples=200)
    @pytest.mark.asyncio
    async def test_pipeline_transition_called_iff_blocked(self, data):
        """IF the gate blocks, THEN PipelineManager.transition_to_validation_failed()
        is called. If not blocked, transition is NOT called.

        **Validates: Requirements 1.2, 1.3**
        """
        material, configs, context = data

        mock_schema_registry = MagicMock()
        mock_schema_registry.get_validation_rules.return_value = configs

        mock_pipeline_manager = AsyncMock()
        mock_pipeline_manager.transition_to_validation_failed = AsyncMock()

        mock_db_repo = AsyncMock()
        mock_db_repo.save_validation_report = AsyncMock()

        mock_send_fn = AsyncMock(return_value={"status": "sent"})

        validator = OutboundValidator(
            schema_registry=mock_schema_registry,
            pipeline_manager=mock_pipeline_manager,
            db_repo=mock_db_repo,
        )

        gate_result = await validator.validate_and_send(
            material=material,
            context=context,
            send_fn=mock_send_fn,
        )

        if gate_result.blocked:
            mock_pipeline_manager.transition_to_validation_failed.assert_called_once()
        else:
            mock_pipeline_manager.transition_to_validation_failed.assert_not_called()
