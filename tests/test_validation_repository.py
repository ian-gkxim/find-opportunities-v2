"""Unit tests for ValidationRepository.

Tests requirement 1.4: Validation report persistence — serialization,
deserialization, and repository save/retrieve operations.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.outbound_validator import (
    RuleResult,
    RuleSeverity,
    TextSpan,
    ValidationReport,
)
from app.repositories.validation_repository import (
    ValidationRepository,
    _deserialize_results,
    _serialize_results,
)


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_rule_results() -> list[RuleResult]:
    """RuleResults with TextSpans for serialization testing."""
    return [
        RuleResult(
            rule_id="unreplaced_tokens",
            passed=False,
            severity=RuleSeverity.BLOCKING,
            message="Found 2 unreplaced token(s)",
            offending_spans=[
                TextSpan(start=4, end=12, field_name="body", text="{{name}}"),
                TextSpan(start=30, end=45, field_name="subject", text="<INSERT_TITLE>"),
            ],
            execution_ms=1.23,
        ),
        RuleResult(
            rule_id="length_bounds",
            passed=True,
            severity=RuleSeverity.WARNING,
            message="",
            offending_spans=[],
            execution_ms=0.45,
        ),
    ]


@pytest.fixture
def sample_report(sample_rule_results: list[RuleResult]) -> ValidationReport:
    """A complete ValidationReport for persistence testing."""
    return ValidationReport(
        id="rpt-001-uuid",
        pipeline_record_id="rec-001-uuid",
        outreach_technique="cold_email_consultant",
        results=sample_rule_results,
        passed=False,
        has_warnings=False,
        total_execution_ms=1.68,
        created_at=datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
    )


# ─── Serialization round-trip tests ──────────────────────────────────────────


class TestSerializationRoundTrip:
    """Test that _serialize_results → _deserialize_results preserves all data."""

    def test_round_trip_preserves_rule_results(
        self, sample_rule_results: list[RuleResult]
    ):
        """Serialize then deserialize should return identical RuleResult objects."""
        serialized = _serialize_results(sample_rule_results)
        deserialized = _deserialize_results(serialized)

        assert len(deserialized) == len(sample_rule_results)
        for original, restored in zip(sample_rule_results, deserialized):
            assert restored.rule_id == original.rule_id
            assert restored.passed == original.passed
            assert restored.severity == original.severity
            assert restored.message == original.message
            assert restored.execution_ms == original.execution_ms
            assert len(restored.offending_spans) == len(original.offending_spans)
            for orig_span, rest_span in zip(
                original.offending_spans, restored.offending_spans
            ):
                assert rest_span.start == orig_span.start
                assert rest_span.end == orig_span.end
                assert rest_span.field_name == orig_span.field_name
                assert rest_span.text == orig_span.text

    def test_round_trip_through_json_string(
        self, sample_rule_results: list[RuleResult]
    ):
        """Simulate database round-trip: serialize → json.dumps → json.loads → deserialize."""
        serialized = _serialize_results(sample_rule_results)
        json_string = json.dumps(serialized)
        deserialized = _deserialize_results(json_string)

        assert len(deserialized) == len(sample_rule_results)
        assert deserialized[0].rule_id == "unreplaced_tokens"
        assert deserialized[0].passed is False
        assert deserialized[1].rule_id == "length_bounds"
        assert deserialized[1].passed is True


# ─── Serialization correctness tests ─────────────────────────────────────────


class TestSerializeResults:
    """Test that _serialize_results includes all required fields."""

    def test_serialize_includes_all_fields(self, sample_rule_results: list[RuleResult]):
        """Serialized dicts must contain rule_id, passed, severity, message, offending_spans, execution_ms."""
        serialized = _serialize_results(sample_rule_results)

        for item in serialized:
            assert "rule_id" in item
            assert "passed" in item
            assert "severity" in item
            assert "message" in item
            assert "offending_spans" in item
            assert "execution_ms" in item

    def test_severity_serialized_as_string(self, sample_rule_results: list[RuleResult]):
        """Severity enum should be serialized as its string value."""
        serialized = _serialize_results(sample_rule_results)

        assert serialized[0]["severity"] == "blocking"
        assert serialized[1]["severity"] == "warning"

    def test_text_spans_serialized_with_all_fields(
        self, sample_rule_results: list[RuleResult]
    ):
        """Each offending span dict includes start, end, field_name, text."""
        serialized = _serialize_results(sample_rule_results)
        spans = serialized[0]["offending_spans"]

        assert len(spans) == 2
        for span in spans:
            assert "start" in span
            assert "end" in span
            assert "field_name" in span
            assert "text" in span

        assert spans[0]["start"] == 4
        assert spans[0]["end"] == 12
        assert spans[0]["field_name"] == "body"
        assert spans[0]["text"] == "{{name}}"

    def test_empty_spans_list_serialized(self):
        """A result with no offending spans serializes to an empty list."""
        result = RuleResult(
            rule_id="length_bounds",
            passed=True,
            severity=RuleSeverity.WARNING,
            message="",
            offending_spans=[],
            execution_ms=0.5,
        )
        serialized = _serialize_results([result])

        assert serialized[0]["offending_spans"] == []


# ─── Deserialization edge case tests ──────────────────────────────────────────


class TestDeserializeResults:
    """Test _deserialize_results handles various input forms and edge cases."""

    def test_deserialize_empty_spans_list(self):
        """Deserializing a result with empty offending_spans returns empty list."""
        data = [
            {
                "rule_id": "empty_subject",
                "passed": True,
                "severity": "blocking",
                "message": "",
                "offending_spans": [],
                "execution_ms": 0.0,
            }
        ]
        results = _deserialize_results(data)

        assert len(results) == 1
        assert results[0].offending_spans == []

    def test_deserialize_zero_execution_ms(self):
        """Zero execution_ms is handled correctly."""
        data = [
            {
                "rule_id": "missing_signature",
                "passed": True,
                "severity": "blocking",
                "message": "",
                "offending_spans": [],
                "execution_ms": 0.0,
            }
        ]
        results = _deserialize_results(data)

        assert results[0].execution_ms == 0.0

    def test_deserialize_none_returns_empty_list(self):
        """None input (e.g. NULL column) returns an empty list."""
        results = _deserialize_results(None)
        assert results == []

    def test_deserialize_json_string(self):
        """Handles raw JSON string input (not pre-parsed)."""
        data = json.dumps([
            {
                "rule_id": "malformed_url",
                "passed": False,
                "severity": "warning",
                "message": "Found 1 malformed URL(s)",
                "offending_spans": [
                    {"start": 10, "end": 25, "field_name": "body", "text": "http://nohost"}
                ],
                "execution_ms": 2.1,
            }
        ])
        results = _deserialize_results(data)

        assert len(results) == 1
        assert results[0].rule_id == "malformed_url"
        assert results[0].severity == RuleSeverity.WARNING
        assert len(results[0].offending_spans) == 1
        assert results[0].offending_spans[0].text == "http://nohost"

    def test_deserialize_missing_optional_fields_uses_defaults(self):
        """Missing message and execution_ms keys use defaults."""
        data = [
            {
                "rule_id": "duplicate_content",
                "passed": True,
                "severity": "warning",
            }
        ]
        results = _deserialize_results(data)

        assert results[0].message == ""
        assert results[0].execution_ms == 0.0
        assert results[0].offending_spans == []


# ─── Repository save/retrieve tests (mocked session) ─────────────────────────


def _make_mock_session_factory(session):
    """Create a mock that mimics async_sessionmaker behavior.

    async_sessionmaker() returns an AsyncSession that is itself an
    async context manager, i.e. `async with factory() as session:`.
    """
    # The factory() call returns an object that supports async with
    context_manager = AsyncMock()
    context_manager.__aenter__ = AsyncMock(return_value=session)
    context_manager.__aexit__ = AsyncMock(return_value=None)

    factory = MagicMock()
    factory.return_value = context_manager
    return factory


class TestValidationRepositorySave:
    """Test save_validation_report calls session with correct parameters."""

    @pytest.fixture
    def mock_session_factory(self):
        """Create a mock async session factory."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        factory = _make_mock_session_factory(session)
        return factory, session

    @pytest.mark.asyncio
    async def test_save_calls_session_execute_with_correct_params(
        self, mock_session_factory, sample_report: ValidationReport
    ):
        """save_validation_report should execute INSERT with report data."""
        factory, session = mock_session_factory
        repo = ValidationRepository(session_factory=factory)

        result_id = await repo.save_validation_report(sample_report)

        assert result_id == sample_report.id
        session.execute.assert_called_once()
        session.commit.assert_called_once()

        # Verify the params passed to execute
        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["id"] == "rpt-001-uuid"
        assert params["pipeline_record_id"] == "rec-001-uuid"
        assert params["outreach_technique"] == "cold_email_consultant"
        assert params["passed"] is False
        assert params["has_warnings"] is False
        assert params["total_execution_ms"] == 1.68
        # results should be JSON-encoded string
        results_parsed = json.loads(params["results"])
        assert len(results_parsed) == 2
        assert results_parsed[0]["rule_id"] == "unreplaced_tokens"


class TestValidationRepositoryGetByPipelineRecord:
    """Test get_reports_for_pipeline_record returns correct reports."""

    @pytest.fixture
    def mock_session_with_rows(self):
        """Create a mock session that returns sample rows."""
        rows = [
            (
                "rpt-002-uuid",
                "rec-001-uuid",
                "cold_email_consultant",
                True,   # passed
                False,  # has_warnings
                2.5,    # total_execution_ms
                json.dumps([
                    {
                        "rule_id": "unreplaced_tokens",
                        "passed": True,
                        "severity": "blocking",
                        "message": "",
                        "offending_spans": [],
                        "execution_ms": 1.1,
                    }
                ]),
                datetime(2024, 6, 15, 11, 0, 0, tzinfo=timezone.utc),
            ),
            (
                "rpt-001-uuid",
                "rec-001-uuid",
                "cold_email_consultant",
                False,  # passed
                False,  # has_warnings
                1.68,   # total_execution_ms
                json.dumps([
                    {
                        "rule_id": "unreplaced_tokens",
                        "passed": False,
                        "severity": "blocking",
                        "message": "Found 1 unreplaced token(s)",
                        "offending_spans": [
                            {"start": 4, "end": 12, "field_name": "body", "text": "{{name}}"}
                        ],
                        "execution_ms": 1.23,
                    }
                ]),
                datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
            ),
        ]

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.fetchall.return_value = rows
        session.execute = AsyncMock(return_value=result_mock)

        return _make_mock_session_factory(session)

    @pytest.mark.asyncio
    async def test_get_reports_for_pipeline_record_returns_all(
        self, mock_session_with_rows
    ):
        """Should return all reports for the given pipeline_record_id."""
        repo = ValidationRepository(session_factory=mock_session_with_rows)

        reports = await repo.get_reports_for_pipeline_record("rec-001-uuid")

        assert len(reports) == 2
        assert reports[0].id == "rpt-002-uuid"
        assert reports[0].passed is True
        assert reports[1].id == "rpt-001-uuid"
        assert reports[1].passed is False

    @pytest.mark.asyncio
    async def test_get_reports_deserializes_results_correctly(
        self, mock_session_with_rows
    ):
        """Returned reports should have properly deserialized RuleResult objects."""
        repo = ValidationRepository(session_factory=mock_session_with_rows)

        reports = await repo.get_reports_for_pipeline_record("rec-001-uuid")

        # Second report has a failing rule with a span
        failing_report = reports[1]
        assert len(failing_report.results) == 1
        assert failing_report.results[0].rule_id == "unreplaced_tokens"
        assert failing_report.results[0].passed is False
        assert failing_report.results[0].severity == RuleSeverity.BLOCKING
        assert len(failing_report.results[0].offending_spans) == 1
        assert failing_report.results[0].offending_spans[0].text == "{{name}}"

    @pytest.mark.asyncio
    async def test_get_reports_empty_result(self):
        """Should return empty list when no reports exist for the pipeline record."""
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

        factory = _make_mock_session_factory(session)

        repo = ValidationRepository(session_factory=factory)
        reports = await repo.get_reports_for_pipeline_record("nonexistent-id")

        assert reports == []
