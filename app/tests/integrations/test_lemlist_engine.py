"""Unit tests for Lemlist Engine integration.

Tests cover sequence creation/sync, enrollment, response polling, 
reply pausing, A/B variant assignment, auto-advance, max follow-ups,
and failed touchpoint skip-and-continue logic.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from app.integrations.lemlist_engine import (
    Channel,
    LemlistEngine,
    ProspectEnrollment,
    ProspectSequenceStatus,
    ResponseEvent,
    ResponseEventType,
    Sequence,
    SequenceStep,
    SequenceSyncStatus,
    SequenceValidationError,
    Touchpoint,
    TouchpointStatus,
    Variant,
    validate_sequence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http_client():
    """Create a mock httpx.AsyncClient for testing."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def mock_db_repo():
    """Create a mock database repository."""
    repo = AsyncMock()
    repo.get_sequence = AsyncMock(return_value=None)
    repo.save_sequence = AsyncMock()
    repo.get_enrollment = AsyncMock(return_value=None)
    repo.save_enrollment = AsyncMock()
    repo.get_active_enrollments = AsyncMock(return_value=[])
    repo.get_prospects_by_filter = AsyncMock(return_value=[])
    repo.get_touchpoints_for_enrollment = AsyncMock(return_value=[])
    repo.save_touchpoint = AsyncMock()
    repo.update_touchpoint_status = AsyncMock()
    repo.get_pending_touchpoints = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def engine(mock_http_client, mock_db_repo):
    """Create a LemlistEngine with mocked dependencies."""
    return LemlistEngine(
        api_key="test-key",
        http_client=mock_http_client,
        db_repo=mock_db_repo,
    )


def _make_response(status_code: int, json_data: dict) -> httpx.Response:
    """Helper to create a mock httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", "https://api.lemlist.com/api/test"),
    )


def _make_sequence(
    num_steps: int = 3, with_variants: bool = False
) -> Sequence:
    """Helper to create a test sequence."""
    steps = []
    for i in range(1, num_steps + 1):
        variants = []
        if with_variants:
            variants = [
                Variant(id="A", content=f"Variant A content step {i}"),
                Variant(id="B", content=f"Variant B content step {i}"),
            ]
        steps.append(
            SequenceStep(
                order=i,
                channel=Channel.EMAIL,
                delay_days=3,
                content_template=f"Step {i} template content",
                variants=variants,
            )
        )
    return Sequence(
        id="seq_test_1",
        name="Test Sequence",
        beneficiary_id="consultant",
        steps=steps,
    )


# ---------------------------------------------------------------------------
# Sequence Validation Tests
# ---------------------------------------------------------------------------


class TestSequenceValidation:
    """Tests for validate_sequence()."""

    def test_valid_sequence_passes(self):
        """A properly formed sequence passes validation."""
        seq = _make_sequence(num_steps=3)
        validate_sequence(seq)  # Should not raise

    def test_empty_steps_rejected(self):
        """Sequence with no steps is rejected."""
        seq = Sequence(
            id="s1", name="Empty", beneficiary_id="team", steps=[]
        )
        with pytest.raises(SequenceValidationError, match="at least 1 step"):
            validate_sequence(seq)

    def test_exceeding_10_steps_rejected(self):
        """Sequence with more than 10 steps is rejected."""
        seq = _make_sequence(num_steps=11)
        with pytest.raises(SequenceValidationError, match="exceed 10 steps"):
            validate_sequence(seq)

    def test_delay_below_1_rejected(self):
        """Step with delay < 1 day is rejected."""
        seq = _make_sequence(num_steps=1)
        seq.steps[0].delay_days = 0
        with pytest.raises(SequenceValidationError, match="1-30 days"):
            validate_sequence(seq)

    def test_delay_above_30_rejected(self):
        """Step with delay > 30 days is rejected."""
        seq = _make_sequence(num_steps=1)
        seq.steps[0].delay_days = 31
        with pytest.raises(SequenceValidationError, match="1-30 days"):
            validate_sequence(seq)

    def test_content_over_5000_chars_rejected(self):
        """Step with content > 5000 chars is rejected."""
        seq = _make_sequence(num_steps=1)
        seq.steps[0].content_template = "x" * 5001
        with pytest.raises(SequenceValidationError, match="5000 chars"):
            validate_sequence(seq)

    def test_single_variant_rejected(self):
        """Step with only 1 variant (need 2-4) is rejected."""
        seq = _make_sequence(num_steps=1)
        seq.steps[0].variants = [Variant(id="A", content="only one")]
        with pytest.raises(SequenceValidationError, match="2-4 variants"):
            validate_sequence(seq)

    def test_five_variants_rejected(self):
        """Step with 5 variants (max is 4) is rejected."""
        seq = _make_sequence(num_steps=1)
        seq.steps[0].variants = [
            Variant(id=c, content=f"V{c}") for c in "ABCDE"
        ]
        with pytest.raises(SequenceValidationError, match="2-4 variants"):
            validate_sequence(seq)


# ---------------------------------------------------------------------------
# Sequence Creation / Sync Tests
# ---------------------------------------------------------------------------


class TestCreateSequence:
    """Tests for LemlistEngine.create_sequence()."""

    async def test_successful_sync(self, engine, mock_http_client):
        """Successful API response marks sequence as synced."""
        mock_http_client.post.return_value = _make_response(
            201, {"_id": "lemlist_camp_123"}
        )
        seq = _make_sequence()
        status = await engine.create_sequence(seq)

        assert status == SequenceSyncStatus.SYNCED
        assert seq.lemlist_campaign_id == "lemlist_camp_123"
        assert seq.sync_error is None

    async def test_api_error_marks_sync_failed(
        self, engine, mock_http_client
    ):
        """Non-success response marks sequence as sync_failed."""
        mock_http_client.post.return_value = _make_response(
            500, {"error": "Internal Server Error"}
        )
        seq = _make_sequence()
        status = await engine.create_sequence(seq)

        assert status == SequenceSyncStatus.SYNC_FAILED
        assert seq.sync_error is not None
        assert "500" in seq.sync_error

    async def test_timeout_marks_sync_failed(
        self, engine, mock_http_client
    ):
        """Timeout marks sequence as sync_failed."""
        mock_http_client.post.side_effect = httpx.TimeoutException(
            "Connection timed out"
        )
        seq = _make_sequence()
        status = await engine.create_sequence(seq)

        assert status == SequenceSyncStatus.SYNC_FAILED
        assert "timed out" in seq.sync_error

    async def test_invalid_sequence_raises(self, engine):
        """Invalid sequence raises SequenceValidationError."""
        seq = Sequence(
            id="s1", name="Invalid", beneficiary_id="x", steps=[]
        )
        with pytest.raises(SequenceValidationError):
            await engine.create_sequence(seq)


# ---------------------------------------------------------------------------
# Enrollment Tests
# ---------------------------------------------------------------------------


class TestEnrollProspects:
    """Tests for LemlistEngine.enroll_prospects()."""

    async def test_single_enrollment(self, engine, mock_db_repo):
        """Single prospect enrollment succeeds."""
        count = await engine.enroll_prospects("seq_1", ["prospect_1"])
        assert count == 1
        mock_db_repo.save_enrollment.assert_called_once()

    async def test_batch_enrollment(self, engine, mock_db_repo):
        """Batch enrollment of multiple prospects."""
        ids = [f"prospect_{i}" for i in range(50)]
        count = await engine.enroll_prospects("seq_1", ids)
        assert count == 50

    async def test_batch_exceeds_200_raises(self, engine):
        """Enrolling more than 200 prospects raises ValueError."""
        ids = [f"p_{i}" for i in range(201)]
        with pytest.raises(ValueError, match="200"):
            await engine.enroll_prospects("seq_1", ids)

    async def test_exactly_200_succeeds(self, engine, mock_db_repo):
        """Enrolling exactly 200 prospects succeeds."""
        ids = [f"p_{i}" for i in range(200)]
        count = await engine.enroll_prospects("seq_1", ids)
        assert count == 200

    async def test_duplicate_enrollment_skipped(self, engine, mock_db_repo):
        """Already-enrolled prospects are skipped."""
        mock_db_repo.get_enrollment.return_value = ProspectEnrollment(
            prospect_id="p_1", sequence_id="seq_1"
        )
        count = await engine.enroll_prospects("seq_1", ["p_1"])
        assert count == 0


# ---------------------------------------------------------------------------
# Filter Enrollment Tests
# ---------------------------------------------------------------------------


class TestEnrollByFilter:
    """Tests for LemlistEngine.enroll_by_filter()."""

    async def test_filter_by_tier(self, engine, mock_db_repo):
        """Filter enrollment by score tier."""
        from app.core.scoring_engine import ScoreTier

        mock_db_repo.get_prospects_by_filter.return_value = [
            "p_1", "p_2", "p_3"
        ]
        count = await engine.enroll_by_filter(
            "seq_1", tier=ScoreTier.A
        )
        assert count == 3

    async def test_filter_caps_at_200(self, engine, mock_db_repo):
        """Filter enrollment caps at 200 even if more match."""
        mock_db_repo.get_prospects_by_filter.return_value = [
            f"p_{i}" for i in range(300)
        ]
        count = await engine.enroll_by_filter("seq_1", has_intent=True)
        assert count == 200


# ---------------------------------------------------------------------------
# Response Polling Tests
# ---------------------------------------------------------------------------


class TestPollResponses:
    """Tests for LemlistEngine.poll_responses()."""

    async def test_successful_poll(self, engine, mock_http_client):
        """Successful poll returns parsed events."""
        mock_http_client.get.return_value = _make_response(
            200,
            [
                {
                    "type": "emailsReplied",
                    "leadId": "p_1",
                    "campaignId": "seq_1",
                    "stepOrder": 2,
                    "text": "Thanks for reaching out!",
                },
                {
                    "type": "emailsBounced",
                    "leadId": "p_2",
                    "campaignId": "seq_1",
                    "stepOrder": 1,
                },
            ],
        )
        events = await engine.poll_responses()
        assert len(events) == 2
        assert events[0].event_type == ResponseEventType.REPLY
        assert events[1].event_type == ResponseEventType.BOUNCE

    async def test_poll_api_error_returns_empty(
        self, engine, mock_http_client
    ):
        """API error during poll returns empty without raising."""
        mock_http_client.get.return_value = _make_response(
            500, {"error": "Server Error"}
        )
        events = await engine.poll_responses()
        assert events == []

    async def test_poll_timeout_returns_empty(
        self, engine, mock_http_client
    ):
        """Timeout during poll returns empty without raising."""
        mock_http_client.get.side_effect = httpx.TimeoutException("timeout")
        events = await engine.poll_responses()
        assert events == []


# ---------------------------------------------------------------------------
# Pause Prospect Tests
# ---------------------------------------------------------------------------


class TestPauseProspect:
    """Tests for LemlistEngine.pause_prospect()."""

    async def test_pauses_active_enrollment(self, engine, mock_db_repo):
        """Active enrollment is paused on reply detection."""
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_1",
            status=ProspectSequenceStatus.ACTIVE,
        )
        mock_db_repo.get_enrollment.return_value = enrollment
        mock_db_repo.get_pending_touchpoints.return_value = []

        await engine.pause_prospect("seq_1", "p_1")

        assert enrollment.status == ProspectSequenceStatus.PAUSED
        assert enrollment.paused_at is not None
        mock_db_repo.save_enrollment.assert_called_once()

    async def test_pauses_pending_touchpoints(self, engine, mock_db_repo):
        """Pending touchpoints are updated on pause."""
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_1",
            status=ProspectSequenceStatus.ACTIVE,
        )
        pending_tp = Touchpoint(
            id="tp_1",
            pipeline_record_id="p_1",
            sequence_id="seq_1",
            step_order=3,
            status=TouchpointStatus.PENDING,
        )
        mock_db_repo.get_enrollment.return_value = enrollment
        mock_db_repo.get_pending_touchpoints.return_value = [pending_tp]

        await engine.pause_prospect("seq_1", "p_1")

        mock_db_repo.update_touchpoint_status.assert_called_once()


# ---------------------------------------------------------------------------
# A/B Variant Assignment Tests
# ---------------------------------------------------------------------------


class TestAssignVariant:
    """Tests for LemlistEngine.assign_variant()."""

    def test_random_assignment_returns_valid_variant(self, engine):
        """Assignment returns one of the configured variant IDs."""
        step = SequenceStep(
            order=1,
            channel=Channel.EMAIL,
            delay_days=3,
            content_template="test",
            variants=[
                Variant(id="A", content="A content"),
                Variant(id="B", content="B content"),
            ],
        )
        result = engine.assign_variant(step)
        assert result in ("A", "B")

    def test_no_variants_raises(self, engine):
        """Assignment with no variants raises ValueError."""
        step = SequenceStep(
            order=1,
            channel=Channel.EMAIL,
            delay_days=3,
            content_template="test",
            variants=[],
        )
        with pytest.raises(ValueError, match="no variants"):
            engine.assign_variant(step)

    def test_distribution_balanced_after_40(self, engine):
        """After 40 assignments, distribution is within ±5pp."""
        step = SequenceStep(
            order=1,
            channel=Channel.EMAIL,
            delay_days=3,
            content_template="test",
            variants=[
                Variant(id="A", content="A", sends=0),
                Variant(id="B", content="B", sends=0),
                Variant(id="C", content="C", sends=0),
            ],
        )
        # Make 60 assignments
        for _ in range(60):
            engine.assign_variant(step)

        total = sum(v.sends for v in step.variants)
        ideal_share = 100 / 3  # ~33.3%
        for v in step.variants:
            share = (v.sends / total) * 100
            assert abs(share - ideal_share) <= 5.0, (
                f"Variant {v.id} share {share:.1f}% "
                f"exceeds ±5pp from ideal {ideal_share:.1f}%"
            )


# ---------------------------------------------------------------------------
# Variant Promotion Tests
# ---------------------------------------------------------------------------


class TestPromoteVariant:
    """Tests for LemlistEngine.promote_variant()."""

    async def test_promote_sets_promoted_flag(self, engine, mock_db_repo):
        """Promoted variant has is_promoted=True, others False."""
        seq = _make_sequence(num_steps=2, with_variants=True)
        mock_db_repo.get_sequence.return_value = seq

        await engine.promote_variant("seq_test_1", step_order=1, variant_id="A")

        step = seq.steps[0]
        assert step.variants[0].is_promoted is True  # A
        assert step.variants[1].is_promoted is False  # B

    async def test_promote_unknown_sequence_raises(
        self, engine, mock_db_repo
    ):
        """Promoting variant in unknown sequence raises ValueError."""
        mock_db_repo.get_sequence.return_value = None
        with pytest.raises(ValueError, match="not found"):
            await engine.promote_variant("nonexistent", 1, "A")

    def test_promoted_variant_always_assigned(self, engine):
        """After promotion, new enrollees always get promoted variant."""
        step = SequenceStep(
            order=1,
            channel=Channel.EMAIL,
            delay_days=3,
            content_template="test",
            variants=[
                Variant(id="A", content="A", is_promoted=True),
                Variant(id="B", content="B", is_promoted=False),
            ],
        )
        # All 20 assignments should be "A"
        for _ in range(20):
            result = engine.assign_variant_for_enrollment(step)
            assert result == "A"


# ---------------------------------------------------------------------------
# Auto-Advance Tests
# ---------------------------------------------------------------------------


class TestAutoAdvance:
    """Tests for LemlistEngine.auto_advance()."""

    async def test_sends_next_touchpoint(self, engine, mock_http_client):
        """Auto-advance sends the next touchpoint on success."""
        mock_http_client.post.return_value = _make_response(200, {})
        seq = _make_sequence(num_steps=4)
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_test_1",
            current_step=2,
            followup_count=1,
        )
        status = await engine.auto_advance(enrollment, seq)

        assert status == TouchpointStatus.SENT
        assert enrollment.current_step == 3
        assert enrollment.followup_count == 2

    async def test_max_followups_completes_sequence(
        self, engine, mock_http_client
    ):
        """After 3 follow-ups, enrollment becomes sequence_complete."""
        seq = _make_sequence(num_steps=5)
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_test_1",
            current_step=4,
            followup_count=3,
        )
        status = await engine.auto_advance(enrollment, seq)

        assert status is None
        assert enrollment.status == ProspectSequenceStatus.SEQUENCE_COMPLETE
        assert enrollment.completed_at is not None

    async def test_paused_enrollment_no_action(self, engine):
        """Paused enrollment does not advance."""
        seq = _make_sequence(num_steps=4)
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_test_1",
            status=ProspectSequenceStatus.PAUSED,
            current_step=2,
        )
        status = await engine.auto_advance(enrollment, seq)
        assert status is None
        assert enrollment.current_step == 2  # unchanged

    async def test_failed_touchpoint_skips(
        self, engine, mock_http_client, mock_db_repo
    ):
        """Failed touchpoint is skipped and next step attempted."""
        # First call fails, second succeeds
        mock_http_client.post.side_effect = [
            _make_response(500, {"error": "fail"}),
            _make_response(200, {}),
        ]
        seq = _make_sequence(num_steps=4)
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_test_1",
            current_step=1,
            followup_count=0,
        )
        status = await engine.auto_advance(enrollment, seq)

        # Should have skipped step 1 (failed) and sent step 2
        assert status == TouchpointStatus.SENT
        assert enrollment.current_step == 3
        assert enrollment.followup_count == 2

    async def test_all_steps_exhausted_completes(
        self, engine, mock_http_client
    ):
        """When all steps are exhausted, enrollment is completed."""
        seq = _make_sequence(num_steps=2)
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_test_1",
            current_step=3,  # beyond last step
            followup_count=2,
        )
        status = await engine.auto_advance(enrollment, seq)

        assert status is None
        assert enrollment.status == ProspectSequenceStatus.SEQUENCE_COMPLETE


# ---------------------------------------------------------------------------
# Process Events Tests
# ---------------------------------------------------------------------------


class TestProcessEvents:
    """Tests for LemlistEngine.process_events()."""

    async def test_reply_event_pauses(self, engine, mock_db_repo):
        """Reply event triggers pause_prospect."""
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_1",
            status=ProspectSequenceStatus.ACTIVE,
        )
        mock_db_repo.get_enrollment.return_value = enrollment
        mock_db_repo.get_pending_touchpoints.return_value = []

        events = [
            ResponseEvent(
                event_type=ResponseEventType.REPLY,
                prospect_id="p_1",
                sequence_id="seq_1",
                step_order=2,
            )
        ]
        counts = await engine.process_events(events)
        assert counts["paused"] == 1
        assert enrollment.status == ProspectSequenceStatus.PAUSED

    async def test_bounce_event_marks_bounced(self, engine, mock_db_repo):
        """Bounce event marks the touchpoint as bounced."""
        tp = Touchpoint(
            id="tp_1",
            pipeline_record_id="p_1",
            sequence_id="seq_1",
            step_order=1,
            status=TouchpointStatus.SENT,
        )
        mock_db_repo.get_touchpoints_for_enrollment.return_value = [tp]

        events = [
            ResponseEvent(
                event_type=ResponseEventType.BOUNCE,
                prospect_id="p_1",
                sequence_id="seq_1",
                step_order=1,
            )
        ]
        counts = await engine.process_events(events)
        assert counts["bounced"] == 1
        mock_db_repo.update_touchpoint_status.assert_called_once_with(
            "tp_1", TouchpointStatus.BOUNCED
        )


# ---------------------------------------------------------------------------
# Sequence Complete Check Tests
# ---------------------------------------------------------------------------


class TestCheckSequenceComplete:
    """Tests for LemlistEngine.check_sequence_complete()."""

    def test_max_followups_triggers_complete(self, engine):
        """3 follow-ups marks enrollment as sequence_complete."""
        seq = _make_sequence(num_steps=5)
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_test_1",
            followup_count=3,
        )
        result = engine.check_sequence_complete(enrollment, seq)
        assert result is True
        assert enrollment.status == ProspectSequenceStatus.SEQUENCE_COMPLETE

    def test_below_max_not_complete(self, engine):
        """Below max follow-ups is not complete."""
        seq = _make_sequence(num_steps=5)
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_test_1",
            followup_count=2,
            current_step=3,
        )
        result = engine.check_sequence_complete(enrollment, seq)
        assert result is False

    def test_all_steps_exhausted_complete(self, engine):
        """All steps exhausted marks as complete."""
        seq = _make_sequence(num_steps=3)
        enrollment = ProspectEnrollment(
            prospect_id="p_1",
            sequence_id="seq_test_1",
            followup_count=2,
            current_step=4,  # beyond 3 steps
        )
        result = engine.check_sequence_complete(enrollment, seq)
        assert result is True
