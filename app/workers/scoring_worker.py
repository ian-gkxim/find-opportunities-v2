"""Score recomputation background worker.

Implements the ARQ task function for:
- run_score_recomputation: Recompute account scores for all non-terminal
  prospects when scoring weights change or enrichment data updates.

Broadcasts score changes via WebSocket for real-time dashboard updates.

Requirements: 4.4
"""

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.scoring_engine import ScoreResult, ScoringEngine, ScoringWeights
from app.core.websocket_manager import WebSocketManager
from app.models.account_score import AccountScore
from app.models.base import get_async_engine, get_async_session_factory
from app.models.enrichment import EnrichmentRecord
from app.models.prospect import Prospect

logger = logging.getLogger(__name__)

# Terminal pipeline statuses — prospects in these states are not recomputed
TERMINAL_STATUSES = {"converted", "won", "lost", "abandoned"}

# SLA: recompute all non-terminal prospects within 60 seconds
RECOMPUTATION_SLA_SECONDS = 60

# Batch size for processing prospects
BATCH_SIZE = 100


async def run_score_recomputation(ctx: dict) -> dict:
    """Recompute account scores for all non-terminal prospects.

    Triggered when:
    1. Scoring weights are changed by the user
    2. Enrichment data is updated for a prospect

    Behavior:
    - Loads all non-terminal prospects (not in Converted/Won/Lost/Abandoned)
    - Recomputes each prospect's score using the current scoring weights
    - Updates the account_scores table with new values
    - Broadcasts score changes via WebSocket for real-time dashboard updates
    - Completes within the 60-second SLA

    Args:
        ctx: ARQ worker context. May contain:
            - 'weights': New ScoringWeights (if triggered by weight change)
            - 'prospect_id': Single prospect ID (if triggered by enrichment update)
            - 'redis': Redis client for WebSocket broadcasting

    Returns:
        Summary dict with recomputation statistics.
    """
    start_time = time.monotonic()
    logger.info("Starting score recomputation")

    # Extract context parameters
    new_weights = ctx.get("weights") if isinstance(ctx, dict) else None
    single_prospect_id = ctx.get("prospect_id") if isinstance(ctx, dict) else None
    redis_client = ctx.get("redis") if isinstance(ctx, dict) else None

    # Initialize scoring engine with new or default weights
    if new_weights and isinstance(new_weights, dict):
        weights = ScoringWeights(**new_weights)
    elif new_weights and isinstance(new_weights, ScoringWeights):
        weights = new_weights
    else:
        weights = ScoringWeights()  # Use defaults

    scoring_engine = ScoringEngine(weights=weights)

    # Initialize WebSocket manager for broadcasting
    ws_manager = WebSocketManager(redis_client=redis_client)

    recomputed = 0
    changed = 0
    errors = 0

    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    try:
        async with session_factory() as session:
            # Get prospects to recompute
            if single_prospect_id:
                prospects = await _get_single_prospect(session, single_prospect_id)
            else:
                prospects = await _get_non_terminal_prospects(session)

            total = len(prospects)
            logger.info("Found %d prospects for score recomputation", total)

            # Process in batches
            for i in range(0, total, BATCH_SIZE):
                batch = prospects[i : i + BATCH_SIZE]

                for prospect_data in batch:
                    try:
                        # Recompute score
                        new_score_result = _compute_prospect_score(
                            scoring_engine, prospect_data
                        )

                        # Check if score actually changed
                        old_score = prospect_data.get("current_score")
                        score_changed = (
                            old_score is None
                            or old_score != new_score_result.total_score
                        )

                        # Update the account_scores table
                        await _upsert_account_score(
                            session,
                            prospect_id=prospect_data["prospect_id"],
                            score_result=new_score_result,
                        )
                        recomputed += 1

                        # Broadcast change if score actually changed
                        if score_changed:
                            changed += 1
                            try:
                                await ws_manager.broadcast_score_change(
                                    prospect_id=str(prospect_data["prospect_id"]),
                                    new_score=new_score_result.total_score,
                                    new_tier=new_score_result.tier.value,
                                )
                            except Exception as ws_err:
                                logger.debug(
                                    "WebSocket broadcast failed for %s: %s",
                                    prospect_data["prospect_id"],
                                    str(ws_err),
                                )

                    except Exception as e:
                        logger.error(
                            "Failed to recompute score for prospect %s: %s",
                            prospect_data.get("prospect_id", "unknown"),
                            str(e),
                        )
                        errors += 1
                        continue

                # Commit batch
                await session.commit()

                # Check SLA
                elapsed = time.monotonic() - start_time
                if elapsed > RECOMPUTATION_SLA_SECONDS:
                    logger.warning(
                        "Score recomputation approaching SLA limit: "
                        "%.1fs elapsed, %d/%d processed",
                        elapsed,
                        recomputed,
                        total,
                    )

    finally:
        await engine.dispose()

    elapsed = time.monotonic() - start_time
    summary = {
        "total_prospects": total if "total" in dir() else 0,
        "recomputed": recomputed,
        "changed": changed,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 2),
        "within_sla": elapsed <= RECOMPUTATION_SLA_SECONDS,
    }
    logger.info("Score recomputation complete: %s", summary)
    return summary


# ─── Internal helper functions ────────────────────────────────────────────────


async def _get_non_terminal_prospects(session: AsyncSession) -> list[dict]:
    """Retrieve all prospects not in terminal pipeline states.

    Joins prospects with their enrichment data and current scores
    to provide all inputs needed for score computation.

    Returns:
        List of dicts containing prospect data for scoring.
    """
    # Query prospects that are NOT in terminal states
    stmt = text("""
        SELECT
            p.id as prospect_id,
            p.source_count,
            e.employee_count,
            e.revenue_range,
            e.industry,
            e.tech_stack,
            e.funding_stage,
            e.status as enrichment_status,
            a.total_score as current_score
        FROM prospects p
        LEFT JOIN enrichment_records e ON e.prospect_id = p.id
        LEFT JOIN account_scores a ON a.prospect_id = p.id
        WHERE NOT EXISTS (
            SELECT 1 FROM pipeline_records pr
            WHERE pr.prospect_id = p.id
              AND pr.is_terminal = true
        )
        ORDER BY p.created_at DESC
    """)

    result = await session.execute(stmt)
    rows = result.fetchall()

    return [
        {
            "prospect_id": row[0],
            "source_count": row[1],
            "employee_count": row[2],
            "revenue_range": row[3],
            "industry": row[4],
            "tech_stack": row[5],
            "funding_stage": row[6],
            "enrichment_status": row[7],
            "current_score": row[8],
        }
        for row in rows
    ]


async def _get_single_prospect(
    session: AsyncSession, prospect_id: str
) -> list[dict]:
    """Retrieve a single prospect's data for score recomputation.

    Used when triggered by an enrichment update for a specific prospect.
    """
    stmt = text("""
        SELECT
            p.id as prospect_id,
            p.source_count,
            e.employee_count,
            e.revenue_range,
            e.industry,
            e.tech_stack,
            e.funding_stage,
            e.status as enrichment_status,
            a.total_score as current_score
        FROM prospects p
        LEFT JOIN enrichment_records e ON e.prospect_id = p.id
        LEFT JOIN account_scores a ON a.prospect_id = p.id
        WHERE p.id = :prospect_id
    """)

    result = await session.execute(stmt, {"prospect_id": prospect_id})
    row = result.fetchone()

    if row is None:
        return []

    return [
        {
            "prospect_id": row[0],
            "source_count": row[1],
            "employee_count": row[2],
            "revenue_range": row[3],
            "industry": row[4],
            "tech_stack": row[5],
            "funding_stage": row[6],
            "enrichment_status": row[7],
            "current_score": row[8],
        }
    ]


def _compute_prospect_score(
    scoring_engine: ScoringEngine, prospect_data: dict
) -> ScoreResult:
    """Compute the score for a single prospect using available data.

    Maps the prospect's enrichment data to scoring sub-scores.
    Missing data results in None for that factor, which triggers
    proportional weight redistribution in the scoring engine.
    """
    # Determine available scoring inputs from enrichment data
    enrichment_status = prospect_data.get("enrichment_status")
    has_enrichment = enrichment_status == "complete"

    # Firmographic sub-score (simplified heuristic based on available data)
    firmographic = None
    if has_enrichment and prospect_data.get("employee_count"):
        # Simple size-based heuristic (in production, would use full profile matching)
        firmographic = _firmographic_heuristic(
            employee_count=prospect_data["employee_count"],
            revenue_range=prospect_data.get("revenue_range"),
            industry=prospect_data.get("industry"),
        )

    # Technographic sub-score
    technographic = None
    if has_enrichment and prospect_data.get("tech_stack"):
        tech_stack = prospect_data["tech_stack"]
        if isinstance(tech_stack, list) and len(tech_stack) > 0:
            # In production, would match against beneficiary profile
            technographic = min(len(tech_stack) * 10, 100)

    # Intent, LLM relevance, and historical are not available in this context
    # (would require additional queries or cached values)
    # These will be None, triggering proportional redistribution

    return scoring_engine.compute_score(
        firmographic=firmographic,
        technographic=technographic,
        intent=None,  # Would need intent signal query
        llm_relevance=None,  # Would need LLM evaluation
        historical=None,  # Would need historical conversion data
        source_count=prospect_data.get("source_count", 1),
        has_strong_intent=False,  # Would need intent signal check
    )


def _firmographic_heuristic(
    employee_count: int | None,
    revenue_range: str | None,
    industry: str | None,
) -> int:
    """Compute a simple firmographic sub-score based on company attributes.

    In production, this would be a more sophisticated profile-matching
    algorithm comparing against the beneficiary's ideal customer profile.
    """
    score = 50  # Base score

    if employee_count:
        if 50 <= employee_count <= 500:
            score += 20  # SMB sweet spot
        elif 500 < employee_count <= 5000:
            score += 15  # Mid-market
        elif employee_count > 5000:
            score += 10  # Enterprise
        else:
            score += 5  # Very small

    if industry:
        score += 10  # Having industry data is a positive signal

    if revenue_range:
        score += 10  # Having revenue data is a positive signal

    return min(score, 100)


async def _upsert_account_score(
    session: AsyncSession,
    prospect_id,
    score_result: ScoreResult,
) -> None:
    """Insert or update the account score for a prospect.

    Uses an upsert pattern to handle both new scores and updates
    to existing scores.
    """
    now = datetime.now(timezone.utc)

    stmt = text("""
        INSERT INTO account_scores
            (prospect_id, total_score, tier, factor_scores,
             missing_factors, is_partial, multi_source_bonus, computed_at)
        VALUES
            (:prospect_id, :score, :tier, :factors,
             :missing, :partial, :bonus, :computed_at)
        ON CONFLICT (prospect_id) DO UPDATE SET
            total_score = :score,
            tier = :tier,
            factor_scores = :factors,
            missing_factors = :missing,
            is_partial = :partial,
            multi_source_bonus = :bonus,
            computed_at = :computed_at
    """)

    import json

    await session.execute(
        stmt,
        {
            "prospect_id": str(prospect_id),
            "score": score_result.total_score,
            "tier": score_result.tier.value,
            "factors": json.dumps(score_result.factor_scores),
            "missing": json.dumps(score_result.missing_factors),
            "partial": score_result.is_partial,
            "bonus": score_result.multi_source_bonus,
            "computed_at": now,
        },
    )
