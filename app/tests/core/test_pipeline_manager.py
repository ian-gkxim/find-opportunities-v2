"""Unit tests for PipelineManager — state machine transitions and event handling.

Tests cover:
- Reply detection advancing pipeline from "Sent" to "Replied"
- Auto-replies, bounces, and unsubscribes NOT advancing pipeline
- Meeting-booked detection advancing to "Meeting Booked"
- Team-specific "Proposal Requested" transition on keyword detection
- WebSocket broadcast on pipeline changes
- "Requires Action" aggregation
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.pipeline_manager import (
    AUTO_REPLY_INDICATORS,
    MEETING_ELIGIBLE_STATES,
    PROPOSAL_KEYWORDS,
    STALE_FOLLOWUP_DAYS,
    TERMINAL_STATES,
    PipelineManager,
    PipelineRecordData,
    PipelineTransitionResult,
    RequiresActionItem,
    RequiresActionType,
    ResponseClassification,
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
        self.stale_records: list[PipelineRecordData] = []
        self.failed_sequence_records: list[PipelineRecordData] = []
        self.enrichment_error_records: list[PipelineRecordData] = []
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
        return self.stale_records

    async def get_failed_sequence_records(self) -> list[PipelineRecordData]:
        return self.failed_sequence_records

    async def get_enrichment_error_records(self) -> list[PipelineRecordData]:
        return self.enrichment_error_records


class FakePublisher:
    """In-memory event publisher for testing broadcasts."""

    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.messages.append((channel, message))
        return 1


# --- Response Classification Tests ---


class TestResponseClassification:
    """Tests for classify_response method."""

    def test_genuine_reply(self):
        manager = PipelineManager()
        assert manager.classify_response("Thanks for reaching out, let's chat!") == (
            ResponseClassification.GENUINE_REPLY
        )

    def test_genuine_reply_with_question(self):
        manager = PipelineManager()
        assert manager.classify_response(
            "Can you tell me more about your services?"
        ) == ResponseClassification.GENUINE_REPLY

    @pytest.mark.parametrize(
        "auto_reply_text",
        [
            "I am out of office until Monday",
            "This is an automatic reply",
            "OOO - I will be back next week",
            "Auto-reply: I am currently out of the office",
            "I'm currently out on vacation",
            "I will be out of the office until Jan 5",
            "Away from the office this week",
        ],
    )
    def test_auto_reply_detected(self, auto_reply_text: str):
        manager = PipelineManager()
        result = manager.classify_response(auto_reply_text)
        assert result == ResponseClassification.AUTO_REPLY

    def test_empty_string_is_genuine(self):
        manager = PipelineManager()
        # Edge case: empty text doesn't match any auto-reply indicators
        assert manager.classify_response("") == ResponseClassification.GENUINE_REPLY


# --- Reply Advancement Tests ---


class TestAdvanceOnReply:
    """Tests for advance_on_reply method."""

    @pytest.mark.asyncio
    async def test_genuine_reply_advances_sent_to_replied(self):
        record = make_record(current_status="Sent")
        repo = FakeRepository([record])
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        result = await manager.advance_on_reply("rec-1", "Let's discuss further")

        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.previous_status == "Sent"
        assert result.new_status == "Replied"
        assert repo.records["rec-1"].current_status == "Replied"

    @pytest.mark.asyncio
    async def test_auto_reply_does_not_advance(self):
        record = make_record(current_status="Sent")
        repo = FakeRepository([record])
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_reply(
            "rec-1", "I am out of office until Monday"
        )

        assert result.result == PipelineTransitionResult.NO_CHANGE
        assert repo.records["rec-1"].current_status == "Sent"

    @pytest.mark.asyncio
    async def test_reply_on_non_sent_status_no_change(self):
        record = make_record(current_status="Replied")
        repo = FakeRepository([record])
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_reply("rec-1", "Thanks!")

        assert result.result == PipelineTransitionResult.NO_CHANGE
        assert repo.records["rec-1"].current_status == "Replied"

    @pytest.mark.asyncio
    async def test_reply_on_terminal_state(self):
        record = make_record(current_status="Converted", is_terminal=True)
        repo = FakeRepository([record])
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_reply("rec-1", "Hello again!")

        assert result.result == PipelineTransitionResult.ALREADY_TERMINAL

    @pytest.mark.asyncio
    async def test_reply_on_nonexistent_record(self):
        repo = FakeRepository()
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_reply("nonexistent", "Hello!")

        assert result.result == PipelineTransitionResult.INVALID_STATE

    @pytest.mark.asyncio
    async def test_reply_broadcasts_pipeline_update(self):
        record = make_record(current_status="Sent")
        repo = FakeRepository([record])
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        await manager.advance_on_reply("rec-1", "Sounds good, let's talk")

        assert len(publisher.messages) == 1
        channel, msg = publisher.messages[0]
        assert channel == "pipeline_updates"
        assert '"new_status": "Replied"' in msg


# --- Meeting Advancement Tests ---


class TestAdvanceOnMeeting:
    """Tests for advance_on_meeting method."""

    @pytest.mark.asyncio
    async def test_meeting_from_sent(self):
        record = make_record(current_status="Sent")
        repo = FakeRepository([record])
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        result = await manager.advance_on_meeting("rec-1")

        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.previous_status == "Sent"
        assert result.new_status == "Meeting Booked"

    @pytest.mark.asyncio
    async def test_meeting_from_replied(self):
        record = make_record(current_status="Replied")
        repo = FakeRepository([record])
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        result = await manager.advance_on_meeting("rec-1")

        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.previous_status == "Replied"
        assert result.new_status == "Meeting Booked"

    @pytest.mark.asyncio
    async def test_meeting_from_drafted_no_change(self):
        record = make_record(current_status="Drafted")
        repo = FakeRepository([record])
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_meeting("rec-1")

        assert result.result == PipelineTransitionResult.NO_CHANGE

    @pytest.mark.asyncio
    async def test_meeting_on_terminal_state(self):
        record = make_record(current_status="Won", is_terminal=True)
        repo = FakeRepository([record])
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_meeting("rec-1")

        assert result.result == PipelineTransitionResult.ALREADY_TERMINAL

    @pytest.mark.asyncio
    async def test_meeting_on_nonexistent_record(self):
        repo = FakeRepository()
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_meeting("nonexistent")

        assert result.result == PipelineTransitionResult.INVALID_STATE

    @pytest.mark.asyncio
    async def test_meeting_broadcasts_update(self):
        record = make_record(current_status="Replied")
        repo = FakeRepository([record])
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        await manager.advance_on_meeting("rec-1")

        assert len(publisher.messages) == 1
        channel, msg = publisher.messages[0]
        assert '"new_status": "Meeting Booked"' in msg


# --- Proposal Request Tests ---


class TestAdvanceOnProposalRequest:
    """Tests for advance_on_proposal_request method."""

    @pytest.mark.asyncio
    async def test_proposal_keyword_advances_team_replied(self):
        record = make_record(
            current_status="Replied",
            opportunity_type_id="cold_outreach_team",
            beneficiary_id="team",
        )
        repo = FakeRepository([record])
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        result = await manager.advance_on_proposal_request(
            "rec-1", "Can you send a proposal for this project?"
        )

        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.new_status == "Proposal Requested"

    @pytest.mark.asyncio
    async def test_no_keyword_no_advance(self):
        record = make_record(
            current_status="Replied",
            opportunity_type_id="cold_outreach_team",
            beneficiary_id="team",
        )
        repo = FakeRepository([record])
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_proposal_request(
            "rec-1", "Thanks, we'll keep you in mind"
        )

        assert result.result == PipelineTransitionResult.NO_CHANGE

    @pytest.mark.asyncio
    async def test_consultant_opportunity_no_advance(self):
        record = make_record(
            current_status="Replied",
            opportunity_type_id="cold_outreach_consultant",
            beneficiary_id="consultant",
        )
        repo = FakeRepository([record])
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_proposal_request(
            "rec-1", "Please send a proposal"
        )

        assert result.result == PipelineTransitionResult.NO_CHANGE
        assert "does not support" in result.reason

    @pytest.mark.asyncio
    async def test_proposal_from_non_replied_no_advance(self):
        record = make_record(
            current_status="Sent",
            opportunity_type_id="cold_outreach_team",
            beneficiary_id="team",
        )
        repo = FakeRepository([record])
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_proposal_request(
            "rec-1", "Send a proposal please"
        )

        assert result.result == PipelineTransitionResult.NO_CHANGE
        assert "expected 'Replied'" in result.reason

    @pytest.mark.asyncio
    async def test_proposal_broadcasts_update(self):
        record = make_record(
            current_status="Replied",
            opportunity_type_id="cold_outreach_team",
            beneficiary_id="team",
        )
        repo = FakeRepository([record])
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        await manager.advance_on_proposal_request(
            "rec-1", "We need a proposal and quote"
        )

        assert len(publisher.messages) == 1
        channel, msg = publisher.messages[0]
        assert '"new_status": "Proposal Requested"' in msg

    def test_detect_proposal_request_keywords(self):
        manager = PipelineManager()
        assert manager.detect_proposal_request("Can you send a proposal?")
        assert manager.detect_proposal_request("We need a quote for this")
        assert manager.detect_proposal_request("Please submit an RFP response")
        assert manager.detect_proposal_request("Send scope of work")
        assert not manager.detect_proposal_request("Thanks, we'll be in touch")
        assert not manager.detect_proposal_request("Interesting, tell me more")


# --- Requires Action Tests ---


class TestRequiresAction:
    """Tests for get_requires_action_items method."""

    @pytest.mark.asyncio
    async def test_stale_followups_included(self):
        stale_record = make_record(
            record_id="stale-1",
            current_status="Sent",
            updated_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        repo = FakeRepository()
        repo.stale_records = [stale_record]
        manager = PipelineManager(repository=repo)

        items = await manager.get_requires_action_items()

        assert len(items) == 1
        assert items[0].action_type == RequiresActionType.STALE_FOLLOWUP
        assert items[0].record_id == "stale-1"
        assert items[0].days_stale is not None
        assert items[0].days_stale >= 10

    @pytest.mark.asyncio
    async def test_failed_sequences_included(self):
        failed_record = make_record(record_id="failed-1", current_status="Sent")
        repo = FakeRepository()
        repo.failed_sequence_records = [failed_record]
        manager = PipelineManager(repository=repo)

        items = await manager.get_requires_action_items()

        assert len(items) == 1
        assert items[0].action_type == RequiresActionType.FAILED_SEQUENCE

    @pytest.mark.asyncio
    async def test_enrichment_errors_included(self):
        error_record = make_record(record_id="error-1", current_status="Drafted")
        repo = FakeRepository()
        repo.enrichment_error_records = [error_record]
        manager = PipelineManager(repository=repo)

        items = await manager.get_requires_action_items()

        assert len(items) == 1
        assert items[0].action_type == RequiresActionType.ENRICHMENT_ERROR

    @pytest.mark.asyncio
    async def test_all_types_aggregated(self):
        stale = make_record(
            record_id="stale-1",
            updated_at=datetime.now(timezone.utc) - timedelta(days=8),
        )
        failed = make_record(record_id="failed-1")
        error = make_record(record_id="error-1")

        repo = FakeRepository()
        repo.stale_records = [stale]
        repo.failed_sequence_records = [failed]
        repo.enrichment_error_records = [error]
        manager = PipelineManager(repository=repo)

        items = await manager.get_requires_action_items()

        assert len(items) == 3
        types = {item.action_type for item in items}
        assert types == {
            RequiresActionType.STALE_FOLLOWUP,
            RequiresActionType.FAILED_SEQUENCE,
            RequiresActionType.ENRICHMENT_ERROR,
        }

    @pytest.mark.asyncio
    async def test_empty_when_no_repo(self):
        manager = PipelineManager()
        items = await manager.get_requires_action_items()
        assert items == []

    @pytest.mark.asyncio
    async def test_sorted_by_staleness(self):
        stale_10 = make_record(
            record_id="stale-10",
            updated_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        stale_15 = make_record(
            record_id="stale-15",
            updated_at=datetime.now(timezone.utc) - timedelta(days=15),
        )
        stale_7 = make_record(
            record_id="stale-7",
            updated_at=datetime.now(timezone.utc) - timedelta(days=7),
        )
        repo = FakeRepository()
        repo.stale_records = [stale_10, stale_15, stale_7]
        manager = PipelineManager(repository=repo)

        items = await manager.get_requires_action_items()

        # Most stale first
        assert items[0].record_id == "stale-15"
        assert items[1].record_id == "stale-10"
        assert items[2].record_id == "stale-7"


# --- WebSocket Broadcast Tests ---


class TestBroadcastBehavior:
    """Tests for WebSocket broadcast on pipeline transitions."""

    @pytest.mark.asyncio
    async def test_no_broadcast_without_publisher(self):
        record = make_record(current_status="Sent")
        repo = FakeRepository([record])
        # No publisher provided
        manager = PipelineManager(repository=repo)

        result = await manager.advance_on_reply("rec-1", "Hello!")

        assert result.result == PipelineTransitionResult.ADVANCED
        # No exception raised, just no broadcast

    @pytest.mark.asyncio
    async def test_broadcast_contains_required_fields(self):
        record = make_record(
            current_status="Sent",
            beneficiary_id="consultant",
            opportunity_type_id="cold_outreach_consultant",
        )
        repo = FakeRepository([record])
        publisher = FakePublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        await manager.advance_on_reply("rec-1", "Interested!")

        assert len(publisher.messages) == 1
        _, msg = publisher.messages[0]
        import json
        data = json.loads(msg)
        assert data["type"] == "pipeline_update"
        assert data["record_id"] == "rec-1"
        assert data["new_status"] == "Replied"
        assert data["previous_status"] == "Sent"
        assert data["beneficiary_id"] == "consultant"
        assert data["opportunity_type_id"] == "cold_outreach_consultant"
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_broadcast_failure_does_not_crash(self):
        """Publisher errors should be logged, not propagated."""
        record = make_record(current_status="Sent")
        repo = FakeRepository([record])

        # Publisher that raises an exception
        publisher = AsyncMock()
        publisher.publish = AsyncMock(side_effect=Exception("Redis down"))
        manager = PipelineManager(repository=repo, publisher=publisher)

        # Should not raise
        result = await manager.advance_on_reply("rec-1", "Hello!")
        assert result.result == PipelineTransitionResult.ADVANCED
