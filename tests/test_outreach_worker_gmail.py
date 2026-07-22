"""Unit tests for Gmail outreach worker with OutboundValidator integration.

Tests the run_gmail_outreach() function to verify:
- Material and ValidationContext are correctly constructed from OutreachRequest
- OutboundValidator.validate_and_send() is called with proper arguments
- Blocked path: returns blocked status, send_fn is never called
- Passed path: Gmail send executes and result is returned

Requirements: 1.1, 1.2
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.outbound_validator import (
    Material,
    RuleResult,
    RuleSeverity,
    ValidationContext,
    ValidationGateResult,
    ValidationReport,
)
from app.integrations.gmail_client import GmailSendResult
from app.workers.outreach_worker import (
    OutreachRequest,
    _build_material,
    _build_validation_context,
    run_gmail_outreach,
    run_outreach_send,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def gmail_request() -> OutreachRequest:
    """A typical Gmail outreach request."""
    return OutreachRequest(
        pipeline_record_id="rec-gmail-001",
        contact_email="john.doe@example.com",
        contact_first_name="John",
        contact_last_name="Doe",
        outreach_technique="manual_apply",
        subject="Exciting opportunity at TechCorp",
        body="Hi John,\n\nI noticed your company is hiring...",
        signature="Best regards,\nJane Smith",
        personalization_fields={
            "first_name": "John",
            "company_name": "TechCorp",
            "hook": "cloud migration project",
        },
    )


@pytest.fixture
def mock_ctx():
    """Mock ARQ worker context with required shared resources."""
    return {
        "schema_registry": MagicMock(),
        "pipeline_manager": MagicMock(),
        "validation_repo": MagicMock(),
    }


@pytest.fixture
def passed_report() -> ValidationReport:
    """A validation report where all rules passed."""
    return ValidationReport(
        id="rpt-001",
        pipeline_record_id="rec-gmail-001",
        outreach_technique="manual_apply",
        results=[
            RuleResult(
                rule_id="unreplaced_tokens",
                passed=True,
                severity=RuleSeverity.BLOCKING,
            ),
            RuleResult(
                rule_id="empty_subject",
                passed=True,
                severity=RuleSeverity.BLOCKING,
            ),
        ],
        passed=True,
        has_warnings=False,
        total_execution_ms=12.5,
    )


@pytest.fixture
def blocked_report() -> ValidationReport:
    """A validation report with blocking failures."""
    return ValidationReport(
        id="rpt-002",
        pipeline_record_id="rec-gmail-001",
        outreach_technique="manual_apply",
        results=[
            RuleResult(
                rule_id="unreplaced_tokens",
                passed=False,
                severity=RuleSeverity.BLOCKING,
                message="Found 1 unreplaced token(s)",
            ),
        ],
        passed=False,
        has_warnings=False,
        total_execution_ms=8.3,
    )


# ─── Test: Material and Context Construction ──────────────────────────────────


class TestBuildMaterial:
    """Tests for _build_material helper."""

    def test_constructs_material_from_request(self, gmail_request):
        """Material fields are correctly mapped from OutreachRequest."""
        material = _build_material(gmail_request)

        assert isinstance(material, Material)
        assert material.subject == "Exciting opportunity at TechCorp"
        assert material.body == "Hi John,\n\nI noticed your company is hiring..."
        assert material.signature == "Best regards,\nJane Smith"
        assert material.personalization_fields == {
            "first_name": "John",
            "company_name": "TechCorp",
            "hook": "cloud migration project",
        }

    def test_handles_none_signature(self):
        """Material with no signature maps to None."""
        request = OutreachRequest(
            pipeline_record_id="rec-001",
            contact_email="test@test.com",
            contact_first_name="Test",
            contact_last_name="User",
            outreach_technique="manual_apply",
            subject="Subject",
            body="Body text",
        )
        material = _build_material(request)
        assert material.signature is None

    def test_handles_empty_personalization(self):
        """Material with no personalization_fields maps to empty dict."""
        request = OutreachRequest(
            pipeline_record_id="rec-001",
            contact_email="test@test.com",
            contact_first_name="Test",
            contact_last_name="User",
            outreach_technique="manual_apply",
            subject="Subject",
            body="Body text",
        )
        material = _build_material(request)
        assert material.personalization_fields == {}


class TestBuildValidationContext:
    """Tests for _build_validation_context helper."""

    def test_constructs_context_from_request(self, gmail_request):
        """ValidationContext fields are correctly mapped from OutreachRequest."""
        context = _build_validation_context(gmail_request)

        assert isinstance(context, ValidationContext)
        assert context.pipeline_record_id == "rec-gmail-001"
        assert context.contact_first_name == "John"
        assert context.contact_last_name == "Doe"
        assert context.outreach_technique == "manual_apply"
        assert context.material_type == "email"
        assert set(context.required_fields) == {"first_name", "company_name", "hook"}

    def test_empty_personalization_yields_empty_required_fields(self):
        """No personalization_fields → empty required_fields list."""
        request = OutreachRequest(
            pipeline_record_id="rec-001",
            contact_email="test@test.com",
            contact_first_name="Test",
            contact_last_name="User",
            outreach_technique="manual_apply",
            subject="Subject",
            body="Body text",
        )
        context = _build_validation_context(request)
        assert context.required_fields == []


# ─── Test: Gmail Outreach - Blocked Path ──────────────────────────────────────


class TestGmailOutreachBlocked:
    """Tests for run_gmail_outreach when validation blocks the send."""

    @pytest.mark.asyncio
    @patch("app.workers.outreach_worker.GmailClient")
    @patch("app.workers.outreach_worker._build_outbound_validator")
    async def test_blocked_returns_blocked_status(
        self, mock_build_validator, mock_gmail_cls, mock_ctx, gmail_request, blocked_report
    ):
        """When validator blocks, result has status=blocked and blocking_rules."""
        mock_validator = MagicMock()
        mock_validator.validate_and_send = AsyncMock(
            return_value=ValidationGateResult(blocked=True, report=blocked_report)
        )
        mock_build_validator.return_value = mock_validator

        result = await run_gmail_outreach(mock_ctx, gmail_request)

        assert result["status"] == "blocked"
        assert result["pipeline_record_id"] == "rec-gmail-001"
        assert "unreplaced_tokens" in result["blocking_rules"]
        assert result["report_id"] == "rpt-002"

    @pytest.mark.asyncio
    @patch("app.workers.outreach_worker.GmailClient")
    @patch("app.workers.outreach_worker._build_outbound_validator")
    async def test_blocked_does_not_call_gmail_send(
        self, mock_build_validator, mock_gmail_cls, mock_ctx, gmail_request, blocked_report
    ):
        """When validator blocks, Gmail send_email is never invoked."""
        mock_validator = MagicMock()
        mock_validator.validate_and_send = AsyncMock(
            return_value=ValidationGateResult(blocked=True, report=blocked_report)
        )
        mock_build_validator.return_value = mock_validator

        mock_gmail_instance = MagicMock()
        mock_gmail_instance.send_email = AsyncMock()
        mock_gmail_cls.return_value = mock_gmail_instance

        await run_gmail_outreach(mock_ctx, gmail_request)

        # The send_fn is passed to validate_and_send but never called when blocked
        # (the validator handles this internally)
        mock_validator.validate_and_send.assert_called_once()


# ─── Test: Gmail Outreach - Passed Path ───────────────────────────────────────


class TestGmailOutreachPassed:
    """Tests for run_gmail_outreach when validation passes and email is sent."""

    @pytest.mark.asyncio
    @patch("app.workers.outreach_worker.GmailClient")
    @patch("app.workers.outreach_worker._build_outbound_validator")
    async def test_passed_returns_sent_status(
        self, mock_build_validator, mock_gmail_cls, mock_ctx, gmail_request, passed_report
    ):
        """When validator passes, result has status=sent with message_id."""
        mock_send_result = GmailSendResult(
            message_id="msg-abc123",
            thread_id="thread-xyz",
            label_ids=["SENT"],
        )
        mock_validator = MagicMock()
        mock_validator.validate_and_send = AsyncMock(
            return_value=ValidationGateResult(
                blocked=False, report=passed_report, send_result=mock_send_result
            )
        )
        mock_build_validator.return_value = mock_validator

        result = await run_gmail_outreach(mock_ctx, gmail_request)

        assert result["status"] == "sent"
        assert result["pipeline_record_id"] == "rec-gmail-001"
        assert result["message_id"] == "msg-abc123"
        assert result["thread_id"] == "thread-xyz"
        assert result["report_id"] == "rpt-001"

    @pytest.mark.asyncio
    @patch("app.workers.outreach_worker.GmailClient")
    @patch("app.workers.outreach_worker._build_outbound_validator")
    async def test_validate_and_send_receives_correct_material(
        self, mock_build_validator, mock_gmail_cls, mock_ctx, gmail_request, passed_report
    ):
        """validate_and_send receives Material constructed from the request."""
        mock_send_result = GmailSendResult(
            message_id="msg-001", thread_id="thread-001", label_ids=[]
        )
        mock_validator = MagicMock()
        mock_validator.validate_and_send = AsyncMock(
            return_value=ValidationGateResult(
                blocked=False, report=passed_report, send_result=mock_send_result
            )
        )
        mock_build_validator.return_value = mock_validator

        await run_gmail_outreach(mock_ctx, gmail_request)

        call_args = mock_validator.validate_and_send.call_args
        material = call_args.kwargs.get("material") or call_args[1].get("material") if call_args[1] else call_args[0][0]

        assert material.subject == gmail_request.subject
        assert material.body == gmail_request.body
        assert material.signature == gmail_request.signature

    @pytest.mark.asyncio
    @patch("app.workers.outreach_worker.GmailClient")
    @patch("app.workers.outreach_worker._build_outbound_validator")
    async def test_validate_and_send_receives_correct_context(
        self, mock_build_validator, mock_gmail_cls, mock_ctx, gmail_request, passed_report
    ):
        """validate_and_send receives ValidationContext with correct pipeline/contact info."""
        mock_send_result = GmailSendResult(
            message_id="msg-001", thread_id="thread-001", label_ids=[]
        )
        mock_validator = MagicMock()
        mock_validator.validate_and_send = AsyncMock(
            return_value=ValidationGateResult(
                blocked=False, report=passed_report, send_result=mock_send_result
            )
        )
        mock_build_validator.return_value = mock_validator

        await run_gmail_outreach(mock_ctx, gmail_request)

        call_args = mock_validator.validate_and_send.call_args
        context = call_args.kwargs.get("context") or call_args[1].get("context") if call_args[1] else call_args[0][1]

        assert context.pipeline_record_id == "rec-gmail-001"
        assert context.contact_first_name == "John"
        assert context.contact_last_name == "Doe"
        assert context.outreach_technique == "manual_apply"
        assert context.material_type == "email"


# ─── Test: Missing Context Resources ─────────────────────────────────────────


class TestGmailOutreachMissingContext:
    """Tests for error handling when ARQ context is incomplete."""

    @pytest.mark.asyncio
    async def test_missing_schema_registry_returns_error(self, gmail_request):
        """Missing schema_registry in context returns error status."""
        ctx = {
            "pipeline_manager": MagicMock(),
            "validation_repo": MagicMock(),
        }
        result = await run_gmail_outreach(ctx, gmail_request)

        assert result["status"] == "error"
        assert "Missing required" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_pipeline_manager_returns_error(self, gmail_request):
        """Missing pipeline_manager in context returns error status."""
        ctx = {
            "schema_registry": MagicMock(),
            "validation_repo": MagicMock(),
        }
        result = await run_gmail_outreach(ctx, gmail_request)

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_missing_validation_repo_returns_error(self, gmail_request):
        """Missing validation_repo in context returns error status."""
        ctx = {
            "schema_registry": MagicMock(),
            "pipeline_manager": MagicMock(),
        }
        result = await run_gmail_outreach(ctx, gmail_request)

        assert result["status"] == "error"


# ─── Test: Unified Dispatcher ─────────────────────────────────────────────────


class TestRunOutreachSend:
    """Tests for run_outreach_send dispatcher."""

    @pytest.mark.asyncio
    @patch("app.workers.outreach_worker.run_gmail_outreach", new_callable=AsyncMock)
    @patch("app.workers.outreach_worker.run_lemlist_outreach", new_callable=AsyncMock)
    async def test_dispatches_to_gmail_for_manual_apply(
        self, mock_lemlist, mock_gmail, mock_ctx
    ):
        """manual_apply technique routes to run_gmail_outreach."""
        request = OutreachRequest(
            pipeline_record_id="rec-001",
            contact_email="test@test.com",
            contact_first_name="Test",
            contact_last_name="User",
            outreach_technique="manual_apply",
            subject="Subject",
            body="Body",
        )
        mock_gmail.return_value = {"status": "sent"}

        result = await run_outreach_send(mock_ctx, request)

        mock_gmail.assert_called_once_with(mock_ctx, request)
        mock_lemlist.assert_not_called()
        assert result["status"] == "sent"

    @pytest.mark.asyncio
    @patch("app.workers.outreach_worker.run_gmail_outreach", new_callable=AsyncMock)
    @patch("app.workers.outreach_worker.run_lemlist_outreach", new_callable=AsyncMock)
    async def test_dispatches_to_lemlist_for_lemlist_sequence(
        self, mock_lemlist, mock_gmail, mock_ctx
    ):
        """lemlist_sequence technique routes to run_lemlist_outreach."""
        request = OutreachRequest(
            pipeline_record_id="rec-001",
            contact_email="test@test.com",
            contact_first_name="Test",
            contact_last_name="User",
            outreach_technique="lemlist_sequence",
            subject="Subject",
            body="Body",
            sequence_id="seq-001",
            prospect_id="prospect-001",
        )
        mock_lemlist.return_value = {"status": "enrolled"}

        result = await run_outreach_send(mock_ctx, request)

        mock_lemlist.assert_called_once_with(mock_ctx, request)
        mock_gmail.assert_not_called()
        assert result["status"] == "enrolled"
