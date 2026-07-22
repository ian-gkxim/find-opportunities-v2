"""Integration test for voice analytics segmentation.

Tests the end-to-end flow of computing voice-segmented funnel metrics
from mixed pipeline records (some with voice_applied=True, some False).

Verifies:
- Mixed pipeline records are correctly partitioned into voice/no-voice segments
- compute_voice_segmented_funnel produces correct segmentation
- Output structure is displayable in the Reports stage

Requirements: 4.2
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.core.analytics_service import (
    AnalyticsService,
    FunnelStage,
    StageTransition,
    VoiceSegmentedFunnel,
)


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_pipeline_records_mixed(
    voice_count: int, no_voice_count: int, reference_date: date
) -> dict:
    """Simulate mixed pipeline records with voice_applied True/False.

    Returns a dict with:
    - transitions_voice: StageTransitions for voice_applied=True records
    - transitions_no_voice: StageTransitions for voice_applied=False records
    - voice_sends/replies: aggregate counts for voice segment
    - no_voice_sends/replies: aggregate counts for no-voice segment
    """
    base_time = datetime(
        reference_date.year, reference_date.month, reference_date.day, 10, 0
    ) - timedelta(days=15)

    stage_order = ["Discovered", "Sent", "Replied"]

    # Voice-applied records: flow through Discovered → Sent → Replied
    transitions_voice = []
    voice_replied = 0
    for i in range(voice_count):
        # All enter Discovered
        transitions_voice.append(
            StageTransition(
                record_id=f"voice-{i}",
                stage_name="Discovered",
                entered_at=base_time,
                exited_at=base_time + timedelta(days=1),
                exited_to_next=True,
            )
        )
        # All move to Sent
        transitions_voice.append(
            StageTransition(
                record_id=f"voice-{i}",
                stage_name="Sent",
                entered_at=base_time + timedelta(days=1),
                exited_at=base_time + timedelta(days=3),
                exited_to_next=(i % 3 == 0),  # ~33% reply
            )
        )
        # Some get to Replied
        if i % 3 == 0:
            voice_replied += 1
            transitions_voice.append(
                StageTransition(
                    record_id=f"voice-{i}",
                    stage_name="Replied",
                    entered_at=base_time + timedelta(days=3),
                    exited_at=None,
                    exited_to_next=False,
                )
            )

    # No-voice records: flow through Discovered → Sent → Replied
    transitions_no_voice = []
    no_voice_replied = 0
    for i in range(no_voice_count):
        transitions_no_voice.append(
            StageTransition(
                record_id=f"novoice-{i}",
                stage_name="Discovered",
                entered_at=base_time,
                exited_at=base_time + timedelta(days=1),
                exited_to_next=True,
            )
        )
        transitions_no_voice.append(
            StageTransition(
                record_id=f"novoice-{i}",
                stage_name="Sent",
                entered_at=base_time + timedelta(days=1),
                exited_at=base_time + timedelta(days=4),
                exited_to_next=(i % 5 == 0),  # ~20% reply
            )
        )
        if i % 5 == 0:
            no_voice_replied += 1
            transitions_no_voice.append(
                StageTransition(
                    record_id=f"novoice-{i}",
                    stage_name="Replied",
                    entered_at=base_time + timedelta(days=4),
                    exited_at=None,
                    exited_to_next=False,
                )
            )

    return {
        "transitions_voice": transitions_voice,
        "transitions_no_voice": transitions_no_voice,
        "stage_order": stage_order,
        "voice_sends": voice_count,
        "voice_replies": voice_replied,
        "no_voice_sends": no_voice_count,
        "no_voice_replies": no_voice_replied,
    }


# ─── INTEGRATION TESTS ───────────────────────────────────────────────────────


class TestVoiceAnalyticsSegmentationIntegration:
    """Integration tests for voice analytics segmentation end-to-end.

    Simulates the real-world scenario where pipeline_records have a mix of
    voice_applied=True and voice_applied=False, and the Analytics_Service
    computes a segmented funnel for the Reports stage.

    Requirements: 4.2
    """

    @pytest.fixture
    def service(self) -> AnalyticsService:
        return AnalyticsService()

    @pytest.fixture
    def reference_date(self) -> date:
        return date(2024, 7, 15)

    def test_mixed_records_segmented_correctly(
        self, service: AnalyticsService, reference_date: date
    ):
        """Mixed voice/no-voice pipeline records produce correct segmented funnel.

        Sets up 30 voice records (voice_applied=True) and 50 no-voice records
        (voice_applied=False), verifying the funnel segments them independently.
        """
        data = _make_pipeline_records_mixed(
            voice_count=30, no_voice_count=50, reference_date=reference_date
        )

        result = service.compute_voice_segmented_funnel(
            transitions_voice=data["transitions_voice"],
            transitions_no_voice=data["transitions_no_voice"],
            stage_order=data["stage_order"],
            period_days=30,
            voice_sends=data["voice_sends"],
            voice_replies=data["voice_replies"],
            no_voice_sends=data["no_voice_sends"],
            no_voice_replies=data["no_voice_replies"],
            reference_date=reference_date,
        )

        # Verify result type
        assert isinstance(result, VoiceSegmentedFunnel)

        # Verify voice segment funnel
        assert len(result.voice_applied_funnel) == 3
        assert result.voice_applied_funnel[0].stage_name == "Discovered"
        assert result.voice_applied_funnel[1].stage_name == "Sent"
        assert result.voice_applied_funnel[2].stage_name == "Replied"

        # All 30 voice records entered Discovered
        assert result.voice_applied_funnel[0].entered_count == 30
        # All 30 moved to Sent
        assert result.voice_applied_funnel[1].entered_count == 30

        # Verify no-voice segment funnel
        assert len(result.no_voice_funnel) == 3
        assert result.no_voice_funnel[0].stage_name == "Discovered"
        assert result.no_voice_funnel[1].stage_name == "Sent"
        assert result.no_voice_funnel[2].stage_name == "Replied"

        # All 50 no-voice records entered Discovered
        assert result.no_voice_funnel[0].entered_count == 50
        # All 50 moved to Sent
        assert result.no_voice_funnel[1].entered_count == 50

        # Verify reply rates are computed independently
        # Voice: ~33% reply rate (every 3rd record replies)
        expected_voice_rr = round(data["voice_replies"] / data["voice_sends"], 4)
        assert result.voice_applied_reply_rate == expected_voice_rr

        # No-voice: ~20% reply rate (every 5th record replies)
        expected_no_voice_rr = round(
            data["no_voice_replies"] / data["no_voice_sends"], 4
        )
        assert result.no_voice_reply_rate == expected_no_voice_rr

        # Verify sample sizes
        assert result.sample_size_voice == 30
        assert result.sample_size_no_voice == 50

    def test_voice_lift_positive_when_voice_outperforms(
        self, service: AnalyticsService, reference_date: date
    ):
        """Voice segment with higher reply rate produces positive lift.

        Voice: 30 sends, 10 replies (33.3%)
        No-voice: 50 sends, 10 replies (20%)
        Expected lift: (0.3333 - 0.2) / 0.2 × 100 ≈ 66.7%
        """
        data = _make_pipeline_records_mixed(
            voice_count=30, no_voice_count=50, reference_date=reference_date
        )

        result = service.compute_voice_segmented_funnel(
            transitions_voice=data["transitions_voice"],
            transitions_no_voice=data["transitions_no_voice"],
            stage_order=data["stage_order"],
            period_days=30,
            voice_sends=30,
            voice_replies=10,
            no_voice_sends=50,
            no_voice_replies=10,
            reference_date=reference_date,
        )

        # Voice reply rate > no-voice reply rate → positive lift
        assert result.voice_applied_reply_rate > result.no_voice_reply_rate
        assert result.lift_percentage is not None
        assert result.lift_percentage > 0

        # Verify lift is approximately correct: (0.3333 - 0.2) / 0.2 × 100 ≈ 66.7%
        # The service computes lift from rounded reply rates, so we check
        # against the actual result from the service's computation.
        voice_rr = 10 / 30  # 0.3333...
        no_voice_rr = 10 / 50  # 0.2
        expected_lift_approx = ((voice_rr - no_voice_rr) / no_voice_rr) * 100
        assert abs(result.lift_percentage - expected_lift_approx) < 1.0

    def test_statistical_significance_with_large_sample(
        self, service: AnalyticsService, reference_date: date
    ):
        """Large samples with divergent reply rates yield statistical significance.

        Uses large send counts (>= AB_MIN_SAMPLE=20) with clearly different
        reply rates so the z-test detects significance at 90% confidence.
        """
        data = _make_pipeline_records_mixed(
            voice_count=100, no_voice_count=100, reference_date=reference_date
        )

        result = service.compute_voice_segmented_funnel(
            transitions_voice=data["transitions_voice"],
            transitions_no_voice=data["transitions_no_voice"],
            stage_order=data["stage_order"],
            period_days=30,
            voice_sends=500,
            voice_replies=200,  # 40%
            no_voice_sends=500,
            no_voice_replies=100,  # 20%
            reference_date=reference_date,
        )

        # Large samples with 40% vs 20% should be significant at 90%
        assert result.is_statistically_significant is True
        assert result.sample_size_voice == 500
        assert result.sample_size_no_voice == 500

    def test_small_sample_not_statistically_significant(
        self, service: AnalyticsService, reference_date: date
    ):
        """Small samples below AB_MIN_SAMPLE do not trigger significance test.

        AB_MIN_SAMPLE is 20, so samples of 10 skip the z-test entirely.
        """
        data = _make_pipeline_records_mixed(
            voice_count=10, no_voice_count=10, reference_date=reference_date
        )

        result = service.compute_voice_segmented_funnel(
            transitions_voice=data["transitions_voice"],
            transitions_no_voice=data["transitions_no_voice"],
            stage_order=data["stage_order"],
            period_days=30,
            voice_sends=10,
            voice_replies=5,
            no_voice_sends=10,
            no_voice_replies=2,
            reference_date=reference_date,
        )

        # Small sample → not significant
        assert result.is_statistically_significant is False

    def test_reports_stage_displayable_structure(
        self, service: AnalyticsService, reference_date: date
    ):
        """VoiceSegmentedFunnel has all fields needed for Reports stage display.

        Verifies the result structure contains the data the Reports stage needs:
        - Two separate funnels (voice vs no-voice) with stage-level metrics
        - Reply rates for both segments
        - Lift percentage for comparison
        - Statistical significance indicator
        - Sample sizes for data confidence labeling
        """
        data = _make_pipeline_records_mixed(
            voice_count=60, no_voice_count=80, reference_date=reference_date
        )

        result = service.compute_voice_segmented_funnel(
            transitions_voice=data["transitions_voice"],
            transitions_no_voice=data["transitions_no_voice"],
            stage_order=data["stage_order"],
            period_days=30,
            voice_sends=data["voice_sends"],
            voice_replies=data["voice_replies"],
            no_voice_sends=data["no_voice_sends"],
            no_voice_replies=data["no_voice_replies"],
            reference_date=reference_date,
        )

        # Reports stage needs these fields for display:

        # 1. Two separate funnel lists with per-stage metrics
        assert isinstance(result.voice_applied_funnel, list)
        assert isinstance(result.no_voice_funnel, list)
        for stage in result.voice_applied_funnel:
            assert isinstance(stage, FunnelStage)
            assert hasattr(stage, "stage_name")
            assert hasattr(stage, "entered_count")
            assert hasattr(stage, "exited_count")
            assert hasattr(stage, "conversion_rate")
            assert hasattr(stage, "dropoff_percentage")
            assert hasattr(stage, "avg_days_in_stage")

        # 2. Reply rates as floats for the comparison card
        assert isinstance(result.voice_applied_reply_rate, float)
        assert isinstance(result.no_voice_reply_rate, float)
        assert 0.0 <= result.voice_applied_reply_rate <= 1.0
        assert 0.0 <= result.no_voice_reply_rate <= 1.0

        # 3. Lift percentage for the "Voice Impact" display
        assert result.lift_percentage is None or isinstance(
            result.lift_percentage, float
        )

        # 4. Significance badge
        assert isinstance(result.is_statistically_significant, bool)

        # 5. Sample sizes for data confidence labeling
        assert isinstance(result.sample_size_voice, int)
        assert isinstance(result.sample_size_no_voice, int)
        assert result.sample_size_voice == 60
        assert result.sample_size_no_voice == 80

    def test_funnel_stages_conversion_rates_independent_per_segment(
        self, service: AnalyticsService, reference_date: date
    ):
        """Each segment's funnel stages have independent conversion rates.

        Voice records convert at ~33% from Sent→Replied (every 3rd replies).
        No-voice records convert at ~20% from Sent→Replied (every 5th replies).
        These rates must be computed independently within each segment.
        """
        data = _make_pipeline_records_mixed(
            voice_count=30, no_voice_count=50, reference_date=reference_date
        )

        result = service.compute_voice_segmented_funnel(
            transitions_voice=data["transitions_voice"],
            transitions_no_voice=data["transitions_no_voice"],
            stage_order=data["stage_order"],
            period_days=30,
            voice_sends=data["voice_sends"],
            voice_replies=data["voice_replies"],
            no_voice_sends=data["no_voice_sends"],
            no_voice_replies=data["no_voice_replies"],
            reference_date=reference_date,
        )

        # Voice Sent stage: 30 entered, ~10 exited_to_next (every 3rd)
        voice_sent = result.voice_applied_funnel[1]
        assert voice_sent.stage_name == "Sent"
        assert voice_sent.entered_count == 30

        # No-voice Sent stage: 50 entered, ~10 exited_to_next (every 5th)
        no_voice_sent = result.no_voice_funnel[1]
        assert no_voice_sent.stage_name == "Sent"
        assert no_voice_sent.entered_count == 50

        # Conversion rates should differ between segments
        # Voice: ~33% conversion from Sent → Replied
        # No-voice: ~20% conversion from Sent → Replied
        assert voice_sent.conversion_rate != no_voice_sent.conversion_rate

    def test_empty_voice_segment_handled_gracefully(
        self, service: AnalyticsService, reference_date: date
    ):
        """When no voice records exist, segmented funnel still works.

        Simulates early adoption where no beneficiary has a Voice_Asset yet —
        all records are no-voice. The funnel should still compute without error.
        """
        data = _make_pipeline_records_mixed(
            voice_count=0, no_voice_count=40, reference_date=reference_date
        )

        result = service.compute_voice_segmented_funnel(
            transitions_voice=data["transitions_voice"],
            transitions_no_voice=data["transitions_no_voice"],
            stage_order=data["stage_order"],
            period_days=30,
            voice_sends=0,
            voice_replies=0,
            no_voice_sends=data["no_voice_sends"],
            no_voice_replies=data["no_voice_replies"],
            reference_date=reference_date,
        )

        # Voice segment is empty → zero rates
        assert result.voice_applied_reply_rate == 0.0
        assert result.sample_size_voice == 0

        # No-voice segment is populated
        assert result.no_voice_reply_rate > 0.0
        assert result.sample_size_no_voice == 40

        # Lift is None since no_voice_rr > 0 but voice_rr is 0
        # lift = (0 - no_voice_rr) / no_voice_rr × 100 = -100.0
        assert result.lift_percentage == -100.0

        # Not significant (voice sends < AB_MIN_SAMPLE)
        assert result.is_statistically_significant is False
