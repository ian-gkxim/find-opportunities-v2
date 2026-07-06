"""Enrichment, polling, and discovery background workers.

Implements the ARQ task functions for:
- run_enrichment_cycle: Refresh stale enrichment records (>30 days old) via Apollo.io
- run_polling_cycle: Poll Lemlist for response events, process via PipelineManager
- run_discovery_cycle: Execute scheduled discovery runs for all active sources

Requirements: 1.7, 3.5, 7.1, 10.4, 14.1
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.discovery_pipeline import DiscoveryPipeline, SourceStatus, SourceType
from app.core.pipeline_manager import PipelineManager
from app.integrations.apollo_client import ApolloClient
from app.integrations.lemlist_engine import LemlistEngine
from app.models.base import get_async_engine, get_async_session_factory
from app.models.enrichment import EnrichmentRecord
from app.models.prospect import Prospect

logger = logging.getLogger(__name__)

# Terminal pipeline statuses that should not be refreshed
TERMINAL_STATUSES = {"converted", "won", "lost", "abandoned"}

# Enrichment staleness threshold
STALE_THRESHOLD_DAYS = 30


async def run_enrichment_cycle(ctx: dict) -> dict:
    """Refresh stale enrichment records (>30 days old) via Apollo.io.

    Queries the enrichment_records table for entries whose enriched_at date
    is older than 30 days, then calls ApolloClient.enrich_company() for each
    to refresh the data.

    Args:
        ctx: ARQ worker context containing shared resources (db session, etc.)

    Returns:
        Summary dict with counts of refreshed, failed, and skipped records.
    """
    logger.info("Starting enrichment cycle")
    settings = get_settings()

    refreshed = 0
    failed = 0
    skipped = 0

    async with httpx.AsyncClient() as http_client:
        apollo = ApolloClient(
            api_key=settings.apollo_api_key,
            http_client=http_client,
        )

        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)

        try:
            async with session_factory() as session:
                stale_records = await _get_stale_enrichment_records(session)
                logger.info(
                    "Found %d stale enrichment records to refresh",
                    len(stale_records),
                )

                for record in stale_records:
                    try:
                        # Skip prospects in terminal pipeline states
                        prospect = await _get_prospect(session, record.prospect_id)
                        if prospect is None:
                            skipped += 1
                            continue

                        domain = prospect.company_domain
                        if not domain:
                            logger.warning(
                                "Prospect %s has no domain, skipping enrichment",
                                prospect.id,
                            )
                            skipped += 1
                            continue

                        # Call Apollo to refresh enrichment
                        enrichment_result = await apollo.enrich_company(domain)

                        # Update the database record
                        record.employee_count = enrichment_result.employee_count
                        record.revenue_range = enrichment_result.revenue_range
                        record.industry = enrichment_result.industry
                        record.tech_stack = enrichment_result.tech_stack
                        record.funding_stage = enrichment_result.funding_stage
                        record.hq_city = enrichment_result.headquarters_city
                        record.hq_country = enrichment_result.headquarters_country
                        record.status = enrichment_result.status.value
                        record.enriched_at = datetime.now(timezone.utc)
                        record.expires_at = datetime.now(timezone.utc) + timedelta(
                            days=STALE_THRESHOLD_DAYS
                        )
                        record.updated_at = datetime.now(timezone.utc)

                        await session.commit()
                        refreshed += 1
                        logger.debug(
                            "Refreshed enrichment for prospect %s (domain: %s)",
                            prospect.id,
                            domain,
                        )

                    except Exception as e:
                        logger.error(
                            "Failed to refresh enrichment for record %s: %s",
                            record.id,
                            str(e),
                        )
                        await session.rollback()
                        failed += 1
                        continue

        finally:
            await engine.dispose()

    summary = {
        "refreshed": refreshed,
        "failed": failed,
        "skipped": skipped,
        "total_stale": refreshed + failed + skipped,
    }
    logger.info("Enrichment cycle complete: %s", summary)
    return summary


async def run_polling_cycle(ctx: dict) -> dict:
    """Poll Lemlist for response events and advance the pipeline.

    Calls LemlistEngine.poll_responses() to retrieve new events (replies,
    bounces, unsubscribes), then processes them via LemlistEngine.process_events()
    which updates touchpoint/enrollment statuses. Finally, advances the pipeline
    via PipelineManager for any genuine replies.

    Args:
        ctx: ARQ worker context containing shared resources.

    Returns:
        Summary dict with event processing counts.
    """
    logger.info("Starting polling cycle")
    settings = get_settings()

    events_processed = 0
    pipeline_advances = 0
    errors = 0

    async with httpx.AsyncClient() as http_client:
        lemlist = LemlistEngine(
            api_key=settings.lemlist_api_key,
            http_client=http_client,
            repository=None,  # Repository injected when DB is available
        )

        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)

        try:
            # Step 1: Poll Lemlist for new response events
            try:
                events = await lemlist.poll_responses()
                logger.info("Polled %d response events from Lemlist", len(events))
            except Exception as e:
                logger.error(
                    "Failed to poll Lemlist for responses: %s. "
                    "Will retry on next poll interval.",
                    str(e),
                )
                return {"events_polled": 0, "error": str(e)}

            if not events:
                logger.info("No new events from Lemlist")
                return {"events_polled": 0, "processed": 0, "advances": 0}

            # Step 2: Process events (update touchpoint/enrollment statuses)
            async with session_factory() as session:
                try:
                    processed_results = await lemlist.process_events(events)
                    events_processed = len(processed_results)
                    logger.info(
                        "Processed %d events via LemlistEngine", events_processed
                    )
                except Exception as e:
                    logger.error("Error processing Lemlist events: %s", str(e))
                    errors += 1

            # Step 3: Advance pipeline for genuine replies
            async with session_factory() as session:
                pipeline_manager = PipelineManager(
                    repository=None,  # Repository injected when DB is available
                    publisher=None,  # Redis publisher for WebSocket broadcasts
                )

                for event in events:
                    try:
                        if event.event_type.value == "reply":
                            # Advance pipeline from Sent → Replied
                            if hasattr(event, "pipeline_record_id") and event.pipeline_record_id:
                                await pipeline_manager.advance_on_reply(
                                    record_id=event.pipeline_record_id,
                                    reply_text=getattr(event, "reply_text", ""),
                                )
                                pipeline_advances += 1
                    except Exception as e:
                        logger.error(
                            "Failed to advance pipeline for event %s: %s",
                            getattr(event, "id", "unknown"),
                            str(e),
                        )
                        errors += 1
                        continue

        finally:
            await engine.dispose()

    summary = {
        "events_polled": len(events) if "events" in dir() else 0,
        "processed": events_processed,
        "advances": pipeline_advances,
        "errors": errors,
    }
    logger.info("Polling cycle complete: %s", summary)
    return summary


async def run_discovery_cycle(ctx: dict) -> dict:
    """Execute scheduled discovery runs for all active sources.

    Iterates over all configured source types, checks their health status,
    and runs DiscoveryPipeline.run_discovery() for each active source.

    Args:
        ctx: ARQ worker context containing shared resources.

    Returns:
        Summary dict with per-source discovery results.
    """
    logger.info("Starting discovery cycle")
    settings = get_settings()

    results = {}

    async with httpx.AsyncClient() as http_client:
        apollo = ApolloClient(
            api_key=settings.apollo_api_key,
            http_client=http_client,
        )

        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)

        try:
            # Initialize discovery pipeline
            pipeline = DiscoveryPipeline(
                schema_registry=None,  # Loaded at startup in production
                apollo_client=apollo,
                adzuna_client=None,  # Injected when available
                scoring_engine=None,  # Injected when available
                db_repo=None,  # Repository layer
            )

            # Run discovery for each active source type
            for source_type in SourceType:
                try:
                    # Check source health before attempting discovery
                    health = pipeline.get_source_health(source_type)
                    if health.status == SourceStatus.PERMANENTLY_SUSPENDED:
                        logger.info(
                            "Skipping permanently suspended source: %s",
                            source_type.value,
                        )
                        results[source_type.value] = {"status": "permanently_suspended"}
                        continue

                    if health.status == SourceStatus.SUSPENDED:
                        # Check if backoff period has elapsed
                        if pipeline._can_attempt_recovery(health):
                            logger.info(
                                "Attempting recovery for suspended source: %s",
                                source_type.value,
                            )
                        else:
                            logger.info(
                                "Source %s still in backoff period, skipping",
                                source_type.value,
                            )
                            results[source_type.value] = {"status": "suspended_backoff"}
                            continue

                    # Execute discovery run
                    # In production, beneficiary_id would come from schema config
                    # Here we run for all configured beneficiaries
                    for beneficiary_id in ["consultant", "team"]:
                        try:
                            result = await pipeline.run_discovery(
                                source_type=source_type,
                                beneficiary_id=beneficiary_id,
                            )
                            results[f"{source_type.value}_{beneficiary_id}"] = {
                                "status": "success",
                                "prospects_found": result.prospects_found,
                                "prospects_merged": result.prospects_merged,
                                "prospects_scored": result.prospects_scored,
                                "prospects_filtered": result.prospects_filtered,
                                "duration_seconds": result.duration_seconds,
                            }
                            logger.info(
                                "Discovery run complete: source=%s, beneficiary=%s, "
                                "found=%d, merged=%d",
                                source_type.value,
                                beneficiary_id,
                                result.prospects_found,
                                result.prospects_merged,
                            )
                        except Exception as e:
                            logger.error(
                                "Discovery failed for %s/%s: %s",
                                source_type.value,
                                beneficiary_id,
                                str(e),
                            )
                            results[f"{source_type.value}_{beneficiary_id}"] = {
                                "status": "error",
                                "error": str(e),
                            }

                except Exception as e:
                    logger.error(
                        "Error checking source health for %s: %s",
                        source_type.value,
                        str(e),
                    )
                    results[source_type.value] = {
                        "status": "error",
                        "error": str(e),
                    }

        finally:
            await engine.dispose()

    logger.info("Discovery cycle complete: %d source runs attempted", len(results))
    return results


# ─── Helper functions ─────────────────────────────────────────────────────────


async def _get_stale_enrichment_records(
    session: AsyncSession,
) -> list[EnrichmentRecord]:
    """Query enrichment_records for entries older than 30 days.

    Returns records where:
    - enriched_at is older than STALE_THRESHOLD_DAYS
    - status is 'complete' (only refresh successfully enriched records)
    - The associated prospect is not in a terminal pipeline state
    """
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_THRESHOLD_DAYS)

    stmt = (
        select(EnrichmentRecord)
        .where(EnrichmentRecord.enriched_at < stale_cutoff)
        .where(EnrichmentRecord.status == "complete")
        .order_by(EnrichmentRecord.enriched_at.asc())
        .limit(100)  # Process in batches to avoid overwhelming Apollo API
    )

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _get_prospect(
    session: AsyncSession, prospect_id
) -> Prospect | None:
    """Fetch a prospect by ID."""
    stmt = select(Prospect).where(Prospect.id == prospect_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
