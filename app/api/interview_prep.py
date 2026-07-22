"""Interview Prep API — endpoints for retrieving and regenerating Interview_Prep_Packs.

Provides REST API for Dashboard consumption:
- GET /interview-prep/{pipeline_record_id} — retrieve pack
- GET /interview-prep/{pipeline_record_id}/status — check generation status
- POST /interview-prep/{pipeline_record_id}/regenerate — trigger regeneration

Requirements: 3.2
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/interview-prep", tags=["interview-prep"])


# ─── Response Models ──────────────────────────────────────────────────────────


class STARTalkingPointResponse(BaseModel):
    competency: str
    question: str
    situation: str
    task: str
    action: str
    result: str
    source_asset_refs: list[str]
    is_gap_handled: bool
    gap_note: str | None


class InterviewPrepPackResponse(BaseModel):
    id: str
    pipeline_record_id: str
    beneficiary_id: str
    opportunity_type_id: str
    likely_questions: list[str]
    star_talking_points: list[STARTalkingPointResponse]
    company_briefing: str
    questions_to_ask: list[str]
    status: str
    omission_notes: list[str]
    grounding_flags: list[str]
    generation_duration_ms: int
    created_at: str
    updated_at: str


class PackStatusResponse(BaseModel):
    pipeline_record_id: str
    status: str
    pack_id: str | None


class RegenerateResponse(BaseModel):
    message: str
    pipeline_record_id: str


# ─── Dependency placeholder ──────────────────────────────────────────────────


async def get_interview_prep_repository():
    """Dependency injection for InterviewPrepRepository.

    In production, this is resolved via FastAPI's dependency injection.
    For testing, it can be overridden.
    """
    from app.core.interview_prep_repository import InterviewPrepRepository
    from app.models.base import get_async_session_factory

    session_factory = get_async_session_factory()
    return InterviewPrepRepository(session_factory)


async def get_redis_pool():
    """Dependency injection for ARQ Redis pool."""
    return None  # Resolved at runtime


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/{pipeline_record_id}", response_model=InterviewPrepPackResponse)
async def get_interview_prep_pack(
    pipeline_record_id: str,
    repo=Depends(get_interview_prep_repository),
):
    """Retrieve the Interview_Prep_Pack for a pipeline record.

    Returns 404 if no pack exists (generation not triggered or still pending).
    """
    pack = await repo.get_pack(pipeline_record_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="No interview prep pack found")

    return InterviewPrepPackResponse(
        id=pack.id,
        pipeline_record_id=pack.pipeline_record_id,
        beneficiary_id=pack.beneficiary_id,
        opportunity_type_id=pack.opportunity_type_id,
        likely_questions=pack.likely_questions,
        star_talking_points=[
            STARTalkingPointResponse(
                competency=tp.competency,
                question=tp.question,
                situation=tp.situation,
                task=tp.task,
                action=tp.action,
                result=tp.result,
                source_asset_refs=tp.source_asset_refs,
                is_gap_handled=tp.is_gap_handled,
                gap_note=tp.gap_note,
            )
            for tp in pack.star_talking_points
        ],
        company_briefing=pack.company_briefing,
        questions_to_ask=pack.questions_to_ask,
        status=pack.status.value,
        omission_notes=pack.omission_notes,
        grounding_flags=pack.grounding_flags,
        generation_duration_ms=pack.generation_duration_ms,
        created_at=pack.created_at.isoformat() if pack.created_at else "",
        updated_at=pack.updated_at.isoformat() if pack.updated_at else "",
    )


@router.get("/{pipeline_record_id}/status", response_model=PackStatusResponse)
async def get_pack_generation_status(
    pipeline_record_id: str,
    repo=Depends(get_interview_prep_repository),
):
    """Check current generation status."""
    pack = await repo.get_pack(pipeline_record_id)
    if pack is None:
        return PackStatusResponse(
            pipeline_record_id=pipeline_record_id,
            status="not_started",
            pack_id=None,
        )
    return PackStatusResponse(
        pipeline_record_id=pipeline_record_id,
        status=pack.status.value,
        pack_id=pack.id,
    )


@router.post(
    "/{pipeline_record_id}/regenerate",
    response_model=RegenerateResponse,
    status_code=202,
)
async def regenerate_interview_prep(
    pipeline_record_id: str,
    redis_pool=Depends(get_redis_pool),
):
    """Trigger on-demand regeneration of the Interview_Prep_Pack.

    Enqueues a regeneration job. Returns 202 Accepted.
    """
    if redis_pool:
        await redis_pool.enqueue_job(
            "regenerate_interview_prep", pipeline_record_id
        )

    return RegenerateResponse(
        message="Regeneration job enqueued",
        pipeline_record_id=pipeline_record_id,
    )
