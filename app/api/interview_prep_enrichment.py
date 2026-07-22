"""Pipeline record detail enrichment with Interview_Prep_Pack data.

Adds interview_prep_pack field to pipeline record API responses when
a pack exists for the record.

Requirements: 3.2
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class InterviewPrepSummary(BaseModel):
    """Summary of interview prep pack for pipeline record detail view.

    Includes pack status, content counts, and action URLs for the Dashboard
    to present the pack and offer regeneration.
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


async def get_interview_prep_summary(
    pipeline_record_id: str,
) -> InterviewPrepSummary | None:
    """Build interview prep summary for a pipeline record's detail response.

    If a pack exists for this pipeline record, returns a summary with
    pack status, content, and action URLs. Returns None if no pack exists.

    Args:
        pipeline_record_id: The pipeline record UUID string.

    Returns:
        InterviewPrepSummary if a pack exists, None otherwise.
    """
    try:
        from app.core.interview_prep_repository import InterviewPrepRepository
        from app.models.base import get_async_session_factory

        session_factory = get_async_session_factory()
        repo = InterviewPrepRepository(session_factory)
        pack = await repo.get_pack(pipeline_record_id)
    except Exception:
        # If repository or DB not available, gracefully return None
        return None

    if pack is None:
        return None

    return InterviewPrepSummary(
        pack_id=pack.id,
        status=pack.status.value,
        likely_questions=pack.likely_questions,
        star_talking_points_count=len(pack.star_talking_points),
        company_briefing=pack.company_briefing,
        questions_to_ask=pack.questions_to_ask,
        has_grounding_flags=bool(pack.grounding_flags),
        generation_duration_ms=pack.generation_duration_ms,
        detail_url=f"/api/interview-prep/{pipeline_record_id}",
        regenerate_url=f"/api/interview-prep/{pipeline_record_id}/regenerate",
    )
