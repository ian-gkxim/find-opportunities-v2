"""Analytics Service — computes funnel metrics, A/B outcomes, and ROI tracking.

Pure computation module with no database access, no async, and no I/O.
All methods receive pre-fetched data structures as input and return
computed analytics results.

Requirements 9.1-9.6: Conversion funnel analytics.
Requirements 6.3-6.4, 6.6: A/B testing metrics and winner detection.
Requirements 7.5-7.6: Response rate computation and low-rate recommendations.
Requirements 15.1-15.7: ROI and performance tracking.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum


# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FunnelStage:
    """A single stage in the conversion funnel.

    Attributes:
        stage_name: Name of the pipeline stage.
        entered_count: Number of records that entered this stage.
        exited_count: Number of records that exited to the next stage.
        conversion_rate: (exited / entered) × 100, 1 decimal place.
        dropoff_percentage: (1 - exited/entered) × 100, 1 decimal place.
        avg_days_in_stage: Mean calendar days in stage, 1 decimal place.
        has_insufficient_data: True if fewer than 5 records entered.
    """

    stage_name: str
    entered_count: int
    exited_count: int
    conversion_rate: float
    dropoff_percentage: float
    avg_days_in_stage: float
    has_insufficient_data: bool



@dataclass(frozen=True)
class ConversionAlert:
    """Alert generated when conversion drops significantly.

    Fires when a stage's current conversion rate drops > 20% below
    its 30-day trailing average. Limited to 1 alert per stage per day.

    Attributes:
        stage: Pipeline stage name.
        opportunity_type: The opportunity type this alert applies to.
        current_rate: Current conversion rate for the stage.
        trailing_avg: 30-day trailing average conversion rate.
        drop_percentage: How much the current rate is below the trailing avg (as fraction).
        generated_at: Date the alert was generated.
    """

    stage: str
    opportunity_type: str
    current_rate: float
    trailing_avg: float
    drop_percentage: float
    generated_at: date


@dataclass(frozen=True)
class ABTestResult:
    """Result metrics for a single A/B test variant.

    Attributes:
        variant_id: Variant label (A, B, C, D).
        sends: Total sends for this variant.
        open_rate: opens / sends (0.0-1.0).
        click_rate: clicks / sends (0.0-1.0).
        reply_rate: replies / sends (0.0-1.0).
        is_winner: True if this variant beats all others by ≥2pp at 90% confidence.
        is_inconclusive: True if all variants have ≥100 sends and no winner found.
    """

    variant_id: str
    sends: int
    open_rate: float
    click_rate: float
    reply_rate: float
    is_winner: bool
    is_inconclusive: bool



@dataclass(frozen=True)
class ChannelEffectiveness:
    """Effectiveness metrics for a discovery source / sequence / beneficiary breakdown.

    Attributes:
        source: Discovery source name.
        sequence_name: Sequence name (None if not applicable).
        beneficiary: Beneficiary id.
        sends: Total touchpoints sent.
        replies: Total replies received.
        meetings: Total meetings booked.
        outcomes: Total positive outcomes.
        total_entered: Total prospects entered into outreach.
        response_rate: replies / sends.
        meeting_rate: meetings / sends.
        conversion_rate: outcomes / total_entered.
        is_low_confidence: True if fewer than 10 prospects sent outreach.
    """

    source: str
    sequence_name: str | None
    beneficiary: str
    sends: int
    replies: int
    meetings: int
    outcomes: int
    total_entered: int
    response_rate: float
    meeting_rate: float
    conversion_rate: float
    is_low_confidence: bool



@dataclass(frozen=True)
class EffortMetrics:
    """Monthly effort metrics summary.

    Attributes:
        month: The calendar month (first day of month).
        discovered: Total prospects discovered.
        sent: Total outreach touchpoints sent.
        responses: Total responses received.
        outcomes: Total positive outcomes (Accepted or Won).
    """

    month: date
    discovered: int
    sent: int
    responses: int
    outcomes: int


@dataclass(frozen=True)
class OutcomeAttribution:
    """Attribution for a positive outcome.

    Attributes:
        pipeline_record_id: The pipeline record that achieved the outcome.
        discovery_source: The earliest discovery source.
        sequence_id: The sequence that generated the first reply (if any).
        variant_id: The variant that generated the first reply (if any).
    """

    pipeline_record_id: str
    discovery_source: str
    sequence_id: str | None
    variant_id: str | None



@dataclass(frozen=True)
class LowResponseRecommendation:
    """Recommendation triggered when response rate is too low.

    Generated when a sequence has ≥ 50 sends and < 2% response rate.

    Attributes:
        sequence_id: The underperforming sequence.
        sends: Total sends.
        response_rate: Current response rate.
        message: Recommendation message.
    """

    sequence_id: str
    sends: int
    response_rate: float
    message: str


@dataclass(frozen=True)
class MonthlyTrend:
    """Monthly trend data point for a funnel stage.

    Attributes:
        month: First day of the calendar month.
        stage_name: Pipeline stage name.
        entered_count: Records entering this stage in this month.
        conversion_rate: Stage conversion rate for this month.
    """

    month: date
    stage_name: str
    entered_count: int
    conversion_rate: float



# ─── Input Data Structures ────────────────────────────────────────────────────
# These represent pre-fetched records passed into the analytics service.


@dataclass
class PipelineRecord:
    """A pipeline record with stage transition data.

    Attributes:
        id: Unique record identifier.
        prospect_id: Associated prospect.
        opportunity_type: Opportunity type id.
        beneficiary: Beneficiary id.
        current_status: Current pipeline stage name.
        discovery_source: Original discovery source.
        entered_stage_at: When the record entered its current stage.
        exited_stage_at: When the record exited its current stage (None if still in stage).
        created_at: When the record was first created.
        outcome_date: When the final outcome occurred (None if not terminal).
        first_response_source: Sequence + variant that got first reply.
    """

    id: str
    prospect_id: str
    opportunity_type: str
    beneficiary: str
    current_status: str
    discovery_source: str
    entered_stage_at: datetime
    exited_stage_at: datetime | None = None
    created_at: datetime | None = None
    outcome_date: datetime | None = None
    first_response_source: str | None = None



@dataclass
class StageTransition:
    """A record's transition between stages for funnel computation.

    Attributes:
        record_id: Pipeline record id.
        stage_name: The stage this transition is about.
        entered_at: When the record entered the stage.
        exited_at: When the record exited the stage (None if still in stage).
        exited_to_next: True if the record moved to the next stage in the funnel.
    """

    record_id: str
    stage_name: str
    entered_at: datetime
    exited_at: datetime | None = None
    exited_to_next: bool = False


@dataclass
class VariantData:
    """Pre-fetched variant metrics for A/B test computation.

    Attributes:
        variant_id: Label (A, B, C, D).
        sends: Number of sends.
        opens: Number of opens.
        clicks: Number of clicks.
        replies: Number of replies.
    """

    variant_id: str
    sends: int
    opens: int
    clicks: int
    replies: int



@dataclass
class ChannelData:
    """Pre-fetched channel data for effectiveness computation.

    Attributes:
        source: Discovery source.
        sequence_name: Sequence name (None if not applicable).
        beneficiary: Beneficiary id.
        sends: Total touchpoints sent.
        replies: Total replies received.
        meetings: Total meetings booked.
        outcomes: Total positive outcomes.
        total_entered: Total prospects entered into outreach.
    """

    source: str
    sequence_name: str | None
    beneficiary: str
    sends: int
    replies: int
    meetings: int
    outcomes: int
    total_entered: int


@dataclass
class DiscoveryEvent:
    """A discovery event for source attribution.

    Attributes:
        prospect_id: The prospect discovered.
        source: Discovery source name.
        discovered_at: When it was discovered.
    """

    prospect_id: str
    source: str
    discovered_at: datetime



@dataclass
class SequenceResponse:
    """Information about which sequence/variant generated a reply.

    Attributes:
        pipeline_record_id: The pipeline record.
        sequence_id: The sequence used.
        variant_id: The variant that got the reply (if any).
        replied_at: When the reply was received.
    """

    pipeline_record_id: str
    sequence_id: str
    variant_id: str | None
    replied_at: datetime


@dataclass
class ConversionRateSnapshot:
    """Historical conversion rate snapshot for trailing average computation.

    Attributes:
        stage: Pipeline stage name.
        opportunity_type: Opportunity type id.
        rate: Conversion rate at this snapshot.
        snapshot_date: Date of the snapshot.
    """

    stage: str
    opportunity_type: str
    rate: float
    snapshot_date: date



# ─── Statistical Helpers ──────────────────────────────────────────────────────


def _z_test_two_proportions(
    successes_a: int,
    trials_a: int,
    successes_b: int,
    trials_b: int,
) -> float:
    """Compute the p-value for a two-proportion z-test (two-tailed).

    Tests whether the proportion successes_a/trials_a is significantly
    different from successes_b/trials_b.

    Args:
        successes_a: Number of successes in sample A.
        trials_a: Total trials in sample A.
        successes_b: Number of successes in sample B.
        trials_b: Total trials in sample B.

    Returns:
        The two-tailed p-value. Returns 1.0 if computation is not possible
        (e.g., zero trials or pooled proportion is 0 or 1).
    """
    if trials_a == 0 or trials_b == 0:
        return 1.0

    p_a = successes_a / trials_a
    p_b = successes_b / trials_b

    # Pooled proportion
    p_pool = (successes_a + successes_b) / (trials_a + trials_b)

    # Avoid division by zero when pooled proportion is 0 or 1
    if p_pool == 0.0 or p_pool == 1.0:
        return 1.0

    # Standard error
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / trials_a + 1.0 / trials_b))

    if se == 0.0:
        return 1.0

    # Z-statistic
    z = (p_a - p_b) / se

    # Two-tailed p-value using the error function
    p_value = 2.0 * (1.0 - _normal_cdf(abs(z)))
    return p_value



def _normal_cdf(x: float) -> float:
    """Compute the standard normal CDF using the error function.

    Args:
        x: The z-value.

    Returns:
        P(Z <= x) for a standard normal distribution.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ─── Analytics Service ────────────────────────────────────────────────────────


class AnalyticsService:
    """Computes funnel metrics, A/B outcomes, and ROI tracking.

    This is a pure computation class with no I/O, no database access,
    and no async operations. It receives pre-fetched data structures
    and returns computed analytics results.

    Key behaviors:
    - Funnel: conversion_rate = (exited_to_next / entered) × 100, 1dp
    - Average time in stage: arithmetic mean of (exit - entry) in calendar days, 1dp
    - Conversion alerts: fire when drop > 20% below 30-day trailing avg, max 1/stage/day
    - A/B: winner if reply_rate exceeds all others by ≥2pp at 90% confidence (z-test)
    - A/B: inconclusive after all variants reach 100 sends each with no winner
    - Channel: response_rate = replies/sends, meeting_rate = meetings/sends,
              conversion_rate = outcomes/total_entered
    - Low confidence: fewer than 10 prospects
    - Insufficient data: fewer than 5 records → indicator + alert exclusion
    - Monthly trend: exactly 12 months with zero-fill for inactive months
    """

    MIN_RECORDS_FOR_ALERT = 5
    ALERT_DROP_THRESHOLD = 0.20  # 20% below trailing avg
    AB_MIN_SAMPLE = 20
    AB_WINNER_MARGIN = 0.02  # 2 percentage points
    AB_CONFIDENCE = 0.90  # 90% confidence
    AB_INCONCLUSIVE_THRESHOLD = 100  # sends per variant
    LOW_RESPONSE_RATE = 0.02  # 2%
    LOW_RESPONSE_MIN_SENDS = 50
    LOW_CONFIDENCE_THRESHOLD = 10


    def compute_funnel(
        self,
        transitions: list[StageTransition],
        stage_order: list[str],
        period_days: int,
        reference_date: date | None = None,
    ) -> list[FunnelStage]:
        """Compute stage-to-stage conversion funnel.

        Args:
            transitions: Pre-fetched stage transition records within the period.
            stage_order: Ordered list of stage names defining the funnel.
            period_days: Time period to consider (7, 30, or 90 days).
            reference_date: End date for the period (defaults to today).

        Returns:
            List of FunnelStage objects, one per stage in stage_order.
        """
        if reference_date is None:
            reference_date = date.today()

        cutoff = datetime(
            reference_date.year, reference_date.month, reference_date.day
        ) - timedelta(days=period_days)

        # Filter transitions within the period
        period_transitions = [
            t for t in transitions if t.entered_at >= cutoff
        ]

        stages: list[FunnelStage] = []
        for stage_name in stage_order:
            stage_trans = [
                t for t in period_transitions if t.stage_name == stage_name
            ]
            entered = len(stage_trans)
            exited = sum(1 for t in stage_trans if t.exited_to_next)

            # Conversion rate: (exited / entered) × 100, 1 decimal place
            if entered > 0:
                conv_rate = round((exited / entered) * 100, 1)
                dropoff = round((1.0 - exited / entered) * 100, 1)
            else:
                conv_rate = 0.0
                dropoff = 0.0

            # Average days in stage: mean of (exit - entry) for completed transitions
            completed = [
                t for t in stage_trans if t.exited_at is not None
            ]
            if completed:
                total_days = sum(
                    (t.exited_at - t.entered_at).total_seconds() / 86400.0
                    for t in completed
                )
                avg_days = round(total_days / len(completed), 1)
            else:
                avg_days = 0.0

            has_insufficient = entered < self.MIN_RECORDS_FOR_ALERT

            stages.append(FunnelStage(
                stage_name=stage_name,
                entered_count=entered,
                exited_count=exited,
                conversion_rate=conv_rate,
                dropoff_percentage=dropoff,
                avg_days_in_stage=avg_days,
                has_insufficient_data=has_insufficient,
            ))

        return stages


    def compute_conversion_alerts(
        self,
        current_rates: dict[tuple[str, str], float],
        snapshots: list[ConversionRateSnapshot],
        existing_alerts_today: set[tuple[str, str]],
        today: date | None = None,
    ) -> list[ConversionAlert]:
        """Generate alerts for stages dropping >20% below 30-day trailing average.

        Args:
            current_rates: Map of (stage, opportunity_type) → current conversion rate.
            snapshots: Historical rate snapshots for trailing average computation.
            existing_alerts_today: Set of (stage, opportunity_type) that already
                have an alert today (to enforce max 1 alert/stage/day).
            today: Override for current date (defaults to date.today()).

        Returns:
            List of ConversionAlert objects for stages that qualify.
        """
        if today is None:
            today = date.today()

        alerts: list[ConversionAlert] = []
        trailing_window = today - timedelta(days=30)

        for (stage, opp_type), current_rate in current_rates.items():
            # Skip if alert already generated today for this stage
            if (stage, opp_type) in existing_alerts_today:
                continue

            # Compute 30-day trailing average for this stage/opp_type
            relevant_snapshots = [
                s for s in snapshots
                if s.stage == stage
                and s.opportunity_type == opp_type
                and s.snapshot_date >= trailing_window
                and s.snapshot_date < today
            ]

            if not relevant_snapshots:
                continue

            trailing_avg = sum(s.rate for s in relevant_snapshots) / len(
                relevant_snapshots
            )

            # Skip if trailing average is zero (can't compute drop percentage)
            if trailing_avg == 0.0:
                continue

            # Compute drop as a fraction
            drop = (trailing_avg - current_rate) / trailing_avg

            # Fire alert if drop > 20%
            if drop > self.ALERT_DROP_THRESHOLD:
                alerts.append(ConversionAlert(
                    stage=stage,
                    opportunity_type=opp_type,
                    current_rate=current_rate,
                    trailing_avg=trailing_avg,
                    drop_percentage=round(drop, 4),
                    generated_at=today,
                ))

        return alerts


    def compute_ab_results(
        self,
        variants: list[VariantData],
    ) -> list[ABTestResult]:
        """Compute A/B test metrics per variant with winner detection.

        Winner detection logic:
        - Min 20 sends before computing metrics for any variant.
        - Winner: reply_rate exceeds ALL other variants by ≥ 2pp with 90% confidence.
        - Inconclusive: all variants have ≥ 100 sends each and no winner found.

        Args:
            variants: Pre-fetched variant metrics data.

        Returns:
            List of ABTestResult objects, one per variant.
        """
        if not variants:
            return []

        # Check if all variants meet minimum sample size
        all_meet_min = all(v.sends >= self.AB_MIN_SAMPLE for v in variants)

        # Compute reply rates
        reply_rates: dict[str, float] = {}
        for v in variants:
            if v.sends > 0:
                reply_rates[v.variant_id] = v.replies / v.sends
            else:
                reply_rates[v.variant_id] = 0.0

        # Determine winner
        winner_id: str | None = None
        if all_meet_min and len(variants) >= 2:
            winner_id = self._detect_ab_winner(variants, reply_rates)

        # Determine if inconclusive
        all_above_inconclusive = all(
            v.sends >= self.AB_INCONCLUSIVE_THRESHOLD for v in variants
        )
        is_inconclusive = all_above_inconclusive and winner_id is None

        # Build results
        results: list[ABTestResult] = []
        for v in variants:
            sends = v.sends
            open_rate = v.opens / sends if sends > 0 else 0.0
            click_rate = v.clicks / sends if sends > 0 else 0.0
            reply_rate = reply_rates[v.variant_id]

            results.append(ABTestResult(
                variant_id=v.variant_id,
                sends=sends,
                open_rate=round(open_rate, 4),
                click_rate=round(click_rate, 4),
                reply_rate=round(reply_rate, 4),
                is_winner=(v.variant_id == winner_id),
                is_inconclusive=is_inconclusive,
            ))

        return results


    def _detect_ab_winner(
        self,
        variants: list[VariantData],
        reply_rates: dict[str, float],
    ) -> str | None:
        """Detect if any variant is a winner based on margin and confidence.

        A variant wins if:
        1. Its reply rate exceeds every other variant by ≥ 2 percentage points.
        2. The difference is statistically significant at 90% confidence (z-test).

        Args:
            variants: Variant data with sends/replies.
            reply_rates: Pre-computed reply rates per variant.

        Returns:
            The winner variant_id, or None if no winner.
        """
        confidence_threshold = 1.0 - self.AB_CONFIDENCE  # p-value threshold = 0.10

        for candidate in variants:
            candidate_rate = reply_rates[candidate.variant_id]
            is_winner = True

            for other in variants:
                if other.variant_id == candidate.variant_id:
                    continue

                other_rate = reply_rates[other.variant_id]

                # Must exceed by at least 2 percentage points
                if candidate_rate - other_rate < self.AB_WINNER_MARGIN:
                    is_winner = False
                    break

                # Must be statistically significant at 90% confidence
                p_value = _z_test_two_proportions(
                    successes_a=candidate.replies,
                    trials_a=candidate.sends,
                    successes_b=other.replies,
                    trials_b=other.sends,
                )
                if p_value > confidence_threshold:
                    is_winner = False
                    break

            if is_winner:
                return candidate.variant_id

        return None


    def compute_channel_effectiveness(
        self,
        channel_data: list[ChannelData],
    ) -> list[ChannelEffectiveness]:
        """Compute response/meeting/conversion rates by channel.

        response_rate = replies / sends
        meeting_rate = meetings / sends
        conversion_rate = outcomes / total_entered
        Low confidence indicator when < 10 prospects sent outreach.

        Args:
            channel_data: Pre-fetched channel breakdown data.

        Returns:
            List of ChannelEffectiveness objects.
        """
        results: list[ChannelEffectiveness] = []

        for ch in channel_data:
            is_low_confidence = ch.sends < self.LOW_CONFIDENCE_THRESHOLD

            if is_low_confidence:
                # Suppress percentage-based rates for low confidence
                response_rate = 0.0
                meeting_rate = 0.0
                conversion_rate = 0.0
            else:
                response_rate = (
                    ch.replies / ch.sends if ch.sends > 0 else 0.0
                )
                meeting_rate = (
                    ch.meetings / ch.sends if ch.sends > 0 else 0.0
                )
                conversion_rate = (
                    ch.outcomes / ch.total_entered
                    if ch.total_entered > 0
                    else 0.0
                )

            results.append(ChannelEffectiveness(
                source=ch.source,
                sequence_name=ch.sequence_name,
                beneficiary=ch.beneficiary,
                sends=ch.sends,
                replies=ch.replies,
                meetings=ch.meetings,
                outcomes=ch.outcomes,
                total_entered=ch.total_entered,
                response_rate=round(response_rate, 4),
                meeting_rate=round(meeting_rate, 4),
                conversion_rate=round(conversion_rate, 4),
                is_low_confidence=is_low_confidence,
            ))

        return results


    def compute_effort_metrics(
        self,
        discovered: list[datetime],
        sent: list[datetime],
        responses: list[datetime],
        outcomes: list[datetime],
        month: date,
    ) -> EffortMetrics:
        """Compute monthly effort metrics: total counts for a calendar month.

        Counts events that fall within the specified calendar month.

        Args:
            discovered: Timestamps of discovery events.
            sent: Timestamps of send events.
            responses: Timestamps of response events.
            outcomes: Timestamps of positive outcome events (Accepted/Won).
            month: Any date within the target month (uses year+month).

        Returns:
            EffortMetrics for the specified month.
        """
        month_start = date(month.year, month.month, 1)
        if month.month == 12:
            month_end = date(month.year + 1, 1, 1)
        else:
            month_end = date(month.year, month.month + 1, 1)

        def count_in_month(events: list[datetime]) -> int:
            return sum(
                1 for e in events
                if month_start <= e.date() < month_end
            )

        return EffortMetrics(
            month=month_start,
            discovered=count_in_month(discovered),
            sent=count_in_month(sent),
            responses=count_in_month(responses),
            outcomes=count_in_month(outcomes),
        )


    def attribute_outcome(
        self,
        pipeline_record_id: str,
        discovery_events: list[DiscoveryEvent],
        sequence_responses: list[SequenceResponse],
    ) -> OutcomeAttribution:
        """Attribute a positive outcome to the earliest discovery source.

        Attribution logic:
        - Discovery source: the source with the earliest discovery date.
        - Sequence/variant: from the first reply received for this record.

        Args:
            pipeline_record_id: The pipeline record with a positive outcome.
            discovery_events: All discovery events for this prospect (may be
                from multiple sources).
            sequence_responses: All sequence responses for this pipeline record.

        Returns:
            OutcomeAttribution with earliest source and first reply details.
        """
        # Find earliest discovery source
        if not discovery_events:
            discovery_source = "unknown"
        else:
            earliest = min(discovery_events, key=lambda e: e.discovered_at)
            discovery_source = earliest.source

        # Find the sequence/variant that generated the first reply
        sequence_id: str | None = None
        variant_id: str | None = None

        relevant_responses = [
            r for r in sequence_responses
            if r.pipeline_record_id == pipeline_record_id
        ]
        if relevant_responses:
            first_reply = min(relevant_responses, key=lambda r: r.replied_at)
            sequence_id = first_reply.sequence_id
            variant_id = first_reply.variant_id

        return OutcomeAttribution(
            pipeline_record_id=pipeline_record_id,
            discovery_source=discovery_source,
            sequence_id=sequence_id,
            variant_id=variant_id,
        )


    def compute_low_response_recommendations(
        self,
        sequences: list[tuple[str, int, int]],
    ) -> list[LowResponseRecommendation]:
        """Identify sequences with low response rates needing revision.

        A recommendation fires when:
        - Sequence has ≥ 50 successfully delivered sends
        - Response rate is < 2%

        Args:
            sequences: List of (sequence_id, total_sends, total_replies).

        Returns:
            List of LowResponseRecommendation for qualifying sequences.
        """
        recommendations: list[LowResponseRecommendation] = []

        for seq_id, sends, replies in sequences:
            if sends < self.LOW_RESPONSE_MIN_SENDS:
                continue

            response_rate = replies / sends if sends > 0 else 0.0

            if response_rate < self.LOW_RESPONSE_RATE:
                recommendations.append(LowResponseRecommendation(
                    sequence_id=seq_id,
                    sends=sends,
                    response_rate=round(response_rate, 4),
                    message=(
                        f"Sequence has {sends} sends with only "
                        f"{response_rate * 100:.1f}% response rate. "
                        f"Consider revising messaging or targeting."
                    ),
                ))

        return recommendations


    def compute_monthly_trend(
        self,
        transitions: list[StageTransition],
        stage_order: list[str],
        reference_date: date | None = None,
    ) -> list[MonthlyTrend]:
        """Compute 12-month trend with zero-fill for inactive months.

        Produces exactly 12 months of data per stage, filling zeros
        for months with no activity.

        Args:
            transitions: All stage transitions for the trailing 12 months.
            stage_order: Ordered list of stage names.
            reference_date: End date for the 12-month window (defaults to today).

        Returns:
            List of MonthlyTrend objects (12 per stage, ordered chronologically).
        """
        if reference_date is None:
            reference_date = date.today()

        # Generate list of 12 months ending with reference_date's month
        months: list[date] = []
        current_month = date(reference_date.year, reference_date.month, 1)
        for i in range(12):
            # Go back i months from current_month
            month_offset = current_month.month - 1 - i
            year_offset = current_month.year + (month_offset // 12)
            month_val = (month_offset % 12) + 1
            months.append(date(year_offset, month_val, 1))
        months.reverse()  # Chronological order

        results: list[MonthlyTrend] = []

        for month_start in months:
            if month_start.month == 12:
                month_end = date(month_start.year + 1, 1, 1)
            else:
                month_end = date(month_start.year, month_start.month + 1, 1)

            for stage_name in stage_order:
                # Count entries for this stage in this month
                stage_trans = [
                    t for t in transitions
                    if t.stage_name == stage_name
                    and t.entered_at.date() >= month_start
                    and t.entered_at.date() < month_end
                ]
                entered = len(stage_trans)
                exited = sum(1 for t in stage_trans if t.exited_to_next)

                if entered > 0:
                    conv_rate = round((exited / entered) * 100, 1)
                else:
                    conv_rate = 0.0

                results.append(MonthlyTrend(
                    month=month_start,
                    stage_name=stage_name,
                    entered_count=entered,
                    conversion_rate=conv_rate,
                ))

        return results
