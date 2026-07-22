"""API routes for grounding verification, resolution, and analytics.

Requirements: 2.4, 3.1, 3.2, 3.3, 4.2
- POST /grounding/resolve — resolution dispatch (regenerate, manual_edit, confirm_and_add)
- GET /grounding/reports/{pipeline_record_id} — latest grounding report
- GET /grounding/reports/{pipeline_record_id}/claims — claims with status filter
- GET /grounding/analytics/rates — weekly ungrounded rates per technique
- GET /grounding/analytics/trend/{technique_id} — trailing weekly trend
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/grounding", tags=["grounding"])


# ─── Request/Response Schemas ─────────────────────────────────────────────────


class ResolutionPathEnum(str, Enum):
    """Resolution path options for blocked materials."""

    regenerate = "regenerate"
    manual_edit = "manual_edit"
    confirm_and_add = "confirm_and_add"


class GroundingResolveRequest(BaseModel):
    """Request body for POST /grounding/resolve.

    Requirements: 3.2, 3.3
    """

    material_id: str = Field(..., description="UUID of the material to resolve")
    resolution_path: ResolutionPathEnum = Field(
        ..., description="Resolution strategy to apply"
    )
    claim_ids: list[str] = Field(
        ..., min_length=1, description="UUIDs of the claims being resolved"
    )
    # Path-specific fields
    edited_content: str | None = Field(
        default=None,
        description="Updated material text (required for manual_edit path)",
    )
    supporting_fact: str | None = Field(
        default=None,
        description="Fact to add to profile asset (required for confirm_and_add path)",
    )
    target_asset_id: str | None = Field(
        default=None,
        description="Profile asset to add the fact to (required for confirm_and_add path)",
    )


class SourcePointerResponse(BaseModel):
    """Source evidence pointer for a grounded claim."""

    asset_type: str
    asset_id: str
    passage: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class ClaimResponse(BaseModel):
    """Single claim within a grounding report."""

    id: str
    material_id: str
    category: str
    claim_text: str
    source_span: str
    source_span_start: int
    source_span_end: int
    grounding_status: str | None = None
    source_pointer: SourcePointerResponse | None = None
    discrepancy: str | None = None
    is_prospect_side: bool = False


class GroundingReportResponse(BaseModel):
    """Full grounding report for a pipeline record.

    Requirements: 2.4, 3.1
    """

    id: str
    material_id: str
    pipeline_record_id: str
    claims: list[ClaimResponse]
    total_claims: int
    grounded_count: int
    partially_grounded_count: int
    ungrounded_count: int
    material_grounding_status: str
    extraction_duration_ms: int
    verification_duration_ms: int
    created_at: datetime
    updated_at: datetime


class GroundingResultResponse(BaseModel):
    """Response from a resolution operation.

    Requirements: 3.2, 3.3
    """

    material_id: str
    material_grounding_status: str
    grounding_report: GroundingReportResponse
    blocked_states: list[str]
    requires_action: bool


class ClaimListResponse(BaseModel):
    """Paginated claim list with optional status filtering."""

    claims: list[ClaimResponse]
    total: int
    grounding_status_filter: str | None = None


class WeeklyRateEntry(BaseModel):
    """Single weekly ungrounded-claim rate entry.

    Requirements: 4.2
    """

    prepare_technique_id: str
    week_start: date
    week_end: date
    total_claims_extracted: int
    ungrounded_claims: int
    partially_grounded_claims: int
    ungrounded_rate: float = Field(..., ge=0.0, le=1.0)
    partially_grounded_rate: float = Field(..., ge=0.0, le=1.0)


class GroundingRatesResponse(BaseModel):
    """Weekly ungrounded rates per technique.

    Requirements: 4.2
    """

    rates: list[WeeklyRateEntry]
    period_weeks: int


class GroundingTrendResponse(BaseModel):
    """Trailing weekly trend for a specific technique.

    Requirements: 4.2
    """

    technique_id: str
    weeks: int
    trend: list[WeeklyRateEntry]


# ─── Helper functions ─────────────────────────────────────────────────────────


def _claim_to_response(claim) -> ClaimResponse:
    """Convert a domain Claim dataclass to a ClaimResponse."""
    source_pointer = None
    if claim.source_pointer is not None:
        source_pointer = SourcePointerResponse(
            asset_type=claim.source_pointer.asset_type,
            asset_id=claim.source_pointer.asset_id,
            passage=claim.source_pointer.passage,
            confidence=claim.source_pointer.confidence,
        )

    return ClaimResponse(
        id=claim.id,
        material_id=claim.material_id,
        category=claim.category.value if hasattr(claim.category, "value") else claim.category,
        claim_text=claim.claim_text,
        source_span=claim.source_span,
        source_span_start=claim.source_span_start,
        source_span_end=claim.source_span_end,
        grounding_status=(
            claim.grounding_status.value
            if claim.grounding_status and hasattr(claim.grounding_status, "value")
            else claim.grounding_status
        ),
        source_pointer=source_pointer,
        discrepancy=claim.discrepancy,
        is_prospect_side=claim.is_prospect_side,
    )


def _report_to_response(report) -> GroundingReportResponse:
    """Convert a domain GroundingReport dataclass to a GroundingReportResponse."""
    return GroundingReportResponse(
        id=report.id,
        material_id=report.material_id,
        pipeline_record_id=report.pipeline_record_id,
        claims=[_claim_to_response(c) for c in report.claims],
        total_claims=report.total_claims,
        grounded_count=report.grounded_count,
        partially_grounded_count=report.partially_grounded_count,
        ungrounded_count=report.ungrounded_count,
        material_grounding_status=(
            report.material_grounding_status.value
            if hasattr(report.material_grounding_status, "value")
            else report.material_grounding_status
        ),
        extraction_duration_ms=report.extraction_duration_ms,
        verification_duration_ms=report.verification_duration_ms,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def _result_to_response(result) -> GroundingResultResponse:
    """Convert a domain GroundingResult to a GroundingResultResponse."""
    return GroundingResultResponse(
        material_id=result.material_id,
        material_grounding_status=(
            result.material_grounding_status.value
            if hasattr(result.material_grounding_status, "value")
            else result.material_grounding_status
        ),
        grounding_report=_report_to_response(result.grounding_report),
        blocked_states=result.blocked_states,
        requires_action=result.requires_action,
    )


# ─── Routes ──────────────────────────────────────────────────────────────────


async def _notify_resolution_outcome(result) -> None:
    """Emit WebSocket notification after resolution completes.

    If no ungrounded claims remain (material is now grounding_verified),
    broadcasts a pipeline_unblocked notification so the Dashboard can
    update in real time.

    If still blocked, broadcasts a still_blocked notification with the
    remaining ungrounded claims for continued resolution.

    Requirements: 3.2, 3.3
    """
    import logging

    from app.core.grounding_verifier import MaterialGroundingStatus

    logger = logging.getLogger(__name__)

    try:
        from app.core.grounding_notifications import GroundingNotificationService
        from app.core.websocket_manager import WebSocketManager

        ws_manager = WebSocketManager()
        notification_service = GroundingNotificationService(ws_manager=ws_manager)

        status = result.material_grounding_status
        if isinstance(status, str):
            status = MaterialGroundingStatus(status)

        if status == MaterialGroundingStatus.GROUNDING_VERIFIED:
            # Material is unblocked — pipeline transitions are now allowed
            notification = {
                "category": "pipeline_unblocked",
                "title": "Material unblocked — grounding verified",
                "message": (
                    f"Material {result.material_id[:8]}... has been resolved. "
                    f"All claims are now grounded. Pipeline can advance."
                ),
                "material_id": result.material_id,
                "pipeline_record_id": result.grounding_report.pipeline_record_id,
                "severity": "success",
                "material_grounding_status": "grounding_verified",
            }
            await ws_manager.broadcast_notification(notification)

            logger.info(
                "Sent pipeline_unblocked notification: material=%s",
                result.material_id,
            )
        elif status == MaterialGroundingStatus.GROUNDING_BLOCKED:
            # Still blocked — notify with remaining ungrounded claims
            await notification_service.notify_requires_action(result)

            logger.info(
                "Material %s still blocked after resolution: %d ungrounded claims remain",
                result.material_id,
                result.grounding_report.ungrounded_count,
            )

    except Exception as exc:
        # Notification failure is non-critical — log and continue
        logging.getLogger(__name__).warning(
            "Failed to send resolution notification for material '%s': %s",
            result.material_id,
            exc,
        )


@router.post("/resolve", response_model=GroundingResultResponse)
async def resolve_grounding(request: GroundingResolveRequest) -> GroundingResultResponse:
    """Dispatch a resolution action for a blocked material.

    Three resolution paths are available:
    - regenerate: re-generates flagged passages excluding ungrounded claims
    - manual_edit: accepts edited content and re-verifies affected claims
    - confirm_and_add: confirms a claim as true and adds supporting fact to profile

    After resolution completes:
    - If no ungrounded claims remain: emits WebSocket notification that material
      is unblocked and pipeline transitions are allowed.
    - If still blocked: returns remaining ungrounded claims for continued resolution.

    Returns the updated grounding result with new gate status.

    Requirements: 3.2, 3.3
    """
    from app.core.grounding_verifier import GroundingVerifier, MaterialGroundingStatus
    from app.models.base import get_async_engine, get_async_session_factory
    from app.repositories.grounding_repository import GroundingRepository

    try:
        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)
        db_repo = GroundingRepository(session_factory)

        # Build GroundingVerifier with repository (other deps stubbed for resolution)
        verifier = GroundingVerifier(
            llm_router=None,
            schema_registry=None,
            db_repo=db_repo,
            personalization_engine=None,
        )

        if request.resolution_path == ResolutionPathEnum.regenerate:
            result = await verifier.resolve_regenerate(
                material_id=request.material_id,
                ungrounded_claim_ids=request.claim_ids,
            )

        elif request.resolution_path == ResolutionPathEnum.manual_edit:
            if request.edited_content is None:
                raise HTTPException(
                    status_code=422,
                    detail="edited_content is required for manual_edit resolution path",
                )
            result = await verifier.re_verify_claims(
                material_id=request.material_id,
                affected_claim_ids=request.claim_ids,
                updated_material_text=request.edited_content,
            )

        elif request.resolution_path == ResolutionPathEnum.confirm_and_add:
            if request.supporting_fact is None or request.target_asset_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="supporting_fact and target_asset_id are required for confirm_and_add resolution path",
                )
            result = await verifier.resolve_confirm_and_add(
                material_id=request.material_id,
                claim_id=request.claim_ids[0],
                supporting_fact=request.supporting_fact,
                target_asset_id=request.target_asset_id,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown resolution path: {request.resolution_path}",
            )

        # ─── Pipeline unblocking notification (Task 16.2) ─────────────────
        # After resolution completes, if no ungrounded claims remain,
        # emit WebSocket notification that material is unblocked.
        # Requirements: 3.2, 3.3
        await _notify_resolution_outcome(result)

        await engine.dispose()
        return _result_to_response(result)

    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Resolution failed: {exc}") from exc


@router.get("/reports/{pipeline_record_id}", response_model=GroundingReportResponse)
async def get_grounding_report(pipeline_record_id: str) -> GroundingReportResponse:
    """Get the latest grounding report for a pipeline record.

    Returns the full report with all claims, counts, and timing data.

    Requirements: 2.4, 3.1
    """
    from app.models.base import get_async_engine, get_async_session_factory
    from app.repositories.grounding_repository import GroundingRepository

    try:
        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)
        db_repo = GroundingRepository(session_factory)

        report = await db_repo.get_latest_grounding_report(pipeline_record_id)
        await engine.dispose()

        if report is None:
            raise HTTPException(
                status_code=404,
                detail=f"No grounding report found for pipeline record {pipeline_record_id}",
            )

        return _report_to_response(report)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve grounding report: {exc}"
        ) from exc


@router.get("/reports/{pipeline_record_id}/claims", response_model=ClaimListResponse)
async def get_grounding_claims(
    pipeline_record_id: str,
    grounding_status: str | None = Query(
        default=None,
        description="Filter claims by status: grounded, partially_grounded, ungrounded",
    ),
) -> ClaimListResponse:
    """Get claims from the latest grounding report with optional status filter.

    Useful for displaying only ungrounded or partially_grounded claims
    in the Dashboard 'Requires Action' section.

    Requirements: 2.4, 3.1
    """
    from app.core.grounding_verifier import GroundingStatus
    from app.models.base import get_async_engine, get_async_session_factory
    from app.repositories.grounding_repository import GroundingRepository

    try:
        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)
        db_repo = GroundingRepository(session_factory)

        report = await db_repo.get_latest_grounding_report(pipeline_record_id)
        await engine.dispose()

        if report is None:
            raise HTTPException(
                status_code=404,
                detail=f"No grounding report found for pipeline record {pipeline_record_id}",
            )

        claims = report.claims

        # Apply grounding_status filter if provided
        if grounding_status is not None:
            # Validate the filter value
            valid_statuses = {s.value for s in GroundingStatus}
            if grounding_status not in valid_statuses:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid grounding_status filter: '{grounding_status}'. "
                    f"Must be one of: {', '.join(sorted(valid_statuses))}",
                )
            claims = [
                c for c in claims
                if c.grounding_status and c.grounding_status.value == grounding_status
            ]

        return ClaimListResponse(
            claims=[_claim_to_response(c) for c in claims],
            total=len(claims),
            grounding_status_filter=grounding_status,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve claims: {exc}"
        ) from exc


@router.get("/analytics/rates", response_model=GroundingRatesResponse)
async def get_grounding_rates(
    period_weeks: int = Query(
        default=4,
        ge=1,
        le=52,
        description="Number of trailing weeks to compute rates for",
    ),
) -> GroundingRatesResponse:
    """Get weekly ungrounded-claim rates per prepare technique.

    Returns one entry per technique per week within the trailing period.
    Used in the Dashboard Reports stage to detect prompt regressions.

    Requirements: 4.2
    """
    from app.core.grounding_analytics_service import GroundingAnalyticsService
    from app.models.base import get_async_engine, get_async_session_factory

    try:
        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)
        analytics_service = GroundingAnalyticsService(session_factory)

        rates = await analytics_service.compute_ungrounded_claim_rates(
            period_weeks=period_weeks,
        )
        await engine.dispose()

        return GroundingRatesResponse(
            rates=[
                WeeklyRateEntry(
                    prepare_technique_id=r.prepare_technique_id,
                    week_start=r.week_start,
                    week_end=r.week_end,
                    total_claims_extracted=r.total_claims_extracted,
                    ungrounded_claims=r.ungrounded_claims,
                    partially_grounded_claims=r.partially_grounded_claims,
                    ungrounded_rate=r.ungrounded_rate,
                    partially_grounded_rate=r.partially_grounded_rate,
                )
                for r in rates
            ],
            period_weeks=period_weeks,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to compute grounding rates: {exc}"
        ) from exc


@router.get("/analytics/trend/{technique_id}", response_model=GroundingTrendResponse)
async def get_grounding_trend(
    technique_id: str,
    weeks: int = Query(
        default=12,
        ge=1,
        le=52,
        description="Number of trailing weeks to include in the trend",
    ),
) -> GroundingTrendResponse:
    """Get the trailing weekly ungrounded-claim rate trend for a technique.

    Returns one entry per week for the trailing N weeks (zero-filled
    for weeks with no data). Used for trend visualization in the Reports stage.

    Requirements: 4.2
    """
    from app.core.grounding_analytics_service import GroundingAnalyticsService
    from app.models.base import get_async_engine, get_async_session_factory

    try:
        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)
        analytics_service = GroundingAnalyticsService(session_factory)

        trend_data = await analytics_service.get_grounding_trend(
            prepare_technique_id=technique_id,
            weeks=weeks,
        )
        await engine.dispose()

        return GroundingTrendResponse(
            technique_id=technique_id,
            weeks=weeks,
            trend=[
                WeeklyRateEntry(
                    prepare_technique_id=r.prepare_technique_id,
                    week_start=r.week_start,
                    week_end=r.week_end,
                    total_claims_extracted=r.total_claims_extracted,
                    ungrounded_claims=r.ungrounded_claims,
                    partially_grounded_claims=r.partially_grounded_claims,
                    ungrounded_rate=r.ungrounded_rate,
                    partially_grounded_rate=r.partially_grounded_rate,
                )
                for r in trend_data
            ],
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve grounding trend: {exc}"
        ) from exc


class WarningBadgeResponse(BaseModel):
    """Response from the warning badge check.

    Requirements: 3.4
    """

    pipeline_record_id: str
    show_warning: bool


@router.get("/warning-badge/{pipeline_record_id}", response_model=WarningBadgeResponse)
async def get_warning_badge(pipeline_record_id: str) -> WarningBadgeResponse:
    """Check if a pipeline record should display a grounding warning badge.

    Returns show_warning=True when the material has partially_grounded claims
    but no ungrounded claims (pipeline can advance with warning).

    Requirements: 3.4
    """
    from app.core.pipeline_gate import PipelineGateService
    from app.models.base import get_async_engine, get_async_session_factory
    from app.repositories.grounding_repository import GroundingRepository

    try:
        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)
        db_repo = GroundingRepository(session_factory)
        gate_service = PipelineGateService(db_repo=db_repo)

        show_warning = await gate_service.get_warning_badge(pipeline_record_id)
        await engine.dispose()

        return WarningBadgeResponse(
            pipeline_record_id=pipeline_record_id,
            show_warning=show_warning,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to check warning badge: {exc}"
        ) from exc
