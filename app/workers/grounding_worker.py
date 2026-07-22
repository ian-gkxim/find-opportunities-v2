"""Grounding verification background worker.

Implements the ARQ task functions for:
- run_grounding_processing: Fetch pending grounding verification items and
  dispatch batch verification via GroundingVerifier.verify_batch().
- run_grounding_analytics: Daily computation of ungrounded-claim rates per
  prepare technique per week (grounding_analytics_weekly).

The worker is lightweight — actual concurrency control (semaphore-bounded
to 3 concurrent verification requests) lives in GroundingVerifier.

Requirements: 1.1, 4.2
"""

import logging
import time

from sqlalchemy import text

from app.models.base import get_async_engine, get_async_session_factory

logger = logging.getLogger(__name__)


class GroundingWorker:
    """Manages batch grounding verification processing.

    Fetches pending materials that need grounding verification, splits into
    batches of BATCH_SIZE, and calls GroundingVerifier.verify_batch() with
    bounded concurrency.

    Class Constants:
        BATCH_SIZE: Maximum materials per processing batch (10).
        CONCURRENCY_LIMIT: Max simultaneous verification requests (3).
    """

    BATCH_SIZE: int = 10
    CONCURRENCY_LIMIT: int = 3


# Module-level aliases for backward compatibility
BATCH_SIZE = GroundingWorker.BATCH_SIZE
CONCURRENCY_LIMIT = GroundingWorker.CONCURRENCY_LIMIT


async def _fetch_pending_verifications(limit: int) -> list[dict]:
    """Query pipeline materials awaiting grounding verification.

    Fetches materials that have completed review but do not yet have a
    grounding report, or materials marked as 'grounding_unverified' that
    should be retried.

    Args:
        limit: Maximum number of pending items to fetch.

    Returns:
        List of dicts with keys: material_id, pipeline_record_id,
        prepare_technique_id, content, beneficiary_id, enrichment_id.
    """
    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    try:
        async with session_factory() as session:
            stmt = text("""
                SELECT
                    pm.id AS material_id,
                    pm.pipeline_record_id,
                    pm.prepare_technique_id,
                    pm.content,
                    pr.beneficiary_id,
                    pr.prospect_id
                FROM pipeline_materials pm
                JOIN pipeline_records pr ON pr.id = pm.pipeline_record_id
                LEFT JOIN grounding_reports gr
                    ON gr.material_id = pm.id::text
                WHERE pm.review_status = 'reviewed'
                  AND (
                      gr.id IS NULL
                      OR gr.material_grounding_status = 'grounding_unverified'
                  )
                ORDER BY pm.generated_at ASC
                LIMIT :limit
            """)

            result = await session.execute(stmt, {"limit": limit})
            rows = result.fetchall()

            return [
                {
                    "material_id": str(row[0]),
                    "pipeline_record_id": str(row[1]),
                    "prepare_technique_id": row[2],
                    "content": row[3],
                    "beneficiary_id": str(row[4]),
                    "prospect_id": str(row[5]),
                }
                for row in rows
            ]
    finally:
        await engine.dispose()


async def run_grounding_processing(ctx: dict) -> dict:
    """Fetch pending grounding items and dispatch batch verification.

    Triggered on schedule or when new materials complete review and are
    ready for grounding verification. Fetches up to BATCH_SIZE pending
    materials and delegates to GroundingVerifier.verify_batch() which
    handles concurrency internally via semaphore (max 3).

    Args:
        ctx: ARQ worker context. May contain:
            - 'grounding_verifier': Pre-initialized GroundingVerifier instance
            - 'grounding_repository': GroundingRepository for DB operations

    Returns:
        Summary dict with processing statistics:
            - processed: Total items attempted
            - verified: Items with all claims grounded
            - blocked: Items with ungrounded claims (pipeline blocked)
            - unverified: Items where extraction failed gracefully
            - elapsed_seconds: Total processing time
    """
    start_time = time.monotonic()
    logger.info("Starting grounding processing worker run")

    # Fetch pending items
    pending = await _fetch_pending_verifications(limit=BATCH_SIZE)

    if not pending:
        logger.info("No pending grounding verification items found, exiting early")
        return {
            "processed": 0,
            "verified": 0,
            "blocked": 0,
            "unverified": 0,
            "elapsed_seconds": 0.0,
        }

    logger.info("Fetched %d pending grounding verification items", len(pending))

    # Import here to avoid circular imports at module level
    from app.core.grounding_verifier import (
        GroundingVerifier,
        MaterialGroundingStatus,
    )

    # Extract service dependencies from worker context
    grounding_verifier: GroundingVerifier | None = (
        ctx.get("grounding_verifier") if isinstance(ctx, dict) else None
    )

    if grounding_verifier is None:
        logger.error(
            "No grounding_verifier in worker context, cannot process verifications"
        )
        elapsed = time.monotonic() - start_time
        return {
            "processed": len(pending),
            "verified": 0,
            "blocked": 0,
            "unverified": len(pending),
            "elapsed_seconds": round(elapsed, 2),
        }

    # Build lightweight material objects for verify_batch
    from dataclasses import dataclass

    @dataclass
    class _PendingMaterial:
        """Lightweight wrapper for materials pending grounding verification."""

        id: str
        pipeline_record_id: str
        text: str

    materials = [
        _PendingMaterial(
            id=item["material_id"],
            pipeline_record_id=item["pipeline_record_id"],
            text=item["content"] or "",
        )
        for item in pending
    ]

    # Get beneficiary and enrichment from context (batch assumes same beneficiary)
    beneficiary = ctx.get("beneficiary") if isinstance(ctx, dict) else None
    enrichment = ctx.get("enrichment") if isinstance(ctx, dict) else None

    verified = 0
    blocked = 0
    unverified = 0

    try:
        results = await grounding_verifier.verify_batch(
            materials=materials,
            beneficiary=beneficiary,
            enrichment=enrichment,
        )

        for result in results:
            if result.material_grounding_status == MaterialGroundingStatus.GROUNDING_VERIFIED:
                verified += 1
            elif result.material_grounding_status == MaterialGroundingStatus.GROUNDING_BLOCKED:
                blocked += 1
            elif result.material_grounding_status == MaterialGroundingStatus.GROUNDING_UNVERIFIED:
                unverified += 1

    except Exception as e:
        logger.error("Grounding batch processing failed: %s", str(e))
        unverified = len(materials)

    elapsed = time.monotonic() - start_time
    summary = {
        "processed": len(materials),
        "verified": verified,
        "blocked": blocked,
        "unverified": unverified,
        "elapsed_seconds": round(elapsed, 2),
    }
    logger.info("Grounding processing complete: %s", summary)
    return summary


async def run_grounding_analytics(ctx: dict) -> dict:
    """Compute weekly ungrounded-claim rates for grounding_analytics_weekly.

    Triggered daily via cron to compute the ungrounded-claim rate per
    prepare technique for the current trailing period (default 1 week).
    Calls GroundingAnalyticsService.compute_ungrounded_claim_rates() which
    groups grounding reports by technique and ISO week, then upserts
    results into the grounding_analytics_weekly table.

    Args:
        ctx: ARQ worker context. May contain:
            - 'analytics_service': Pre-initialized GroundingAnalyticsService

    Returns:
        Summary dict with:
            - techniques_computed: Number of technique/week combinations processed
            - period_weeks: Trailing period used for computation
            - computed_at: ISO timestamp of computation
    """
    from datetime import datetime, timezone

    logger.info("Starting grounding analytics aggregation")

    # Try to get analytics_service from context, otherwise create one
    analytics_service = ctx.get("analytics_service") if isinstance(ctx, dict) else None

    if analytics_service is None:
        # Initialize from DB
        from app.core.grounding_analytics_service import GroundingAnalyticsService

        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)
        analytics_service = GroundingAnalyticsService(session_factory)

    try:
        # Compute rates for the trailing period (current week)
        rates = await analytics_service.compute_ungrounded_claim_rates(
            period_weeks=1,
        )

        summary = {
            "techniques_computed": len(rates),
            "period_weeks": 1,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("Grounding analytics aggregation complete: %s", summary)
        return summary

    except Exception as e:
        logger.error("Grounding analytics aggregation failed: %s", str(e))
        return {
            "techniques_computed": 0,
            "period_weeks": 1,
            "error": str(e),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
