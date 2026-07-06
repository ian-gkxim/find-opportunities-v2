"""Lemlist Engine — multi-channel sequence management, A/B testing, and response tracking.

Requirements 5.1-5.6: Sequence creation, sync, enrollment, tracking, reply pausing.
Requirements 6.1-6.5: A/B variant creation, assignment, promotion.
Requirements 7.1-7.4: Response polling, pipeline advancement, error handling.
Requirements 14.1-14.6: Auto-advance, max follow-ups, failed touchpoint skip.
"""

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

import httpx

from app.core.errors import APITimeoutError
from app.core.scoring_engine import ScoreTier

logger = logging.getLogger(__name__)


# --- Enums ---


class Channel(str, Enum):
    """Outreach channel type for a sequence step."""

    EMAIL = "email"
    LINKEDIN = "linkedin"
    MANUAL_TASK = "manual_task"


class SequenceSyncStatus(str, Enum):
    """Sync status between local sequence definition and Lemlist API."""

    SYNCED = "synced"
    SYNC_FAILED = "sync_failed"
    PENDING = "pending"


class TouchpointStatus(str, Enum):
    """Status of an individual touchpoint interaction."""

    PENDING = "pending"
    SENT = "sent"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    FAILED = "failed"


class ProspectSequenceStatus(str, Enum):
    """Status of a prospect's enrollment in a sequence."""

    ACTIVE = "active"
    PAUSED = "paused"
    SEQUENCE_COMPLETE = "sequence_complete"


class ResponseEventType(str, Enum):
    """Types of response events from Lemlist polling."""

    REPLY = "reply"
    BOUNCE = "bounce"
    OUT_OF_OFFICE = "out_of_office"
    UNSUBSCRIBE = "unsubscribe"
    OPEN = "open"
    CLICK = "click"


# --- Data Models ---


@dataclass
class Variant:
    """An A/B test variant for a touchpoint within a sequence step.

    Requirement 6.1: 2-4 variants (A, B, C, D) per touchpoint.
    """

    id: str  # A, B, C, D
    content: str
    sends: int = 0
    opens: int = 0
    clicks: int = 0
    replies: int = 0
    is_promoted: bool = False


@dataclass
class SequenceStep:
    """A single step within a sequence.

    Requirement 5.1: Each step has channel, delay (1-30 days), and
    content template (≤5000 chars).
    """

    order: int  # 1-10
    channel: Channel
    delay_days: int  # 1-30
    content_template: str  # max 5000 chars
    variants: list[Variant] = field(default_factory=list)


@dataclass
class Sequence:
    """A multi-channel outreach sequence definition.

    Requirement 5.1: Up to 10 steps per sequence.
    """

    id: str
    name: str
    beneficiary_id: str
    steps: list[SequenceStep] = field(default_factory=list)
    sync_status: SequenceSyncStatus = SequenceSyncStatus.PENDING
    sync_error: str | None = None
    lemlist_campaign_id: str | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class Touchpoint:
    """An individual interaction sent to a prospect within a sequence."""

    id: str
    pipeline_record_id: str
    sequence_id: str
    step_order: int
    variant_id: str | None = None
    status: TouchpointStatus = TouchpointStatus.PENDING
    sent_at: datetime | None = None
    opened_at: datetime | None = None
    replied_at: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class ProspectEnrollment:
    """A prospect's enrollment in a sequence, tracking progress."""

    prospect_id: str
    sequence_id: str
    status: ProspectSequenceStatus = ProspectSequenceStatus.ACTIVE
    current_step: int = 1
    followup_count: int = 0
    enrolled_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    paused_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class ResponseEvent:
    """A response event received from Lemlist polling."""

    event_type: ResponseEventType
    prospect_id: str
    sequence_id: str
    step_order: int
    variant_id: str | None = None
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class EnrollmentFilter:
    """Filter criteria for batch enrollment.

    Requirement 5.4: Filter by tier, opportunity type, or intent presence.
    """

    tier: ScoreTier | None = None
    opportunity_type: str | None = None
    has_intent: bool | None = None


# --- Repository Protocol ---


class LemlistRepository(Protocol):
    """Protocol for the database repository used by LemlistEngine.

    Allows mock injection for testing.
    """

    async def get_sequence(self, sequence_id: str) -> Sequence | None: ...

    async def save_sequence(self, sequence: Sequence) -> None: ...

    async def get_enrollment(
        self, prospect_id: str, sequence_id: str
    ) -> ProspectEnrollment | None: ...

    async def save_enrollment(self, enrollment: ProspectEnrollment) -> None: ...

    async def get_active_enrollments(
        self, sequence_id: str
    ) -> list[ProspectEnrollment]: ...

    async def get_prospects_by_filter(
        self, enrollment_filter: EnrollmentFilter
    ) -> list[str]: ...

    async def get_touchpoints_for_enrollment(
        self, prospect_id: str, sequence_id: str
    ) -> list[Touchpoint]: ...

    async def save_touchpoint(self, touchpoint: Touchpoint) -> None: ...

    async def update_touchpoint_status(
        self, touchpoint_id: str, status: TouchpointStatus, **kwargs: Any
    ) -> None: ...

    async def get_pending_touchpoints(
        self, prospect_id: str, sequence_id: str
    ) -> list[Touchpoint]: ...


# --- Validation ---


class SequenceValidationError(ValueError):
    """Raised when a sequence definition fails validation."""

    pass


def validate_sequence(sequence: Sequence) -> None:
    """Validate a sequence definition against constraints.

    Requirement 5.1:
    - 1-10 steps
    - Each step delay 1-30 days
    - Each step content template ≤ 5000 chars
    - Variants per step: 0, or 2-4

    Raises:
        SequenceValidationError: If validation fails.
    """
    if not sequence.steps:
        raise SequenceValidationError(
            "Sequence must have at least 1 step"
        )
    if len(sequence.steps) > 10:
        raise SequenceValidationError(
            f"Sequence cannot exceed 10 steps, got {len(sequence.steps)}"
        )

    for step in sequence.steps:
        if step.delay_days < 1 or step.delay_days > 30:
            raise SequenceValidationError(
                f"Step {step.order} delay must be 1-30 days, "
                f"got {step.delay_days}"
            )
        if len(step.content_template) > 5000:
            raise SequenceValidationError(
                f"Step {step.order} content template exceeds 5000 chars "
                f"({len(step.content_template)} chars)"
            )
        if step.variants and (
            len(step.variants) < 2 or len(step.variants) > 4
        ):
            raise SequenceValidationError(
                f"Step {step.order} must have 2-4 variants if A/B testing, "
                f"got {len(step.variants)}"
            )


# --- Engine ---


class LemlistEngine:
    """Manages Lemlist sequences, A/B tests, and response tracking.

    Key behaviors:
    - Sequence CRUD with 10s sync timeout to Lemlist API
    - Batch enrollment up to 200 prospects
    - Filter-based enrollment (tier, opportunity type, intent)
    - 5-minute polling for response events
    - Reply detection pauses prospect within 60 seconds
    - A/B variant assignment with equal distribution (±5pp after 40)
    - Variant promotion: 100% for new enrollees, existing stay
    - Auto-advance: send next touchpoint when delay elapses without reply
    - Max 3 follow-ups after initial, then sequence_complete
    - Failed touchpoint: skip and continue
    """

    SYNC_TIMEOUT = 10.0  # seconds (Requirement 5.2)
    MAX_BATCH_ENROLL = 200  # (Requirement 5.4)
    MAX_FOLLOWUPS = 3  # after initial touchpoint (Requirement 14.4)
    POLL_INTERVAL = 300  # 5 minutes (Requirement 7.1)
    PAUSE_DEADLINE = 60  # seconds (Requirement 5.6, 14.3)

    BASE_URL = "https://api.lemlist.com/api"

    def __init__(
        self,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        db_repo: LemlistRepository | None = None,
    ):
        """Initialize the Lemlist engine.

        Args:
            api_key: Lemlist API key for authentication.
            http_client: Optional httpx.AsyncClient for testing.
            db_repo: Optional repository for persistence (protocol-based).
        """
        self._api_key = api_key
        self._client = http_client or httpx.AsyncClient(
            timeout=self.SYNC_TIMEOUT
        )
        self._db = db_repo

    @property
    def headers(self) -> dict[str, str]:
        """Standard headers for Lemlist API requests."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @property
    def auth(self) -> tuple[str, str]:
        """Basic auth credentials for Lemlist API."""
        return ("", self._api_key)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # --- Sequence CRUD ---

    async def create_sequence(self, sequence: Sequence) -> SequenceSyncStatus:
        """Create and sync a sequence to the Lemlist API.

        Requirement 5.1: Validates sequence definition.
        Requirement 5.2: Synchronizes within 10 seconds.
        Requirement 5.3: Marks sync_failed on failure, allows retry.

        Args:
            sequence: The sequence definition to create and sync.

        Returns:
            The sync status after the operation.

        Raises:
            SequenceValidationError: If the sequence definition is invalid.
        """
        validate_sequence(sequence)

        try:
            response = await self._client.post(
                f"{self.BASE_URL}/campaigns",
                headers=self.headers,
                auth=self.auth,
                json=self._serialize_sequence(sequence),
                timeout=self.SYNC_TIMEOUT,
            )

            if response.status_code in (200, 201):
                data = response.json()
                sequence.lemlist_campaign_id = data.get("_id", "")
                sequence.sync_status = SequenceSyncStatus.SYNCED
                sequence.sync_error = None
            else:
                sequence.sync_status = SequenceSyncStatus.SYNC_FAILED
                sequence.sync_error = (
                    f"Lemlist API returned {response.status_code}: "
                    f"{response.text[:200]}"
                )
                logger.error(
                    "Lemlist sync failed for sequence %s: %s",
                    sequence.id,
                    sequence.sync_error,
                )

        except httpx.TimeoutException:
            sequence.sync_status = SequenceSyncStatus.SYNC_FAILED
            sequence.sync_error = (
                f"Sync timed out after {self.SYNC_TIMEOUT}s"
            )
            logger.error(
                "Lemlist sync timed out for sequence %s", sequence.id
            )

        except httpx.HTTPError as e:
            sequence.sync_status = SequenceSyncStatus.SYNC_FAILED
            sequence.sync_error = f"HTTP error: {str(e)[:200]}"
            logger.error(
                "Lemlist sync HTTP error for sequence %s: %s",
                sequence.id,
                str(e),
            )

        if self._db:
            await self._db.save_sequence(sequence)

        return sequence.sync_status

    def _serialize_sequence(self, sequence: Sequence) -> dict[str, Any]:
        """Serialize a sequence definition for the Lemlist API."""
        steps = []
        for step in sequence.steps:
            step_data: dict[str, Any] = {
                "order": step.order,
                "channel": step.channel.value,
                "delay_days": step.delay_days,
                "content": step.content_template,
            }
            if step.variants:
                step_data["variants"] = [
                    {"id": v.id, "content": v.content}
                    for v in step.variants
                ]
            steps.append(step_data)

        return {
            "name": sequence.name,
            "beneficiary_id": sequence.beneficiary_id,
            "steps": steps,
        }

    # --- Enrollment ---

    async def enroll_prospects(
        self, sequence_id: str, prospect_ids: list[str]
    ) -> int:
        """Enroll prospects in a sequence (max 200 per operation).

        Requirement 5.4: Individual or batch enrollment up to 200.

        Args:
            sequence_id: The sequence to enroll prospects in.
            prospect_ids: List of prospect IDs to enroll.

        Returns:
            Number of prospects successfully enrolled.

        Raises:
            ValueError: If batch exceeds 200 prospects.
        """
        if len(prospect_ids) > self.MAX_BATCH_ENROLL:
            raise ValueError(
                f"Batch enrollment cannot exceed {self.MAX_BATCH_ENROLL} "
                f"prospects, got {len(prospect_ids)}"
            )

        enrolled_count = 0

        for prospect_id in prospect_ids:
            enrollment = ProspectEnrollment(
                prospect_id=prospect_id,
                sequence_id=sequence_id,
            )

            if self._db:
                existing = await self._db.get_enrollment(
                    prospect_id, sequence_id
                )
                if existing:
                    # Already enrolled, skip
                    continue
                await self._db.save_enrollment(enrollment)

            enrolled_count += 1

        return enrolled_count

    async def enroll_by_filter(
        self,
        sequence_id: str,
        tier: ScoreTier | None = None,
        opportunity_type: str | None = None,
        has_intent: bool | None = None,
    ) -> int:
        """Batch enroll prospects matching filter criteria.

        Requirement 5.4: Filter by tier, opportunity type, or intent presence.
        Caps enrollment at MAX_BATCH_ENROLL (200).

        Args:
            sequence_id: The sequence to enroll prospects in.
            tier: Optional ScoreTier filter.
            opportunity_type: Optional opportunity type filter.
            has_intent: Optional filter for intent signal presence.

        Returns:
            Number of prospects enrolled.
        """
        enrollment_filter = EnrollmentFilter(
            tier=tier,
            opportunity_type=opportunity_type,
            has_intent=has_intent,
        )

        if self._db:
            prospect_ids = await self._db.get_prospects_by_filter(
                enrollment_filter
            )
        else:
            prospect_ids = []

        # Cap at max batch size
        prospect_ids = prospect_ids[: self.MAX_BATCH_ENROLL]

        return await self.enroll_prospects(sequence_id, prospect_ids)

    # --- Response Polling ---

    async def poll_responses(self) -> list[ResponseEvent]:
        """Poll Lemlist for response events.

        Requirement 7.1: Poll every 5 minutes for replies, bounces,
        out-of-office, and unsubscribes.
        Requirement 7.4: On API error, log failure and return empty
        without altering pipeline records.

        Returns:
            List of response events detected since last poll.
        """
        try:
            response = await self._client.get(
                f"{self.BASE_URL}/activities",
                headers=self.headers,
                auth=self.auth,
                timeout=self.SYNC_TIMEOUT,
            )

            if response.status_code != 200:
                logger.warning(
                    "Lemlist poll returned status %d, "
                    "will retry on next interval",
                    response.status_code,
                )
                return []

            data = response.json()
            return self._parse_response_events(data)

        except httpx.TimeoutException:
            logger.warning(
                "Lemlist poll timed out, will retry on next interval"
            )
            return []

        except httpx.HTTPError as e:
            logger.warning(
                "Lemlist poll HTTP error: %s, will retry on next interval",
                str(e),
            )
            return []

    def _parse_response_events(
        self, data: dict[str, Any] | list[Any]
    ) -> list[ResponseEvent]:
        """Parse raw API response into ResponseEvent objects."""
        events: list[ResponseEvent] = []
        activities = data if isinstance(data, list) else data.get(
            "activities", []
        )

        event_type_map = {
            "emailsReplied": ResponseEventType.REPLY,
            "emailsBounced": ResponseEventType.BOUNCE,
            "emailsUnsubscribed": ResponseEventType.UNSUBSCRIBE,
            "emailsOpened": ResponseEventType.OPEN,
            "emailsClicked": ResponseEventType.CLICK,
        }

        for activity in activities:
            activity_type = activity.get("type", "")
            event_type = event_type_map.get(activity_type)

            if not event_type:
                # Check for out-of-office in reply content
                if activity_type == "emailsReplied":
                    text = activity.get("text", "").lower()
                    if "out of office" in text or "ooo" in text:
                        event_type = ResponseEventType.OUT_OF_OFFICE
                    else:
                        event_type = ResponseEventType.REPLY
                else:
                    continue

            events.append(
                ResponseEvent(
                    event_type=event_type,
                    prospect_id=activity.get("leadId", ""),
                    sequence_id=activity.get("campaignId", ""),
                    step_order=activity.get("stepOrder", 1),
                    variant_id=activity.get("variantId"),
                    detected_at=datetime.now(timezone.utc),
                )
            )

        return events

    # --- Reply Handling ---

    async def pause_prospect(
        self, sequence_id: str, prospect_id: str
    ) -> None:
        """Pause all pending touchpoints for a prospect on reply detection.

        Requirement 5.6, 14.3: Pause within 60 seconds of reply detection.

        Args:
            sequence_id: The sequence the prospect is enrolled in.
            prospect_id: The prospect to pause.
        """
        if self._db:
            enrollment = await self._db.get_enrollment(
                prospect_id, sequence_id
            )
            if enrollment and enrollment.status == ProspectSequenceStatus.ACTIVE:
                enrollment.status = ProspectSequenceStatus.PAUSED
                enrollment.paused_at = datetime.now(timezone.utc)
                await self._db.save_enrollment(enrollment)

            # Pause all pending touchpoints
            pending = await self._db.get_pending_touchpoints(
                prospect_id, sequence_id
            )
            for touchpoint in pending:
                if touchpoint.status == TouchpointStatus.PENDING:
                    await self._db.update_touchpoint_status(
                        touchpoint.id, TouchpointStatus.PENDING
                    )

        # Also pause in Lemlist API
        try:
            await self._client.post(
                f"{self.BASE_URL}/campaigns/{sequence_id}/leads/"
                f"{prospect_id}/pause",
                headers=self.headers,
                auth=self.auth,
                timeout=self.SYNC_TIMEOUT,
            )
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            logger.warning(
                "Failed to pause prospect %s in Lemlist API: %s",
                prospect_id,
                str(e),
            )

    # --- A/B Variant Management ---

    def assign_variant(self, step: SequenceStep) -> str:
        """Assign a variant using random equal-distribution.

        Requirement 6.2: Equal share within ±5pp after 40 assignments.
        Uses least-assigned strategy to maintain balance.

        Args:
            step: The sequence step with variants to choose from.

        Returns:
            The variant ID (A, B, C, or D) assigned.

        Raises:
            ValueError: If step has no variants configured.
        """
        if not step.variants:
            raise ValueError(
                f"Step {step.order} has no variants for assignment"
            )

        total_sends = sum(v.sends for v in step.variants)

        if total_sends < 40:
            # Below threshold: pure random assignment
            chosen = random.choice(step.variants)
            chosen.sends += 1
            return chosen.id

        # After 40 assignments: assign to least-used variant to maintain
        # equal distribution within ±5pp tolerance
        # Find variant(s) with fewest sends
        min_sends = min(v.sends for v in step.variants)
        least_used = [v for v in step.variants if v.sends == min_sends]
        chosen = random.choice(least_used)
        chosen.sends += 1
        return chosen.id

    async def promote_variant(
        self, sequence_id: str, step_order: int, variant_id: str
    ) -> None:
        """Promote a variant to 100% allocation for new enrollees.

        Requirement 6.5: Promoted variant gets 100% of new enrollees.
        Existing prospects stay on their current variant.

        Args:
            sequence_id: The sequence containing the step.
            step_order: The step order within the sequence.
            variant_id: The variant to promote (A, B, C, or D).
        """
        if self._db:
            sequence = await self._db.get_sequence(sequence_id)
            if not sequence:
                raise ValueError(f"Sequence {sequence_id} not found")

            step = next(
                (s for s in sequence.steps if s.order == step_order), None
            )
            if not step:
                raise ValueError(
                    f"Step {step_order} not found in sequence {sequence_id}"
                )

            if not step.variants:
                raise ValueError(
                    f"Step {step_order} has no variants to promote"
                )

            target_variant = next(
                (v for v in step.variants if v.id == variant_id), None
            )
            if not target_variant:
                raise ValueError(
                    f"Variant {variant_id} not found in step {step_order}"
                )

            # Mark the promoted variant
            for v in step.variants:
                v.is_promoted = v.id == variant_id

            await self._db.save_sequence(sequence)

    def assign_variant_for_enrollment(self, step: SequenceStep) -> str:
        """Assign variant considering promotion status.

        If a variant has been promoted, new enrollees always get it.
        Otherwise, use equal-distribution assignment.

        Args:
            step: The sequence step with variants.

        Returns:
            The variant ID assigned.
        """
        if not step.variants:
            raise ValueError(
                f"Step {step.order} has no variants for assignment"
            )

        # Check if any variant is promoted
        promoted = next(
            (v for v in step.variants if v.is_promoted), None
        )
        if promoted:
            promoted.sends += 1
            return promoted.id

        return self.assign_variant(step)

    # --- Auto-Advance Logic ---

    async def auto_advance(
        self, enrollment: ProspectEnrollment, sequence: Sequence
    ) -> TouchpointStatus | None:
        """Send next touchpoint when delay elapses without reply.

        Requirement 14.1: Auto-advance on no reply after delay.
        Requirement 14.4: Max 3 follow-ups then sequence_complete.
        Requirement 14.6: Failed touchpoint skip-and-continue.

        Args:
            enrollment: The prospect's enrollment record.
            sequence: The sequence definition.

        Returns:
            The status of the sent touchpoint, or None if no action taken.
        """
        if enrollment.status != ProspectSequenceStatus.ACTIVE:
            return None

        # Check if max follow-ups reached (initial + 3 follow-ups = 4 total)
        if enrollment.followup_count >= self.MAX_FOLLOWUPS:
            enrollment.status = ProspectSequenceStatus.SEQUENCE_COMPLETE
            enrollment.completed_at = datetime.now(timezone.utc)
            if self._db:
                await self._db.save_enrollment(enrollment)
            return None

        # Find current step
        if enrollment.current_step > len(sequence.steps):
            # All steps exhausted
            enrollment.status = ProspectSequenceStatus.SEQUENCE_COMPLETE
            enrollment.completed_at = datetime.now(timezone.utc)
            if self._db:
                await self._db.save_enrollment(enrollment)
            return None

        current_step = next(
            (s for s in sequence.steps if s.order == enrollment.current_step),
            None,
        )
        if not current_step:
            return None

        # Attempt to send the touchpoint
        status = await self._send_touchpoint(enrollment, current_step)

        if status == TouchpointStatus.FAILED:
            # Requirement 14.6: Skip failed touchpoint and continue
            logger.warning(
                "Touchpoint failed for prospect %s at step %d, skipping",
                enrollment.prospect_id,
                current_step.order,
            )
            enrollment.current_step += 1
            enrollment.followup_count += 1
            if self._db:
                await self._db.save_enrollment(enrollment)
            # Recursively try next step
            return await self.auto_advance(enrollment, sequence)

        if status == TouchpointStatus.SENT:
            enrollment.current_step += 1
            enrollment.followup_count += 1
            if self._db:
                await self._db.save_enrollment(enrollment)

        return status

    async def _send_touchpoint(
        self, enrollment: ProspectEnrollment, step: SequenceStep
    ) -> TouchpointStatus:
        """Send a single touchpoint for a prospect.

        Assigns a variant if A/B testing is active, then sends via API.

        Args:
            enrollment: The prospect enrollment.
            step: The sequence step to send.

        Returns:
            TouchpointStatus.SENT on success, TouchpointStatus.FAILED on error.
        """
        # Assign variant if applicable
        variant_id: str | None = None
        if step.variants:
            variant_id = self.assign_variant_for_enrollment(step)

        touchpoint = Touchpoint(
            id=f"{enrollment.sequence_id}_{enrollment.prospect_id}_{step.order}",
            pipeline_record_id=enrollment.prospect_id,
            sequence_id=enrollment.sequence_id,
            step_order=step.order,
            variant_id=variant_id,
            status=TouchpointStatus.PENDING,
        )

        try:
            response = await self._client.post(
                f"{self.BASE_URL}/campaigns/{enrollment.sequence_id}"
                f"/leads/{enrollment.prospect_id}/send",
                headers=self.headers,
                auth=self.auth,
                json={
                    "step_order": step.order,
                    "variant_id": variant_id,
                    "channel": step.channel.value,
                },
                timeout=self.SYNC_TIMEOUT,
            )

            if response.status_code in (200, 201):
                touchpoint.status = TouchpointStatus.SENT
                touchpoint.sent_at = datetime.now(timezone.utc)
            else:
                touchpoint.status = TouchpointStatus.FAILED
                logger.warning(
                    "Touchpoint send failed with status %d for prospect %s",
                    response.status_code,
                    enrollment.prospect_id,
                )

        except (httpx.TimeoutException, httpx.HTTPError) as e:
            touchpoint.status = TouchpointStatus.FAILED
            logger.warning(
                "Touchpoint send error for prospect %s: %s",
                enrollment.prospect_id,
                str(e),
            )

        if self._db:
            await self._db.save_touchpoint(touchpoint)

        return touchpoint.status

    # --- Process Response Events ---

    async def process_events(
        self, events: list[ResponseEvent]
    ) -> dict[str, int]:
        """Process polled response events and update enrollments.

        Handles reply detection → pause, bounce → mark failed,
        and updates variant metrics.

        Args:
            events: List of response events from poll_responses().

        Returns:
            Dict with counts of actions taken (paused, bounced, etc.).
        """
        counts: dict[str, int] = {
            "paused": 0,
            "bounced": 0,
            "unsubscribed": 0,
            "opened": 0,
            "clicked": 0,
        }

        for event in events:
            if event.event_type == ResponseEventType.REPLY:
                await self.pause_prospect(
                    event.sequence_id, event.prospect_id
                )
                counts["paused"] += 1

            elif event.event_type == ResponseEventType.BOUNCE:
                # Mark touchpoint as bounced/failed, skip and continue
                if self._db:
                    touchpoints = await self._db.get_touchpoints_for_enrollment(
                        event.prospect_id, event.sequence_id
                    )
                    for tp in touchpoints:
                        if tp.step_order == event.step_order:
                            await self._db.update_touchpoint_status(
                                tp.id, TouchpointStatus.BOUNCED
                            )
                counts["bounced"] += 1

            elif event.event_type == ResponseEventType.UNSUBSCRIBE:
                # Pause the prospect on unsubscribe
                await self.pause_prospect(
                    event.sequence_id, event.prospect_id
                )
                counts["unsubscribed"] += 1

            elif event.event_type == ResponseEventType.OPEN:
                if self._db:
                    touchpoints = await self._db.get_touchpoints_for_enrollment(
                        event.prospect_id, event.sequence_id
                    )
                    for tp in touchpoints:
                        if tp.step_order == event.step_order:
                            await self._db.update_touchpoint_status(
                                tp.id,
                                TouchpointStatus.OPENED,
                                opened_at=event.detected_at,
                            )
                counts["opened"] += 1

            elif event.event_type == ResponseEventType.CLICK:
                if self._db:
                    touchpoints = await self._db.get_touchpoints_for_enrollment(
                        event.prospect_id, event.sequence_id
                    )
                    for tp in touchpoints:
                        if tp.step_order == event.step_order:
                            await self._db.update_touchpoint_status(
                                tp.id,
                                TouchpointStatus.CLICKED,
                            )
                counts["clicked"] += 1

        return counts

    # --- Sequence Completion Check ---

    def check_sequence_complete(
        self, enrollment: ProspectEnrollment, sequence: Sequence
    ) -> bool:
        """Check if enrollment should be marked sequence_complete.

        Requirement 14.4: After initial + 3 follow-ups without reply,
        mark as sequence_complete.

        Args:
            enrollment: The prospect enrollment.
            sequence: The sequence definition.

        Returns:
            True if the enrollment is now complete.
        """
        if enrollment.status != ProspectSequenceStatus.ACTIVE:
            return enrollment.status == ProspectSequenceStatus.SEQUENCE_COMPLETE

        # Max follow-ups reached
        if enrollment.followup_count >= self.MAX_FOLLOWUPS:
            enrollment.status = ProspectSequenceStatus.SEQUENCE_COMPLETE
            enrollment.completed_at = datetime.now(timezone.utc)
            return True

        # All steps exhausted
        if enrollment.current_step > len(sequence.steps):
            enrollment.status = ProspectSequenceStatus.SEQUENCE_COMPLETE
            enrollment.completed_at = datetime.now(timezone.utc)
            return True

        return False
