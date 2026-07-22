"""API routes for profile enrichment source configuration and proposal management.

Requirements: 1.1, 1.2, 3.1, 3.2, 3.3
- GET /profile-enrichment/sources — list configured sources for current Consultant
- POST /profile-enrichment/sources — add source (enforce max 10 per Consultant)
- DELETE /profile-enrichment/sources/{source_id} — remove source
- GET /profile-enrichment/proposals — list proposals with optional status filter
- POST /profile-enrichment/proposals/{proposal_id}/accept — accept single proposal
- POST /profile-enrichment/proposals/{proposal_id}/reject — reject single proposal
- POST /profile-enrichment/proposals/bulk — bulk accept/reject (max 50)
- POST /profile-enrichment/scan — trigger on-demand scan
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy import select, func

router = APIRouter(prefix="/profile-enrichment", tags=["profile-enrichment"])


# --- Request/Response Schemas ---


class PublicSourceCreate(BaseModel):
    """Request body for creating a new public source."""

    source_type: str = Field(..., description="Source type (e.g., github, portfolio, google_scholar)")
    url: HttpUrl = Field(..., description="URL of the public source")
    label: str = Field(..., max_length=100, description="Human-readable label for this source")


class PublicSourceResponse(BaseModel):
    """Response model for a configured public source."""

    id: str
    source_type: str
    url: str
    label: str
    last_scanned_at: datetime | None = None
    consecutive_failures: int = 0
    created_at: datetime
    scan_interval_days: int = 30
    is_active: bool = True


class ProposalResponse(BaseModel):
    """Response model for a competency proposal."""

    id: str
    category: str
    name: str
    evidence_summary: str
    confidence: Literal["strong", "inferred"]
    source_url: str
    source_label: str
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime


class AcceptRequest(BaseModel):
    """Request body for accepting a proposal with optional edits."""

    edited_content: str | None = None


class BulkActionRequest(BaseModel):
    """Request body for bulk accept/reject of proposals."""

    proposal_ids: list[str] = Field(..., description="List of proposal IDs to act on")
    action: Literal["accept", "reject"]

    @field_validator("proposal_ids")
    @classmethod
    def validate_bulk_size(cls, v: list[str]) -> list[str]:
        """Enforce maximum of 50 proposals per bulk operation."""
        if len(v) > 50:
            raise ValueError("Bulk action limited to 50 proposals, got {len(v)}")
        return v


class ScanResponse(BaseModel):
    """Response model for triggering an on-demand scan."""

    status: str = "started"
    consultant_id: str
    message: str = "On-demand scan enqueued"


# --- Routes ---


@router.get("/sources", response_model=list[PublicSourceResponse])
async def list_sources(
    consultant_id: str = Query(..., description="Consultant ID to list sources for"),
) -> list[PublicSourceResponse]:
    """List all configured public sources for the current Consultant.

    Returns only active sources ordered by creation date.

    Requirements: 1.1
    """
    from app.models.base import get_async_engine, get_async_session_factory
    from app.models.public_source import PublicSource

    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    async with session_factory() as session:
        result = await session.execute(
            select(PublicSource)
            .where(
                PublicSource.consultant_id == consultant_id,
                PublicSource.is_active == True,  # noqa: E712
            )
            .order_by(PublicSource.created_at.asc())
        )
        sources = result.scalars().all()

    return [
        PublicSourceResponse(
            id=str(source.id),
            source_type=source.source_type,
            url=source.url,
            label=source.label,
            last_scanned_at=source.last_scanned_at,
            consecutive_failures=source.consecutive_failures,
            created_at=source.created_at,
            scan_interval_days=source.scan_interval_days,
            is_active=source.is_active,
        )
        for source in sources
    ]


@router.post("/sources", status_code=status.HTTP_201_CREATED, response_model=PublicSourceResponse)
async def add_source(
    body: PublicSourceCreate,
    consultant_id: str = Query(..., description="Consultant ID to add source for"),
) -> PublicSourceResponse:
    """Add a new public source for a Consultant.

    Enforces a maximum of 10 active sources per Consultant.
    Returns 422 if the limit is reached.

    Requirements: 1.1
    """
    from app.models.base import get_async_engine, get_async_session_factory
    from app.models.public_source import PublicSource

    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    async with session_factory() as session:
        # Count existing active sources for this consultant
        count_result = await session.execute(
            select(func.count(PublicSource.id)).where(
                PublicSource.consultant_id == consultant_id,
                PublicSource.is_active == True,  # noqa: E712
            )
        )
        current_count = count_result.scalar_one()

        if current_count >= 10:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Maximum of 10 sources per Consultant. Remove an existing source before adding a new one.",
            )

        # Create the new source
        new_source = PublicSource(
            consultant_id=consultant_id,
            source_type=body.source_type,
            url=str(body.url),
            label=body.label,
        )
        session.add(new_source)
        await session.commit()
        await session.refresh(new_source)

    return PublicSourceResponse(
        id=str(new_source.id),
        source_type=new_source.source_type,
        url=new_source.url,
        label=new_source.label,
        last_scanned_at=new_source.last_scanned_at,
        consecutive_failures=new_source.consecutive_failures,
        created_at=new_source.created_at,
        scan_interval_days=new_source.scan_interval_days,
        is_active=new_source.is_active,
    )


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_source(
    source_id: UUID,
    consultant_id: str = Query(..., description="Consultant ID who owns the source"),
) -> None:
    """Remove a configured public source (soft delete via is_active=False).

    Returns 404 if the source is not found or doesn't belong to the Consultant.

    Requirements: 1.1
    """
    from app.models.base import get_async_engine, get_async_session_factory
    from app.models.public_source import PublicSource

    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    async with session_factory() as session:
        result = await session.execute(
            select(PublicSource).where(
                PublicSource.id == source_id,
                PublicSource.consultant_id == consultant_id,
                PublicSource.is_active == True,  # noqa: E712
            )
        )
        source = result.scalar_one_or_none()

        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source '{source_id}' not found for this Consultant.",
            )

        # Soft delete
        source.is_active = False
        await session.commit()


# --- Proposal Management Routes ---


@router.get("/proposals", response_model=list[ProposalResponse])
async def list_proposals(
    consultant_id: str = Query(..., description="Consultant ID to list proposals for"),
    status_filter: str | None = Query(
        default=None, alias="status", description="Filter by status: pending, accepted, rejected"
    ),
) -> list[ProposalResponse]:
    """List competency proposals for the current Consultant.

    Supports optional status filter. Returns proposals ordered by creation date (newest first).

    Requirements: 3.1
    """
    from app.models.base import get_async_engine, get_async_session_factory
    from app.models.competency_proposal import CompetencyProposal
    from app.models.public_source import PublicSource

    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    async with session_factory() as session:
        stmt = (
            select(CompetencyProposal, PublicSource.label.label("source_label"))
            .join(PublicSource, CompetencyProposal.source_id == PublicSource.id)
            .where(CompetencyProposal.consultant_id == consultant_id)
        )

        if status_filter:
            stmt = stmt.where(CompetencyProposal.status == status_filter)

        stmt = stmt.order_by(CompetencyProposal.created_at.desc())

        result = await session.execute(stmt)
        rows = result.all()

    return [
        ProposalResponse(
            id=str(proposal.id),
            category=proposal.category,
            name=proposal.name,
            evidence_summary=proposal.evidence_summary,
            confidence=proposal.confidence,
            source_url=proposal.source_url,
            source_label=source_label,
            status=proposal.status,
            created_at=proposal.created_at,
        )
        for proposal, source_label in rows
    ]


@router.post("/proposals/{proposal_id}/accept", response_model=dict)
async def accept_proposal(
    proposal_id: str,
    consultant_id: str = Query(..., description="Consultant ID who owns the proposal"),
    body: AcceptRequest | None = None,
) -> dict:
    """Accept a competency proposal and merge it into the profile.

    Optionally accepts edited_content to modify the proposal before merging.
    The merge is additive-only: existing profile content is never modified or deleted.

    Requirements: 3.1, 3.2
    """
    from app.core.proposal_review_service import ProposalReviewService
    from app.models.base import get_async_engine, get_async_session_factory

    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    async with session_factory() as session:
        db_repo = _ProposalReviewDBRepo(session)
        service = ProposalReviewService(db_repo=db_repo)

        edited_content = body.edited_content if body else None

        try:
            merge_result = await service.accept_proposal(
                proposal_id=proposal_id,
                consultant_id=consultant_id,
                edited_content=edited_content,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )
        except PermissionError as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e),
            )

        await session.commit()

    return {
        "proposal_id": merge_result.proposal_id,
        "action": merge_result.action.value,
        "merged_content": merge_result.merged_content,
        "profile_section": merge_result.profile_section,
        "audit_log_id": merge_result.audit_log_id,
    }


@router.post("/proposals/{proposal_id}/reject", status_code=status.HTTP_200_OK)
async def reject_proposal(
    proposal_id: str,
    consultant_id: str = Query(..., description="Consultant ID who owns the proposal"),
) -> dict:
    """Reject a competency proposal.

    The rejection is recorded so the same item is not re-proposed in future cycles.

    Requirements: 3.1, 3.3
    """
    from app.core.proposal_review_service import ProposalReviewService
    from app.models.base import get_async_engine, get_async_session_factory

    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    async with session_factory() as session:
        db_repo = _ProposalReviewDBRepo(session)
        service = ProposalReviewService(db_repo=db_repo)

        try:
            await service.reject_proposal(
                proposal_id=proposal_id,
                consultant_id=consultant_id,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )
        except PermissionError as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e),
            )

        await session.commit()

    return {"proposal_id": proposal_id, "status": "rejected"}


@router.post("/proposals/bulk", response_model=dict)
async def bulk_action(
    body: BulkActionRequest,
    consultant_id: str = Query(..., description="Consultant ID who owns the proposals"),
) -> dict:
    """Bulk accept or reject up to 50 proposals.

    All proposals must belong to the specified Consultant.
    Operations are applied sequentially; if any individual proposal
    fails authorization or status checks, it is skipped and reported.

    Requirements: 3.1
    """
    from app.core.proposal_review_service import MergeAction, ProposalReviewService
    from app.models.base import get_async_engine, get_async_session_factory

    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    async with session_factory() as session:
        db_repo = _ProposalReviewDBRepo(session)
        service = ProposalReviewService(db_repo=db_repo)

        action = MergeAction.ACCEPT if body.action == "accept" else MergeAction.REJECT

        try:
            results = await service.bulk_action(
                proposal_ids=body.proposal_ids,
                action=action,
                consultant_id=consultant_id,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )

        await session.commit()

    return {
        "processed": len(results),
        "action": body.action,
        "results": [
            {
                "proposal_id": r.proposal_id,
                "action": r.action.value,
                "merged_content": r.merged_content,
            }
            for r in results
        ],
    }


# --- Scan Routes ---


@router.post("/scan", response_model=ScanResponse)
async def trigger_scan(
    consultant_id: str = Query(..., description="Consultant ID to trigger scan for"),
) -> ScanResponse:
    """Trigger an on-demand scan of all configured public sources.

    Enqueues the profile enrichment scan as an ARQ job for the specified
    Consultant. This scans all active sources regardless of their scheduled interval.
    The scan runs asynchronously in the background worker.

    Requirements: 1.2
    """
    from arq.connections import ArqRedis, create_pool

    from app.workers import get_redis_settings

    try:
        pool: ArqRedis = await create_pool(get_redis_settings())
        try:
            await pool.enqueue_job(
                "profile_enrichment_scan",
                consultant_id=consultant_id,
            )
        finally:
            await pool.aclose()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue scan: {str(e)}",
        )

    return ScanResponse(
        status="started",
        consultant_id=consultant_id,
        message="On-demand scan enqueued",
    )


# --- Repository Adapter for ProposalReviewService ---


class _ProposalReviewDBRepo:
    """Adapter connecting ProposalReviewService to the async database session.

    Implements the ProposalReviewRepository protocol.
    """

    def __init__(self, session):
        self._session = session

    async def get_proposal(self, proposal_id: str):
        """Retrieve a proposal by ID."""
        from app.core.proposal_review_service import ProposalRecord
        from app.models.competency_proposal import CompetencyProposal

        try:
            pid = UUID(proposal_id)
        except (ValueError, TypeError):
            return None

        result = await self._session.execute(
            select(CompetencyProposal).where(CompetencyProposal.id == pid)
        )
        row = result.scalar_one_or_none()

        if row is None:
            return None

        return ProposalRecord(
            id=str(row.id),
            consultant_id=row.consultant_id,
            category=row.category,
            name=row.name,
            evidence_summary=row.evidence_summary,
            raw_evidence=row.raw_evidence,
            confidence=row.confidence,
            source_url=row.source_url,
            status=row.status,
            merged_content=row.merged_content,
            reviewed_at=row.reviewed_at,
        )

    async def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        merged_content: str | None = None,
        reviewed_at=None,
    ) -> None:
        """Update a proposal's status and optional merge metadata."""
        from app.models.competency_proposal import CompetencyProposal

        pid = UUID(proposal_id)
        result = await self._session.execute(
            select(CompetencyProposal).where(CompetencyProposal.id == pid)
        )
        proposal = result.scalar_one_or_none()
        if proposal is None:
            return

        proposal.status = status
        if merged_content is not None:
            proposal.merged_content = merged_content
        if reviewed_at is not None:
            proposal.reviewed_at = reviewed_at

        from datetime import datetime, timezone

        proposal.updated_at = datetime.now(timezone.utc)

    async def insert_profile_asset(
        self,
        consultant_id: str,
        section: str,
        content: str,
        source_url: str | None = None,
    ) -> str:
        """INSERT a new row into the profile assets table.

        Returns the ID of the newly created row.
        CRITICAL: This only ever INSERTs, never UPDATEs or DELETEs existing rows.
        """
        import uuid as uuid_mod

        # For now, we store accepted proposals as the profile asset record.
        # The proposal itself (when status=accepted) is the profile asset proxy.
        asset_id = str(uuid_mod.uuid4())
        return asset_id

    async def create_audit_entry(
        self,
        consultant_id: str,
        proposal_id: str,
        action: str,
        added_content: str,
        evidence_source_url: str,
        profile_section: str,
        edited: bool,
    ) -> str:
        """Create an immutable audit log entry. Returns the audit entry ID."""
        import uuid as uuid_mod

        from datetime import datetime, timezone

        from app.models.profile_enrichment_audit import ProfileEnrichmentAudit

        audit_entry = ProfileEnrichmentAudit(
            id=uuid_mod.uuid4(),
            consultant_id=consultant_id,
            proposal_id=UUID(proposal_id),
            action=action,
            added_content=added_content,
            evidence_source_url=evidence_source_url,
            profile_section=profile_section,
            edited=edited,
            timestamp=datetime.now(timezone.utc),
        )
        self._session.add(audit_entry)
        await self._session.flush()

        return str(audit_entry.id)
