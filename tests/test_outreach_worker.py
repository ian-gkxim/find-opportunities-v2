"""Unit tests for the Lemlist outreach worker with validation gate.

Tests the run_lemlist_outreach() and run_outreach_send() ARQ task functions
to verify:
- Validation gate blocks send when blocking rules fail
- Validation gate permits send (enrollment proceeds) when all pass or only warnings
- Material and ValidationContext are correctly constructed from OutreachRequest
- Error handling for missing dependencies
- Blocked path logs and skips send

Requirements: 1.1, 1.2
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.outbound_validator import (
    Material,
    OutboundValidator,
    RuleResult,
    RuleSeverity,
    ValidationContext,
    ValidationGateResult,
    ValidationReport,
)
from app.workers.outreach_worker import (
    OutreachRequest,
    run_lemlist_outreach,
    run_outreach_send,
    _build_material,
    _build_validation_context,
)


@pytest.fixture
def base_request():
    """Base OutreachRequest for testing."""
    return OutreachRequest(
        pipeline_record_id="record-001",
        contact_email="john@acme.com",
        contact_first_name="John",
        contact_last_name="Smith",
        outreach_technique="cold_email_consultant",
        subject="Collaboration opportunity",
        body="Hi John, I noticed your work at Acme Corp...",
        signature="Best regards,\nJane Doe",
        personalization_fields={
            "first_name": "John",
            "company_name": "Acme Corp",
            "hook": "recent funding round",
        },
        sequence_id="seq-001",
        prospect_id="prospect-001",
    )


@pytest.fixture
def passing_report():
    """A ValidationReport where all rules passed."""
    return ValidationReport(
        id="report-001",
        pipeline_record_id="record-001",
        outreach_technique="cold_email_consultant",
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
def blocked_report():
    """A ValidationReport with blocking failures."""
    return ValidationReport(
        id="report-002",
        pipeline_record_id="record-001",
        outreach_technique="cold_email_consultant",
        results=[
            RuleResult(
                rule_id="unreplaced_tokens",
                passed=False,
                severity=RuleSeverity.BLOCKING,
                message="Found 1 unreplaced token(s)",
            ),
            RuleResult(
                rule_id="empty_subject",
                passed=True,
                severity=RuleSeverity.BLOCKING,
            ),
        ],
        passed=False,
        has_warnings=False,
        total_execution_ms=8.3,
    )


@pytest.fixture
def warning_report():
    """A ValidationReport with only warnings (not blocked)."""
    return ValidationReport(
        id="report-003",
        pipeline_record_id="record-001",
        outreach_technique="cold_email_consultant",
        results=[
            RuleResult(
                rule_id="unreplaced_tokens",
                passed=True,
                severity=RuleSeverity.BLOCKING,
            ),
            RuleResult(
                rule_id="length_bounds",
                passed=False,
                severity=RuleSeverity.WARNING,
                message="Body too short (45 < 50 chars)",
            ),
        ],
        passed=True,
        has_warnings=True,
        total_execution_ms=10.0,
    )


@pytest.fixture
def mock_ctx(passing_report):
    """Create a mock ARQ worker context with required dependencies."""
    mock_schema_registry = MagicMock()
    mock_pipeline_manager = MagicMock()
    mock_validation_repo = MagicMock()

    return {
        "schema_registry": mock_schema_registry,
        "pipeline_manager": mock_pipeline_manager,
        "validation_repo": mock_validation_repo,
    }


class TestBuildMaterial:
    """Tests for Material construction from OutreachRequest."""

    def test_material_has_correct_subject(self, base_request):
        """Material subject matches request subject."""
        material = _build_material(base_request)
        assert material.subject == "Collaboration opportunity"

    def test_material_has_correct_body(self, base_request):
        """Material body matches request body."""
        material = _build_material(base_request)
        assert material.body == "Hi John, I noticed your work at Acme Corp..."

    def test_material_has_correct_signature(self, base_request):
        """Material signature matches request signature."""
        material = _build_material(base_request)
        assert material.signature == "Best regards,\nJane Doe"

    def test_material_has_correct_personalization_fields(self, base_request):
        """Material personalization_fields matches request."""
        material = _build_material(base_request)
        assert material.personalization_fields == {
            "first_name": "John",
            "company_name": "Acme Corp",
            "hook": "recent funding round",
        }

    def test_material_empty_personalization_defaults_to_empty_dict(self):
        """Material with None personalization_fields defaults to empty dict."""
        request = OutreachRequest(
            pipeline_record_id="r-1",
            contact_email="x@y.com",
            contact_first_name="X",
            contact_last_name="Y",
            outreach_technique="tech",
            subject="S",
            body="B",
            personalization_fields=None,
        )
        material = _build_material(request)
        assert material.personalization_fields == {}


class TestBuildValidationContext:
    """Tests for ValidationContext construction from OutreachRequest."""

    def test_context_has_pipeline_record_id(self, base_request):
        """Context pipeline_record_id matches request."""
        context = _build_validation_context(base_request)
        assert context.pipeline_record_id == "record-001"

    def test_context_has_contact_name(self, base_request):
        """Context contact names match request."""
        context = _build_validation_context(base_request)
        assert context.contact_first_name == "John"
        assert context.contact_last_name == "Smith"

    def test_context_has_outreach_technique(self, base_request):
        """Context outreach_technique matches request."""
        context = _build_validation_context(base_request)
        assert context.outreach_technique == "cold_email_consultant"

    def test_context_material_type_is_email(self, base_request):
        """Context material_type defaults to 'email'."""
        context = _build_validation_context(base_request)
        assert context.material_type == "email"

    def test_context_required_fields_from_personalization_keys(self, base_request):
        """Context required_fields are derived from personalization_fields keys."""
        context = _build_validation_context(base_request)
        assert set(context.required_fields) == {"first_name", "company_name", "hook"}


class TestLemlistOutreachBlocked:
    """Tests for when validation blocks the Lemlist enrollment."""

    @pytest.mark.asyncio
    async def test_blocked_returns_blocked_status(
        self, base_request, mock_ctx, blocked_report
    ):
        """When validation blocks, status is 'blocked' and no enrollment occurs."""
        with patch(
            "app.workers.outreach_worker._build_outbound_validator"
        ) as mock_build:
            mock_validator = AsyncMock()
            mock_validator.validate_and_send.return_value = ValidationGateResult(
                blocked=True, report=blocked_report
            )
            mock_build.return_value = mock_validator

            result = await run_lemlist_outreach(mock_ctx, base_request)

        assert result["status"] == "blocked"
        assert "unreplaced_tokens" in result["blocking_rules"]
        assert result["report_id"] == "report-002"

    @pytest.mark.asyncio
    async def test_blocked_send_skips_lemlist_enrollment(
        self, base_request, mock_ctx, blocked_report
    ):
        """When blocked, LemlistEngine.enroll_prospects() is never called."""
        with patch(
            "app.workers.outreach_worker._build_outbound_validator"
        ) as mock_build:
            mock_validator = AsyncMock()
            mock_validator.validate_and_send.return_value = ValidationGateResult(
                blocked=True, report=blocked_report
            )
            mock_build.return_value = mock_validator

            with patch(
                "app.workers.outreach_worker.LemlistEngine"
            ) as mock_lemlist_cls:
                mock_lemlist = AsyncMock()
                mock_lemlist_cls.return_value = mock_lemlist

                result = await run_lemlist_outreach(mock_ctx, base_request)

                # enroll_prospects should NOT be called when blocked
                mock_lemlist.enroll_prospects.assert_not_called()


class TestLemlistOutreachPassed:
    """Tests for when validation passes and enrollment proceeds."""

    @pytest.mark.asyncio
    async def test_passed_returns_enrolled_status(
        self, base_request, mock_ctx, passing_report
    ):
        """When validation passes, enrollment succeeds with enrolled_count."""
        with patch(
            "app.workers.outreach_worker._build_outbound_validator"
        ) as mock_build:
            mock_validator = AsyncMock()
            mock_validator.validate_and_send.return_value = ValidationGateResult(
                blocked=False,
                report=passing_report,
                send_result={"enrolled_count": 1},
            )
            mock_build.return_value = mock_validator

            result = await run_lemlist_outreach(mock_ctx, base_request)

        assert result["status"] == "enrolled"
        assert result["enrolled_count"] == 1
        assert result["report_id"] == "report-001"

    @pytest.mark.asyncio
    async def test_validate_and_send_receives_send_fn(
        self, base_request, mock_ctx, passing_report
    ):
        """validate_and_send is called with material, context, and a callable send_fn."""
        with patch(
            "app.workers.outreach_worker._build_outbound_validator"
        ) as mock_build:
            mock_validator = AsyncMock()
            mock_validator.validate_and_send.return_value = ValidationGateResult(
                blocked=False,
                report=passing_report,
                send_result={"enrolled_count": 1},
            )
            mock_build.return_value = mock_validator

            await run_lemlist_outreach(mock_ctx, base_request)

            # Verify validate_and_send was called with Material, ValidationContext, send_fn
            call_args = mock_validator.validate_and_send.call_args
            assert call_args is not None
            kwargs = call_args.kwargs
            assert isinstance(kwargs["material"], Material)
            assert isinstance(kwargs["context"], ValidationContext)
            assert callable(kwargs["send_fn"])


class TestLemlistOutreachErrorHandling:
    """Tests for error handling in the Lemlist outreach worker."""

    @pytest.mark.asyncio
    async def test_missing_context_returns_error(self, base_request):
        """Missing required context resources returns error status."""
        ctx = {}  # No dependencies

        result = await run_lemlist_outreach(ctx, base_request)

        assert result["status"] == "error"
        assert "Missing required" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_schema_registry_returns_error(self, base_request):
        """Missing schema_registry returns error."""
        ctx = {
            "pipeline_manager": MagicMock(),
            "validation_repo": MagicMock(),
        }

        result = await run_lemlist_outreach(ctx, base_request)

        assert result["status"] == "error"


class TestUnifiedEntryPoint:
    """Tests for run_outreach_send dispatch logic."""

    @pytest.mark.asyncio
    async def test_lemlist_technique_dispatches_to_lemlist(
        self, mock_ctx, passing_report
    ):
        """Lemlist technique routes to run_lemlist_outreach."""
        request = OutreachRequest(
            pipeline_record_id="r-1",
            contact_email="a@b.com",
            contact_first_name="A",
            contact_last_name="B",
            outreach_technique="lemlist_sequence",
            subject="Test",
            body="Test body",
            sequence_id="seq-1",
            prospect_id="p-1",
        )

        with patch(
            "app.workers.outreach_worker.run_lemlist_outreach"
        ) as mock_lemlist:
            mock_lemlist.return_value = {"status": "enrolled"}
            result = await run_outreach_send(mock_ctx, request)

            mock_lemlist.assert_called_once_with(mock_ctx, request)
            assert result["status"] == "enrolled"

    @pytest.mark.asyncio
    async def test_non_lemlist_technique_dispatches_to_gmail(
        self, mock_ctx, passing_report
    ):
        """Non-Lemlist technique routes to run_gmail_outreach."""
        request = OutreachRequest(
            pipeline_record_id="r-1",
            contact_email="a@b.com",
            contact_first_name="A",
            contact_last_name="B",
            outreach_technique="cold_email_consultant",
            subject="Test",
            body="Test body",
        )

        with patch(
            "app.workers.outreach_worker.run_gmail_outreach"
        ) as mock_gmail:
            mock_gmail.return_value = {"status": "sent"}
            result = await run_outreach_send(mock_ctx, request)

            mock_gmail.assert_called_once_with(mock_ctx, request)
            assert result["status"] == "sent"
