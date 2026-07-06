"""Discovery Pipeline — orchestrates multi-source discovery with deduplication and scoring.

Coordinates discovery across four source types (Adzuna, Apollo, Internet Search,
Project Marketplace) with:
- 5-minute timeout per source per run
- Deduplication by company domain or normalized company name
- Multi-source bonus scoring (+10 per additional source, max +30)
- Configurable score threshold filtering (default 25)
- Source health tracking with suspension and recovery state machine

Requirements 10.1–10.6: Improved Discovery Pipeline with Multi-Source Scoring.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol

from app.core.scoring_engine import ScoringEngine
from app.core.utils import normalize_company_name

logger = logging.getLogger(__name__)

# ─── Enums ────────────────────────────────────────────────────────────────────


class SourceType(str, Enum):
    """Supported discovery source types (Requirement 10.1)."""

    ADZUNA = "adzuna"
    APOLLO = "apollo"
    INTERNET_SEARCH = "internet_search"
    PROJECT_MARKETPLACE = "project_marketplace"


class SourceStatus(str, Enum):
    """Source health state machine states (Requirements 10.5, 10.6).

    State transitions:
        active → suspended (3 consecutive failures)
        suspended → active (successful recovery)
        suspended → permanently_suspended (3 failed recovery attempts)
    """

    ACTIVE = "active"
    SUSPENDED = "suspended"
    PERMANENTLY_SUSPENDED = "permanently_suspended"


# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class DiscoveryConfig:
    """Configuration for a discovery source run.

    Attributes:
        source_type: Which source to discover from.
        schedule: Run schedule — "hourly", "daily", or "manual".
        min_score_threshold: Minimum Account Score to surface (0-100, default 25).
        max_runtime: Maximum runtime in seconds (default 300 = 5 minutes).
    """

    source_type: SourceType
    schedule: str = "daily"  # "hourly", "daily", "manual"
    min_score_threshold: int = 25
    max_runtime: int = 300  # 5 minutes


@dataclass
class DiscoveryResult:
    """Result summary from a discovery run.

    Attributes:
        prospects_found: Total raw prospects discovered from the source.
        prospects_merged: Number of prospects that matched existing records and were merged.
        prospects_scored: Number of prospects that were scored.
        prospects_filtered: Number of prospects filtered out (below threshold).
        source_type: Source type that was queried.
        duration_seconds: Total runtime in seconds.
    """

    prospects_found: int
    prospects_merged: int
    prospects_scored: int
    prospects_filtered: int
    source_type: SourceType
    duration_seconds: float


@dataclass
class SourceHealthState:
    """In-memory representation of a source's health state.

    Attributes:
        source_type: The discovery source type.
        status: Current status (active, suspended, permanently_suspended).
        consecutive_failures: Number of consecutive failures without success.
        last_failure_at: Timestamp of the most recent failure.
        suspended_at: Timestamp when the source was suspended.
        recovery_attempts: Number of recovery attempts after suspension.
    """

    source_type: SourceType
    status: SourceStatus = SourceStatus.ACTIVE
    consecutive_failures: int = 0
    last_failure_at: datetime | None = None
    suspended_at: datetime | None = None
    recovery_attempts: int = 0


@dataclass
class RawProspect:
    """A raw prospect discovered from a source before deduplication.

    Attributes:
        company_name: Original company name as discovered.
        company_domain: Company website domain (may be None).
        source_type: Which source discovered this prospect.
        beneficiary_id: Target beneficiary for this prospect.
        opportunity_type_id: Opportunity type classification.
        enrichment_data: Additional source-specific data fields.
        discovered_at: When the prospect was discovered.
    """

    company_name: str
    company_domain: str | None = None
    source_type: SourceType = SourceType.ADZUNA
    beneficiary_id: str = ""
    opportunity_type_id: str = ""
    enrichment_data: dict[str, Any] = field(default_factory=dict)
    discovered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ─── Source Client Protocol ───────────────────────────────────────────────────


class SourceClient(Protocol):
    """Protocol that discovery source clients must implement."""

    async def discover(
        self, beneficiary_id: str, **kwargs: Any
    ) -> list[RawProspect]:
        """Discover raw prospects from this source."""
        ...


# ─── Discovery Pipeline ──────────────────────────────────────────────────────


class DiscoveryPipeline:
    """Orchestrates multi-source discovery with deduplication and scoring.

    Key behaviors:
    - 5-minute timeout per source per run (Requirement 10.4)
    - Deduplication by domain or normalized company name (Requirement 10.2)
    - Multi-source bonus: +10 per additional source, max +30 (Requirement 10.2)
    - Score threshold filtering: configurable, default 25 (Requirement 10.3)
    - Source health state machine: 3 failures → suspended → recovery (Requirements 10.5, 10.6)
    """

    CONSECUTIVE_FAILURE_THRESHOLD = 3
    BACKOFF_PERIOD_SECONDS = 3600  # 1 hour
    MAX_RECOVERY_ATTEMPTS = 3
    DEFAULT_SCORE_THRESHOLD = 25
    MULTI_SOURCE_BONUS_PER_SOURCE = 10
    MULTI_SOURCE_BONUS_MAX = 30
    DEFAULT_MAX_RUNTIME = 300  # 5 minutes

    def __init__(
        self,
        scoring_engine: ScoringEngine,
        source_clients: dict[SourceType, SourceClient] | None = None,
        existing_prospects: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the discovery pipeline.

        Args:
            scoring_engine: ScoringEngine instance for score computation.
            source_clients: Map of source type to client implementations.
            existing_prospects: Pre-loaded existing prospects for deduplication
                (each dict must have 'company_domain', 'normalized_name',
                 'source_count', 'sources', and other enrichment fields).
        """
        self._scoring = scoring_engine
        self._source_clients = source_clients or {}
        self._existing_prospects = existing_prospects or []
        self._source_health: dict[SourceType, SourceHealthState] = {
            st: SourceHealthState(source_type=st) for st in SourceType
        }

    # ─── Public API ───────────────────────────────────────────────────────

    async def run_discovery(
        self,
        source_type: SourceType,
        beneficiary_id: str,
        config: DiscoveryConfig | None = None,
    ) -> DiscoveryResult:
        """Execute a discovery run for a specific source and beneficiary.

        Enforces 5-minute timeout per source (Requirement 10.4). Checks
        source health before proceeding. On failure, records the failure
        for health tracking.

        Args:
            source_type: Which source to discover from.
            beneficiary_id: Target beneficiary for the discovery.
            config: Optional configuration overriding defaults.

        Returns:
            DiscoveryResult summarizing the discovery run.

        Raises:
            asyncio.TimeoutError: If the source exceeds the configured timeout.
        """
        if config is None:
            config = DiscoveryConfig(source_type=source_type)

        start_time = time.monotonic()
        max_runtime = config.max_runtime or self.DEFAULT_MAX_RUNTIME
        threshold = config.min_score_threshold

        # Check source health — skip if suspended or permanently suspended
        health_status = await self.check_source_health(source_type)
        if health_status == SourceStatus.PERMANENTLY_SUSPENDED:
            logger.warning(
                "Source %s is permanently suspended, skipping discovery",
                source_type.value,
            )
            return DiscoveryResult(
                prospects_found=0,
                prospects_merged=0,
                prospects_scored=0,
                prospects_filtered=0,
                source_type=source_type,
                duration_seconds=time.monotonic() - start_time,
            )

        if health_status == SourceStatus.SUSPENDED:
            # Check if backoff period has elapsed for recovery attempt
            health = self._source_health[source_type]
            if not self._can_attempt_recovery(health):
                logger.info(
                    "Source %s is suspended, backoff period not yet elapsed",
                    source_type.value,
                )
                return DiscoveryResult(
                    prospects_found=0,
                    prospects_merged=0,
                    prospects_scored=0,
                    prospects_filtered=0,
                    source_type=source_type,
                    duration_seconds=time.monotonic() - start_time,
                )
            logger.info(
                "Source %s attempting recovery (attempt %d/%d)",
                source_type.value,
                health.recovery_attempts + 1,
                self.MAX_RECOVERY_ATTEMPTS,
            )

        # Get the source client
        client = self._source_clients.get(source_type)
        if client is None:
            logger.error("No client configured for source %s", source_type.value)
            return DiscoveryResult(
                prospects_found=0,
                prospects_merged=0,
                prospects_scored=0,
                prospects_filtered=0,
                source_type=source_type,
                duration_seconds=time.monotonic() - start_time,
            )

        # Execute discovery with timeout
        try:
            raw_prospects = await asyncio.wait_for(
                client.discover(beneficiary_id),
                timeout=max_runtime,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            self._record_failure(source_type)
            duration = time.monotonic() - start_time
            logger.error(
                "Discovery failed for source %s: %s",
                source_type.value,
                str(exc),
            )
            return DiscoveryResult(
                prospects_found=0,
                prospects_merged=0,
                prospects_scored=0,
                prospects_filtered=0,
                source_type=source_type,
                duration_seconds=duration,
            )

        # Record success — resets failure tracking
        self._record_success(source_type)

        # Deduplicate and merge
        deduped_prospects = await self.deduplicate_and_merge(raw_prospects)

        # Score and filter
        scored_count = 0
        filtered_count = 0
        merged_count = len(raw_prospects) - len(
            [p for p in deduped_prospects if p.get("is_new", True)]
        )

        for prospect in deduped_prospects:
            source_count = prospect.get("source_count", 1)
            score_result = self._scoring.compute_score(
                source_count=source_count,
            )
            prospect["score"] = score_result.total_score
            prospect["tier"] = score_result.tier.value
            scored_count += 1

            if score_result.total_score < threshold:
                filtered_count += 1

        duration = time.monotonic() - start_time

        return DiscoveryResult(
            prospects_found=len(raw_prospects),
            prospects_merged=merged_count,
            prospects_scored=scored_count,
            prospects_filtered=filtered_count,
            source_type=source_type,
            duration_seconds=duration,
        )

    async def deduplicate_and_merge(
        self, new_prospects: list[RawProspect]
    ) -> list[dict[str, Any]]:
        """Match by domain or normalized company name; merge enrichment data.

        Deduplication logic (Requirement 10.2):
        1. For each new prospect, check if an existing record matches by:
           - Company domain (exact match, case-insensitive)
           - OR normalized company name
        2. If match found: merge by retaining most recent values for each
           enrichment field, combine sources, increment source_count.
        3. If no match: create new record.

        Multi-source bonus is applied during scoring: +10 per additional source,
        max +30 (e.g., source_count=4 → +30 bonus).

        Args:
            new_prospects: List of raw prospects from the current discovery run.

        Returns:
            List of prospect dicts, each with is_new, source_count, and merged data.
        """
        results: list[dict[str, Any]] = []

        # Build an index of existing prospects for fast lookup
        domain_index: dict[str, dict[str, Any]] = {}
        name_index: dict[str, dict[str, Any]] = {}
        for existing in self._existing_prospects:
            domain = existing.get("company_domain")
            if domain:
                domain_index[domain.lower().strip()] = existing
            normalized = existing.get("normalized_name", "")
            if normalized:
                name_index[normalized] = existing

        for raw in new_prospects:
            normalized_name = self._normalize_company_name(raw.company_name)
            match = self._find_match(raw, normalized_name, domain_index, name_index)

            if match is not None:
                # Merge: retain most recent values
                merged = self._merge_prospect(match, raw, normalized_name)
                results.append(merged)
            else:
                # New prospect
                new_entry = self._create_new_prospect(raw, normalized_name)
                # Add to index for deduplication within this batch
                if raw.company_domain:
                    domain_index[raw.company_domain.lower().strip()] = new_entry
                if normalized_name:
                    name_index[normalized_name] = new_entry
                results.append(new_entry)

        return results

    def _normalize_company_name(self, name: str) -> str:
        """Normalize company name for deduplication matching.

        Delegates to the shared utility in app.core.utils which applies:
        1. Unicode normalization (NFKD) and lowercasing
        2. Remove common company suffixes (Inc, LLC, Ltd, etc.)
        3. Strip punctuation and special characters
        4. Collapse whitespace

        Args:
            name: Raw company name string.

        Returns:
            Normalized company name suitable for comparison.
        """
        return normalize_company_name(name)

    async def check_source_health(self, source_type: SourceType) -> SourceStatus:
        """Check and return the current health status of a source.

        State machine (Requirements 10.5, 10.6):
        - active: Source is operational, consecutive_failures < 3
        - suspended: 3 consecutive failures triggered suspension;
          recovery attempted after 1-hour backoff
        - permanently_suspended: 3 failed recovery attempts after suspension

        Args:
            source_type: The source to check.

        Returns:
            Current SourceStatus for the requested source.
        """
        health = self._source_health[source_type]
        return health.status

    def get_source_health(self, source_type: SourceType) -> SourceHealthState:
        """Return the full health state for a source (for testing/inspection).

        Args:
            source_type: The source to inspect.

        Returns:
            SourceHealthState with all tracking fields.
        """
        return self._source_health[source_type]

    def set_source_health(
        self, source_type: SourceType, health: SourceHealthState
    ) -> None:
        """Set the health state for a source (for testing/initialization).

        Args:
            source_type: The source to update.
            health: The new health state.
        """
        self._source_health[source_type] = health

    def apply_score_threshold(
        self,
        prospects: list[dict[str, Any]],
        threshold: int | None = None,
    ) -> list[dict[str, Any]]:
        """Filter prospects below the score threshold.

        Requirement 10.3: Filter out prospects with Account_Score below
        user-configurable minimum threshold (default: 25, range: 0–100).

        Args:
            prospects: List of prospect dicts with 'score' field.
            threshold: Minimum score to keep. Defaults to DEFAULT_SCORE_THRESHOLD.

        Returns:
            List of prospects at or above the threshold.
        """
        if threshold is None:
            threshold = self.DEFAULT_SCORE_THRESHOLD
        return [p for p in prospects if p.get("score", 0) >= threshold]

    def compute_multi_source_bonus(self, source_count: int) -> int:
        """Compute the multi-source confidence bonus.

        Requirement 10.2: +10 points per additional source, max +30.
        - 1 source: 0 bonus
        - 2 sources: +10
        - 3 sources: +20
        - 4+ sources: +30

        Args:
            source_count: Number of sources that discovered this prospect.

        Returns:
            Bonus points (0, 10, 20, or 30).
        """
        if source_count <= 1:
            return 0
        return min(
            (source_count - 1) * self.MULTI_SOURCE_BONUS_PER_SOURCE,
            self.MULTI_SOURCE_BONUS_MAX,
        )

    # ─── Private Helpers ──────────────────────────────────────────────────

    def _find_match(
        self,
        raw: RawProspect,
        normalized_name: str,
        domain_index: dict[str, dict[str, Any]],
        name_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Find an existing prospect matching by domain or normalized name.

        Priority: domain match first, then name match.

        Args:
            raw: The raw prospect to match.
            normalized_name: Pre-computed normalized name.
            domain_index: Index of existing prospects by domain.
            name_index: Index of existing prospects by normalized name.

        Returns:
            Matching existing prospect dict, or None.
        """
        # Match by domain (exact, case-insensitive)
        if raw.company_domain:
            domain_key = raw.company_domain.lower().strip()
            if domain_key in domain_index:
                return domain_index[domain_key]

        # Match by normalized company name
        if normalized_name and normalized_name in name_index:
            return name_index[normalized_name]

        return None

    def _merge_prospect(
        self,
        existing: dict[str, Any],
        raw: RawProspect,
        normalized_name: str,
    ) -> dict[str, Any]:
        """Merge a new raw prospect into an existing record.

        Retains most recent values for each enrichment field, combines
        sources, and increments source_count.

        Args:
            existing: The existing prospect record.
            raw: The new raw prospect to merge.
            normalized_name: Pre-computed normalized name.

        Returns:
            Updated prospect dict with merged data.
        """
        merged = dict(existing)
        merged["is_new"] = False

        # Add this source if not already tracked
        sources = set(merged.get("sources", []))
        sources.add(raw.source_type.value)
        merged["sources"] = list(sources)
        merged["source_count"] = len(sources)

        # Retain most recent values: new data overwrites if present
        if raw.company_domain and raw.company_domain.strip():
            merged["company_domain"] = raw.company_domain
        if raw.company_name:
            merged["company_name"] = raw.company_name
        merged["normalized_name"] = normalized_name

        # Merge enrichment data — retain most recent for each field
        existing_enrichment = merged.get("enrichment_data", {})
        for key, value in raw.enrichment_data.items():
            if value is not None:
                existing_enrichment[key] = value
        merged["enrichment_data"] = existing_enrichment
        merged["updated_at"] = raw.discovered_at

        return merged

    def _create_new_prospect(
        self,
        raw: RawProspect,
        normalized_name: str,
    ) -> dict[str, Any]:
        """Create a new prospect dict from a raw discovery.

        Args:
            raw: The raw prospect.
            normalized_name: Pre-computed normalized name.

        Returns:
            New prospect dict ready for persistence.
        """
        return {
            "company_name": raw.company_name,
            "company_domain": raw.company_domain,
            "normalized_name": normalized_name,
            "beneficiary_id": raw.beneficiary_id,
            "opportunity_type_id": raw.opportunity_type_id,
            "source_type": raw.source_type.value,
            "sources": [raw.source_type.value],
            "source_count": 1,
            "enrichment_data": dict(raw.enrichment_data),
            "discovered_at": raw.discovered_at,
            "updated_at": raw.discovered_at,
            "is_new": True,
        }

    def _record_failure(self, source_type: SourceType) -> None:
        """Record a source failure and potentially trigger suspension.

        State machine transitions (Requirement 10.5):
        - If active and consecutive_failures reaches 3 → suspended
        - If suspended (recovery attempt failed) → increment recovery_attempts
        - If recovery_attempts reaches 3 → permanently_suspended (Requirement 10.6)

        Args:
            source_type: The source that failed.
        """
        health = self._source_health[source_type]
        now = datetime.now(timezone.utc)
        health.last_failure_at = now
        health.consecutive_failures += 1

        if health.status == SourceStatus.ACTIVE:
            if health.consecutive_failures >= self.CONSECUTIVE_FAILURE_THRESHOLD:
                health.status = SourceStatus.SUSPENDED
                health.suspended_at = now
                health.recovery_attempts = 0
                logger.warning(
                    "Source %s suspended after %d consecutive failures",
                    source_type.value,
                    health.consecutive_failures,
                )
        elif health.status == SourceStatus.SUSPENDED:
            health.recovery_attempts += 1
            if health.recovery_attempts >= self.MAX_RECOVERY_ATTEMPTS:
                health.status = SourceStatus.PERMANENTLY_SUSPENDED
                logger.error(
                    "Source %s permanently suspended after %d recovery failures",
                    source_type.value,
                    health.recovery_attempts,
                )

    def _record_success(self, source_type: SourceType) -> None:
        """Record a successful discovery run, resetting failure tracking.

        On success:
        - If active: reset consecutive_failures to 0
        - If suspended (recovery attempt succeeded): transition back to active

        Args:
            source_type: The source that succeeded.
        """
        health = self._source_health[source_type]
        health.consecutive_failures = 0
        health.last_failure_at = None

        if health.status == SourceStatus.SUSPENDED:
            # Recovery succeeded
            health.status = SourceStatus.ACTIVE
            health.suspended_at = None
            health.recovery_attempts = 0
            logger.info(
                "Source %s recovered from suspension", source_type.value
            )

    def _can_attempt_recovery(self, health: SourceHealthState) -> bool:
        """Check if the backoff period has elapsed for a suspended source.

        Requirement 10.5: Recovery attempted after 1-hour backoff period.

        Args:
            health: The source health state to check.

        Returns:
            True if the backoff has elapsed and recovery can be attempted.
        """
        if health.suspended_at is None:
            return False
        elapsed = datetime.now(timezone.utc) - health.suspended_at
        return elapsed >= timedelta(seconds=self.BACKOFF_PERIOD_SECONDS)
