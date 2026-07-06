"""API routes for analytics and reporting.

Requirements 9.1, 9.3, 15.2, 15.7:
- GET /analytics/funnel — get funnel data with period selection
- GET /analytics/ab-results — get A/B test results for a sequence step
- GET /analytics/channel-effectiveness — get channel effectiveness metrics
- GET /analytics/effort — get monthly effort metrics
- GET /analytics/trends — get 12-month trend data
"""

from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["analytics"])


# --- Request/Response Schemas ---


class FunnelStageData(BaseModel):
    """Data for a single funnel stage."""

    stage_name: str
    entered_count: int
    exited_count: int
    dropoff_percentage: float = Field(..., ge=0, le=100)
    avg_days_in_stage: float
    has_insufficient_data: bool = Field(
        default=False, description="True if fewer than 5 records in period"
    )


class FunnelResponse(BaseModel):
    """Conversion funnel data."""

    opportunity_type: str
    beneficiary: str
    period_days: int
    stages: list[FunnelStageData]


class ABVariantResult(BaseModel):
    """A/B test metrics for a single variant."""

    variant_id: str = Field(..., description="Variant label (A, B, C, D)")
    sends: int
    open_rate: float = Field(..., ge=0, le=1)
    click_rate: float = Field(..., ge=0, le=1)
    reply_rate: float = Field(..., ge=0, le=1)
    is_winner: bool = False
    is_inconclusive: bool = False


class ABResultsResponse(BaseModel):
    """A/B test results for a sequence step."""

    sequence_id: UUID
    step_order: int
    variants: list[ABVariantResult]
    test_status: str = Field(
        ..., description="Status: active, winner_found, inconclusive"
    )


class ChannelEffectivenessEntry(BaseModel):
    """Effectiveness metrics for a single channel/source/sequence combo."""

    source: str
    sequence_name: str | None = None
    beneficiary: str
    response_rate: float = Field(..., ge=0, le=1)
    meeting_rate: float = Field(..., ge=0, le=1)
    conversion_rate: float = Field(..., ge=0, le=1)
    is_low_confidence: bool = Field(
        default=False, description="True if fewer than 10 prospects"
    )


class ChannelEffectivenessResponse(BaseModel):
    """Channel effectiveness metrics."""

    period_days: int
    entries: list[ChannelEffectivenessEntry]


class EffortMetricsResponse(BaseModel):
    """Monthly effort metrics."""

    month: str = Field(..., description="Month in YYYY-MM format")
    total_discovered: int
    total_touchpoints_sent: int
    total_responses: int
    total_positive_outcomes: int


class MonthlyTrendEntry(BaseModel):
    """Trend data for a single month."""

    month: str = Field(..., description="Month in YYYY-MM format")
    stage_name: str
    entered_count: int
    conversion_rate: float = Field(..., ge=0, le=1)


class TrendsResponse(BaseModel):
    """12-month trend data."""

    months: list[MonthlyTrendEntry]
    period_months: int = 12


# --- Routes ---


@router.get("/analytics/funnel", response_model=FunnelResponse)
async def get_funnel_data(
    period_days: int = Query(
        default=30,
        description="Time period: 7, 30, or 90 days",
    ),
    opportunity_type: str = Query(..., description="Opportunity type to analyze"),
    beneficiary: str = Query(..., description="Beneficiary to analyze"),
) -> FunnelResponse:
    """Get conversion funnel data for a specific opportunity type and beneficiary.

    Shows stage-to-stage conversion rates, drop-off percentages, and
    average time in each stage. Stages with fewer than 5 records are
    flagged with 'insufficient data'.
    """
    # Stub: In production, delegates to AnalyticsService.compute_funnel()
    return FunnelResponse(
        opportunity_type=opportunity_type,
        beneficiary=beneficiary,
        period_days=period_days,
        stages=[],
    )


@router.get("/analytics/ab-results", response_model=ABResultsResponse)
async def get_ab_results(
    sequence_id: UUID = Query(..., description="Sequence ID"),
    step_order: int = Query(..., ge=1, le=10, description="Step order number"),
) -> ABResultsResponse:
    """Get A/B test results for a specific sequence step.

    Includes per-variant metrics (open rate, click rate, reply rate)
    and winner/inconclusive determination.
    """
    # Stub: In production, delegates to AnalyticsService.compute_ab_results()
    return ABResultsResponse(
        sequence_id=sequence_id,
        step_order=step_order,
        variants=[],
        test_status="active",
    )


@router.get("/analytics/channel-effectiveness", response_model=ChannelEffectivenessResponse)
async def get_channel_effectiveness(
    period_days: int = Query(default=30, description="Time period in days"),
) -> ChannelEffectivenessResponse:
    """Get channel effectiveness metrics broken down by source, sequence, and beneficiary.

    Entries with fewer than 10 prospects are flagged as 'low confidence'.
    """
    # Stub: In production, delegates to AnalyticsService.compute_channel_effectiveness()
    return ChannelEffectivenessResponse(
        period_days=period_days,
        entries=[],
    )


@router.get("/analytics/effort", response_model=EffortMetricsResponse)
async def get_effort_metrics(
    month: str = Query(
        ...,
        description="Month in YYYY-MM format",
        pattern=r"^\d{4}-\d{2}$",
    ),
) -> EffortMetricsResponse:
    """Get monthly effort metrics: discovered, sent, responses, outcomes."""
    # Stub: In production, delegates to AnalyticsService.compute_effort_metrics()
    return EffortMetricsResponse(
        month=month,
        total_discovered=0,
        total_touchpoints_sent=0,
        total_responses=0,
        total_positive_outcomes=0,
    )


@router.get("/analytics/trends", response_model=TrendsResponse)
async def get_trends(
    opportunity_type: str | None = Query(default=None, description="Filter by opportunity type"),
    beneficiary: str | None = Query(default=None, description="Filter by beneficiary"),
) -> TrendsResponse:
    """Get 12-month trend data showing funnel stage counts and conversion rates.

    Displays zero for months with no activity.
    """
    # Stub: In production, queries funnel_snapshots for trailing 12 months
    return TrendsResponse(
        months=[],
        period_months=12,
    )
