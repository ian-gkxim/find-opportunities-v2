"""Gap analytics background worker.

Implements the ARQ task function for:
- run_gap_analysis_cycle: Execute nightly gap analysis at 02:30 UTC
  (after run_analytics_daily at 02:00 UTC).

Extracts capabilities from lost/rejected/low-tier opportunities via the
LLM_Router, diffs against Beneficiary profiles, and generates prioritized
gap heatmaps with estimated blocked pipeline value.

Requirements: 1.1, 1.3
"""

import logging
import time
from datetime import datetime, timezone

from app.core.capability_normalizer import load_normalizer_from_db
from app.core.gap_analyzer import GapAnalysisConfig, GapAnalyzer
from app.models.base import get_async_engine, get_async_session_factory

logger = logging.getLogger(__name__)


async def run_gap_analysis_cycle(ctx: dict) -> dict:
    """ARQ task: Execute nightly gap analysis cycle.

    Scheduled at 02:30 UTC (after run_analytics_daily at 02:00 UTC).
    Configured with unique=True to prevent concurrent execution.

    Orchestrates:
    1. Fetch eligible opportunities (lost/rejected/C-D tier within window)
    2. Extract capabilities via LLM (bounded by batch cap, default 200)
    3. Carry forward unprocessed opportunities to next cycle
    4. Generate gap heatmaps for each Beneficiary and firm-level
    5. Compute trend diffs and notify Dashboard via WebSocket

    Args:
        ctx: ARQ worker context containing shared resources:
            - 'llm_router': LLM_Router instance for capability extraction
            - 'schema_registry': SchemaRegistry for Beneficiary profile access
            - 'redis_client': Async Redis client for extraction caching
            - 'ws_manager': WebSocketManager for Dashboard notifications

    Returns:
        Summary dict: {
            "extracted": int,
            "carried_forward": int,
            "heatmaps_generated": int,
            "duration_seconds": float,
            "timestamp": str
        }
    """
    start_time = time.monotonic()
    logger.info(
        "Starting gap analysis cycle at %s", datetime.now(timezone.utc).isoformat()
    )

    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    try:
        async with session_factory() as db_session:
            # Extract shared resources from ARQ worker context
            llm_router = ctx.get("llm_router") if isinstance(ctx, dict) else None
            schema_registry = ctx.get("schema_registry") if isinstance(ctx, dict) else None
            redis_client = ctx.get("redis_client") if isinstance(ctx, dict) else None
            ws_manager = ctx.get("ws_manager") if isinstance(ctx, dict) else None

            # Load configuration (use defaults; can be extended to load from DB)
            config = GapAnalysisConfig()

            # Load the capability normalizer from DB synonym mappings
            normalizer = await load_normalizer_from_db(db_session)

            # Instantiate the GapAnalyzer with all dependencies
            analyzer = GapAnalyzer(
                config=config,
                llm_router=llm_router,
                schema_registry=schema_registry,
                db_session=db_session,
                redis_client=redis_client,
                ws_manager=ws_manager,
                normalizer=normalizer,
            )

            # Execute the full nightly cycle
            summary = await analyzer.run_nightly_cycle()

    except Exception as exc:
        elapsed = time.monotonic() - start_time
        logger.error(
            "Gap analysis cycle failed after %.1fs: %s",
            elapsed,
            str(exc),
            exc_info=True,
        )
        return {
            "extracted": 0,
            "carried_forward": 0,
            "heatmaps_generated": 0,
            "duration_seconds": round(elapsed, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }
    finally:
        await engine.dispose()

    elapsed = time.monotonic() - start_time
    # Enrich the summary returned by run_nightly_cycle with timing and timestamp
    summary.setdefault("duration_seconds", round(elapsed, 2))
    summary["timestamp"] = datetime.now(timezone.utc).isoformat()

    logger.info("Gap analysis cycle complete in %.1fs: %s", elapsed, summary)
    return summary
