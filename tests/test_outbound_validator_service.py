"""Unit tests for OutboundValidator service.

Tests the validate_and_send() and validate() methods with mocked dependencies:
- SchemaRegistry (controls get_validation_rules() return)
- PipelineManager (verifies transition_to_validation_failed calls)
- ValidationRepository (verifies save_validation_report calls)

Validates: Requirements 1.1, 1.2, 1.3, 1.4
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.outbound_validator import (
    DEFAULT_BLOCKING_RULE_IDS,
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
    """Mock ValidationRepository with async save method."""
    repo = MagicMock()
    repo.save_validation_report = AsyncMock(return_value="report-id-1")
    return repo


@pytest.fixture
def validator(mock_schema_registry, mock_pipeline_manager, mock_validation_repo):
    """OutboundValidator wired with all mocked dependencies."""
    return OutboundValidator(
        schema_registry=mock_schema_registry,
        pipeline_manager=mock_pipeline_manager,
        db_repo=mock_validation_repo,
    )


@pytest.fixture
def email_context() -> ValidationContext:
    """Standard email context for testing."""
    return ValidationContext(
        pipeline_record_id="rec-100",
        contact_first_name="John",
        contact_last_name="Doe",
        outreach_technique="cold_email_consultant",
        material_type="email",
        required_fields=["first_name", "company_name"],
    )


# ─── TEST: Blocking rule fails → blocked ─────────────────────────────────────


class TestValidateAndSendBlocking:
    """Test that validate_and_send blocks when a blocking rule fails."""

    @pytest.mark.asyncio
    async def test_blocks_when_blocking_rule_fails(
        self,
        validator,
        mock_schema_registry,
        mock_pipeline_manager,
        mock_validation_repo,
        email_context,
    ):
        """Material with {{name}} token triggers blocking; send_fn is never called.

        Validates: Requirements 1.2
        """
        # Configure schema to return unreplaced_tokens as blocking
        mock_schema_registry.get_validation_rules.return_value = [
            ValidationRuleConfig(
                rule_id="unreplaced_tokens",
                severity=RuleSeverity.BLOCKING,
                params={},
            ),
        ]

        material = Material(
            subject="Hello {{name}}",
            body="Hi {{name}}, we noticed your profile.",
            signature="Best, Team",
        )

        send_fn = AsyncMock(return_value={"status": "sent"})

        result = await validator.validate_and_send(material, email_context, send_fn)

        # Gate should block
        assert result.blocked is True
        assert result.send_result is None

        # PipelineManager should have been called with the blocking failures
        mock_pipeline_manager.transition_to_validation_failed.assert_called_once()
        call_kwargs = mock_pipeline_manager.transition_to_validation_failed.call_args[1]
        assert call_kwargs["record_id"] == "rec-100"
        assert len(call_kwargs["blocking_failures"]) >= 1
        assert call_kwargs["blocking_failures"][0].rule_id == "unreplaced_tokens"
        assert call_kwargs["blocking_failures"][0].passed is False

        # send_fn should NOT have been called
        send_fn.assert_not_called()

        # Report should still be persisted
        mock_validation_repo.save_validation_report.assert_called_once()
        saved_report = mock_validation_repo.save_validation_report.call_args[0][0]
        assert saved_report.passed is False


# ─── TEST: Only warnings → permitted ─────────────────────────────────────────


class TestValidateAndSendWarningsOnly:
    """Test that validate_and_send permits send when only warnings are present."""

    @pytest.mark.asyncio
    async def test_permits_send_with_only_warnings(
        self,
        validator,
        mock_schema_registry,
        mock_pipeline_manager,
        mock_validation_repo,
        email_context,
    ):
        """Material with body too short (warning severity) still gets sent.

        Validates: Requirements 1.3
        """
        # Configure schema to return length_bounds as warning-only
        mock_schema_registry.get_validation_rules.return_value = [
            ValidationRuleConfig(
                rule_id="length_bounds",
                severity=RuleSeverity.WARNING,
                params={"min_length": 100, "max_length": 5000},
            ),
        ]

        # Body is only 20 chars — below min_length, so warning fires
        material = Material(
            subject="Quick question",
            body="Short body text.",
            signature="Best, Team",
        )

        send_fn = AsyncMock(return_value={"message_id": "msg-123"})

        result = await validator.validate_and_send(material, email_context, send_fn)

        # Gate should NOT block
        assert result.blocked is False
        assert result.send_result == {"message_id": "msg-123"}

        # send_fn should have been called
        send_fn.assert_called_once()

        # PipelineManager should NOT have been called
        mock_pipeline_manager.transition_to_validation_failed.assert_not_called()

        # Report should indicate warnings present
        mock_validation_repo.save_validation_report.assert_called_once()
        saved_report = mock_validation_repo.save_validation_report.call_args[0][0]
        assert saved_report.passed is True
        assert saved_report.has_warnings is True


# ─── TEST: Default rules fallback ────────────────────────────────────────────


class TestDefaultRulesFallback:
    """Test that default blocking rules are applied when technique has no config."""

    @pytest.mark.asyncio
    async def test_default_rules_when_schema_returns_none(
        self,
        validator,
        mock_schema_registry,
        mock_validation_repo,
        email_context,
    ):
        """When get_validation_rules returns None, default 5 blocking rules applied.

        Validates: Requirements 1.1, 3.3
        """
        # Schema returns None → no custom config for this technique
        mock_schema_registry.get_validation_rules.return_value = None

        rules = validator.get_rules_for_technique("unknown_technique")

        # Should return configs for all default blocking rules
        assert len(rules) == len(DEFAULT_BLOCKING_RULE_IDS)
        returned_ids = [r.rule_id for r in rules]
        assert returned_ids == DEFAULT_BLOCKING_RULE_IDS

    @pytest.mark.asyncio
    async def test_default_rules_executed_in_validate(
        self,
        validator,
        mock_schema_registry,
        mock_validation_repo,
        email_context,
    ):
        """validate() executes default rules and produces results for each.

        Validates: Requirements 1.1
        """
        mock_schema_registry.get_validation_rules.return_value = None

        # Clean material that passes all default rules
        material = Material(
            subject="Meeting follow-up",
            body="Hi John, great chatting with you about the consulting project at Acme Corp.",
            signature="Best regards,\nJohn",
            personalization_fields={
                "first_name": "John",
                "company_name": "Acme Corp",
            },
        )

        report = await validator.validate(material, email_context)

        # Should have results for all 5 default blocking rules
        assert len(report.results) == len(DEFAULT_BLOCKING_RULE_IDS)
        result_rule_ids = {r.rule_id for r in report.results}
        assert result_rule_ids == set(DEFAULT_BLOCKING_RULE_IDS)
        assert report.passed is True


# ─── TEST: Report persistence ─────────────────────────────────────────────────


class TestReportPersistence:
    """Test that ValidationReport is persisted via the repository."""

    @pytest.mark.asyncio
    async def test_validate_persists_report(
        self,
        validator,
        mock_schema_registry,
        mock_validation_repo,
        email_context,
    ):
        """After validate(), repository.save_validation_report is called with correct report.

        Validates: Requirements 1.4
        """
        mock_schema_registry.get_validation_rules.return_value = [
            ValidationRuleConfig(
                rule_id="unreplaced_tokens",
                severity=RuleSeverity.BLOCKING,
                params={},
            ),
        ]

        material = Material(
            subject="Clean subject",
            body="Hi John, clean body with no tokens.",
            signature="Best, Team",
        )

        report = await validator.validate(material, email_context)

        # Repository save should have been called exactly once
        mock_validation_repo.save_validation_report.assert_called_once()

        # The saved report should match what validate() returned
        saved_report = mock_validation_repo.save_validation_report.call_args[0][0]
        assert saved_report.id == report.id
        assert saved_report.pipeline_record_id == "rec-100"
        assert saved_report.outreach_technique == "cold_email_consultant"
        assert saved_report.total_execution_ms >= 0
        assert saved_report.results == report.results
        assert saved_report.created_at is not None
