"""Pipeline Manager — state machine transitions and event handling.

Requirements 7.2: Non-auto-reply advances pipeline from "Sent" to "Replied".
Requirements 7.3: Meeting signal advances to "Meeting Booked" from Sent or Replied.
Requirements 8.2: "Requires Action" aggregation (stale 7+ days, failed sequences, enrichment errors).
Requirements 13.5: Team pipeline state machine (Drafted → Sent → Replied → Proposal Requested → Won → Lost).
Requirements 13.6: Keyword detection advances Team pipeline from "Replied" to "Proposal Requested".
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from arq.connections import ArqRedis

    from app.core.outbound_validator import RuleResult
    from app.core.pipeline_gate import PipelineGateService
    from app.core.schema_registry import SchemaRegistry

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
    GROUNDING_BLOCKED = "grounding_blocked"


class RequiresActionType(str, Enum):
    """Types of items that require user action."""

    STALE_FOLLOWUP = "stale_followup"
    FAILED_SEQUENCE = "failed_sequence"
    ENRICHMENT_ERROR = "enrichment_error"
    VALIDATION_FAILED = "validation_failed"
    INTERVIEW_PREP_FAILED = "interview_prep_failed"


# --- Data Models ---


@dataclass
class PipelineTransition:
    """Result of a pipeline state transition attempt."""

    result: PipelineTransitionResult
    record_id: str
    previous_status: str | None = None
    new_status: str | None = None
    reason: str = ""
    ungrounded_claims: list | None = None


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
        gate_service: PipelineGateService | None = None,
        schema_registry: SchemaRegistry | None = None,
        redis_pool: ArqRedis | None = None,
        interview_prep_repo=None,  # InterviewPrepRepository
    ):
        """Initialize the pipeline manager.

        Args:
            repository: Database repository for pipeline record access.
            publisher: Event publisher for WebSocket broadcasts via Redis.
            gate_service: Pipeline gate service for grounding verification checks.
            schema_registry: Schema registry for state-entry technique lookup.
            redis_pool: ARQ Redis pool for enqueueing background jobs.
            interview_prep_repo: Interview prep repository for failed pack queries.
        """
        self._repo = repository
        self._publisher = publisher
        self._gate_service = gate_service
        self._schema = schema_registry
        self._redis_pool = redis_pool
        self._interview_prep_repo = interview_prep_repo

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

        # 4. Failed interview prep packs
        if self._interview_prep_repo:
            failed_packs = await self._interview_prep_repo.get_failed_packs(limit=20)
            for pack in failed_packs:
                items.append(
                    RequiresActionItem(
                        action_type=RequiresActionType.INTERVIEW_PREP_FAILED,
                        record_id=pack.pipeline_record_id,
                        prospect_id="",  # Not directly available on pack
                        beneficiary_id=pack.beneficiary_id,
                        description="Interview prep pack generation failed for pipeline record",
                        last_activity_at=pack.updated_at,
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

    # --- Manual Transitions ---

    async def transition_to(
        self, record_id: str, new_status: str
    ) -> PipelineTransition:
        """Manually transition a pipeline record to a new status.

        Enforces grounding verification gate for gated states (Approve,
        Applied, Sent, Proposal Submitted). If ungrounded claims exist,
        the transition is blocked and the ungrounded claims list is returned.

        Requirements: 3.1 (Claim Grounding Verification)

        Args:
            record_id: The pipeline record ID.
            new_status: The target status to transition to.

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

        return await self._transition(record, new_status)

    # --- Validation Failed Transition ---

    async def transition_to_validation_failed(
        self,
        record_id: str,
        blocking_failures: list[RuleResult],
    ) -> PipelineTransition:
        """Transition a pipeline record to validation_failed state.

        Broadcasts the failure to the Dashboard "Requires Action" section
        with the offending text spans from each blocking rule.

        Requirement 1.2: Blocking validation failures prevent submission and
        surface failed rules with offending text spans in Dashboard.

        Args:
            record_id: The pipeline record ID.
            blocking_failures: List of RuleResult objects for blocking failures.

        Returns:
            PipelineTransition with the result of the operation.
        """
        record = await self._get_record(record_id)
        if record is None:
            logger.error(
                "Cannot transition to validation_failed: "
                "pipeline record %s not found",
                record_id,
            )
            return PipelineTransition(
                result=PipelineTransitionResult.INVALID_STATE,
                record_id=record_id,
                reason="Pipeline record not found",
            )

        transition = await self._transition(record, "validation_failed")

        # Broadcast detailed failure info for Dashboard
        await self._broadcast_validation_failure(
            record_id=record_id,
            blocking_failures=blocking_failures,
            beneficiary_id=record.beneficiary_id,
        )

        return transition

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

        Before advancing to a gated state (Approve, Applied, Sent, Proposal Submitted),
        checks the grounding gate. If ungrounded claims exist, the transition is blocked.

        Args:
            record: The current pipeline record data.
            new_status: The target status to transition to.

        Returns:
            PipelineTransition with ADVANCED result, or GROUNDING_BLOCKED if gate rejects.
        """
        # Check grounding gate before allowing transition to gated states
        if self._gate_service is not None:
            allowed, ungrounded_claims = await self._gate_service.can_transition(
                record.id, new_status
            )
            if not allowed:
                logger.info(
                    "Pipeline record %s blocked from transitioning to '%s': "
                    "%d ungrounded claim(s)",
                    record.id,
                    new_status,
                    len(ungrounded_claims) if ungrounded_claims else 0,
                )
                return PipelineTransition(
                    result=PipelineTransitionResult.GROUNDING_BLOCKED,
                    record_id=record.id,
                    previous_status=record.current_status,
                    new_status=new_status,
                    reason=(
                        f"Transition to '{new_status}' blocked by grounding "
                        f"verification: {len(ungrounded_claims) if ungrounded_claims else 0} "
                        f"ungrounded claim(s) must be resolved"
                    ),
                    ungrounded_claims=ungrounded_claims,
                )

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

        # Dispatch state-entry techniques (non-blocking)
        await self._dispatch_state_entry_techniques(record, new_status)

        return PipelineTransition(
            result=PipelineTransitionResult.ADVANCED,
            record_id=record.id,
            previous_status=previous_status,
            new_status=new_status,
            reason=f"Advanced from '{previous_status}' to '{new_status}'",
        )

    async def _dispatch_state_entry_techniques(
        self,
        record: PipelineRecordData,
        new_status: str,
    ) -> None:
        """Dispatch techniques configured for state entry.

        Queries Schema_Registry for any prepare techniques triggered
        on entry to `new_status` for this opportunity type.
        Enqueues ARQ jobs for each matching technique.

        This is non-blocking: jobs are enqueued and the method returns
        immediately without awaiting generation results.

        Requirements: 1.1, 3.1
        """
        if not self._schema:
            return

        techniques = self._schema.get_state_entry_techniques(
            opportunity_type_id=record.opportunity_type_id,
            state=new_status,
        )

        if not techniques:
            return

        for technique in techniques:
            try:
                if self._redis_pool:
                    await self._redis_pool.enqueue_job(
                        "process_interview_prep",
                        record.id,
                    )
                    logger.info(
                        "Enqueued state-entry technique '%s' for record %s (state=%s)",
                        technique.id,
                        record.id,
                        new_status,
                    )
                else:
                    logger.warning(
                        "Cannot enqueue state-entry technique '%s' for record %s: "
                        "no redis_pool configured",
                        technique.id,
                        record.id,
                    )
            except Exception as e:
                logger.error(
                    "Failed to enqueue state-entry technique '%s' for record %s: %s",
                    technique.id,
                    record.id,
                    e,
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

    async def _broadcast_validation_failure(
        self,
        record_id: str,
        blocking_failures: list[RuleResult],
        beneficiary_id: str,
    ) -> None:
        """Broadcast validation failure details via Redis pub/sub.

        Sends detailed failure info (including offending text spans) to the
        Dashboard "Requires Action" section via WebSocket.

        Requirement 1.2: Surface each failed rule with offending text span
        in the Dashboard "Requires Action" section.

        Args:
            record_id: The pipeline record ID that failed validation.
            blocking_failures: List of RuleResult for each blocking failure.
            beneficiary_id: The beneficiary who owns this pipeline record.
        """
        if self._publisher is None:
            return

        # Serialize blocking failures with offending spans
        failures_payload = [
            {
                "rule_id": failure.rule_id,
                "message": failure.message,
                "severity": failure.severity.value
                if hasattr(failure.severity, "value")
                else str(failure.severity),
                "offending_spans": [
                    {
                        "start": span.start,
                        "end": span.end,
                        "field_name": span.field_name,
                        "text": span.text,
                    }
                    for span in failure.offending_spans
                ],
            }
            for failure in blocking_failures
        ]

        message = json.dumps({
            "type": "validation_failed",
            "action_type": RequiresActionType.VALIDATION_FAILED.value,
            "record_id": record_id,
            "beneficiary_id": beneficiary_id,
            "blocking_failures": failures_payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        try:
            await self._publisher.publish(
                self.CHANNEL_NOTIFICATIONS, message
            )
        except Exception as e:
            logger.error(
                "Failed to broadcast validation failure for record %s: %s",
                record_id,
                str(e),
            )
