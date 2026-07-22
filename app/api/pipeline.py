"""API routes for pipeline management.

Requirements 8.2, 8.3, 3.4:
- GET /pipeline — list pipeline records with status/beneficiary filtering
- PATCH /pipeline/{id}/status — manually update pipeline status
- GET /pipeline/requires-action — get requires action items
- GET /pipeline/{id} — pipeline record detail with review status
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


class InterviewPrepSummaryResponse(BaseModel):
    """Summary of interview prep pack for pipeline record detail view.

    Includes pack status, content, and action URLs for the Dashboard
    to present the pack and offer regeneration.

    Requirements: 3.2
    """

    pack_id: str
    status: str
    likely_questions: list[str]
    star_talking_points_count: int
    company_briefing: str
    questions_to_ask: list[str]
    has_grounding_flags: bool
    generation_duration_ms: int
    detail_url: str
    regenerate_url: str


class PipelineRecordDetail(BaseModel):
    """Detail view of a pipeline record including review status and grounding badge."""

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
    review_status: str | None = None
    edits_applied_count: int | None = None
    grounding_warning_badge: bool = Field(
        default=False,
        description=(
            "True when material has partially_grounded claims but no "
            "ungrounded claims — pipeline can advance with warning. "
            "Requirements: 3.4"
        ),
    )
    interview_prep: InterviewPrepSummaryResponse | None = Field(
        default=None,
        description=(
            "Interview prep pack summary when a pack exists for this record. "
            "Includes pack status, content, and regenerate action URL. "
            "Requirements: 3.2"
        ),
    )


# --- Helpers ---


async def _get_review_status_for_record(
    session: AsyncSession, pipeline_record_id: str
) -> dict[str, str | int | None]:
    """Query review_reasoning_logs for a pipeline record's review data.

    Returns a dict with review_status and edits_applied_count, or
    None values if no review data exists for this record.
    """
    stmt = text("""
        SELECT rrl.final_review_status,
               COALESCE(SUM(rcd.edits_applied), 0) as total_edits_applied
        FROM review_reasoning_logs rrl
        LEFT JOIN review_cycle_details rcd ON rcd.reasoning_log_id = rrl.id
        WHERE rrl.pipeline_record_id = :pipeline_record_id
        GROUP BY rrl.id, rrl.final_review_status
        ORDER BY rrl.created_at DESC
        LIMIT 1
    """)
    result = await session.execute(stmt, {"pipeline_record_id": pipeline_record_id})
    row = result.fetchone()

    if row is None:
        return {"review_status": None, "edits_applied_count": None}

    return {
        "review_status": row[0],
        "edits_applied_count": int(row[1]),
    }


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


@router.get("/pipeline/{record_id}", response_model=PipelineRecordDetail)
async def get_pipeline_record_detail(record_id: UUID) -> PipelineRecordDetail:
    """Get detailed view of a single pipeline record, including review status.

    Queries review_reasoning_logs for the record's review data and includes
    review_status and edits_applied_count in the response.
    Calls PipelineGateService.get_warning_badge() to determine if a warning
    badge should display (partially_grounded_count > 0, ungrounded_count == 0).
    Includes interview_prep pack summary when a pack exists for this record.

    Requirements: 3.2, 3.4
    """
    try:
        from app.api.interview_prep_enrichment import get_interview_prep_summary
        from app.core.pipeline_gate import PipelineGateService
        from app.models.base import get_async_engine, get_async_session_factory
        from app.repositories.grounding_repository import GroundingRepository

        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)

        async with session_factory() as session:
            review_data = await _get_review_status_for_record(session, str(record_id))

        # Check grounding warning badge via PipelineGateService
        grounding_warning_badge = False
        try:
            db_repo = GroundingRepository(session_factory)
            gate_service = PipelineGateService(db_repo)
            grounding_warning_badge = await gate_service.get_warning_badge(str(record_id))
        except Exception:
            # If grounding tables don't exist yet, skip gracefully
            pass

        # Fetch interview prep pack summary if one exists
        interview_prep = await get_interview_prep_summary(str(record_id))

        await engine.dispose()

        # Stub: In production, also fetches the pipeline record itself from DB
        return PipelineRecordDetail(
            id=record_id,
            prospect_id=record_id,  # placeholder
            opportunity_type_id="unknown",
            beneficiary_id="unknown",
            current_status="Unknown",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            review_status=review_data["review_status"],
            edits_applied_count=review_data["edits_applied_count"],
            grounding_warning_badge=grounding_warning_badge,
            interview_prep=interview_prep,
        )

    except Exception:
        # If DB isn't available, return record without review data
        return PipelineRecordDetail(
            id=record_id,
            prospect_id=record_id,  # placeholder
            opportunity_type_id="unknown",
            beneficiary_id="unknown",
            current_status="Unknown",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            review_status=None,
            edits_applied_count=None,
            grounding_warning_badge=False,
            interview_prep=None,
        )
