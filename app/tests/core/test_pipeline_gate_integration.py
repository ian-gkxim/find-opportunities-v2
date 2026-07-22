"""Unit tests for PipelineGateService integration into PipelineManager.

Validates that the grounding gate check is enforced during pipeline state
transitions. When ungrounded claims exist, transitions to gated states
(Approve, Applied, Sent, Proposal Submitted) are blocked.

Requirements: 3.1
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.grounding_verifier import Claim, ClaimCategory, GroundingStatus
from app.core.pipeline_manager import (
    PipelineManager,
    PipelineRecordData,
    PipelineTransitionResult,
)


# --- Helpers ---


def make_record(
    record_id: str = "rec-1",
    prospect_id: str = "prospect-1",
    opportunity_type_id: str = "cold_outreach_consultant",
    beneficiary_id: str = "consultant",
    current_status: str = "Sent",
    is_terminal: bool = False,
) -> PipelineRecordData:
    """Create a PipelineRecordData for testing."""
    return PipelineRecordData(
        id=record_id,
        prospect_id=prospect_id,
        opportunity_type_id=opportunity_type_id,
        beneficiary_id=beneficiary_id,
        current_status=current_status,
        is_terminal=is_terminal,
        updated_at=datetime.now(timezone.utc),
    )


def make_ungrounded_claim(claim_id: str = "claim-1") -> Claim:
    """Create an ungrounded Claim for testing."""
    return Claim(
        id=claim_id,
        material_id="mat-1",
        category=ClaimCategory.SKILL_TECHNOLOGY,
        claim_text="10 years of Python experience",
        source_span="10 years of Python experience",
        source_span_start=0,
        source_span_end=30,
        grounding_status=GroundingStatus.UNGROUNDED,
    )


class FakeRepository:
    """In-memory PipelineRepository for testing."""

    def __init__(self, records: list[PipelineRecordData] | None = None):
        self.records: dict[str, PipelineRecordData] = {}
        self.updates: list[dict] = []
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
        self.updates.append({
            "record_id": record_id,
            "new_status": new_status,
            "previous_status": previous_status,
            "is_terminal": is_terminal,
        })
        if record_id in self.records:
            record = self.records[record_id]
            record.previous_status = record.current_status
            record.current_status = new_status
            record.is_terminal = is_terminal

    async def get_stale_records(self, days_threshold: int) -> list:
        return []

    async def get_failed_sequence_records(self) -> list:
        return []

    async def get_enrichment_error_records(self) -> list:
        return []


class FakePublisher:
    """In-memory event publisher."""

    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.messages.append((channel, message))
        return 1


# --- Tests: Grounding Gate Integration ---


class TestGroundingGateIntegration:
    """Tests for PipelineGateService integration in PipelineManager._transition."""

    @pytest.mark.asyncio
    async def test_transition_blocked_when_gate_rejects(self):
        """Transition to gated state is blocked when ungrounded claims exist."""
        ungrounded = [make_ungrounded_claim("c-1"), make_ungrounded_claim("c-2")]
        gate_service = AsyncMock()
        gate_service.can_transition.return_value = (False, ungrounded)

        repo = FakeRepository(records=[make_record(current_status="Drafted")])
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=gate_service
        )

        # Manually trigger a transition to a gated state
        record = await repo.get_pipeline_record("rec-1")
        result = await manager._transition(record, "Sent")

        assert result.result == PipelineTransitionResult.GROUNDING_BLOCKED
        assert result.record_id == "rec-1"
        assert result.previous_status == "Drafted"
        assert result.new_status == "Sent"
        assert result.ungrounded_claims == ungrounded
        assert len(result.ungrounded_claims) == 2
        assert "blocked" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_transition_allowed_when_gate_passes(self):
        """Transition to gated state proceeds when grounding is verified."""
        gate_service = AsyncMock()
        gate_service.can_transition.return_value = (True, None)

        repo = FakeRepository(records=[make_record(current_status="Drafted")])
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=gate_service
        )

        record = await repo.get_pipeline_record("rec-1")
        result = await manager._transition(record, "Sent")

        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.new_status == "Sent"
        assert result.ungrounded_claims is None

    @pytest.mark.asyncio
    async def test_non_gated_transition_not_blocked(self):
        """Gate allows transitions to non-gated states without blocking."""
        gate_service = AsyncMock()
        gate_service.can_transition.return_value = (True, None)

        repo = FakeRepository(records=[make_record(current_status="Sent")])
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=gate_service
        )

        record = await repo.get_pipeline_record("rec-1")
        result = await manager._transition(record, "Replied")

        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.new_status == "Replied"
        # Gate was called for "Replied" which is not gated — PipelineGateService
        # returns (True, None) for non-gated states
        gate_service.can_transition.assert_called_once_with("rec-1", "Replied")

    @pytest.mark.asyncio
    async def test_no_gate_service_allows_all_transitions(self):
        """Without a gate service, transitions proceed as before."""
        repo = FakeRepository(records=[make_record(current_status="Drafted")])
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=None
        )

        record = await repo.get_pipeline_record("rec-1")
        result = await manager._transition(record, "Sent")

        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.new_status == "Sent"

    @pytest.mark.asyncio
    async def test_blocked_transition_does_not_persist(self):
        """When gate blocks, no DB update is made."""
        gate_service = AsyncMock()
        gate_service.can_transition.return_value = (False, [make_ungrounded_claim()])

        repo = FakeRepository(records=[make_record(current_status="Drafted")])
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=gate_service
        )

        record = await repo.get_pipeline_record("rec-1")
        await manager._transition(record, "Approve")

        # No DB update should have been made
        assert len(repo.updates) == 0
        # Record status unchanged
        assert repo.records["rec-1"].current_status == "Drafted"

    @pytest.mark.asyncio
    async def test_blocked_transition_does_not_broadcast(self):
        """When gate blocks, no WebSocket broadcast is made."""
        gate_service = AsyncMock()
        gate_service.can_transition.return_value = (False, [make_ungrounded_claim()])

        publisher = FakePublisher()
        repo = FakeRepository(records=[make_record(current_status="Drafted")])
        manager = PipelineManager(
            repository=repo, publisher=publisher, gate_service=gate_service
        )

        record = await repo.get_pipeline_record("rec-1")
        await manager._transition(record, "Approve")

        # No broadcast should have been made
        assert len(publisher.messages) == 0

    @pytest.mark.asyncio
    async def test_gate_called_with_correct_arguments(self):
        """Gate service is called with the record ID and target state."""
        gate_service = AsyncMock()
        gate_service.can_transition.return_value = (True, None)

        repo = FakeRepository(records=[make_record(record_id="pr-123", current_status="Drafted")])
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=gate_service
        )

        record = await repo.get_pipeline_record("pr-123")
        await manager._transition(record, "Applied")

        gate_service.can_transition.assert_called_once_with("pr-123", "Applied")

    @pytest.mark.asyncio
    async def test_all_gated_states_are_checked(self):
        """All four gated states trigger the gate check."""
        gated_states = ["Approve", "Applied", "Sent", "Proposal Submitted"]

        for state in gated_states:
            gate_service = AsyncMock()
            gate_service.can_transition.return_value = (False, [])

            repo = FakeRepository(records=[make_record(current_status="Drafted")])
            manager = PipelineManager(
                repository=repo, publisher=FakePublisher(), gate_service=gate_service
            )

            record = await repo.get_pipeline_record("rec-1")
            result = await manager._transition(record, state)

            assert result.result == PipelineTransitionResult.GROUNDING_BLOCKED, (
                f"State '{state}' should be blocked when gate returns (False, [])"
            )
            gate_service.can_transition.assert_called_once_with("rec-1", state)

    @pytest.mark.asyncio
    async def test_empty_ungrounded_claims_still_blocks(self):
        """Gate blocks even with empty claims list (no report exists case)."""
        gate_service = AsyncMock()
        gate_service.can_transition.return_value = (False, [])

        repo = FakeRepository(records=[make_record(current_status="Drafted")])
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=gate_service
        )

        record = await repo.get_pipeline_record("rec-1")
        result = await manager._transition(record, "Approve")

        assert result.result == PipelineTransitionResult.GROUNDING_BLOCKED
        assert result.ungrounded_claims == []


class TestTransitionToMethod:
    """Tests for the public transition_to method."""

    @pytest.mark.asyncio
    async def test_transition_to_valid_state(self):
        """transition_to advances when gate allows."""
        gate_service = AsyncMock()
        gate_service.can_transition.return_value = (True, None)

        repo = FakeRepository(records=[make_record(current_status="Drafted")])
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=gate_service
        )

        result = await manager.transition_to("rec-1", "Sent")

        assert result.result == PipelineTransitionResult.ADVANCED
        assert result.new_status == "Sent"

    @pytest.mark.asyncio
    async def test_transition_to_blocked_by_gate(self):
        """transition_to returns GROUNDING_BLOCKED when gate rejects."""
        claims = [make_ungrounded_claim()]
        gate_service = AsyncMock()
        gate_service.can_transition.return_value = (False, claims)

        repo = FakeRepository(records=[make_record(current_status="Drafted")])
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=gate_service
        )

        result = await manager.transition_to("rec-1", "Approve")

        assert result.result == PipelineTransitionResult.GROUNDING_BLOCKED
        assert result.ungrounded_claims == claims

    @pytest.mark.asyncio
    async def test_transition_to_nonexistent_record(self):
        """transition_to returns INVALID_STATE for unknown record."""
        repo = FakeRepository(records=[])
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=AsyncMock()
        )

        result = await manager.transition_to("unknown-id", "Sent")

        assert result.result == PipelineTransitionResult.INVALID_STATE

    @pytest.mark.asyncio
    async def test_transition_to_terminal_state_blocked(self):
        """transition_to returns ALREADY_TERMINAL for terminal records."""
        repo = FakeRepository(
            records=[make_record(current_status="Won", is_terminal=True)]
        )
        manager = PipelineManager(
            repository=repo, publisher=FakePublisher(), gate_service=AsyncMock()
        )

        result = await manager.transition_to("rec-1", "Sent")

        assert result.result == PipelineTransitionResult.ALREADY_TERMINAL
