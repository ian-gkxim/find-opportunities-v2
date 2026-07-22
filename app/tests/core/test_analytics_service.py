"""Unit tests for AnalyticsService.

Tests core computation logic for funnel metrics, A/B testing,
channel effectiveness, effort metrics, and source attribution.
"""

from datetime import date, datetime, timedelta

import pytest

from app.core.analytics_service import (
    ABTestResult,
    AnalyticsService,
    ChannelData,
    ChannelEffectiveness,
    ConversionAlert,
    ConversionRateSnapshot,
    DiscoveryEvent,
    EffortMetrics,
    FunnelStage,
    LowResponseRecommendation,
    MonthlyTrend,
    OutcomeAttribution,
    SequenceResponse,
    StageTransition,
    VariantData,
    VoiceSegmentedFunnel,
    _z_test_two_proportions,
)


@pytest.fixture
def service() -> AnalyticsService:
    return AnalyticsService()


# ─── Funnel Computation ───────────────────────────────────────────────────────


class TestComputeFunnel:
    def test_basic_funnel(self, service: AnalyticsService):
        """Funnel with clear conversion and drop-off."""
        ref = date(2024, 6, 15)
        transitions = [
            StageTransition(
                record_id=f"r{i}", stage_name="Discovered",
                entered_at=datetime(2024, 6, 1, 10, 0),
                exited_at=datetime(2024, 6, 2, 10, 0),
                exited_to_next=True,
            )
            for i in range(10)
        ] + [
            StageTransition(
                record_id=f"r{10+i}", stage_name="Sent",
                entered_at=datetime(2024, 6, 2, 10, 0),
                exited_at=datetime(2024, 6, 5, 10, 0),
                exited_to_next=True,
            )
            for i in range(6)
        ] + [
            StageTransition(
                record_id=f"r{16+i}", stage_name="Sent",
                entered_at=datetime(2024, 6, 2, 10, 0),
                exited_at=None,
                exited_to_next=False,
            )
            for i in range(4)
        ]

        result = service.compute_funnel(
            transitions=transitions,
            stage_order=["Discovered", "Sent"],
            period_days=30,
            reference_date=ref,
        )

        assert len(result) == 2
        # Discovered: 10 entered, 10 exited → 100% conversion
        assert result[0].stage_name == "Discovered"
        assert result[0].entered_count == 10
        assert result[0].exited_count == 10
        assert result[0].conversion_rate == 100.0
        assert result[0].dropoff_percentage == 0.0
        assert result[0].avg_days_in_stage == 1.0

        # Sent: 10 entered, 6 exited → 60% conversion
        assert result[1].stage_name == "Sent"
        assert result[1].entered_count == 10
        assert result[1].exited_count == 6
        assert result[1].conversion_rate == 60.0
        assert result[1].dropoff_percentage == 40.0


    def test_insufficient_data_indicator(self, service: AnalyticsService):
        """Stages with < 5 records get insufficient data flag."""
        ref = date(2024, 6, 15)
        transitions = [
            StageTransition(
                record_id=f"r{i}", stage_name="Discovered",
                entered_at=datetime(2024, 6, 1),
                exited_at=datetime(2024, 6, 2),
                exited_to_next=True,
            )
            for i in range(3)
        ]

        result = service.compute_funnel(
            transitions=transitions,
            stage_order=["Discovered"],
            period_days=30,
            reference_date=ref,
        )

        assert result[0].has_insufficient_data is True
        assert result[0].entered_count == 3

    def test_empty_stage(self, service: AnalyticsService):
        """Stage with no transitions returns zero values."""
        ref = date(2024, 6, 15)
        result = service.compute_funnel(
            transitions=[],
            stage_order=["Discovered"],
            period_days=30,
            reference_date=ref,
        )

        assert result[0].entered_count == 0
        assert result[0].conversion_rate == 0.0
        assert result[0].avg_days_in_stage == 0.0
        assert result[0].has_insufficient_data is True

    def test_period_filtering(self, service: AnalyticsService):
        """Only transitions within the period are counted."""
        ref = date(2024, 6, 15)
        # One within period, one outside
        transitions = [
            StageTransition(
                record_id="r1", stage_name="Discovered",
                entered_at=datetime(2024, 6, 10),
                exited_at=datetime(2024, 6, 11),
                exited_to_next=True,
            ),
            StageTransition(
                record_id="r2", stage_name="Discovered",
                entered_at=datetime(2024, 1, 1),  # Outside 30-day window
                exited_at=datetime(2024, 1, 2),
                exited_to_next=True,
            ),
        ]

        result = service.compute_funnel(
            transitions=transitions,
            stage_order=["Discovered"],
            period_days=30,
            reference_date=ref,
        )

        assert result[0].entered_count == 1



# ─── Conversion Alerts ────────────────────────────────────────────────────────


class TestConversionAlerts:
    def test_alert_fires_on_significant_drop(self, service: AnalyticsService):
        """Alert fires when current rate drops > 20% below trailing average."""
        today = date(2024, 6, 15)
        # Trailing average of 50%, current rate of 30% → 40% drop
        current_rates = {("Sent", "cold_outreach"): 30.0}
        snapshots = [
            ConversionRateSnapshot(
                stage="Sent", opportunity_type="cold_outreach",
                rate=50.0, snapshot_date=today - timedelta(days=i),
            )
            for i in range(1, 10)
        ]

        alerts = service.compute_conversion_alerts(
            current_rates=current_rates,
            snapshots=snapshots,
            existing_alerts_today=set(),
            today=today,
        )

        assert len(alerts) == 1
        assert alerts[0].stage == "Sent"
        assert alerts[0].current_rate == 30.0
        assert alerts[0].trailing_avg == 50.0
        assert alerts[0].drop_percentage == 0.4  # (50-30)/50

    def test_no_alert_when_drop_within_threshold(self, service: AnalyticsService):
        """No alert when drop is ≤ 20%."""
        today = date(2024, 6, 15)
        # Trailing avg 50%, current 42% → 16% drop (below 20% threshold)
        current_rates = {("Sent", "cold_outreach"): 42.0}
        snapshots = [
            ConversionRateSnapshot(
                stage="Sent", opportunity_type="cold_outreach",
                rate=50.0, snapshot_date=today - timedelta(days=i),
            )
            for i in range(1, 10)
        ]

        alerts = service.compute_conversion_alerts(
            current_rates=current_rates,
            snapshots=snapshots,
            existing_alerts_today=set(),
            today=today,
        )

        assert len(alerts) == 0


    def test_max_one_alert_per_stage_per_day(self, service: AnalyticsService):
        """No alert if one already exists today for the same stage."""
        today = date(2024, 6, 15)
        current_rates = {("Sent", "cold_outreach"): 10.0}
        snapshots = [
            ConversionRateSnapshot(
                stage="Sent", opportunity_type="cold_outreach",
                rate=50.0, snapshot_date=today - timedelta(days=i),
            )
            for i in range(1, 10)
        ]

        # Already have an alert today
        alerts = service.compute_conversion_alerts(
            current_rates=current_rates,
            snapshots=snapshots,
            existing_alerts_today={("Sent", "cold_outreach")},
            today=today,
        )

        assert len(alerts) == 0

    def test_no_alert_when_no_snapshots(self, service: AnalyticsService):
        """No alert generated when there's no historical data."""
        today = date(2024, 6, 15)
        current_rates = {("Sent", "cold_outreach"): 10.0}

        alerts = service.compute_conversion_alerts(
            current_rates=current_rates,
            snapshots=[],
            existing_alerts_today=set(),
            today=today,
        )

        assert len(alerts) == 0


# ─── A/B Test Results ─────────────────────────────────────────────────────────


class TestABResults:
    def test_winner_detected_with_margin_and_confidence(
        self, service: AnalyticsService
    ):
        """Winner flagged when reply rate exceeds all others by ≥2pp with confidence."""
        variants = [
            VariantData(variant_id="A", sends=200, opens=100, clicks=50, replies=40),
            VariantData(variant_id="B", sends=200, opens=80, clicks=30, replies=10),
        ]
        # A: 20% reply rate, B: 5% reply rate → A wins by 15pp

        results = service.compute_ab_results(variants)

        assert len(results) == 2
        winner = next(r for r in results if r.is_winner)
        assert winner.variant_id == "A"
        assert not any(r.is_inconclusive for r in results)


    def test_no_winner_when_margin_too_small(self, service: AnalyticsService):
        """No winner when difference is < 2 percentage points."""
        variants = [
            VariantData(variant_id="A", sends=200, opens=100, clicks=50, replies=22),
            VariantData(variant_id="B", sends=200, opens=80, clicks=30, replies=20),
        ]
        # A: 11% reply rate, B: 10% reply rate → only 1pp difference

        results = service.compute_ab_results(variants)

        assert not any(r.is_winner for r in results)

    def test_inconclusive_after_threshold(self, service: AnalyticsService):
        """Inconclusive flagged when all variants reach 100 sends with no winner."""
        variants = [
            VariantData(variant_id="A", sends=100, opens=50, clicks=25, replies=10),
            VariantData(variant_id="B", sends=100, opens=48, clicks=24, replies=9),
        ]
        # A: 10%, B: 9% → 1pp difference, not enough for winner

        results = service.compute_ab_results(variants)

        assert not any(r.is_winner for r in results)
        assert all(r.is_inconclusive for r in results)

    def test_not_inconclusive_before_threshold(self, service: AnalyticsService):
        """Not inconclusive when variants haven't all reached 100 sends."""
        variants = [
            VariantData(variant_id="A", sends=80, opens=40, clicks=20, replies=8),
            VariantData(variant_id="B", sends=80, opens=38, clicks=19, replies=7),
        ]

        results = service.compute_ab_results(variants)

        assert not any(r.is_winner for r in results)
        assert not any(r.is_inconclusive for r in results)

    def test_no_computation_below_min_sample(self, service: AnalyticsService):
        """No winner detection when below minimum 20 sends."""
        variants = [
            VariantData(variant_id="A", sends=15, opens=10, clicks=5, replies=5),
            VariantData(variant_id="B", sends=15, opens=5, clicks=2, replies=0),
        ]

        results = service.compute_ab_results(variants)

        # Still returns results but no winner
        assert len(results) == 2
        assert not any(r.is_winner for r in results)

    def test_empty_variants(self, service: AnalyticsService):
        """Empty variant list returns empty results."""
        results = service.compute_ab_results([])
        assert results == []



# ─── Channel Effectiveness ────────────────────────────────────────────────────


class TestChannelEffectiveness:
    def test_basic_rates(self, service: AnalyticsService):
        """Correctly computes response, meeting, and conversion rates."""
        data = [
            ChannelData(
                source="apollo", sequence_name="Seq1", beneficiary="consultant",
                sends=100, replies=20, meetings=5, outcomes=2, total_entered=50,
            ),
        ]

        results = service.compute_channel_effectiveness(data)

        assert len(results) == 1
        r = results[0]
        assert r.response_rate == 0.2
        assert r.meeting_rate == 0.05
        assert r.conversion_rate == 0.04
        assert r.is_low_confidence is False

    def test_low_confidence_suppresses_rates(self, service: AnalyticsService):
        """Low confidence (< 10 sends) suppresses percentage rates."""
        data = [
            ChannelData(
                source="adzuna", sequence_name=None, beneficiary="team",
                sends=5, replies=2, meetings=1, outcomes=1, total_entered=5,
            ),
        ]

        results = service.compute_channel_effectiveness(data)

        assert len(results) == 1
        r = results[0]
        assert r.is_low_confidence is True
        assert r.response_rate == 0.0
        assert r.meeting_rate == 0.0
        assert r.conversion_rate == 0.0

    def test_zero_sends(self, service: AnalyticsService):
        """Zero sends handled gracefully."""
        data = [
            ChannelData(
                source="apollo", sequence_name="Seq1", beneficiary="consultant",
                sends=0, replies=0, meetings=0, outcomes=0, total_entered=0,
            ),
        ]

        results = service.compute_channel_effectiveness(data)

        assert results[0].is_low_confidence is True



# ─── Effort Metrics ───────────────────────────────────────────────────────────


class TestEffortMetrics:
    def test_monthly_counts(self, service: AnalyticsService):
        """Counts events within the specified calendar month."""
        month = date(2024, 6, 1)
        discovered = [
            datetime(2024, 6, 1, 10, 0),
            datetime(2024, 6, 15, 10, 0),
            datetime(2024, 5, 31, 23, 59),  # Previous month
        ]
        sent = [datetime(2024, 6, 5, 10, 0)] * 5
        responses = [datetime(2024, 6, 10, 10, 0)] * 2
        outcomes = [datetime(2024, 6, 20, 10, 0)]

        result = service.compute_effort_metrics(
            discovered=discovered,
            sent=sent,
            responses=responses,
            outcomes=outcomes,
            month=month,
        )

        assert result.month == date(2024, 6, 1)
        assert result.discovered == 2
        assert result.sent == 5
        assert result.responses == 2
        assert result.outcomes == 1

    def test_december_month_boundary(self, service: AnalyticsService):
        """December correctly uses January of next year as boundary."""
        month = date(2024, 12, 1)
        discovered = [
            datetime(2024, 12, 15),
            datetime(2025, 1, 1),  # Next year, excluded
        ]

        result = service.compute_effort_metrics(
            discovered=discovered, sent=[], responses=[], outcomes=[],
            month=month,
        )

        assert result.discovered == 1



# ─── Source Attribution ───────────────────────────────────────────────────────


class TestAttributeOutcome:
    def test_earliest_source_attribution(self, service: AnalyticsService):
        """Attributes outcome to the source with earliest discovery date."""
        discovery_events = [
            DiscoveryEvent(
                prospect_id="p1", source="adzuna",
                discovered_at=datetime(2024, 6, 5),
            ),
            DiscoveryEvent(
                prospect_id="p1", source="apollo",
                discovered_at=datetime(2024, 6, 1),  # Earliest
            ),
        ]
        sequence_responses = [
            SequenceResponse(
                pipeline_record_id="pr1", sequence_id="seq1",
                variant_id="A", replied_at=datetime(2024, 6, 10),
            ),
        ]

        result = service.attribute_outcome(
            pipeline_record_id="pr1",
            discovery_events=discovery_events,
            sequence_responses=sequence_responses,
        )

        assert result.discovery_source == "apollo"
        assert result.sequence_id == "seq1"
        assert result.variant_id == "A"

    def test_no_discovery_events(self, service: AnalyticsService):
        """Unknown source when no discovery events exist."""
        result = service.attribute_outcome(
            pipeline_record_id="pr1",
            discovery_events=[],
            sequence_responses=[],
        )

        assert result.discovery_source == "unknown"
        assert result.sequence_id is None
        assert result.variant_id is None

    def test_first_reply_variant_attribution(self, service: AnalyticsService):
        """Attributes the first reply's sequence and variant."""
        discovery_events = [
            DiscoveryEvent(
                prospect_id="p1", source="apollo",
                discovered_at=datetime(2024, 6, 1),
            ),
        ]
        sequence_responses = [
            SequenceResponse(
                pipeline_record_id="pr1", sequence_id="seq2",
                variant_id="B", replied_at=datetime(2024, 6, 15),
            ),
            SequenceResponse(
                pipeline_record_id="pr1", sequence_id="seq1",
                variant_id="A", replied_at=datetime(2024, 6, 10),  # First reply
            ),
        ]

        result = service.attribute_outcome(
            pipeline_record_id="pr1",
            discovery_events=discovery_events,
            sequence_responses=sequence_responses,
        )

        assert result.sequence_id == "seq1"
        assert result.variant_id == "A"



# ─── Low Response Recommendations ────────────────────────────────────────────


class TestLowResponseRecommendations:
    def test_recommendation_fires(self, service: AnalyticsService):
        """Recommendation when ≥ 50 sends and < 2% response rate."""
        sequences = [("seq1", 100, 1)]  # 1% response rate

        results = service.compute_low_response_recommendations(sequences)

        assert len(results) == 1
        assert results[0].sequence_id == "seq1"
        assert results[0].sends == 100
        assert results[0].response_rate == 0.01

    def test_no_recommendation_above_threshold(self, service: AnalyticsService):
        """No recommendation when response rate ≥ 2%."""
        sequences = [("seq1", 100, 3)]  # 3% response rate

        results = service.compute_low_response_recommendations(sequences)

        assert len(results) == 0

    def test_no_recommendation_below_min_sends(self, service: AnalyticsService):
        """No recommendation when sends < 50."""
        sequences = [("seq1", 30, 0)]  # 0% but only 30 sends

        results = service.compute_low_response_recommendations(sequences)

        assert len(results) == 0


# ─── Monthly Trend ────────────────────────────────────────────────────────────


class TestMonthlyTrend:
    def test_twelve_months_per_stage(self, service: AnalyticsService):
        """Produces exactly 12 months of data per stage."""
        ref = date(2024, 6, 15)
        result = service.compute_monthly_trend(
            transitions=[],
            stage_order=["Discovered", "Sent"],
            reference_date=ref,
        )

        # 12 months × 2 stages = 24 entries
        assert len(result) == 24

    def test_zero_fill_for_inactive_months(self, service: AnalyticsService):
        """Months with no activity get zero-filled entries."""
        ref = date(2024, 6, 15)
        # Only one transition in June
        transitions = [
            StageTransition(
                record_id="r1", stage_name="Discovered",
                entered_at=datetime(2024, 6, 5),
                exited_at=datetime(2024, 6, 6),
                exited_to_next=True,
            ),
        ]

        result = service.compute_monthly_trend(
            transitions=transitions,
            stage_order=["Discovered"],
            reference_date=ref,
        )

        assert len(result) == 12
        # June should have 1 entry, all others 0
        june_entry = next(
            r for r in result if r.month == date(2024, 6, 1)
        )
        assert june_entry.entered_count == 1
        assert june_entry.conversion_rate == 100.0

        # All other months should be zero
        other_months = [r for r in result if r.month != date(2024, 6, 1)]
        assert all(r.entered_count == 0 for r in other_months)
        assert all(r.conversion_rate == 0.0 for r in other_months)



# ─── Z-Test Helper ────────────────────────────────────────────────────────────


class TestZTest:
    def test_identical_proportions(self):
        """Identical proportions should give high p-value (not significant)."""
        p = _z_test_two_proportions(50, 100, 50, 100)
        assert p > 0.90  # Not significant

    def test_very_different_proportions(self):
        """Very different proportions should give low p-value (significant)."""
        p = _z_test_two_proportions(80, 100, 20, 100)
        assert p < 0.01  # Highly significant

    def test_zero_trials(self):
        """Zero trials returns p-value of 1.0."""
        assert _z_test_two_proportions(0, 0, 50, 100) == 1.0
        assert _z_test_two_proportions(50, 100, 0, 0) == 1.0

    def test_all_successes(self):
        """All successes in both groups (pooled = 1.0) returns 1.0."""
        assert _z_test_two_proportions(100, 100, 100, 100) == 1.0


# ─── Voice Segmented Funnel ───────────────────────────────────────────────────


class TestVoiceSegmentedFunnel:
    """Unit tests for compute_voice_segmented_funnel().

    Requirements: 4.2
    """

    def _make_transitions(self, count: int, stage: str) -> list[StageTransition]:
        """Helper to create simple stage transitions."""
        return [
            StageTransition(
                record_id=f"r{i}",
                stage_name=stage,
                entered_at=datetime(2024, 6, 1, 10, 0),
                exited_at=datetime(2024, 6, 2, 10, 0),
                exited_to_next=True,
            )
            for i in range(count)
        ]

    def test_lift_calculation_known_values(self, service: AnalyticsService):
        """Known values produce expected reply rates and lift.

        voice_sends=100, voice_replies=30, no_voice_sends=100, no_voice_replies=20
        → voice_rr=0.3, no_voice_rr=0.2, lift=50.0%
        """
        result = service.compute_voice_segmented_funnel(
            transitions_voice=self._make_transitions(5, "Sent"),
            transitions_no_voice=self._make_transitions(5, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=100,
            voice_replies=30,
            no_voice_sends=100,
            no_voice_replies=20,
        )

        assert result.voice_applied_reply_rate == 0.3
        assert result.no_voice_reply_rate == 0.2
        assert result.lift_percentage == 50.0
        assert result.sample_size_voice == 100
        assert result.sample_size_no_voice == 100

    def test_statistically_significant_large_sample(self, service: AnalyticsService):
        """Large sample with different rates is statistically significant.

        With 1000 sends each and very different reply rates (40% vs 20%),
        the z-test should detect significance at 90% confidence.
        """
        result = service.compute_voice_segmented_funnel(
            transitions_voice=self._make_transitions(5, "Sent"),
            transitions_no_voice=self._make_transitions(5, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=1000,
            voice_replies=400,
            no_voice_sends=1000,
            no_voice_replies=200,
        )

        assert result.is_statistically_significant is True

    def test_not_significant_small_sample(self, service: AnalyticsService):
        """Small sample below AB_MIN_SAMPLE is not statistically significant.

        AB_MIN_SAMPLE is 20, so samples of 10 should skip z-test.
        """
        result = service.compute_voice_segmented_funnel(
            transitions_voice=self._make_transitions(5, "Sent"),
            transitions_no_voice=self._make_transitions(5, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=10,
            voice_replies=5,
            no_voice_sends=10,
            no_voice_replies=2,
        )

        assert result.is_statistically_significant is False

    def test_zero_voice_sends_gives_zero_rate(self, service: AnalyticsService):
        """Zero voice sends results in voice_applied_reply_rate=0.0."""
        result = service.compute_voice_segmented_funnel(
            transitions_voice=[],
            transitions_no_voice=self._make_transitions(5, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=0,
            voice_replies=0,
            no_voice_sends=100,
            no_voice_replies=20,
        )

        assert result.voice_applied_reply_rate == 0.0

    def test_zero_no_voice_sends_gives_zero_rate(self, service: AnalyticsService):
        """Zero no-voice sends results in no_voice_reply_rate=0.0."""
        result = service.compute_voice_segmented_funnel(
            transitions_voice=self._make_transitions(5, "Sent"),
            transitions_no_voice=[],
            stage_order=["Sent"],
            period_days=30,
            voice_sends=100,
            voice_replies=30,
            no_voice_sends=0,
            no_voice_replies=0,
        )

        assert result.no_voice_reply_rate == 0.0

    def test_equal_rates_lift_zero(self, service: AnalyticsService):
        """Equal reply rates produce lift=0.0."""
        result = service.compute_voice_segmented_funnel(
            transitions_voice=self._make_transitions(5, "Sent"),
            transitions_no_voice=self._make_transitions(5, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=100,
            voice_replies=25,
            no_voice_sends=100,
            no_voice_replies=25,
        )

        assert result.lift_percentage == 0.0

    def test_no_voice_rate_zero_lift_none(self, service: AnalyticsService):
        """When no_voice reply rate is zero, lift is None (division by zero)."""
        result = service.compute_voice_segmented_funnel(
            transitions_voice=self._make_transitions(5, "Sent"),
            transitions_no_voice=self._make_transitions(5, "Sent"),
            stage_order=["Sent"],
            period_days=30,
            voice_sends=100,
            voice_replies=30,
            no_voice_sends=100,
            no_voice_replies=0,
        )

        assert result.lift_percentage is None
        assert result.no_voice_reply_rate == 0.0
