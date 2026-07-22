"""ARQ background worker entry point.

Runs scheduled tasks:
- run_enrichment_cycle: Refresh stale enrichment records (every hour)
- run_polling_cycle: Poll Lemlist for response events (every 5 minutes)
- run_discovery_cycle: Execute discovery runs for all active sources (every hour)
- profile_enrichment_scan: Profile enrichment scanning (daily at 04:00 UTC)

Usage:
    python -m app.worker

Requirements: 1.7, 3.5, 7.1, 10.4, 14.1
"""

import logging
from datetime import timedelta

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.workers.enrichment_worker import (
    run_discovery_cycle,
    run_enrichment_cycle,
    run_polling_cycle,
)
from app.workers.profile_enrichment_worker import profile_enrichment_scan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def startup(ctx: dict) -> None:
    """Worker startup — initialize shared resources."""
    settings = get_settings()
    ctx["settings"] = settings
    logger.info(
        "ARQ worker started (enrichment=%ds, polling=%ds)",
        settings.worker_enrichment_interval,
        settings.worker_polling_interval,
    )


async def shutdown(ctx: dict) -> None:
    """Worker shutdown — clean up shared resources."""
    logger.info("ARQ worker shutting down")


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [
        run_enrichment_cycle,
        run_polling_cycle,
        run_discovery_cycle,
        profile_enrichment_scan,
    ]

    cron_jobs = [
        # Poll Lemlist every 5 minutes for response events
        cron(run_polling_cycle, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        # Run enrichment refresh every hour
        cron(run_enrichment_cycle, minute={0}),
        # Run discovery cycle every hour at minute 30
        cron(run_discovery_cycle, minute={30}),
        # Profile enrichment: daily at 04:00 UTC
        cron(profile_enrichment_scan, hour=4, minute=0, unique=True),
    ]

    on_startup = startup
    on_shutdown = shutdown

    # Redis connection
    @staticmethod
    def redis_settings() -> RedisSettings:
        settings = get_settings()
        # Parse redis URL to RedisSettings
        url = settings.redis_url
        # redis://host:port/db
        if url.startswith("redis://"):
            url = url[len("redis://"):]
        parts = url.split("/")
        host_port = parts[0]
        db = int(parts[1]) if len(parts) > 1 else 0
        host, port = host_port.split(":") if ":" in host_port else (host_port, "6379")
        return RedisSettings(host=host, port=int(port), database=db)
