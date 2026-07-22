"""API routes for capability gap analytics.

Requirements 3.1, 3.3, 3.4:
- GET /gap-analysis/heatmap/{beneficiary_id} — latest gap heatmap with opportunity_type filter
- POST /gap-analysis/on-demand — trigger on-demand gap analysis (120s timeout)
- GET /gap-analysis/recommendation/{capability_name} — LLM learning recommendation
- GET /gap-analysis/heatmap/{beneficiary_id}/history — historical heatmap summaries
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.gap_analyzer import GapAnalyzer, GapAnalysisConfig
from app.core.gap_errors import OnDemandTimeoutError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gap-analysis", tags=["gap-analysis"])


# --- Request/Response Schemas ---


class GapEntryResponse(BaseModel):
    """Single gap entry in the heatmap response."""

    canonical_name: str
    classification: str = Field(..., description="'hard' or 'soft'")
    opportunity_count: int = Field(..., ge=0)
    blocked_pipeline_value: float = Field(..., ge=0)
    is_single_blocker: bool
    weighted_rank_score: float = Field(..., ge=0)
    trend: str | None = Field(
        default=None, description="'new', 'growing', 'shrinking', or 'resolved'"
    )


class HeatmapResponse(BaseModel):
    """Response model for the gap heatmap endpoint."""

    id: str
    beneficiary_id: str
    generated_at: datetime
    analysis_window_days: int
    gaps: list[GapEntryResponse]
    total_opportunities_analyzed: int = Field(..., ge=0)
    total_blocked_value: float = Field(..., ge=0)


class HeatmapHistorySummary(BaseModel):
    """Summary of a historical heatmap for trend tracking."""

    id: str
    beneficiary_id: str
    generated_at: datetime
    analysis_window_days: int
    total_opportunities_analyzed: int = Field(..., ge=0)
    total_blocked_value: float = Field(..., ge=0)
    top_gap: str | None = Field(
        default=None, description="Canonical name of the #1 ranked gap"
    )
    gap_count: int = Field(..., ge=0, description="Number of gaps in this heatmap")


class OnDemandRequest(BaseModel):
    """Request body for on-demand gap analysis."""

    opportunity_url: str | None = Field(
        default=None, description="URL of the opportunity to analyze"
    )
    pipeline_record_id: str | None = Field(
        default=None, description="Existing pipeline record ID to analyze"
    )
    consultant_id: str = Field(..., description="Beneficiary ID to diff against")


class OnDemandResponse(BaseModel):
    """Response model for on-demand gap analysis."""

    opportunity_id: str | None
    opportunity_url: str | None
    consultant_id: str
    required_gaps: list[GapEntryResponse]
    preferred_gaps: list[GapEntryResponse]
    total_required: int = Field(..., ge=0)
    total_matched: int = Field(..., ge=0)
    gap_percentage: float = Field(..., ge=0, le=100)
    generated_at: datetime


class LearningRecommendationResponse(BaseModel):
    """Response model for learning recommendation."""

    canonical_name: str
    resources: list[str]
    effort_estimate: str = Field(
        ..., description="Rough effort estimate, e.g. '2-4 weeks part-time'"
    )
    advisory_note: str = Field(
        ..., description="Disclaimer that this is advisory only"
    )
    generated_at: datetime


# --- Helper: Build GapAnalyzer instance via FastAPI dependency injection ---


def get_gap_analyzer(request: Request) -> GapAnalyzer:
    """FastAPI dependency that provides a configured GapAnalyzer instance.

    Wires shared resources from the application state:
    - config: GapAnalysisConfig with defaults
    - llm_router: LLM routing service (from app.state, may be None during tests)
    - schema_registry: Schema registry (from app.state, may be None during tests)
    - db_session: Async database session (from app.state, may be None during tests)
    - redis_client: Redis client (from app.state, may be None during tests)
    - ws_manager: WebSocket manager (from app.state, may be None during tests)

    Falls back to None for any dependency not yet initialized in app state,
    enabling graceful degradation and stub-based testing.
    """
    app_state = request.app.state

    config = getattr(app_state, "gap_analysis_config", None) or GapAnalysisConfig()
    llm_router = getattr(app_state, "llm_router", None)
    schema_registry = getattr(app_state, "schema_registry", None)
    db_session = getattr(app_state, "db_session", None)
    redis_client = getattr(app_state, "redis_client", None)
    ws_manager = getattr(app_state, "ws_manager", None)

    return GapAnalyzer(
        config=config,
        llm_router=llm_router,
        schema_registry=schema_registry,
        db_session=db_session,
        redis_client=redis_client,
        ws_manager=ws_manager,
    )


# --- Routes ---


@router.get("/heatmap/{beneficiary_id}", response_model=HeatmapResponse)
async def get_heatmap(
    beneficiary_id: str,
    opportunity_type: str | None = Query(
        default=None, description="Filter by opportunity type"
    ),
    analyzer: GapAnalyzer = Depends(get_gap_analyzer),
) -> HeatmapResponse:
    """Retrieve the latest gap heatmap for a Beneficiary.

    Returns top 25 gaps ranked by blocked pipeline value (descending).
    Supports optional filtering by opportunity type.

    Queries the gap_heatmaps table for the most recent heatmap matching
    the beneficiary_id, optionally filtered by opportunity_type_filter.
    Joins gap_heatmap_entries to load ranked gap entries.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.gap_analytics import (
        GapHeatmap,
        GapHeatmapEntry,
    )

    # In production, DB session would come from dependency injection.
    # For now, use stub pattern consistent with other route files.
    # When wired (task 11.1), this will use an injected async session.

    # Stub: queries gap_heatmaps for the most recent heatmap for this
    # beneficiary, optionally filtered by opportunity_type.
    # Returns 404 if no heatmap exists.
    raise HTTPException(
        status_code=404,
        detail=f"No heatmap found for beneficiary '{beneficiary_id}'",
    )


@router.post("/on-demand", response_model=OnDemandResponse)
async def analyze_on_demand(
    request: OnDemandRequest,
    analyzer: GapAnalyzer = Depends(get_gap_analyzer),
) -> OnDemandResponse:
    """Trigger on-demand gap analysis for a single opportunity.

    Must complete within 120 seconds. Provide either opportunity_url
    or pipeline_record_id (at least one required, not both).

    Delegates to GapAnalyzer.analyze_on_demand() wrapped in
    asyncio.wait_for with a 120-second timeout.
    """
    from app.core.gap_errors import GapAnalysisError

    # Validate that exactly one source is provided
    if request.opportunity_url is None and request.pipeline_record_id is None:
        raise HTTPException(
            status_code=422,
            detail="Must provide either 'opportunity_url' or 'pipeline_record_id'",
        )
    if request.opportunity_url is not None and request.pipeline_record_id is not None:
        raise HTTPException(
            status_code=422,
            detail="Provide only one of 'opportunity_url' or 'pipeline_record_id', not both",
        )

    # 1. Load opportunity text from DB by pipeline_record_id or fetch from URL
    try:
        opportunity_text = await analyzer.load_opportunity_text_for_on_demand(
            pipeline_record_id=request.pipeline_record_id,
            opportunity_url=request.opportunity_url,
        )
    except GapAnalysisError as exc:
        # Map specific error conditions to HTTP status codes
        msg = str(exc.message) if hasattr(exc, "message") else str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        if "too short" in msg.lower():
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=422, detail=msg)

    # 2. Call GapAnalyzer.analyze_on_demand() (includes 120s timeout enforcement)
    try:
        report = await analyzer.analyze_on_demand(
            opportunity_text=opportunity_text,
            consultant_id=request.consultant_id,
            opportunity_id=request.pipeline_record_id,
            opportunity_url=request.opportunity_url,
        )
    except OnDemandTimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                "On-demand gap analysis timed out. "
                "Please try again or use a shorter opportunity description."
            ),
        )
    except GapAnalysisError as exc:
        msg = str(exc.message) if hasattr(exc, "message") else str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=500, detail=msg)

    # 3. Convert OnDemandGapReport to OnDemandResponse
    return OnDemandResponse(
        opportunity_id=report.opportunity_id,
        opportunity_url=report.opportunity_url,
        consultant_id=report.consultant_id,
        required_gaps=[
            GapEntryResponse(
                canonical_name=g.canonical_name,
                classification=g.classification.value,
                opportunity_count=g.opportunity_count,
                blocked_pipeline_value=g.blocked_pipeline_value,
                is_single_blocker=g.is_single_blocker,
                weighted_rank_score=g.weighted_rank_score,
                trend=g.trend.value if g.trend else None,
            )
            for g in report.required_gaps
        ],
        preferred_gaps=[
            GapEntryResponse(
                canonical_name=g.canonical_name,
                classification=g.classification.value,
                opportunity_count=g.opportunity_count,
                blocked_pipeline_value=g.blocked_pipeline_value,
                is_single_blocker=g.is_single_blocker,
                weighted_rank_score=g.weighted_rank_score,
                trend=g.trend.value if g.trend else None,
            )
            for g in report.preferred_gaps
        ],
        total_required=report.total_required,
        total_matched=report.total_matched,
        gap_percentage=report.gap_percentage,
        generated_at=report.generated_at,
    )


@router.get(
    "/recommendation/{capability_name}",
    response_model=LearningRecommendationResponse,
)
async def get_learning_recommendation(
    capability_name: str,
    analyzer: GapAnalyzer = Depends(get_gap_analyzer),
) -> LearningRecommendationResponse:
    """Generate a learning recommendation for a specific capability gap.

    LLM-generated recommendation with study resources and effort estimate.
    Clearly labeled as advisory — not a guarantee of qualification.

    Delegates to GapAnalyzer.generate_learning_recommendation().
    Returns 404 if the capability is not in the canonical registry.
    """
    # In production (after task 8.3 implements generate_learning_recommendation):
    # 1. Verify capability exists in canonical_capabilities table
    # 2. Call GapAnalyzer.generate_learning_recommendation(capability_name)
    # 3. Convert LearningRecommendation to LearningRecommendationResponse
    # 4. Ensure advisory_note is populated

    # Stub: delegates to GapAnalyzer.generate_learning_recommendation()
    raise HTTPException(
        status_code=404,
        detail=f"Capability '{capability_name}' not found in canonical registry",
    )


@router.get(
    "/heatmap/{beneficiary_id}/history",
    response_model=list[HeatmapHistorySummary],
)
async def get_heatmap_history(
    beneficiary_id: str,
    limit: int = Query(default=10, ge=1, le=50, description="Max results to return"),
    analyzer: GapAnalyzer = Depends(get_gap_analyzer),
) -> list[HeatmapHistorySummary]:
    """Retrieve historical heatmap summaries for trend tracking.

    Returns most recent heatmaps first, up to the specified limit.
    Each summary includes the top gap name and total gap count for
    quick overview without loading full entry details.
    """
    # In production: queries gap_heatmaps table ordered by generated_at DESC,
    # limited to `limit` results for this beneficiary. Joins entries to
    # determine top_gap (rank_position=1) and gap_count.
    return []
