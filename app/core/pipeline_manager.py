"""Pipeline Manager — state machine transitions and event handling.

Requirements 7.2: Non-auto-reply advances pipeline from "Sent" to "Replied".
Requirements 7.3: Meeting signal advances to "Meeting Booked" from Sent or Replied.
Requirements 8.2: "Requires Action" aggregation (stale 7+ days, failed sequences, enrichment errors).
Requirements 13.5: Team pipeline state machine (Drafted → Sent → Replied → Proposal Requested → Won → Lost).
Requirements 13.6: Keyword detection advances Team pipeline from "Replied" to "Proposal Requested".
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# --- Constants ---

# Keywords that indicate a Team prospect is requesting a proposal
PROPOSAL_KEYWORDS: list[str] = [
    "proposal",
    "send a proposal",
    "submit a proposal",
    "proposal requested",
    "send proposal",
    "rfp",
    "request for proposal",
    "quote",
    "send a quote",
    "pricing",
    "scope of work",
    "statement of work",
    "sow",
]

# Terminal pipeline states (no further transitions from these)
TERMINAL_STATES: set[str] = {
    "Converted",
    "Accepted",
    "Rejected",
    "Won",
    "Lost",
    "Abandoned",
}

# States from which a meeting signal can advance the pipeline
MEETING_ELIGIBLE_STATES: set[str] = {"Sent", "Replied"}

# Auto-reply indicators (these do NOT advance pipeline)
AUTO_REPLY_INDICATORS: list[str] = [
    "out of office",
    "ooo",
    "automatic reply",
    "auto-reply",
    "autoreply",
    "i am currently out",
    "i'm currently out",
    "i will be out",
    "i'll be out",
    "on vacation",
    "on leave",
    "away from the office",
    "maternity leave",
    "paternity leave",
]

# Stale follow-up threshold in days
STALE_FOLLOWUP_DAYS: int = 7


# --- Enums ---


class ResponseClassification(str, Enum):
    """Classification of an incoming response event."""

    GENUINE_REPLY = "genuine_reply"
    AUTO_REPLY = "auto_reply"
    BOUNCE = "bounce"
    UNSUBSCRIBE = "unsubscribe"
    OUT_OF_OFFICE = "out_of_office"


class PipelineTransitionResult(str, Enum):
    """Result of attempting a pipeline state transition."""

    ADVANCED = "advanced"
    NO_CHANGE = "no_change"
    INVALID_STATE = "invalid_state"
    ALREADY_TERMINAL = "already_terminal"


class RequiresActionType(str, Enum):
    """Types of items that require user action."""

    STALE_FOLLOWUP = "stale_followup"
    FAILED_SEQUENCE = "failed_sequence"
    ENRICHMENT_ERROR = "enrichment_error"


# --- Data Models ---


@dataclass
class PipelineTransition:
    """Result of a pipeline state transition attempt."""

    result: PipelineTransitionResult
    record_id: str
    previous_status: str | None = None
    new_status: str | None = None
    reason: str = ""


@dataclass
class RequiresActionItem:
    """An item that requires user attention in the Dashboard."""

    action_type: RequiresActionType
    record_id: str
    prospect_id: str
    beneficiary_id: str
    description: str
    last_activity_at: datetime | None = None
    days_stale: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineRecordData:
    """Lightweight representation of a pipeline record for the manager.

    Protocol-based approach allows testing without ORM dependencies.
    """

    id: str
    prospect_id: str
    opportunity_type_id: str
    beneficiary_id: str
    current_status: str
    previous_status: str | None = None
    is_terminal: bool = False
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# --- Repository Protocol ---


class PipelineRepository(Protocol):
    """Protocol for the database repository used by PipelineManager."""

    async def get_pipeline_record(
        self, record_id: str
    ) -> PipelineRecordData | None: ...

    async def update_pipeline_record(
        self, record_id: str,
        new_status: str,
        previous_status: str,
        is_terminal: bool,
    ) -> None: ...

    async def get_stale_records(
        self, days_threshold: int
    ) -> list[PipelineRecordData]: ...

    async def get_failed_sequence_records(self) -> list[PipelineRecordData]: ...

    async def get_enrichment_error_records(self) -> list[PipelineRecordData]: ...


# --- Event Publisher Protocol ---


class EventPublisher(Protocol):
    """Protocol for publishing pipeline events (Redis pub/sub)."""

    async def publish(self, channel: str, message: str) -> int: ...


# --- Pipeline Manager ---


class PipelineManager:
    """Manages pipeline state machine transitions and event handling.

    Pure logic class with protocol-based dependencies for testability.
    Handles:
    - Reply detection advancing pipeline from "Sent" to "Replied"
    - Meeting-booked detection advancing to "Meeting Booked"
    - Team-specific "Proposal Requested" transition on keyword detection
    - WebSocket broadcasts on pipeline changes
    - "Requires Action" aggregation
    """

    CHANNEL_PIPELINE_UPDATES = "pipeline_updates"
    CHANNEL_NOTIFICATIONS = "notifications"

    def __init__(
        self,
        repository: PipelineRepository | None = None,
        publisher: EventPublisher | None = None,
    ):
        """Initialize the pipeline manager.

        Args:
            repository: Database repository for pipeline record access.
            publisher: Event publisher for WebSocket broadcasts via Redis.
        """
        self._repo = repository
        self._publisher = publisher

    # --- Reply Detection ---

    def classify_response(self, reply_text: str) -> ResponseClassification:
        """Classify a response event to determine if it's a genuine reply.

        Auto-replies, bounces, and unsubscribes do NOT advance the pipeline.

        Args:
            reply_text: The text content of the reply message.

        Returns:
            Classification of the response.
        """
        lower_text = reply_text.lower().strip()

        # Check for auto-reply indicators
        for indicator in AUTO_REPLY_INDICATORS:
            if indicator in lower_text:
                return ResponseClassification.AUTO_REPLY

        return ResponseClassification.GENUINE_REPLY

    async def advance_on_reply(
        self, record_id: str, reply_text: str
    ) -> PipelineTransition:
        """Advance pipeline from "Sent" to "Replied" on genuine reply detection.

        Requirement 7.2: Non-auto-reply advances pipeline from Sent to Replied.
        Auto-replies, bounces, and unsubscribes do NOT advance pipeline.

        Args:
            record_id: The pipeline record ID.
            reply_text: The reply text content for classification.

        Returns:
            PipelineTransition with the result of the operation.
        """
        classification = self.classify_response(reply_text)

        if classification != ResponseClassification.GENUINE_REPLY:
            return PipelineTransition(
                result=PipelineTransitionResult.NO_CHANGE,
                record_id=record_id,
                reason=f"Response classified as {classification.value}, "
                       f"pipeline not advanced",
            )

        record = await self._get_record(record_id)
        if record is None:
            return PipelineTransition(
                result=PipelineTransitionResult.INVALID_STATE,
                record_id=record_id,
                reason="Pipeline record not found",
            )

        if record.is_terminal:
            return PipelineTransition(
                result=PipelineTransitionResult.ALREADY_TERMINAL,
                record_id=record_id,
                previous_status=record.current_status,
                reason="Record is in a terminal state",
            )

        if record.current_status != "Sent":
            return PipelineTransition(
                result=PipelineTransitionResult.NO_CHANGE,
                record_id=record_id,
                previous_status=record.current_status,
                reason=f"Record status is '{record.current_status}', "
                       f"expected 'Sent' for reply advancement",
            )

        # Advance to Replied
        return await self._transition(record, "Replied")

    # --- Meeting Detection ---

    async def advance_on_meeting(self, record_id: str) -> PipelineTransition:
        """Advance pipeline to "Meeting Booked" on meeting signal detection.

        Requirement 7.3: Meeting signal advances to "Meeting Booked"
        regardless of whether current status is "Sent" or "Replied".

        Args:
            record_id: The pipeline record ID.

        Returns:
            PipelineTransition with the result of the operation.
        """
        record = await self._get_record(record_id)
        if record is None:
            return PipelineTransition(
                result=PipelineTransitionResult.INVALID_STATE,
                record_id=record_id,
                reason="Pipeline record not found",
            )

        if record.is_terminal:
            return PipelineTransition(
                result=PipelineTransitionResult.ALREADY_TERMINAL,
                record_id=record_id,
                previous_status=record.current_status,
                reason="Record is in a terminal state",
            )

        if record.current_status not in MEETING_ELIGIBLE_STATES:
            return PipelineTransition(
                result=PipelineTransitionResult.NO_CHANGE,
                record_id=record_id,
                previous_status=record.current_status,
                reason=f"Record status is '{record.current_status}', "
                       f"must be in {MEETING_ELIGIBLE_STATES} "
                       f"for meeting advancement",
            )

        # Advance to Meeting Booked
        return await self._transition(record, "Meeting Booked")

    # --- Proposal Request Detection (Team-specific) ---

    def detect_proposal_request(self, reply_text: str) -> bool:
        """Detect if a reply contains proposal request keywords.

        Requirement 13.6: Keyword detection in reply text signals
        a Team prospect is requesting a proposal.

        Args:
            reply_text: The reply text content to scan.

        Returns:
            True if proposal request keywords are detected.
        """
        lower_text = reply_text.lower()
        return any(keyword in lower_text for keyword in PROPOSAL_KEYWORDS)

    async def advance_on_proposal_request(
        self, record_id: str, reply_text: str
    ) -> PipelineTransition:
        """Advance Team pipeline from "Replied" to "Proposal Requested".

        Requirement 13.6: Keyword detection advances Team pipeline
        from "Replied" to "Proposal Requested".

        Args:
            record_id: The pipeline record ID.
            reply_text: The reply text to scan for proposal keywords.

        Returns:
            PipelineTransition with the result of the operation.
        """
        if not self.detect_proposal_request(reply_text):
            return PipelineTransition(
                result=PipelineTransitionResult.NO_CHANGE,
                record_id=record_id,
                reason="No proposal request keywords detected in reply",
            )

        record = await self._get_record(record_id)
        if record is None:
            return PipelineTransition(
                result=PipelineTransitionResult.INVALID_STATE,
                record_id=record_id,
                reason="Pipeline record not found",
            )

        if record.is_terminal:
            return PipelineTransition(
                result=PipelineTransitionResult.ALREADY_TERMINAL,
                record_id=record_id,
                previous_status=record.current_status,
                reason="Record is in a terminal state",
            )

        if record.current_status != "Replied":
            return PipelineTransition(
                result=PipelineTransitionResult.NO_CHANGE,
                record_id=record_id,
                previous_status=record.current_status,
                reason=f"Record status is '{record.current_status}', "
                       f"expected 'Replied' for proposal request advancement",
            )

        # Verify this is a Team opportunity type (has Proposal Requested state)
        if record.opportunity_type_id not in (
            "cold_outreach_team",
        ):
            return PipelineTransition(
                result=PipelineTransitionResult.NO_CHANGE,
                record_id=record_id,
                previous_status=record.current_status,
                reason=f"Opportunity type '{record.opportunity_type_id}' "
                       f"does not support 'Proposal Requested' transition",
            )

        # Advance to Proposal Requested
        return await self._transition(record, "Proposal Requested")

    # --- Requires Action Aggregation ---

    async def get_requires_action_items(self) -> list[RequiresActionItem]:
        """Aggregate all items requiring user action for the Dashboard.

        Requirement 8.2: "Requires Action" section listing:
        - Prospects with stale follow-ups (no activity for 7+ days)
        - Failed sequences
        - Enrichment errors

        Returns:
            List of RequiresActionItem sorted by urgency/recency.
        """
        items: list[RequiresActionItem] = []

        if self._repo is None:
            return items

        # 1. Stale follow-ups: no activity for 7+ days in non-terminal status
        stale_records = await self._repo.get_stale_records(STALE_FOLLOWUP_DAYS)
        now = datetime.now(timezone.utc)
        for record in stale_records:
            days_stale = (now - record.updated_at).days
            items.append(
                RequiresActionItem(
                    action_type=RequiresActionType.STALE_FOLLOWUP,
                    record_id=record.id,
                    prospect_id=record.prospect_id,
                    beneficiary_id=record.beneficiary_id,
                    description=(
                        f"No activity for {days_stale} days "
                        f"(status: {record.current_status})"
                    ),
                    last_activity_at=record.updated_at,
                    days_stale=days_stale,
                )
            )

        # 2. Failed sequences
        failed_records = await self._repo.get_failed_sequence_records()
        for record in failed_records:
            items.append(
                RequiresActionItem(
                    action_type=RequiresActionType.FAILED_SEQUENCE,
                    record_id=record.id,
                    prospect_id=record.prospect_id,
                    beneficiary_id=record.beneficiary_id,
                    description="Sequence failed — review and retry or revise",
                    last_activity_at=record.updated_at,
                )
            )

        # 3. Enrichment errors
        error_records = await self._repo.get_enrichment_error_records()
        for record in error_records:
            items.append(
                RequiresActionItem(
                    action_type=RequiresActionType.ENRICHMENT_ERROR,
                    record_id=record.id,
                    prospect_id=record.prospect_id,
                    beneficiary_id=record.beneficiary_id,
                    description="Enrichment failed — manual review required",
                    last_activity_at=record.updated_at,
                )
            )

        # Sort by staleness (most urgent first), then by last activity
        items.sort(
            key=lambda x: (
                -(x.days_stale or 0),
                x.last_activity_at or datetime.min.replace(tzinfo=timezone.utc),
            )
        )

        return items

    # --- Internal Helpers ---

    async def _get_record(self, record_id: str) -> PipelineRecordData | None:
        """Retrieve a pipeline record from the repository."""
        if self._repo is None:
            return None
        return await self._repo.get_pipeline_record(record_id)

    async def _transition(
        self, record: PipelineRecordData, new_status: str
    ) -> PipelineTransition:
        """Execute a state transition and broadcast the change.

        Args:
            record: The current pipeline record data.
            new_status: The target status to transition to.

        Returns:
            PipelineTransition with ADVANCED result.
        """
        previous_status = record.current_status
        is_terminal = new_status in TERMINAL_STATES

        # Persist the transition
        if self._repo:
            await self._repo.update_pipeline_record(
                record_id=record.id,
                new_status=new_status,
                previous_status=previous_status,
                is_terminal=is_terminal,
            )

        # Broadcast via WebSocket (Redis pub/sub)
        await self._broadcast_pipeline_update(
            record_id=record.id,
            new_status=new_status,
            previous_status=previous_status,
            beneficiary_id=record.beneficiary_id,
            opportunity_type_id=record.opportunity_type_id,
        )

        logger.info(
            "Pipeline record %s transitioned: %s → %s",
            record.id,
            previous_status,
            new_status,
        )

        return PipelineTransition(
            result=PipelineTransitionResult.ADVANCED,
            record_id=record.id,
            previous_status=previous_status,
            new_status=new_status,
            reason=f"Advanced from '{previous_status}' to '{new_status}'",
        )

    async def _broadcast_pipeline_update(
        self,
        record_id: str,
        new_status: str,
        previous_status: str,
        beneficiary_id: str,
        opportunity_type_id: str,
    ) -> None:
        """Broadcast a pipeline status change via Redis pub/sub.

        Requirement 8.4: Pipeline updates reflected within 10 seconds.
        """
        if self._publisher is None:
            return

        message = json.dumps({
            "type": "pipeline_update",
            "record_id": record_id,
            "new_status": new_status,
            "previous_status": previous_status,
            "beneficiary_id": beneficiary_id,
            "opportunity_type_id": opportunity_type_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        try:
            await self._publisher.publish(
                self.CHANNEL_PIPELINE_UPDATES, message
            )
        except Exception as e:
            logger.error(
                "Failed to broadcast pipeline update for record %s: %s",
                record_id,
                str(e),
            )
