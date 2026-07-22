"""Review processing background worker.

Implements the ARQ task function for:
- run_review_processing: Fetch pending review items and dispatch
  fresh-context LLM critiques via ReviewService.review_batch().

The worker is lightweight — actual concurrency control (semaphore-bounded
to 3 concurrent critique requests) lives in ReviewService.

Requirements: 3.5
"""

import logging
import time

from sqlalchemy import text

from app.models.base import get_async_engine, get_async_session_factory

logger = logging.getLogger(__name__)


class ReviewWorker:
    """Manages batch review processing via the Review_Service.

    Fetches pending draft materials, splits into batches of BATCH_SIZE,
    and calls review_service.review_batch() with bounded concurrency.

    Class Constants:
        BATCH_SIZE: Maximum materials per processing batch (10).
        CONCURRENCY_LIMIT: Max simultaneous critique requests (3).
    """

    BATCH_SIZE: int = 10
    CONCURRENCY_LIMIT: int = 3


# Module-level aliases for backward compatibility
BATCH_SIZE = ReviewWorker.BATCH_SIZE
CONCURRENCY_LIMIT = ReviewWorker.CONCURRENCY_LIMIT


async def _fetch_pending_reviews(limit: int) -> list[dict]:
    """Query pipeline_records that are awaiting review.

    Fetches materials in 'review_pending' status that have not yet been
    picked up by a review worker. Returns a list of dicts with the fields
    needed to construct DraftMaterial instances.

    Args:
        limit: Maximum number of pending items to fetch.

    Returns:
        List of dicts with keys: id, pipeline_record_id, prepare_technique_id,
        material_type, content, quality_score, generated_at.
    """
    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    try:
        async with session_factory() as session:
            stmt = text("""
                SELECT
                    pm.id,
                    pm.pipeline_record_id,
                    pm.prepare_technique_id,
                    pm.material_type,
                    pm.content,
                    pm.quality_score,
                    pm.generated_at
                FROM pipeline_materials pm
                JOIN pipeline_records pr ON pr.id = pm.pipeline_record_id
                WHERE pm.review_status = 'review_pending'
                ORDER BY pm.generated_at ASC
                LIMIT :limit
            """)

            result = await session.execute(stmt, {"limit": limit})
            rows = result.fetchall()

            return [
                {
                    "id": str(row[0]),
                    "pipeline_record_id": str(row[1]),
                    "prepare_technique_id": row[2],
                    "material_type": row[3],
                    "content": row[4],
                    "quality_score": row[5],
                    "generated_at": row[6],
                }
                for row in rows
            ]
    finally:
        await engine.dispose()


async def run_review_processing(ctx: dict) -> dict:
    """Fetch pending review items and dispatch batch critique via ReviewService.

    Triggered on schedule or when new materials are queued for review.
    Fetches up to BATCH_SIZE pending materials and delegates to
    ReviewService.review_batch() which handles concurrency internally.

    Args:
        ctx: ARQ worker context. May contain:
            - 'review_service': Pre-initialized ReviewService instance
            - 'prospect': Prospect object for the batch
            - 'beneficiary': Beneficiary object for grounding
            - 'enrichment': Enrichment record for context
            - 'opportunity_description': Description of the opportunity

    Returns:
        Summary dict with processing statistics:
            - processed: Total items attempted
            - reviewed: Items successfully reviewed
            - unreviewed: Items that degraded gracefully
            - failed: Items that encountered errors
            - elapsed_seconds: Total processing time
    """
    start_time = time.monotonic()
    logger.info("Starting review processing worker run")

    # Fetch pending items
    pending = await _fetch_pending_reviews(limit=BATCH_SIZE)

    if not pending:
        logger.info("No pending review items found, exiting early")
        return {
            "processed": 0,
            "reviewed": 0,
            "unreviewed": 0,
            "failed": 0,
            "elapsed_seconds": 0.0,
        }

    logger.info("Fetched %d pending review items", len(pending))

    # Import here to avoid circular imports at module level
    from datetime import datetime, timezone

    from app.core.review_models import DraftMaterial, ReviewStatus
    from app.core.review_service import ReviewService

    # Build DraftMaterial instances from raw query results
    materials = [
        DraftMaterial(
            id=item["id"],
            pipeline_record_id=item["pipeline_record_id"],
            prepare_technique_id=item["prepare_technique_id"],
            material_type=item["material_type"],
            content=item["content"],
            quality_score=item["quality_score"] or 0,
            generated_at=item["generated_at"] or datetime.now(timezone.utc),
        )
        for item in pending
    ]

    # Extract service dependencies from worker context
    review_service: ReviewService | None = (
        ctx.get("review_service") if isinstance(ctx, dict) else None
    )
    prospect = ctx.get("prospect") if isinstance(ctx, dict) else None
    beneficiary = (
        ctx.get("beneficiary") if isinstance(ctx, dict) else None
    )
    enrichment = (
        ctx.get("enrichment") if isinstance(ctx, dict) else None
    )
    opportunity_description = (
        ctx.get("opportunity_description", "")
        if isinstance(ctx, dict)
        else ""
    )

    reviewed = 0
    unreviewed = 0
    failed = 0

    if review_service is None:
        logger.error("No review_service in worker context, cannot process reviews")
        elapsed = time.monotonic() - start_time
        return {
            "processed": len(materials),
            "reviewed": 0,
            "unreviewed": 0,
            "failed": len(materials),
            "elapsed_seconds": round(elapsed, 2),
        }

    try:
        results = await review_service.review_batch(
            materials=materials,
            prospect=prospect,
            beneficiary=beneficiary,
            enrichment=enrichment,
            opportunity_description=opportunity_description,
        )

        for result in results:
            if result.review_status == ReviewStatus.REVIEWED:
                reviewed += 1
            elif result.review_status == ReviewStatus.UNREVIEWED:
                unreviewed += 1
            else:
                failed += 1

    except Exception as e:
        logger.error("Review batch processing failed: %s", str(e))
        failed = len(materials)

    elapsed = time.monotonic() - start_time
    summary = {
        "processed": len(materials),
        "reviewed": reviewed,
        "unreviewed": unreviewed,
        "failed": failed,
        "elapsed_seconds": round(elapsed, 2),
    }
    logger.info("Review processing complete: %s", summary)
    return summary
