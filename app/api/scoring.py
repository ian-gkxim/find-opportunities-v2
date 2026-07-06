"""API routes for account scoring.

Requirements 4.3, 4.4:
- GET /scores — list account scores with tier filtering
- PUT /settings/scoring-weights — update scoring weight configuration
- POST /scores/recompute — trigger bulk score recomputation
"""

from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator

router = APIRouter(tags=["scoring"])


# --- Request/Response Schemas ---


class AccountScoreSummary(BaseModel):
    """Summary of an account score."""

    prospect_id: UUID
    company_name: str
    total_score: int = Field(..., ge=0, le=100)
    tier: str = Field(..., description="A-tier, B-tier, C-tier, or D-tier")
    is_partial: bool = False
    missing_factors: list[str] = Field(default_factory=list)
    multi_source_bonus: int = Field(default=0, ge=0, le=30)


class ScoreListResponse(BaseModel):
    """Paginated list of account scores."""

    items: list[AccountScoreSummary]
    total: int
    page: int
    page_size: int
    has_next: bool


class ScoringWeightsRequest(BaseModel):
    """Request to update scoring weight configuration.

    All five weights must be integers in [0, 100] and sum to exactly 100.
    """

    firmographic: int = Field(..., ge=0, le=100)
    technographic: int = Field(..., ge=0, le=100)
    intent: int = Field(..., ge=0, le=100)
    llm_relevance: int = Field(..., ge=0, le=100)
    historical: int = Field(..., ge=0, le=100)

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "ScoringWeightsRequest":
        total = (
            self.firmographic
            + self.technographic
            + self.intent
            + self.llm_relevance
            + self.historical
        )
        if total != 100:
            raise ValueError(f"Weights must sum to 100, got {total}")
        return self


class ScoringWeightsResponse(BaseModel):
    """Current scoring weights configuration."""

    firmographic: int
    technographic: int
    intent: int
    llm_relevance: int
    historical: int
    min_score_threshold: int = 25


class RecomputeScoresRequest(BaseModel):
    """Request to trigger bulk score recomputation."""

    beneficiary_id: str | None = Field(
        default=None, description="Limit recomputation to a specific beneficiary"
    )


class RecomputeScoresResponse(BaseModel):
    """Response from bulk score recomputation."""

    status: str = "started"
    prospects_queued: int = 0


# --- Routes ---


@router.get("/scores", response_model=ScoreListResponse)
async def list_scores(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    tier: str | None = Query(default=None, description="Filter by tier (A-tier, B-tier, etc.)"),
    beneficiary_id: str | None = Query(default=None, description="Filter by beneficiary"),
) -> ScoreListResponse:
    """List account scores with tier and beneficiary filtering.

    Returns scores ordered by total_score descending.
    """
    # Stub: In production, queries account_scores joined with prospects
    return ScoreListResponse(
        items=[],
        total=0,
        page=page,
        page_size=page_size,
        has_next=False,
    )


@router.put("/settings/scoring-weights", response_model=ScoringWeightsResponse)
async def update_scoring_weights(request: ScoringWeightsRequest) -> ScoringWeightsResponse:
    """Update scoring weight configuration.

    When weights change, all non-terminal prospects are queued for
    score recomputation (completed within 60 seconds).
    """
    # Stub: In production, updates scoring_configs table and triggers recomputation worker
    return ScoringWeightsResponse(
        firmographic=request.firmographic,
        technographic=request.technographic,
        intent=request.intent,
        llm_relevance=request.llm_relevance,
        historical=request.historical,
    )


@router.post("/scores/recompute", response_model=RecomputeScoresResponse)
async def recompute_scores(request: RecomputeScoresRequest) -> RecomputeScoresResponse:
    """Trigger bulk score recomputation for all non-terminal prospects.

    Optionally limited to a specific beneficiary.
    """
    # Stub: In production, dispatches to scoring_worker
    return RecomputeScoresResponse(
        status="started",
        prospects_queued=0,
    )
