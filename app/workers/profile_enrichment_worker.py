"""Profile Enrichment Worker — scans public sources for competency evidence.

Scheduled via ARQ cron. Runs once per 30 days per Consultant (configurable).
Respects per-domain throttling (1 req/s) and 15-second fetch timeout.
Tracks consecutive failures and surfaces Dashboard notices at threshold.

Orchestrates: DomainThrottler → HTTP fetch → CompetencyExtractor →
ProposalDeduplicator → CompetencyProposal creation → WebSocket notification.

Requirements: 1.2, 1.3, 1.4, 2.1, 2.2, 2.4
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.competency_extractor import CompetencyExtractor
from app.core.config import get_settings
from app.core.domain_throttler import DomainThrottler
from app.core.proposal_deduplicator import ProposalDeduplicator
from app.core.redis import get_redis_client
from app.core.websocket_manager import WebSocketManager
from app.models.base import get_async_engine, get_async_session_factory
from app.models.competency_proposal import CompetencyProposal
from app.models.enrichment_scan_history import EnrichmentScanHistory
from app.models.public_source import PublicSource

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

FETCH_TIMEOUT = 15.0  # seconds per page fetch (Requirement 1.3)
MAX_FETCH_RETRIES = 3  # attempts per source per cycle (Requirement 1.4)
RETRY_BACKOFF = 5.0  # seconds between retries for 5xx errors
CONSECUTIVE_FAILURE_THRESHOLD = 3  # cycles before Dashboard notice (Requirement 1.4)
MAX_CONTENT_SIZE = 1_000_000  # 1MB content cap


# ─── ARQ Task Function ────────────────────────────────────────────────────────


async def profile_enrichment_scan(ctx: dict, consultant_id: str | None = None) -> dict:
    """Scan public sources for competency evidence.

    If consultant_id is provided, performs an on-demand scan for that
    specific consultant. Otherwise, scans all consultants due for their
    scheduled scan (last_scanned_at + scan_interval_days <= now OR never scanned).

    Args:
        ctx: ARQ worker context containing shared resources.
        consultant_id: Optional consultant ID for on-demand scan.

    Returns:
        Summary dict with scan results (sources_scanned, proposals_created, failures).
    """
    scan_type = "on_demand" if consultant_id else "scheduled"
    logger.info(
        "Starting profile enrichment scan: type=%s, consultant=%s",
        scan_type,
        consultant_id or "all-due",
    )

    settings = get_settings()
    redis_client = get_redis_client()
    ws_manager = WebSocketManager(redis_client=redis_client)
    throttler = DomainThrottler(redis_client=redis_client)

    engine = get_async_engine()
    session_factory = get_async_session_factory(engine)

    sources_scanned = 0
    proposals_created = 0
    failures = 0

    try:
        async with session_factory() as session:
            # Determine which sources to scan
            if consultant_id:
                sources = await _get_sources_for_consultant(session, consultant_id)
            else:
                sources = await _get_sources_due_for_scan(session)

            logger.info("Found %d sources to scan", len(sources))

            # Group sources by consultant for scan history tracking
            consultant_sources: dict[str, list[PublicSource]] = {}
            for source in sources:
                consultant_sources.setdefault(source.consultant_id, []).append(source)

            for c_id, c_sources in consultant_sources.items():
                # Create scan history record
                scan_history = EnrichmentScanHistory(
                    id=uuid.uuid4(),
                    consultant_id=c_id,
                    scan_type=scan_type,
                    started_at=datetime.now(timezone.utc),
                    status="running",
                    proposals_generated=0,
                )
                session.add(scan_history)
                await session.flush()

                consultant_proposals = 0

                for source in c_sources:
                    try:
                        new_proposals = await _scan_source(
                            session=session,
                            source=source,
                            throttler=throttler,
                            ws_manager=ws_manager,
                            settings=settings,
                        )
                        proposals_created += new_proposals
                        consultant_proposals += new_proposals
                        sources_scanned += 1

                        # Update last_scanned_at on success
                        source.last_scanned_at = datetime.now(timezone.utc)
                        source.updated_at = datetime.now(timezone.utc)

                    except SourceFetchError as e:
                        logger.warning(
                            "Source fetch failed: source_id=%s, url=%s, error=%s",
                            source.id,
                            source.url,
                            str(e),
                        )
                        failures += 1

                        # Increment consecutive failures
                        source.consecutive_failures += 1
                        source.updated_at = datetime.now(timezone.utc)

                        # Emit Dashboard notice at threshold
                        if source.consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD:
                            await _emit_source_failure_notice(
                                ws_manager=ws_manager,
                                consultant_id=c_id,
                                source=source,
                            )

                    except Exception as e:
                        logger.error(
                            "Unexpected error scanning source %s: %s",
                            source.id,
                            str(e),
                            exc_info=True,
                        )
                        failures += 1

                # Update scan history with results
                scan_history.completed_at = datetime.now(timezone.utc)
                scan_history.status = "completed" if failures == 0 else "failed"
                scan_history.proposals_generated = consultant_proposals
                if failures > 0:
                    scan_history.error_message = (
                        f"{failures} source(s) failed during scan"
                    )

                await session.commit()

                # Notify consultant of new proposals
                if consultant_proposals > 0:
                    await _emit_new_proposals_notification(
                        ws_manager=ws_manager,
                        consultant_id=c_id,
                        count=consultant_proposals,
                    )

    except Exception as e:
        logger.error(
            "Profile enrichment scan failed: %s", str(e), exc_info=True
        )
        raise
    finally:
        await engine.dispose()
        await redis_client.aclose()

    summary = {
        "scan_type": scan_type,
        "sources_scanned": sources_scanned,
        "proposals_created": proposals_created,
        "failures": failures,
    }
    logger.info("Profile enrichment scan complete: %s", summary)
    return summary


# ─── Source Scanning ──────────────────────────────────────────────────────────


class SourceFetchError(Exception):
    """Raised when a source cannot be fetched after all retry attempts."""

    pass


async def _scan_source(
    session: AsyncSession,
    source: PublicSource,
    throttler: DomainThrottler,
    ws_manager: WebSocketManager,
    settings,
) -> int:
    """Scan a single public source: fetch, extract, deduplicate, create proposals.

    Args:
        session: Active database session.
        source: The PublicSource to scan.
        throttler: DomainThrottler for rate limiting.
        ws_manager: WebSocketManager for notifications.
        settings: Application settings.

    Returns:
        Number of new proposals created.

    Raises:
        SourceFetchError: If the source cannot be fetched after retries.
    """
    # Step 1: Acquire throttle slot and fetch content
    await throttler.acquire(source.url)
    content = await _fetch_with_retries(source.url)

    # Step 2: Extract competencies via LLM
    from app.integrations.llm_router import LLMRouter

    llm_router = LLMRouter()
    extractor = CompetencyExtractor(llm_router=llm_router)

    candidates = await extractor.extract(
        content=content,
        source_type=source.source_type,
        source_url=source.url,
    )

    if not candidates:
        logger.debug("No candidates extracted from source %s", source.url)
        # Reset consecutive failures on successful fetch (even with no candidates)
        source.consecutive_failures = 0
        return 0

    # Step 3: Deduplicate candidates
    dedup_repo = _DeduplicationDBRepo(session)
    deduplicator = ProposalDeduplicator(db_repo=dedup_repo)

    new_candidates = await deduplicator.deduplicate(
        candidates=candidates,
        consultant_id=source.consultant_id,
    )

    if not new_candidates:
        logger.debug(
            "All candidates deduplicated for source %s", source.url
        )
        # Reset consecutive failures on successful fetch
        source.consecutive_failures = 0
        return 0

    # Step 4: Create CompetencyProposal records
    for candidate in new_candidates:
        proposal = CompetencyProposal(
            id=uuid.uuid4(),
            consultant_id=source.consultant_id,
            source_id=source.id,
            category=candidate.category,
            name=candidate.name,
            evidence_summary=candidate.evidence_summary,
            raw_evidence=candidate.raw_evidence,
            confidence=candidate.confidence,
            source_url=candidate.source_url,
            status="pending",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(proposal)

    await session.flush()

    # Reset consecutive failures on success
    source.consecutive_failures = 0

    logger.info(
        "Created %d proposals from source %s for consultant %s",
        len(new_candidates),
        source.url,
        source.consultant_id,
    )

    return len(new_candidates)


async def _fetch_with_retries(url: str) -> str:
    """Fetch page content with 15s timeout and up to 3 retries.

    Retry strategy:
    - HTTP 4xx: Do not retry (likely permanent error).
    - HTTP 5xx: Retry up to MAX_FETCH_RETRIES with RETRY_BACKOFF between.
    - Timeout/connection errors: Retry up to MAX_FETCH_RETRIES.

    Args:
        url: The URL to fetch.

    Returns:
        Page content as string (truncated to MAX_CONTENT_SIZE).

    Raises:
        SourceFetchError: If all attempts fail.
    """
    import asyncio

    last_error: Exception | None = None

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(FETCH_TIMEOUT),
        follow_redirects=True,
    ) as client:
        for attempt in range(1, MAX_FETCH_RETRIES + 1):
            try:
                response = await client.get(url)

                if response.status_code >= 400 and response.status_code < 500:
                    # Client error — don't retry
                    raise SourceFetchError(
                        f"HTTP {response.status_code} for {url} (client error, not retrying)"
                    )

                if response.status_code >= 500:
                    # Server error — retry
                    last_error = SourceFetchError(
                        f"HTTP {response.status_code} for {url} "
                        f"(attempt {attempt}/{MAX_FETCH_RETRIES})"
                    )
                    if attempt < MAX_FETCH_RETRIES:
                        await asyncio.sleep(RETRY_BACKOFF)
                        continue
                    raise last_error

                # Success
                content = response.text
                if len(content) > MAX_CONTENT_SIZE:
                    logger.warning(
                        "Content truncated from %d to %d bytes: %s",
                        len(content),
                        MAX_CONTENT_SIZE,
                        url,
                    )
                    content = content[:MAX_CONTENT_SIZE]

                return content

            except httpx.TimeoutException as e:
                last_error = SourceFetchError(
                    f"Timeout fetching {url} (attempt {attempt}/{MAX_FETCH_RETRIES}): {e}"
                )
                if attempt < MAX_FETCH_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF)
                    continue

            except httpx.ConnectError as e:
                last_error = SourceFetchError(
                    f"Connection error for {url} "
                    f"(attempt {attempt}/{MAX_FETCH_RETRIES}): {e}"
                )
                if attempt < MAX_FETCH_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF)
                    continue

            except SourceFetchError:
                # Re-raise 4xx errors (no retry)
                raise

            except httpx.HTTPError as e:
                last_error = SourceFetchError(
                    f"HTTP error for {url} "
                    f"(attempt {attempt}/{MAX_FETCH_RETRIES}): {e}"
                )
                if attempt < MAX_FETCH_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF)
                    continue

    raise last_error or SourceFetchError(f"Failed to fetch {url} after {MAX_FETCH_RETRIES} attempts")


# ─── Scheduling Helpers ───────────────────────────────────────────────────────


def is_source_due(
    last_scanned_at: datetime | None,
    scan_interval_days: int,
    now: datetime | None = None,
) -> bool:
    """Determine if a source needs scanning based on its schedule.

    A source is due if:
    - last_scanned_at is None (never scanned), OR
    - current_time - last_scanned_at >= scan_interval_days

    Args:
        last_scanned_at: When the source was last successfully scanned.
        scan_interval_days: Configured interval between scans.
        now: Current time (defaults to UTC now if not provided).

    Returns:
        True if the source is due for scanning.
    """
    if last_scanned_at is None:
        return True

    if now is None:
        now = datetime.now(timezone.utc)

    elapsed = now - last_scanned_at
    return elapsed >= timedelta(days=scan_interval_days)


async def _get_sources_due_for_scan(session: AsyncSession) -> list[PublicSource]:
    """Query all active sources that are due for scanning.

    A source is due if:
    - is_active = True
    - last_scanned_at is NULL (never scanned), OR
    - NOW() - last_scanned_at >= scan_interval_days

    Returns sources ordered by last_scanned_at (oldest first, NULL first).
    """
    stmt = (
        select(PublicSource)
        .where(PublicSource.is_active.is_(True))
        .order_by(PublicSource.last_scanned_at.asc().nulls_first())
    )
    result = await session.execute(stmt)
    all_sources = list(result.scalars().all())

    now = datetime.now(timezone.utc)
    return [
        source
        for source in all_sources
        if is_source_due(source.last_scanned_at, source.scan_interval_days, now)
    ]


async def _get_sources_for_consultant(
    session: AsyncSession, consultant_id: str
) -> list[PublicSource]:
    """Get all active sources for a specific consultant (on-demand scan).

    Args:
        session: Active database session.
        consultant_id: The consultant requesting the scan.

    Returns:
        All active sources for the consultant regardless of schedule.
    """
    stmt = (
        select(PublicSource)
        .where(PublicSource.consultant_id == consultant_id)
        .where(PublicSource.is_active.is_(True))
        .order_by(PublicSource.created_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ─── WebSocket Notifications ─────────────────────────────────────────────────


async def _emit_new_proposals_notification(
    ws_manager: WebSocketManager,
    consultant_id: str,
    count: int,
) -> None:
    """Emit WebSocket notification for new competency proposals.

    Args:
        ws_manager: WebSocketManager instance.
        consultant_id: The consultant who has new proposals.
        count: Number of new proposals created.
    """
    try:
        await ws_manager.broadcast_notification({
            "category": "new_proposals",
            "consultant_id": consultant_id,
            "title": "New competency proposals available",
            "message": (
                f"{count} new competency proposal(s) discovered from your "
                f"public sources. Review them in the Understand stage."
            ),
            "count": count,
        })
        logger.debug(
            "Emitted new_proposals notification: consultant=%s, count=%d",
            consultant_id,
            count,
        )
    except Exception as e:
        logger.warning(
            "Failed to emit new_proposals notification: %s", str(e)
        )


async def _emit_source_failure_notice(
    ws_manager: WebSocketManager,
    consultant_id: str,
    source: PublicSource,
) -> None:
    """Emit Dashboard notice when a source reaches the failure threshold.

    Called when consecutive_failures reaches CONSECUTIVE_FAILURE_THRESHOLD (3).

    Args:
        ws_manager: WebSocketManager instance.
        consultant_id: The consultant whose source is failing.
        source: The PublicSource that has reached the failure threshold.
    """
    try:
        await ws_manager.broadcast_notification({
            "category": "source_failure_notice",
            "consultant_id": consultant_id,
            "title": "Public source unreachable",
            "message": (
                f"The source '{source.label}' ({source.url}) has been "
                f"unreachable for {CONSECUTIVE_FAILURE_THRESHOLD} consecutive "
                f"scan cycles. Please verify the URL is still accessible."
            ),
            "source_id": str(source.id),
            "source_url": source.url,
            "source_label": source.label,
            "consecutive_failures": source.consecutive_failures,
        })
        logger.info(
            "Emitted source_failure_notice: consultant=%s, source=%s, "
            "consecutive_failures=%d",
            consultant_id,
            source.url,
            source.consecutive_failures,
        )
    except Exception as e:
        logger.warning(
            "Failed to emit source_failure_notice: %s", str(e)
        )


# ─── Deduplication Repository Adapter ────────────────────────────────────────


class _DeduplicationDBRepo:
    """Adapter connecting ProposalDeduplicator to the database.

    Implements the DeduplicationRepository protocol by querying existing
    profile assets, rejected proposals, and pending proposals from PostgreSQL.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_profile_assets(self, consultant_id: str):
        """Return existing profile assets for deduplication.

        Note: In the current implementation, accepted proposals serve as
        the proxy for profile assets since they represent competencies
        already merged into the profile.
        """
        from app.core.proposal_deduplicator import ProfileAsset

        stmt = (
            select(CompetencyProposal)
            .where(CompetencyProposal.consultant_id == consultant_id)
            .where(CompetencyProposal.status == "accepted")
        )
        result = await self._session.execute(stmt)
        accepted = result.scalars().all()

        return [
            ProfileAsset(name=p.name, category=p.category) for p in accepted
        ]

    async def get_rejected_proposals(self, consultant_id: str):
        """Return previously rejected proposals for deduplication."""
        from app.core.proposal_deduplicator import ProposalRecord

        stmt = (
            select(CompetencyProposal)
            .where(CompetencyProposal.consultant_id == consultant_id)
            .where(CompetencyProposal.status == "rejected")
        )
        result = await self._session.execute(stmt)
        rejected = result.scalars().all()

        return [
            ProposalRecord(name=p.name, category=p.category) for p in rejected
        ]

    async def get_pending_proposals(self, consultant_id: str):
        """Return currently pending proposals for deduplication."""
        from app.core.proposal_deduplicator import ProposalRecord

        stmt = (
            select(CompetencyProposal)
            .where(CompetencyProposal.consultant_id == consultant_id)
            .where(CompetencyProposal.status == "pending")
        )
        result = await self._session.execute(stmt)
        pending = result.scalars().all()

        return [
            ProposalRecord(name=p.name, category=p.category) for p in pending
        ]
