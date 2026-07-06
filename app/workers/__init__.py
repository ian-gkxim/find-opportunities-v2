"""ARQ background workers for enrichment, polling, analytics, and discovery.

Configures the ARQ worker settings including Redis connection, task scheduling,
and cron jobs for the background processing pipeline.

Workers:
- enrichment_worker: Scheduled Apollo.io enrichment refresh (hourly)
- polling_worker: Lemlist response polling (every 5 minutes)
- discovery_worker: Scheduled discovery runs (hourly/daily per source)
- analytics_worker: Daily funnel computation and metrics (02:00 UTC cron)
- scoring_worker: Score recomputation on weight changes or enrichment updates
"""

from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import get_settings


def get_redis_settings() -> RedisSettings:
    """Parse the redis_url from application settings into ARQ RedisSettings."""
    settings = get_settings()
    url = settings.redis_url

    # Parse redis://host:port/db format
    # Strip scheme
    if url.startswith("redis://"):
        url_body = url[len("redis://"):]
    elif url.startswith("rediss://"):
        url_body = url[len("rediss://"):]
    else:
        url_body = url

    # Extract auth if present (user:password@host:port/db)
    password = None
    if "@" in url_body:
        auth_part, url_body = url_body.rsplit("@", 1)
        if ":" in auth_part:
            _, password = auth_part.split(":", 1)
        else:
            password = auth_part

    # Extract database number
    database = 0
    if "/" in url_body:
        host_port, db_str = url_body.rsplit("/", 1)
        if db_str.isdigit():
            database = int(db_str)
    else:
        host_port = url_body

    # Extract host and port
    if ":" in host_port:
        host, port_str = host_port.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_port
        port = 6379

    return RedisSettings(
        host=host,
        port=port,
        database=database,
        password=password,
        conn_timeout=10,
        conn_retries=3,
    )


# ----- Task functions (delegating to worker modules) -----

from app.workers.enrichment_worker import (
    run_discovery_cycle,
    run_enrichment_cycle,
    run_polling_cycle,
)
from app.workers.analytics_worker import run_analytics_daily
from app.workers.scoring_worker import run_score_recomputation


async def startup(ctx: dict) -> None:
    """ARQ worker startup hook. Initialize shared resources."""
    # Will initialize DB session, Redis client, HTTP client, etc.
    pass


async def shutdown(ctx: dict) -> None:
    """ARQ worker shutdown hook. Clean up shared resources."""
    # Will close DB session, Redis pool, HTTP client, etc.
    pass


# ----- ARQ WorkerSettings class -----


class WorkerSettings:
    """ARQ worker configuration.

    This class is discovered by ARQ when starting the worker with:
        arq app.workers.WorkerSettings
    """

    # Task functions the worker can execute
    functions = [
        run_enrichment_cycle,
        run_polling_cycle,
        run_discovery_cycle,
        run_analytics_daily,
        run_score_recomputation,
    ]

    # Cron jobs for scheduled tasks
    @staticmethod
    def cron_jobs():
        jobs = [
            # Analytics: daily at 02:00 UTC (Requirement 9.1)
            cron(
                run_analytics_daily,
                hour=2,
                minute=0,
                unique=True,
            ),
            # Enrichment: hourly refresh of stale records (Requirement 1.7)
            cron(
                run_enrichment_cycle,
                minute=0,
                unique=True,
            ),
            # Polling: every 5 minutes for Lemlist responses (Requirement 7.1)
            cron(
                run_polling_cycle,
                minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
                unique=True,
            ),
            # Discovery: hourly scheduled runs (Requirement 10.4)
            cron(
                run_discovery_cycle,
                minute=30,
                unique=True,
            ),
        ]
        return jobs

    # Redis connection
    redis_settings = get_redis_settings()

    # Worker lifecycle hooks
    on_startup = startup
    on_shutdown = shutdown

    # Worker behavior
    max_jobs = 10
    job_timeout = 600  # 10 minutes max per job
    keep_result = 3600  # Keep results for 1 hour
    poll_delay = 1.0  # Poll for new jobs every second
