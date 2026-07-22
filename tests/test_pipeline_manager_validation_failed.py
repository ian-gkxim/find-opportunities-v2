"""Unit tests for PipelineManager.transition_to_validation_failed().

Tests cover:
- Successful transition updates record state to validation_failed
- WebSocket broadcast includes blocking failure details with text spans
- Missing record_id returns INVALID_STATE result

Validates: Requirements 1.2
"""

import json
from datetime import datetime, timezone

import pytest

from app.core.outbound_validator import RuleResult, RuleSeverity, TextSpan
from app.core.pipeline_manager import (
    PipelineManager,
    PipelineRecordData,
    PipelineTransition,
    PipelineTransitionResult,
    RequiresActionType,
)


# --- Fixtures ---


def make_record(
    record_id: str = "rec-1",
    prospect_id: str = "prospect-1",
    opportunity_type_id: str = "cold_outreach_consultant",
    beneficiary_id: str = "consultant",
    current_status: str = "Sent",
    is_terminal: bool = False,
    updated_at: datetime | None = None,
) -> PipelineRecordData:
    """Helper to create a PipelineRecordData for testing."""
    return PipelineRecordData(
        id=record_id,
        prospect_id=prospect_id,
        opportunity_type_id=opportunity_type_id,
        beneficiary_id=beneficiary_id,
        current_status=current_status,
        is_terminal=is_terminal,
        updated_at=updated_at or datetime.now(timezone.utc),
    )


class FakeRepository:
    """In-memory repository implementing PipelineRepository protocol."""

    def __init__(self, records: list[PipelineRecordData] | None = None):
        self.records: dict[str, PipelineRecordData] = {}
        if records:
            for r in records:
                self.records[r.id] = r

    async def get_pipeline_record(
        self, record_id: str
    ) -> PipelineRecordData | None:
        return self.records.get(record_id)

    async def update_pipeline_record(
        self,
        record_id: str,
        new_status: str,
        previous_status: str,
        is_terminal: bool,
    ) -> None:
        if record_id in self.records:
            record = self.records[record_id]
            record.previous_status = record.current_status
            record.current_status = new_status
            record.is_terminal = is_terminal
            record.updated_at = datetime.now(timezone.utc)

    async def get_stale_records(
        self, days_threshold: int
    ) -> list[PipelineRecordData]:
        return []

    async def get_failed_sequence_records(self) -> list[PipelineRecordData]:
        return []

    async def get_enrichment_error_records(self) -> list[PipelineRecordData]:
        return []


class FakePublisher:
    """In-memory event publisher for testing broadcasts."""

    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.messages.append((channel, message))
        return 1


# --- Tests ---


class TestTransitionToValidationFailed:
    """Tests for PipelineManager.transition_to_validation_failed()."""

    @pytest.mark.asyncio
    async def test_successful_transition_updates_state(self):
        """When record exists, transitions to validation_failed and returns ADVANCED."""
        record = make_record(record_id="rec-100", current_status="Sent")
        repo = FakeRepository(records=[record])
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        blocking_failures = [
            RuleResult(
                rule_id="unreplaced_tokens",
                passed=False,
                severity=RuleSeverity.BLOCKING,
                message="Found 1 unreplaced token(s)",
                offending_spans=[
                    TextSpan(start=4, end=18, field_name="body", text="{{first_name}}")
                ],
            )
        ]

        result = await manager.transition_to_validation_failed(
            record_id="rec-100",
            blocking_failures=blocking_failures,
        )

        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.record_id == "rec-100"
        assert result.new_status == "validation_failed"
        assert result.previous_status == "Sent"
        # Verify the record was actually updated in the repository
        assert repo.records["rec-100"].current_status == "validation_failed"

    @pytest.mark.asyncio
    async def test_websocket_broadcast_includes_blocking_failure_details(self):
        """When record exists and publisher is available, publishes failure details with spans."""
        record = make_record(
            record_id="rec-200",
            current_status="Drafted",
            beneficiary_id="ben-1",
        )
        repo = FakeRepository(records=[record])
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        blocking_failures = [
            RuleResult(
                rule_id="unreplaced_tokens",
                passed=False,
                severity=RuleSeverity.BLOCKING,
                message="Found 2 unreplaced token(s)",
                offending_spans=[
                    TextSpan(start=0, end=12, field_name="subject", text="{{company}}"),
                    TextSpan(start=20, end=34, field_name="body", text="{{first_name}}"),
                ],
            ),
            RuleResult(
                rule_id="empty_subject",
                passed=False,
                severity=RuleSeverity.BLOCKING,
                message="Email has empty or missing subject",
                offending_spans=[],
            ),
        ]

        await manager.transition_to_validation_failed(
            record_id="rec-200",
            blocking_failures=blocking_failures,
        )

        # Find the validation_failed broadcast (on notifications channel)
        notification_messages = [
            (ch, json.loads(msg))
            for ch, msg in publisher.messages
            if ch == PipelineManager.CHANNEL_NOTIFICATIONS
        ]
        assert len(notification_messages) >= 1

        channel, payload = notification_messages[0]
        assert payload["type"] == "validation_failed"
        assert payload["action_type"] == RequiresActionType.VALIDATION_FAILED.value
        assert payload["record_id"] == "rec-200"
        assert payload["beneficiary_id"] == "ben-1"
        assert "timestamp" in payload

        # Verify blocking_failures are serialized with spans
        failures = payload["blocking_failures"]
        assert len(failures) == 2

        # First failure: unreplaced_tokens with 2 spans
        assert failures[0]["rule_id"] == "unreplaced_tokens"
        assert failures[0]["message"] == "Found 2 unreplaced token(s)"
        assert failures[0]["severity"] == "blocking"
        assert len(failures[0]["offending_spans"]) == 2
        assert failures[0]["offending_spans"][0] == {
            "start": 0,
            "end": 12,
            "field_name": "subject",
            "text": "{{company}}",
        }
        assert failures[0]["offending_spans"][1] == {
            "start": 20,
            "end": 34,
            "field_name": "body",
            "text": "{{first_name}}",
        }

        # Second failure: empty_subject with no spans
        assert failures[1]["rule_id"] == "empty_subject"
        assert failures[1]["message"] == "Email has empty or missing subject"
        assert failures[1]["offending_spans"] == []

    @pytest.mark.asyncio
    async def test_missing_record_returns_invalid_state(self):
        """When _get_record() returns None, returns INVALID_STATE result."""
        repo = FakeRepository(records=[])  # No records
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        blocking_failures = [
            RuleResult(
                rule_id="unreplaced_tokens",
                passed=False,
                severity=RuleSeverity.BLOCKING,
                message="Found 1 unreplaced token(s)",
                offending_spans=[
                    TextSpan(start=0, end=14, field_name="body", text="{{first_name}}")
                ],
            )
        ]

        result = await manager.transition_to_validation_failed(
            record_id="nonexistent-record",
            blocking_failures=blocking_failures,
        )

        assert result.result == PipelineTransitionResult.INVALID_STATE
        assert result.record_id == "nonexistent-record"
        assert "not found" in result.reason.lower()
        # No broadcast should have been sent on the notifications channel
        notification_messages = [
            (ch, msg)
            for ch, msg in publisher.messages
            if ch == PipelineManager.CHANNEL_NOTIFICATIONS
        ]
        assert len(notification_messages) == 0
