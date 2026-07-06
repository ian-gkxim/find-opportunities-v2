"""API routes for Lemlist sequence management.

Requirements 5.1, 5.2, 5.4, 6.5, 13.4:
- GET /sequences — list sequences
- POST /sequences — create a new sequence
- GET /sequences/{id} — get sequence detail
- PUT /sequences/{id} — update a sequence
- DELETE /sequences/{id} — delete a sequence
- POST /sequences/{id}/enroll — enroll prospects in a sequence
- POST /sequences/{id}/promote-variant — promote a winning variant
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["sequences"])


# --- Request/Response Schemas ---


class SequenceStepSchema(BaseModel):
    """A single step within a sequence."""

    order: int = Field(..., ge=1, le=10, description="Step order (1-10)")
    channel: str = Field(..., description="Channel: email, linkedin, manual_task")
    delay_days: int = Field(..., ge=1, le=30, description="Delay in days before this step")
    content_template: str = Field(
        ..., max_length=5000, description="Content template (max 5000 chars)"
    )


class VariantSchema(BaseModel):
    """A/B test variant for a sequence step."""

    variant_label: str = Field(..., description="Variant label: A, B, C, or D")
    content: str = Field(..., description="Variant content")
    sends: int = 0
    opens: int = 0
    clicks: int = 0
    replies: int = 0
    is_winner: bool = False
    is_promoted: bool = False


class CreateSequenceRequest(BaseModel):
    """Request to create a new sequence."""

    name: str = Field(..., min_length=1, max_length=300)
    beneficiary_id: str = Field(..., description="Beneficiary this sequence belongs to")
    steps: list[SequenceStepSchema] = Field(
        ..., min_length=1, max_length=10, description="Sequence steps (1-10)"
    )


class UpdateSequenceRequest(BaseModel):
    """Request to update an existing sequence."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    steps: list[SequenceStepSchema] | None = Field(
        default=None, min_length=1, max_length=10, description="Updated steps"
    )


class SequenceSummary(BaseModel):
    """Summary view of a sequence for list endpoints."""

    id: UUID
    name: str
    beneficiary_id: str
    step_count: int
    sync_status: str
    created_at: datetime


class SequenceDetail(BaseModel):
    """Full detail view of a sequence."""

    id: UUID
    name: str
    beneficiary_id: str
    steps: list[SequenceStepSchema]
    sync_status: str
    lemlist_campaign_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SequenceListResponse(BaseModel):
    """Paginated list of sequences."""

    items: list[SequenceSummary]
    total: int
    page: int
    page_size: int
    has_next: bool


class EnrollProspectsRequest(BaseModel):
    """Request to enroll prospects in a sequence.

    Either specify prospect_ids directly, or use filter criteria for batch enrollment.
    """

    prospect_ids: list[UUID] | None = Field(
        default=None, description="Specific prospect IDs to enroll"
    )
    tier: str | None = Field(default=None, description="Filter by score tier for batch enroll")
    opportunity_type: str | None = Field(
        default=None, description="Filter by opportunity type for batch enroll"
    )
    has_intent: bool | None = Field(
        default=None, description="Filter by intent signal presence for batch enroll"
    )


class EnrollProspectsResponse(BaseModel):
    """Response from prospect enrollment."""

    enrolled_count: int = 0
    sequence_id: UUID
    status: str = "enrolled"


class PromoteVariantRequest(BaseModel):
    """Request to promote a winning A/B test variant."""

    step_order: int = Field(..., ge=1, le=10, description="Which step to promote for")
    variant_label: str = Field(..., description="Variant to promote (A, B, C, or D)")


class PromoteVariantResponse(BaseModel):
    """Response from variant promotion."""

    sequence_id: UUID
    step_order: int
    promoted_variant: str
    status: str = "promoted"


class DeleteSequenceResponse(BaseModel):
    """Response from sequence deletion."""

    id: UUID
    status: str = "deleted"


# --- Routes ---


@router.get("/sequences", response_model=SequenceListResponse)
async def list_sequences(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    beneficiary_id: str | None = Query(default=None, description="Filter by beneficiary"),
) -> SequenceListResponse:
    """List all sequences with optional beneficiary filtering."""
    # Stub: In production, queries sequences table
    return SequenceListResponse(
        items=[],
        total=0,
        page=page,
        page_size=page_size,
        has_next=False,
    )


@router.post("/sequences", response_model=SequenceDetail, status_code=201)
async def create_sequence(request: CreateSequenceRequest) -> SequenceDetail:
    """Create a new outreach sequence.

    The sequence is synchronized to Lemlist within 10 seconds.
    Supports up to 10 steps with configurable channels and delays.
    """
    # Stub: In production, creates sequence and syncs to Lemlist via LemlistEngine
    from uuid import uuid4

    sequence_id = uuid4()
    return SequenceDetail(
        id=sequence_id,
        name=request.name,
        beneficiary_id=request.beneficiary_id,
        steps=request.steps,
        sync_status="pending",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@router.get("/sequences/{sequence_id}", response_model=SequenceDetail)
async def get_sequence_detail(sequence_id: UUID) -> SequenceDetail:
    """Get full detail for a specific sequence including steps and sync status."""
    # Stub: In production, fetches from DB with joined steps
    return SequenceDetail(
        id=sequence_id,
        name="Placeholder Sequence",
        beneficiary_id="consultant",
        steps=[],
        sync_status="synced",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@router.put("/sequences/{sequence_id}", response_model=SequenceDetail)
async def update_sequence(sequence_id: UUID, request: UpdateSequenceRequest) -> SequenceDetail:
    """Update an existing sequence's name or steps.

    Re-synchronizes to Lemlist after update.
    """
    # Stub: In production, updates and re-syncs
    return SequenceDetail(
        id=sequence_id,
        name=request.name or "Updated Sequence",
        beneficiary_id="consultant",
        steps=request.steps or [],
        sync_status="pending",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@router.delete("/sequences/{sequence_id}", response_model=DeleteSequenceResponse)
async def delete_sequence(sequence_id: UUID) -> DeleteSequenceResponse:
    """Delete a sequence. Active enrollments are completed before deletion."""
    # Stub: In production, marks as deleted and handles active enrollments
    return DeleteSequenceResponse(id=sequence_id)


@router.post("/sequences/{sequence_id}/enroll", response_model=EnrollProspectsResponse)
async def enroll_prospects(
    sequence_id: UUID, request: EnrollProspectsRequest
) -> EnrollProspectsResponse:
    """Enroll prospects in a sequence.

    Supports both direct enrollment (by prospect IDs) and batch enrollment
    by filter criteria (tier, opportunity type, intent signal presence).
    Maximum 200 prospects per batch enrollment.
    """
    # Stub: In production, delegates to LemlistEngine.enroll_prospects()
    return EnrollProspectsResponse(
        enrolled_count=0,
        sequence_id=sequence_id,
    )


@router.post("/sequences/{sequence_id}/promote-variant", response_model=PromoteVariantResponse)
async def promote_variant(
    sequence_id: UUID, request: PromoteVariantRequest
) -> PromoteVariantResponse:
    """Promote a winning A/B test variant to 100% allocation.

    Subsequent enrollees receive only the promoted variant.
    Prospects already assigned to other variants continue their current variant.
    """
    # Stub: In production, delegates to LemlistEngine.promote_variant()
    return PromoteVariantResponse(
        sequence_id=sequence_id,
        step_order=request.step_order,
        promoted_variant=request.variant_label,
    )
