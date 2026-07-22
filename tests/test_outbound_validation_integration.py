"""Integration tests for end-to-end Outbound Validation Gate flow.

Wires up the full OutboundValidator pipeline with real rule execution
(no mocking of rules). Only external boundaries are mocked:
- SchemaRegistry.get_validation_rules() → controls which rules are configured
- ValidationRepository.save_validation_report() → captures the saved report
- PipelineManager.transition_to_validation_failed() → verifies pipeline transitions
- send_fn → verifies whether the send channel is invoked or suppressed

Validates: Requirements 1.1, 1.2, 1.3, 1.4
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.outbound_validator import (
    Material,
    OutboundValidator,
    RuleSeverity,
    ValidationContext,
    ValidationRuleConfig,
)


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_schema_registry():
    """Mock SchemaRegistry with controllable get_validation_rules()."""
    registry = MagicMock()
    registry.get_validation_rules = MagicMock(return_value=None)
    return registry


@pytest.fixture
def mock_pipeline_manager():
    """Mock PipelineManager with async transition method."""
    manager = MagicMock()
    manager.transition_to_validation_failed = AsyncMock()
    return manager


@pytest.fixture
def mock_validation_repo():
    """Mock ValidationRepository — captures the saved report for inspection."""
    repo = MagicMock()
    repo.save_validation_report = AsyncMock(return_value="report-id-integration")
    return repo


@pytest.fixture
def validator(mock_schema_registry, mock_pipeline_manager, mock_validation_repo):
    """OutboundValidator wired with mocked boundaries but real rule execution."""
    return OutboundValidator(
        schema_registry=mock_schema_registry,
        pipeline_manager=mock_pipeline_manager,
        db_repo=mock_validation_repo,
    )


@pytest.fixture
def email_context() -> ValidationContext:
    """Standard email ValidationContext for integration tests."""
    return ValidationContext(
        pipeline_record_id="integration-rec-001",
        contact_first_name="Alice",
        contact_last_name="Smith",
        outreach_technique="cold_email_consultant",
        material_type="email",
        required_fields=["first_name", "company_name"],
    )


# ─── TEST: Blocking failure → send_fn never called, pipeline transitions ─────


class TestBlockingFailureE2E:
    """End-to-end: material with blocking defect is blocked before send."""

    @pytest.mark.asyncio
    async def test_unreplaced_token_blocks_send(
        self,
        validator,
        mock_schema_registry,
        mock_pipeline_manager,
        mock_validation_repo,
        email_context,
    ):
        """Material with {{name}} unreplaced token triggers blocking.

        Real rules execute — unreplaced_tokens detects the token,
        send_fn is never called, pipeline transitions to validation_failed,
        and the report records the blocking failure.

        Validates: Requirements 1.1, 1.2
        """
        # Configure all default blocking rules via schema mock
        mock_schema_registry.get_validation_rules.return_value = [
            ValidationRuleConfig(rule_id="unreplaced_tokens", severity=RuleSeverity.BLOCKING, params={}),
            ValidationRuleConfig(rule_id="empty_subject", severity=RuleSeverity.BLOCKING, params={}),
            ValidationRuleConfig(rule_id="missing_signature", severity=RuleSeverity.BLOCKING, params={}),
            ValidationRuleConfig(rule_id="recipient_name_mismatch", severity=RuleSeverity.BLOCKING, params={}),
            ValidationRuleConfig(
                rule_id="empty_personalization_field",
                severity=RuleSeverity.BLOCKING,
                params={"required_fields": ["first_name", "company_name"]},
            ),
        ]

        # Material has an unreplaced {{name}} token in the body
        material = Material(
            subject="Quick follow-up",
            body="Hi Alice, I wanted to reach out about {{name}}'s opportunity at Acme.",
            signature="Best regards,\nTeam",
            personalization_fields={"first_name": "Alice", "company_name": "Acme"},
        )

        send_fn = AsyncMock(return_value={"message_id": "msg-999"})

        result = await validator.validate_and_send(material, email_context, send_fn)

        # 1. Result must be blocked
        assert result.blocked is True

        # 2. send_fn was never called
        send_fn.assert_not_called()

        # 3. PipelineManager.transition_to_validation_failed() was called
        mock_pipeline_manager.transition_to_validation_failed.assert_called_once()
        call_kwargs = mock_pipeline_manager.transition_to_validation_failed.call_args[1]
        assert call_kwargs["record_id"] == "integration-rec-001"
        assert len(call_kwargs["blocking_failures"]) >= 1

        # 4. Report has passed=False and blocking failure with rule_id="unreplaced_tokens"
        mock_validation_repo.save_validation_report.assert_called_once()
        saved_report = mock_validation_repo.save_validation_report.call_args[0][0]
        assert saved_report.passed is False
        blocking_rule_ids = [r.rule_id for r in saved_report.blocking_failures]
        assert "unreplaced_tokens" in blocking_rule_ids


# ─── TEST: Warnings only → send_fn called, report stored with warnings ───────


class TestWarningsOnlyE2E:
    """End-to-end: material with only warnings is permitted through the gate."""

    @pytest.mark.asyncio
    async def test_short_body_warning_permits_send(
        self,
        validator,
        mock_schema_registry,
        mock_pipeline_manager,
        mock_validation_repo,
        email_context,
    ):
        """Material with body below min_length triggers warning but send proceeds.

        Real LengthBoundsRule executes with WARNING severity. The gate does
        not block, send_fn is called, and the report records the warning.

        Validates: Requirements 1.3, 1.4
        """
        # Configure only length_bounds as WARNING severity
        mock_schema_registry.get_validation_rules.return_value = [
            ValidationRuleConfig(
                rule_id="length_bounds",
                severity=RuleSeverity.WARNING,
                params={"min_length": 100, "max_length": 5000},
            ),
        ]

        # Body is very short — well below min_length of 100
        material = Material(
            subject="Hello",
            body="Short body.",
            signature="Best, Team",
            personalization_fields={"first_name": "Alice", "company_name": "Acme"},
        )

        send_fn = AsyncMock(return_value={"message_id": "msg-200"})

        result = await validator.validate_and_send(material, email_context, send_fn)

        # 1. Result is NOT blocked
        assert result.blocked is False

        # 2. send_fn was called
        send_fn.assert_called_once()

        # 3. Report has passed=True and has_warnings=True
        mock_validation_repo.save_validation_report.assert_called_once()
        saved_report = mock_validation_repo.save_validation_report.call_args[0][0]
        assert saved_report.passed is True
        assert saved_report.has_warnings is True

        # 4. The warning result has rule_id="length_bounds"
        warning_rule_ids = [r.rule_id for r in saved_report.warnings]
        assert "length_bounds" in warning_rule_ids


# ─── TEST: All pass → send_fn called, report stored with passed=True ─────────


class TestAllPassE2E:
    """End-to-end: clean material passes all rules and gets sent."""

    @pytest.mark.asyncio
    async def test_clean_material_passes_all_rules(
        self,
        validator,
        mock_schema_registry,
        mock_pipeline_manager,
        mock_validation_repo,
        email_context,
    ):
        """Clean material passes all default blocking rules — send proceeds.

        Material has: valid subject, body with correct greeting name matching
        the contact, signature present, all personalization fields populated.
        Real rules execute and all pass.

        Validates: Requirements 1.1, 1.3, 1.4
        """
        # Configure all default blocking rules
        mock_schema_registry.get_validation_rules.return_value = [
            ValidationRuleConfig(rule_id="unreplaced_tokens", severity=RuleSeverity.BLOCKING, params={}),
            ValidationRuleConfig(rule_id="empty_subject", severity=RuleSeverity.BLOCKING, params={}),
            ValidationRuleConfig(rule_id="missing_signature", severity=RuleSeverity.BLOCKING, params={}),
            ValidationRuleConfig(rule_id="recipient_name_mismatch", severity=RuleSeverity.BLOCKING, params={}),
            ValidationRuleConfig(
                rule_id="empty_personalization_field",
                severity=RuleSeverity.BLOCKING,
                params={"required_fields": ["first_name", "company_name"]},
            ),
        ]

        # Clean material: correct greeting name, signature, all fields populated
        material = Material(
            subject="Consulting opportunity at Acme",
            body=(
                "Hi Alice, I came across your profile and wanted to reach out about "
                "a consulting opportunity at Acme Corp. Your background in data engineering "
                "is a great match for what we are looking for. Would you be open to a quick chat?"
            ),
            signature="Best regards,\nJohn from the Outreach Team",
            personalization_fields={"first_name": "Alice", "company_name": "Acme Corp"},
        )

        send_fn = AsyncMock(return_value={"message_id": "msg-300", "thread_id": "t-1"})

        result = await validator.validate_and_send(material, email_context, send_fn)

        # 1. Result is NOT blocked
        assert result.blocked is False

        # 2. send_fn was called and result is returned
        send_fn.assert_called_once()
        assert result.send_result == {"message_id": "msg-300", "thread_id": "t-1"}

        # 3. Report has passed=True and has_warnings=False
        mock_validation_repo.save_validation_report.assert_called_once()
        saved_report = mock_validation_repo.save_validation_report.call_args[0][0]
        assert saved_report.passed is True
        assert saved_report.has_warnings is False

        # 4. All individual results passed
        for rule_result in saved_report.results:
            assert rule_result.passed is True, (
                f"Rule {rule_result.rule_id} unexpectedly failed: {rule_result.message}"
            )

        # 5. PipelineManager was NOT called (no transition needed)
        mock_pipeline_manager.transition_to_validation_failed.assert_not_called()
