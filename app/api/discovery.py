"""API routes for discovery and prospects.

Requirements 10.1, 10.4, 1.1, 1.7:
- POST /discovery/run — trigger a discovery run for a source+beneficiary
- GET /prospects — list prospects with pagination, filtering
- GET /prospects/{id} — get prospect detail
- GET /prospects/{id}/enrichment — get enrichment data for a prospect
- POST /enrichment/refresh — trigger enrichment refresh for stale records
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["discovery"])


# --- Request/Response Schemas ---


class DiscoveryRunRequest(BaseModel):
    """Request to trigger a discovery run."""

    source_type: str = Field(
        ...,
        description="Source type: adzuna, apollo, internet_search, project_marketplace",
    )
    beneficiary_id: str = Field(
        ..., description="Beneficiary to run discovery for (e.g., 'consultant', 'team')"
    )


class DiscoveryRunResponse(BaseModel):
    """Response from triggering a discovery run."""

    status: str = "started"
    source_type: str
    beneficiary_id: str
    prospects_found: int = 0
    prospects_merged: int = 0
    prospects_scored: int = 0
    prospects_filtered: int = 0
    duration_seconds: float = 0.0


class ProspectSummary(BaseModel):
    """Summary view of a prospect for list endpoints."""

    id: UUID
    company_name: str
    company_domain: str | None = None
    beneficiary_id: str
    opportunity_type_id: str
    discovery_source: str
    source_count: int = 1
    score: int | None = None
    tier: str | None = None
    first_discovered_at: datetime


class ProspectListResponse(BaseModel):
    """Paginated list of prospects."""

    items: list[ProspectSummary]
    total: int
    page: int
    page_size: int
    has_next: bool


class ProspectDetail(BaseModel):
    """Full detail view of a single prospect."""

    id: UUID
    company_name: str
    company_domain: str | None = None
    normalized_name: str
    beneficiary_id: str
    opportunity_type_id: str
    discovery_source: str
    source_count: int = 1
    first_discovered_at: datetime
    created_at: datetime
    updated_at: datetime
    score: int | None = None
    tier: str | None = None
    pipeline_status: str | None = None


class EnrichmentRecordResponse(BaseModel):
    """Enrichment data for a prospect."""

    prospect_id: UUID
    employee_count: int | None = None
    revenue_range: str | None = None
    industry: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    funding_stage: str | None = None
    hq_city: str | None = None
    hq_country: str | None = None
    status: str
    retry_count: int = 0
    enriched_at: datetime | None = None
    expires_at: datetime | None = None


class EnrichmentRefreshRequest(BaseModel):
    """Request to refresh stale enrichment records."""

    prospect_ids: list[UUID] | None = Field(
        default=None,
        description="Specific prospect IDs to refresh. If null, refreshes all stale records.",
    )
    max_age_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Records older than this are considered stale.",
    )


class EnrichmentRefreshResponse(BaseModel):
    """Response from enrichment refresh request."""

    status: str = "started"
    records_queued: int = 0


# --- Routes ---


@router.post("/discovery/run", response_model=DiscoveryRunResponse)
async def trigger_discovery_run(request: DiscoveryRunRequest) -> DiscoveryRunResponse:
    """Trigger a discovery run for a specific source and beneficiary.

    This initiates an asynchronous discovery process that searches for
    prospects from the specified source, deduplicates, scores, and filters them.
    """
    # Stub: In production, this dispatches to DiscoveryPipeline
    return DiscoveryRunResponse(
        source_type=request.source_type,
        beneficiary_id=request.beneficiary_id,
    )


@router.get("/prospects", response_model=ProspectListResponse)
async def list_prospects(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    beneficiary_id: str | None = Query(default=None, description="Filter by beneficiary"),
    tier: str | None = Query(default=None, description="Filter by score tier"),
    opportunity_type: str | None = Query(default=None, description="Filter by opportunity type"),
) -> ProspectListResponse:
    """List prospects with pagination and filtering.

    Supports filtering by beneficiary, tier, and opportunity type.
    Results are ordered by score descending.
    """
    # Stub: In production, queries the prospects table with filters
    return ProspectListResponse(
        items=[],
        total=0,
        page=page,
        page_size=page_size,
        has_next=False,
    )


@router.get("/prospects/{prospect_id}", response_model=ProspectDetail)
async def get_prospect_detail(prospect_id: UUID) -> ProspectDetail:
    """Get full detail for a single prospect including score and pipeline status."""
    # Stub: In production, fetches from DB with joined score/pipeline data
    return ProspectDetail(
        id=prospect_id,
        company_name="Placeholder Company",
        normalized_name="placeholder company",
        beneficiary_id="consultant",
        opportunity_type_id="cold_outreach",
        discovery_source="apollo",
        first_discovered_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@router.get("/prospects/{prospect_id}/enrichment", response_model=EnrichmentRecordResponse)
async def get_prospect_enrichment(prospect_id: UUID) -> EnrichmentRecordResponse:
    """Get enrichment data for a specific prospect."""
    # Stub: In production, fetches from enrichment_records table
    return EnrichmentRecordResponse(
        prospect_id=prospect_id,
        status="pending",
    )


@router.post("/enrichment/refresh", response_model=EnrichmentRefreshResponse)
async def refresh_enrichment(request: EnrichmentRefreshRequest) -> EnrichmentRefreshResponse:
    """Trigger enrichment refresh for stale records.

    If prospect_ids are specified, refreshes those specific records.
    Otherwise, refreshes all records older than max_age_days.
    """
    # Stub: In production, queues enrichment refresh tasks
    return EnrichmentRefreshResponse(
        status="started",
        records_queued=0,
    )
