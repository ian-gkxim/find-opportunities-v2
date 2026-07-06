"""API routes for pipeline management.

Requirements 8.2, 8.3:
- GET /pipeline — list pipeline records with status/beneficiary filtering
- PATCH /pipeline/{id}/status — manually update pipeline status
- GET /pipeline/requires-action — get requires action items
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["pipeline"])


# --- Request/Response Schemas ---


class PipelineRecordSummary(BaseModel):
    """Summary view of a pipeline record."""

    id: UUID
    prospect_id: UUID
    company_name: str | None = None
    opportunity_type_id: str
    beneficiary_id: str
    current_status: str
    previous_status: str | None = None
    is_terminal: bool = False
    created_at: datetime
    updated_at: datetime


class PipelineListResponse(BaseModel):
    """Paginated list of pipeline records."""

    items: list[PipelineRecordSummary]
    total: int
    page: int
    page_size: int
    has_next: bool


class PipelineStatusUpdateRequest(BaseModel):
    """Request to manually update a pipeline record's status."""

    new_status: str = Field(..., description="The target pipeline status")
    reason: str | None = Field(default=None, description="Optional reason for the manual update")


class PipelineStatusUpdateResponse(BaseModel):
    """Response from a pipeline status update."""

    id: UUID
    previous_status: str
    new_status: str
    updated_at: datetime


class RequiresActionItem(BaseModel):
    """An item requiring user attention."""

    action_type: str = Field(
        ..., description="Type: stale_followup, failed_sequence, enrichment_error"
    )
    record_id: str
    prospect_id: str
    beneficiary_id: str
    description: str
    last_activity_at: datetime | None = None
    days_stale: int | None = None


class RequiresActionResponse(BaseModel):
    """List of items requiring user action."""

    items: list[RequiresActionItem]
    total: int


# --- Routes ---


@router.get("/pipeline", response_model=PipelineListResponse)
async def list_pipeline_records(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: str | None = Query(default=None, description="Filter by current status"),
    beneficiary_id: str | None = Query(default=None, description="Filter by beneficiary"),
    opportunity_type: str | None = Query(default=None, description="Filter by opportunity type"),
    is_terminal: bool | None = Query(default=None, description="Filter by terminal status"),
) -> PipelineListResponse:
    """List pipeline records with filtering.

    Supports filtering by status, beneficiary, opportunity type, and terminal status.
    Results are ordered by updated_at descending (most recent activity first).
    """
    # Stub: In production, queries pipeline_records with filters
    return PipelineListResponse(
        items=[],
        total=0,
        page=page,
        page_size=page_size,
        has_next=False,
    )


@router.patch("/pipeline/{record_id}/status", response_model=PipelineStatusUpdateResponse)
async def update_pipeline_status(
    record_id: UUID, request: PipelineStatusUpdateRequest
) -> PipelineStatusUpdateResponse:
    """Manually update a pipeline record's status.

    Used for manual status transitions such as marking a prospect as
    "Won", "Lost", or "Abandoned".
    """
    # Stub: In production, validates transition and updates via PipelineManager
    return PipelineStatusUpdateResponse(
        id=record_id,
        previous_status="Drafted",
        new_status=request.new_status,
        updated_at=datetime.utcnow(),
    )


@router.get("/pipeline/requires-action", response_model=RequiresActionResponse)
async def get_requires_action() -> RequiresActionResponse:
    """Get all items requiring user action for the Dashboard.

    Includes:
    - Prospects with stale follow-ups (no activity for 7+ days)
    - Failed sequences
    - Enrichment errors
    """
    # Stub: In production, delegates to PipelineManager.get_requires_action_items()
    return RequiresActionResponse(
        items=[],
        total=0,
    )
