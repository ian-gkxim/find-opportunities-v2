"""Interview Prep Worker — ARQ background tasks for Interview_Prep_Pack generation.

Dispatched by PipelineManager on Interview state entry. Enforces the 120-second
overall deadline and surfaces failures in Dashboard "Requires Action".

Requirements: 1.1, 3.3
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.interview_prep_models import (
    DeadlineExceededError,
    InterviewPrepError,
    PackStatus,
)
from app.core.interview_prep_service import InterviewPrepService
from app.core.interview_prep_repository import InterviewPrepRepository

logger = logging.getLogger(__name__)

TOTAL_DEADLINE = 120.0  # seconds


async def process_interview_prep(ctx: dict, pipeline_record_id: str) -> dict:
    """ARQ task: generate Interview_Prep_Pack for a record entering Interview state.

    Dispatched by PipelineManager on Interview state entry.
    Enforces the 120-second overall deadline.
    On failure after MAX_RETRIES: marks pack as failed, surfaces in Requires Action.

    Returns:
        {"status": "ready" | "ready_with_flags" | "failed", "pack_id": str | None}
    """
    service = _build_service(ctx)

    try:
        async with asyncio.timeout(TOTAL_DEADLINE):
            pack = await service.generate_pack(pipeline_record_id)

        logger.info(
            "Interview prep pack generated for %s: status=%s, pack_id=%s",
            pipeline_record_id, pack.status.value, pack.id,
        )
        return {"status": pack.status.value, "pack_id": pack.id}

    except (asyncio.TimeoutError, DeadlineExceededError) as e:
        logger.error(
            "Interview prep generation timed out for %s: %s",
            pipeline_record_id, e,
        )
        return {"status": PackStatus.FAILED.value, "pack_id": None}

    except InterviewPrepError as e:
        logger.error(
            "Interview prep generation failed for %s: %s",
            pipeline_record_id, e,
        )
        return {"status": PackStatus.FAILED.value, "pack_id": None}

    except Exception as e:
        logger.exception(
            "Unexpected error generating interview prep for %s",
            pipeline_record_id,
        )
        return {"status": PackStatus.FAILED.value, "pack_id": None}


async def regenerate_interview_prep(ctx: dict, pipeline_record_id: str) -> dict:
    """ARQ task: regenerate pack on user demand.

    Same logic as initial generation but replaces existing pack.

    Returns:
        {"status": "ready" | "ready_with_flags" | "failed", "pack_id": str | None}
    """
    service = _build_service(ctx)

    try:
        async with asyncio.timeout(TOTAL_DEADLINE):
            pack = await service.regenerate_pack(pipeline_record_id)

        logger.info(
            "Interview prep pack regenerated for %s: status=%s, pack_id=%s",
            pipeline_record_id, pack.status.value, pack.id,
        )
        return {"status": pack.status.value, "pack_id": pack.id}

    except (asyncio.TimeoutError, DeadlineExceededError) as e:
        logger.error(
            "Interview prep regeneration timed out for %s: %s",
            pipeline_record_id, e,
        )
        return {"status": PackStatus.FAILED.value, "pack_id": None}

    except InterviewPrepError as e:
        logger.error(
            "Interview prep regeneration failed for %s: %s",
            pipeline_record_id, e,
        )
        return {"status": PackStatus.FAILED.value, "pack_id": None}

    except Exception as e:
        logger.exception(
            "Unexpected error regenerating interview prep for %s",
            pipeline_record_id,
        )
        return {"status": PackStatus.FAILED.value, "pack_id": None}


def _build_service(ctx: dict) -> InterviewPrepService:
    """Construct InterviewPrepService from ARQ worker context.

    The ctx dict is populated during worker startup with shared
    dependencies (session factory, LLM router, grounding verifier, etc.).
    """
    session_factory = ctx["session_factory"]
    llm_router = ctx["llm_router"]
    schema_registry = ctx["schema_registry"]

    # Build dependencies
    db_repo = InterviewPrepRepository(session_factory)
    grounding_verifier = ctx.get("grounding_verifier")
    event_publisher = ctx.get("event_publisher")

    return InterviewPrepService(
        llm_router=llm_router,
        grounding_verifier=grounding_verifier,
        schema_registry=schema_registry,
        db_repo=db_repo,
        event_publisher=event_publisher,
    )
