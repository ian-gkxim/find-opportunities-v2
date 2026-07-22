"""Gap Analyzer — orchestrates capability gap analysis.

Extracts required capabilities from lost/rejected/low-tier opportunities via
the LLM_Router, diffs them against Beneficiary profiles, and produces a
prioritized gap heatmap with estimated blocked pipeline value.

Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.core.capability_normalizer import CapabilityNormalizer
from app.core.gap_errors import (
    ExtractionError,
    GapAnalysisError,
    NormalizationError,
    OnDemandTimeoutError,
    retry_llm_call,
)

if TYPE_CHECKING:
    from app.core.schema_registry import SchemaRegistry
    from app.core.websocket_manager import WebSocketManager
    from app.integrations.llm_router import LLMRouter

logger = logging.getLogger(__name__)

# ─── Enums ────────────────────────────────────────────────────────────────────


class GapClassification(str, Enum):
    """Classification of a capability gap."""

    HARD = "hard"  # Capability completely absent from profile
    SOFT = "soft"  # Capability present but junior/unevidenced


class GapTrend(str, Enum):
    """Trend classification for a gap between consecutive heatmap reports."""

    NEW = "new"  # Not in previous report
    GROWING = "growing"  # Higher blocked value or frequency than previous
    SHRINKING = "shrinking"  # Lower blocked value or frequency than previous
    RESOLVED = "resolved"  # Was in previous report, now absent


class CapabilityLevel(str, Enum):
    """Level qualifier for an extracted capability requirement."""

    REQUIRED = "required"
    PREFERRED = "preferred"


# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExtractedCapability:
    """A single capability extracted from an opportunity description."""

    raw_name: str  # Original text from LLM extraction
    canonical_name: str  # Normalized canonical name after synonym merge
    level: CapabilityLevel  # Required or preferred
    opportunity_id: str  # Source opportunity


@dataclass(frozen=True)
class GapEntry:
    """A single gap in the heatmap."""

    canonical_name: str
    classification: GapClassification
    opportunity_count: int  # Number of opportunities requiring this
    blocked_pipeline_value: float  # Sum of estimated blocked value
    is_single_blocker: bool  # Was sole unmet required capability in any opp
    weighted_rank_score: float  # blocked_value * (2 if single_blocker else 1)
    trend: GapTrend | None  # Compared to previous report


@dataclass
class GapHeatmap:
    """The full gap heatmap report for a single Beneficiary or firm-level."""

    id: str
    beneficiary_id: str  # Consultant ID or "__firm__" for firm-level
    generated_at: datetime
    analysis_window_days: int
    gaps: list[GapEntry]  # Top 25, ranked by weighted_rank_score desc
    total_opportunities_analyzed: int
    total_blocked_value: float
    previous_heatmap_id: str | None


@dataclass
class ExtractionResult:
    """Result of LLM-based capability extraction from a single opportunity."""

    opportunity_id: str
    required_capabilities: list[str]  # Raw names before normalization
    preferred_capabilities: list[str]  # Raw names before normalization
    extracted_at: datetime
    cached: bool  # True if served from cache


@dataclass
class OnDemandGapReport:
    """Result of a single-opportunity gap analysis against one Consultant."""

    opportunity_id: str | None
    opportunity_url: str | None
    consultant_id: str
    required_gaps: list[GapEntry]
    preferred_gaps: list[GapEntry]
    total_required: int
    total_matched: int
    gap_percentage: float  # required_gaps / total_required * 100
    generated_at: datetime


@dataclass
class LearningRecommendation:
    """LLM-generated learning recommendation for a specific gap."""

    canonical_name: str
    resources: list[str]  # Suggested study resources
    effort_estimate: str  # e.g., "2-4 weeks part-time"
    advisory_note: str  # Disclaimer: "This is advisory only"
    generated_at: datetime


@dataclass
class GapAnalysisConfig:
    """Configuration for gap analysis behavior."""

    analysis_window_days: int = 90
    max_extractions_per_cycle: int = 200
    max_heatmap_entries: int = 25
    single_blocker_weight: float = 2.0
    on_demand_timeout_seconds: int = 120
    default_opportunity_value: float = 10000.0  # Used when opp value unknown


# ─── Extraction Prompt ────────────────────────────────────────────────────────

CAPABILITY_EXTRACTION_PROMPT = """Analyze the following opportunity description and extract all technical capabilities, skills, technologies, methodologies, certifications, and domain expertise required or preferred.

Categorize each capability as either "required" or "preferred" based on the language used in the description.

Respond in JSON format:
{{
  "required": ["capability1", "capability2", ...],
  "preferred": ["capability3", "capability4", ...]
}}

If no capabilities are found for a category, return an empty list.

Opportunity description:
{opportunity_text}"""


# ─── GapAnalyzer ──────────────────────────────────────────────────────────────


class GapAnalyzer:
    """Orchestrates capability gap analysis: extraction, normalization, diffing, ranking.

    Integrates with:
    - LLM_Router: For capability extraction and learning recommendations
    - SchemaRegistry: For Beneficiary profile access
    - PostgreSQL: For opportunity data, extraction cache, and heatmap storage
    - Redis: For extraction result caching
    - WebSocketManager: For Dashboard notifications
    """

    TIER_WEIGHT_MAP = {
        "A-tier": 1.0,  # Not analyzed (high score)
        "B-tier": 1.0,  # Not analyzed (mid-high score)
        "C-tier": 0.5,  # Lower estimated value weight
        "D-tier": 0.25,  # Lowest estimated value weight
    }

    REDIS_EXTRACTION_PREFIX = "gap:extraction:"
    REDIS_EXTRACTION_TTL = 60 * 60 * 24 * 30  # 30 days (opps are immutable once lost)

    def __init__(
        self,
        config: GapAnalysisConfig,
        llm_router: "LLMRouter | None",
        schema_registry: "SchemaRegistry | None",
        db_session: Any | None,
        redis_client: Any | None,
        ws_manager: "WebSocketManager | None",
        normalizer: CapabilityNormalizer | None = None,
    ) -> None:
        """Initialize GapAnalyzer with all dependencies.

        Args:
            config: Gap analysis configuration parameters.
            llm_router: LLM router for extraction and recommendation calls.
            schema_registry: Schema registry for Beneficiary profile access.
            db_session: SQLAlchemy async session for DB operations.
            redis_client: Async Redis client for caching.
            ws_manager: WebSocket manager for Dashboard notifications.
            normalizer: Optional pre-built CapabilityNormalizer instance.
        """
        self._config = config
        self._llm = llm_router
        self._schema = schema_registry
        self._db = db_session
        self._redis = redis_client
        self._ws = ws_manager
        self._normalizer = normalizer or CapabilityNormalizer({})

    # ─── Extraction ───────────────────────────────────────────────────────

    async def extract_capabilities(
        self, opportunity_id: str, opportunity_text: str
    ) -> ExtractionResult:
        """Extract capabilities from an opportunity description via LLM.

        Uses Redis cache keyed by opportunity_id. If cached, returns immediately.
        Otherwise, calls LLM_Router and stores result in both Redis and PostgreSQL.

        Args:
            opportunity_id: UUID of the opportunity/pipeline_record.
            opportunity_text: Full text description of the opportunity.

        Returns:
            ExtractionResult with required and preferred capabilities.
        """
        cache_key = f"{self.REDIS_EXTRACTION_PREFIX}{opportunity_id}"

        # 1. Check Redis cache
        if self._redis is not None:
            cached_data = await self._redis.get(cache_key)
            if cached_data is not None:
                parsed = json.loads(cached_data)
                logger.debug(
                    "Extraction cache hit for opportunity %s", opportunity_id
                )
                return ExtractionResult(
                    opportunity_id=opportunity_id,
                    required_capabilities=parsed["required"],
                    preferred_capabilities=parsed["preferred"],
                    extracted_at=datetime.fromisoformat(parsed["extracted_at"]),
                    cached=True,
                )

        # 2. Call LLM_Router for extraction with retry logic
        prompt = CAPABILITY_EXTRACTION_PROMPT.format(
            opportunity_text=opportunity_text
        )
        extraction_response = await retry_llm_call(
            self._llm.dispatch_extraction,
            prompt,
            opportunity_id=opportunity_id,
        )

        required_raw = extraction_response.get("required", [])
        preferred_raw = extraction_response.get("preferred", [])

        extracted_at = datetime.now(timezone.utc)

        # 3. Normalize capabilities
        required_normalized = self._normalizer.batch_normalize(required_raw)
        preferred_normalized = self._normalizer.batch_normalize(preferred_raw)

        # 4. Store in PostgreSQL (opportunity_extractions + extracted_capabilities)
        if self._db is not None:
            await self._store_extraction_in_db(
                opportunity_id=opportunity_id,
                required_raw=required_raw,
                required_normalized=required_normalized,
                preferred_raw=preferred_raw,
                preferred_normalized=preferred_normalized,
                extracted_at=extracted_at,
            )

        # 5. Store in Redis cache
        if self._redis is not None:
            cache_payload = json.dumps({
                "required": required_raw,
                "preferred": preferred_raw,
                "extracted_at": extracted_at.isoformat(),
            })
            await self._redis.set(
                cache_key, cache_payload, ex=self.REDIS_EXTRACTION_TTL
            )
            logger.debug(
                "Cached extraction for opportunity %s", opportunity_id
            )

        return ExtractionResult(
            opportunity_id=opportunity_id,
            required_capabilities=required_raw,
            preferred_capabilities=preferred_raw,
            extracted_at=extracted_at,
            cached=False,
        )

    async def _store_extraction_in_db(
        self,
        opportunity_id: str,
        required_raw: list[str],
        required_normalized: list[str],
        preferred_raw: list[str],
        preferred_normalized: list[str],
        extracted_at: datetime,
    ) -> None:
        """Store extraction results in PostgreSQL.

        Creates an OpportunityExtraction record and associated
        ExtractedCapability records, resolving canonical IDs.

        Args:
            opportunity_id: Pipeline record UUID.
            required_raw: Raw required capability names.
            required_normalized: Normalized required capability names.
            preferred_raw: Raw preferred capability names.
            preferred_normalized: Normalized preferred capability names.
            extracted_at: Timestamp of extraction.
        """
        from app.models.gap_analytics import (
            CanonicalCapability,
            ExtractedCapability as ExtractedCapabilityModel,
            OpportunityExtraction,
        )
        from sqlalchemy import select

        # Create the extraction record
        extraction = OpportunityExtraction(
            pipeline_record_id=uuid.UUID(opportunity_id),
            extracted_at=extracted_at,
            extraction_model="extraction",  # LLM model identifier
        )
        self._db.add(extraction)
        await self._db.flush()  # Get the extraction ID

        # Store each extracted capability
        all_capabilities = [
            (raw, norm, "required")
            for raw, norm in zip(required_raw, required_normalized)
        ] + [
            (raw, norm, "preferred")
            for raw, norm in zip(preferred_raw, preferred_normalized)
        ]

        for raw_name, canonical_name, level in all_capabilities:
            # Find or create canonical capability
            stmt = select(CanonicalCapability).where(
                CanonicalCapability.canonical_name == canonical_name
            )
            result = await self._db.execute(stmt)
            canonical = result.scalar_one_or_none()

            if canonical is None:
                canonical = CanonicalCapability(canonical_name=canonical_name)
                self._db.add(canonical)
                await self._db.flush()

            cap_record = ExtractedCapabilityModel(
                extraction_id=extraction.id,
                canonical_id=canonical.id,
                raw_name=raw_name,
                level=level,
            )
            self._db.add(cap_record)

        await self._db.commit()
        logger.info(
            "Stored extraction for opportunity %s: %d required, %d preferred",
            opportunity_id,
            len(required_raw),
            len(preferred_raw),
        )

    # ─── Normalization ────────────────────────────────────────────────────

    def normalize_capability(self, raw_name: str) -> str:
        """Normalize a capability name to its canonical form.

        Delegates to the CapabilityNormalizer instance.

        Args:
            raw_name: Raw capability name from LLM extraction.

        Returns:
            Canonical capability name string.
        """
        return self._normalizer.normalize(raw_name)

    # ─── Eligibility Selection ────────────────────────────────────────────

    async def get_eligible_opportunities(self) -> list[str]:
        """Fetch eligible pipeline record IDs for gap analysis.

        Selects pipeline records where:
        - current_status IN ('rejected', 'lost') OR tier IN ('C-tier', 'D-tier')
        - Record was updated within analysis_window_days of now
        - Record has NOT already been extracted (no entry in opportunity_extractions)

        Returns:
            List of eligible pipeline record ID strings (UUIDs).
        """
        from datetime import timedelta

        from sqlalchemy import select

        from app.models.account_score import AccountScore
        from app.models.gap_analytics import OpportunityExtraction
        from app.models.pipeline_record import PipelineRecord

        # Calculate the window cutoff
        window_cutoff = datetime.now(timezone.utc) - timedelta(
            days=self._config.analysis_window_days
        )

        # Subquery: pipeline_record_ids that have already been extracted
        already_extracted_subq = (
            select(OpportunityExtraction.pipeline_record_id)
            .scalar_subquery()
        )

        # Main query: records matching eligibility criteria within the window
        stmt = (
            select(PipelineRecord.id)
            .outerjoin(
                AccountScore,
                AccountScore.prospect_id == PipelineRecord.prospect_id,
            )
            .where(
                PipelineRecord.updated_at >= window_cutoff,
            )
            .where(
                # State-based OR tier-based eligibility
                (
                    PipelineRecord.current_status.in_(["rejected", "lost"])
                )
                | (
                    AccountScore.tier.in_(["C-tier", "D-tier"])
                )
            )
            .where(
                # Exclude already-extracted opportunities
                PipelineRecord.id.notin_(already_extracted_subq)
            )
        )

        result = await self._db.execute(stmt)
        rows = result.scalars().all()

        logger.info(
            "Found %d eligible opportunities within %d-day window",
            len(rows),
            self._config.analysis_window_days,
        )

        return [str(record_id) for record_id in rows]

    # ─── Batch Cap Enforcement ────────────────────────────────────────────

    async def enforce_batch_cap(
        self, eligible_ids: list[str]
    ) -> list[str]:
        """Enforce the batch cap on eligible opportunities, ordering by recency.

        Selects the top N (max_extractions_per_cycle) most recent eligible
        pipeline records for processing this cycle. Any remainder is inserted
        into the gap_extraction_queue table with a priority_score based on
        recency rank (higher score = more recent = higher priority).

        Args:
            eligible_ids: List of eligible pipeline record ID strings from
                get_eligible_opportunities().

        Returns:
            List of pipeline record ID strings selected for this cycle
            (at most max_extractions_per_cycle, ordered most-recent first).
        """
        from decimal import Decimal

        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models.gap_analytics import GapExtractionQueue
        from app.models.pipeline_record import PipelineRecord

        cap = self._config.max_extractions_per_cycle

        # If within cap, no need to query DB for ordering — return all
        if len(eligible_ids) <= cap:
            logger.info(
                "Batch within cap (%d <= %d), no carry-forward needed",
                len(eligible_ids),
                cap,
            )
            return eligible_ids

        # Query DB for the eligible records with their updated_at timestamps
        # to determine recency ordering
        eligible_uuids = [uuid.UUID(id_str) for id_str in eligible_ids]

        stmt = (
            select(PipelineRecord.id, PipelineRecord.updated_at)
            .where(PipelineRecord.id.in_(eligible_uuids))
            .order_by(PipelineRecord.updated_at.desc())
        )

        result = await self._db.execute(stmt)
        ordered_records = result.all()

        # Select top N for this cycle
        batch_records = ordered_records[:cap]
        remainder_records = ordered_records[cap:]

        batch_ids = [str(record.id) for record in batch_records]

        # Insert remainder into gap_extraction_queue with priority_score
        # Priority score = rank based on recency (higher = more recent)
        # The first remainder item gets the highest remainder priority,
        # decreasing from there
        if remainder_records:
            total_remainder = len(remainder_records)
            queue_entries = []
            for rank, record in enumerate(remainder_records):
                # Priority score: higher rank = more recent within remainder
                # Score ranges from total_remainder down to 1
                priority = Decimal(str(total_remainder - rank))
                queue_entries.append({
                    "pipeline_record_id": record.id,
                    "priority_score": priority,
                    "processed": False,
                })

            # Use INSERT ... ON CONFLICT DO NOTHING to handle re-runs gracefully
            insert_stmt = pg_insert(GapExtractionQueue).values(queue_entries)
            insert_stmt = insert_stmt.on_conflict_do_nothing(
                index_elements=["pipeline_record_id"]
            )
            await self._db.execute(insert_stmt)
            await self._db.commit()

            logger.info(
                "Batch cap enforced: %d selected, %d carried forward to queue",
                len(batch_ids),
                total_remainder,
            )

        return batch_ids

    # ─── Nightly Cycle Orchestration ─────────────────────────────────────

    async def run_nightly_cycle(self) -> dict:
        """Execute the full nightly gap analysis cycle.

        Steps:
        1. Fetch eligible opportunities (lost/rejected/C-D tier, within window)
        2. Filter already-extracted opportunities
        3. Extract capabilities from up to max_extractions_per_cycle opps
        4. Carry forward remainder to next cycle
        5. Generate heatmaps for each Consultant and firm-level
        6. Compute trend diffs against previous reports
        7. Notify Dashboard via WebSocket

        Returns:
            Summary dict with counts: extracted, carried_forward,
            heatmaps_generated, duration_seconds.
        """
        import time
        from datetime import timedelta
        from decimal import Decimal

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.models.gap_analytics import (
            BeneficiaryCapability,
            CanonicalCapability,
            ExtractedCapability as ExtractedCapabilityModel,
            GapHeatmap as GapHeatmapModel,
            GapHeatmapEntry,
            OpportunityExtraction,
        )
        from app.models.pipeline_record import PipelineRecord

        start_time = time.time()
        extracted_count = 0
        carried_forward_count = 0
        heatmaps_generated = 0

        logger.info("Starting nightly gap analysis cycle")

        # ── Step 1: Get eligible opportunities ────────────────────────────
        eligible_ids = await self.get_eligible_opportunities()
        logger.info("Eligible opportunities: %d", len(eligible_ids))

        # ── Step 2: Enforce batch cap (recency ordered) ───────────────────
        batch_ids = await self.enforce_batch_cap(eligible_ids)
        carried_forward_count = max(0, len(eligible_ids) - len(batch_ids))
        logger.info(
            "Batch: %d to process, %d carried forward",
            len(batch_ids),
            carried_forward_count,
        )

        # ── Step 3: Extract capabilities for each opportunity in batch ────
        for opp_id in batch_ids:
            try:
                # Load opportunity text from pipeline record + prospect data
                opportunity_text = await self._load_opportunity_text(opp_id)
                if not opportunity_text:
                    logger.warning(
                        "No text available for opportunity %s, skipping",
                        opp_id,
                    )
                    continue

                # Graceful degradation: skip extraction if LLM unavailable
                if self._llm is None:
                    logger.warning(
                        "LLM unavailable, skipping extraction for %s "
                        "(will use cached data only)",
                        opp_id,
                    )
                    continue

                await self.extract_capabilities(opp_id, opportunity_text)
                extracted_count += 1

            except ExtractionError as exc:
                # Graceful degradation: extraction failed after retries,
                # log and continue with next opportunity
                logger.error(
                    "Extraction failed for opportunity %s after %d attempts: %s",
                    opp_id,
                    exc.attempts,
                    str(exc),
                )
                continue

            except GapAnalysisError as exc:
                # Graceful degradation: other gap analysis errors
                logger.error(
                    "Gap analysis error for opportunity %s: %s",
                    opp_id,
                    str(exc),
                )
                continue

            except Exception as exc:
                # Graceful degradation: unexpected errors
                logger.error(
                    "Unexpected error during extraction for opportunity %s: %s",
                    opp_id,
                    str(exc),
                )
                continue

        logger.info(
            "Extraction phase complete: %d extracted this cycle",
            extracted_count,
        )

        # ── Step 4: Load all extracted capabilities within analysis window ─
        window_cutoff = datetime.now(timezone.utc) - timedelta(
            days=self._config.analysis_window_days
        )

        stmt = (
            select(ExtractedCapabilityModel)
            .join(OpportunityExtraction)
            .where(OpportunityExtraction.extracted_at >= window_cutoff)
            .options(selectinload(ExtractedCapabilityModel.canonical))
        )
        result = await self._db.execute(stmt)
        all_extracted_models = result.scalars().all()

        # Build ExtractedCapability dataclass instances from DB models
        # We need to map extraction_id → pipeline_record_id
        extraction_ids = {m.extraction_id for m in all_extracted_models}
        extraction_stmt = (
            select(
                OpportunityExtraction.id,
                OpportunityExtraction.pipeline_record_id,
            ).where(OpportunityExtraction.id.in_(extraction_ids))
        )
        extraction_result = await self._db.execute(extraction_stmt)
        extraction_to_opp = {
            row.id: str(row.pipeline_record_id)
            for row in extraction_result.all()
        }

        all_demanded: list[ExtractedCapability] = []
        for m in all_extracted_models:
            opp_id = extraction_to_opp.get(m.extraction_id, "")
            all_demanded.append(ExtractedCapability(
                raw_name=m.raw_name,
                canonical_name=m.canonical.canonical_name,
                level=CapabilityLevel(m.level),
                opportunity_id=opp_id,
            ))

        # Build opportunity_values map (opportunity_id → estimated value)
        opportunity_values = await self._build_opportunity_values(
            list(extraction_to_opp.values())
        )

        total_opportunities_analyzed = len(set(
            cap.opportunity_id for cap in all_demanded
        ))

        logger.info(
            "Loaded %d extracted capabilities from %d opportunities",
            len(all_demanded),
            total_opportunities_analyzed,
        )

        # ── Step 5: Load all beneficiary profiles ─────────────────────────
        ben_stmt = (
            select(BeneficiaryCapability)
            .options(selectinload(BeneficiaryCapability.canonical))
        )
        ben_result = await self._db.execute(ben_stmt)
        all_ben_caps = ben_result.scalars().all()

        # Group by beneficiary_id
        beneficiary_profiles: dict[str, set[str]] = defaultdict(set)
        beneficiary_levels: dict[str, dict[str, str]] = defaultdict(dict)
        for bc in all_ben_caps:
            cap_name = bc.canonical.canonical_name
            beneficiary_profiles[bc.beneficiary_id].add(cap_name)
            beneficiary_levels[bc.beneficiary_id][cap_name] = bc.proficiency_level

        # Build firm-level aggregate profile (union of all consultant caps)
        firm_profile: set[str] = set()
        firm_levels: dict[str, str] = {}
        for ben_id, caps in beneficiary_profiles.items():
            firm_profile.update(caps)
            for cap_name, level in beneficiary_levels[ben_id].items():
                # For firm-level, use highest proficiency if conflict
                existing = firm_levels.get(cap_name)
                if existing is None or _proficiency_rank(level) > _proficiency_rank(existing):
                    firm_levels[cap_name] = level

        # Collect all beneficiary IDs + "__firm__" for iteration
        all_beneficiary_ids = list(beneficiary_profiles.keys()) + ["__firm__"]

        logger.info(
            "Processing heatmaps for %d beneficiaries (including firm-level)",
            len(all_beneficiary_ids),
        )

        # ── Step 6: For each beneficiary, compute gaps → rank → trend → store ─
        for beneficiary_id in all_beneficiary_ids:
            try:
                if beneficiary_id == "__firm__":
                    profile_set = firm_profile
                    profile_lvls = firm_levels
                else:
                    profile_set = beneficiary_profiles.get(beneficiary_id, set())
                    profile_lvls = beneficiary_levels.get(beneficiary_id, {})

                # Compute gaps
                gaps = self.compute_gaps(
                    all_demanded, profile_set, opportunity_values, profile_lvls
                )

                # Detect single blockers
                single_blockers = self.detect_single_blockers(
                    all_demanded, profile_set
                )

                # Apply single-blocker weighting
                weighted_gaps = self.apply_single_blocker_weighting(
                    gaps, single_blockers
                )

                # Rank gaps (top 25)
                ranked_gaps = self.rank_gaps(
                    weighted_gaps,
                    max_entries=self._config.max_heatmap_entries,
                )

                # Load previous heatmap for trend comparison
                previous_gaps = await self._load_previous_heatmap_gaps(
                    beneficiary_id
                )

                # Compute trends
                gaps_with_trends = self.compute_trend(ranked_gaps, previous_gaps)

                # Filter out RESOLVED entries for storage (keep only active gaps)
                active_gaps = [
                    g for g in gaps_with_trends
                    if g.trend != GapTrend.RESOLVED
                ]

                # Store new heatmap in DB
                heatmap_id = await self._store_heatmap(
                    beneficiary_id=beneficiary_id,
                    gaps=active_gaps,
                    total_opportunities_analyzed=total_opportunities_analyzed,
                )

                heatmaps_generated += 1

                # Notify via WebSocket
                if self._ws is not None:
                    try:
                        generated_at = datetime.now(timezone.utc).isoformat()
                        await self._broadcast_heatmap_available(
                            beneficiary_id=beneficiary_id,
                            heatmap_id=heatmap_id,
                            generated_at=generated_at,
                        )
                    except Exception as ws_exc:
                        logger.warning(
                            "WebSocket notification failed for %s: %s",
                            beneficiary_id,
                            str(ws_exc),
                        )

            except Exception as exc:
                logger.error(
                    "Heatmap generation failed for beneficiary %s: %s",
                    beneficiary_id,
                    str(exc),
                )
                continue

        duration = time.time() - start_time
        summary = {
            "extracted": extracted_count,
            "carried_forward": carried_forward_count,
            "heatmaps_generated": heatmaps_generated,
            "duration_seconds": round(duration, 2),
        }

        logger.info("Nightly gap analysis cycle complete: %s", summary)
        return summary

    # ─── Nightly Cycle Helpers ────────────────────────────────────────────

    async def _load_opportunity_text(self, opportunity_id: str) -> str | None:
        """Load opportunity text from pipeline record and associated prospect data.

        Constructs a text description from the prospect's company information
        and enrichment data, suitable for LLM capability extraction.

        Args:
            opportunity_id: Pipeline record UUID string.

        Returns:
            Constructed opportunity text, or None if record not found.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.models.pipeline_record import PipelineRecord

        stmt = (
            select(PipelineRecord)
            .where(PipelineRecord.id == uuid.UUID(opportunity_id))
            .options(selectinload(PipelineRecord.prospect))
        )
        result = await self._db.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            return None

        prospect = record.prospect
        parts: list[str] = []

        parts.append(f"Company: {prospect.company_name}")
        if prospect.company_domain:
            parts.append(f"Domain: {prospect.company_domain}")
        parts.append(f"Opportunity Type: {record.opportunity_type_id}")
        parts.append(f"Beneficiary: {record.beneficiary_id}")

        # Add enrichment data if available
        if hasattr(prospect, "enrichment_record") and prospect.enrichment_record:
            enrichment = prospect.enrichment_record
            if enrichment.industry:
                parts.append(f"Industry: {enrichment.industry}")
            if enrichment.tech_stack:
                parts.append(f"Tech Stack: {', '.join(enrichment.tech_stack)}")
            if enrichment.employee_count:
                parts.append(f"Employee Count: {enrichment.employee_count}")

        return "\n".join(parts)

    async def _build_opportunity_values(
        self, opportunity_ids: list[str]
    ) -> dict[str, float]:
        """Build a map of opportunity_id → estimated pipeline value.

        Uses Account_Score tier to weight opportunity values:
        - C-tier: 50% of default_opportunity_value
        - D-tier: 25% of default_opportunity_value
        - Others: 100% of default_opportunity_value

        Args:
            opportunity_ids: List of pipeline record ID strings.

        Returns:
            Dict mapping opportunity_id → estimated value.
        """
        from sqlalchemy import select

        from app.models.account_score import AccountScore
        from app.models.pipeline_record import PipelineRecord

        if not opportunity_ids:
            return {}

        opp_uuids = [uuid.UUID(oid) for oid in set(opportunity_ids)]

        stmt = (
            select(PipelineRecord.id, AccountScore.tier)
            .outerjoin(
                AccountScore,
                AccountScore.prospect_id == PipelineRecord.prospect_id,
            )
            .where(PipelineRecord.id.in_(opp_uuids))
        )
        result = await self._db.execute(stmt)
        rows = result.all()

        values: dict[str, float] = {}
        for row in rows:
            tier = row.tier or "B-tier"
            weight = self.TIER_WEIGHT_MAP.get(tier, 1.0)
            values[str(row.id)] = self._config.default_opportunity_value * weight

        # Fill in defaults for any IDs not found
        for oid in opportunity_ids:
            if oid not in values:
                values[oid] = self._config.default_opportunity_value

        return values

    async def _load_previous_heatmap_gaps(
        self, beneficiary_id: str
    ) -> list[GapEntry] | None:
        """Load the most recent previous heatmap gaps for trend comparison.

        Args:
            beneficiary_id: The beneficiary to load previous heatmap for.

        Returns:
            List of GapEntry from the previous heatmap, or None if no previous.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.models.gap_analytics import (
            GapHeatmap as GapHeatmapModel,
            GapHeatmapEntry,
        )

        stmt = (
            select(GapHeatmapModel)
            .where(GapHeatmapModel.beneficiary_id == beneficiary_id)
            .order_by(GapHeatmapModel.generated_at.desc())
            .limit(1)
            .options(selectinload(GapHeatmapModel.entries).selectinload(
                GapHeatmapEntry.canonical
            ))
        )
        result = await self._db.execute(stmt)
        previous_heatmap = result.scalar_one_or_none()

        if previous_heatmap is None:
            return None

        previous_gaps: list[GapEntry] = []
        for entry in previous_heatmap.entries:
            previous_gaps.append(GapEntry(
                canonical_name=entry.canonical.canonical_name,
                classification=GapClassification(entry.classification),
                opportunity_count=entry.opportunity_count,
                blocked_pipeline_value=float(entry.blocked_pipeline_value),
                is_single_blocker=entry.is_single_blocker,
                weighted_rank_score=float(entry.weighted_rank_score),
                trend=GapTrend(entry.trend) if entry.trend else None,
            ))

        return previous_gaps

    async def _store_heatmap(
        self,
        beneficiary_id: str,
        gaps: list[GapEntry],
        total_opportunities_analyzed: int,
    ) -> str:
        """Store a new gap heatmap and its entries in the database.

        Uses a per-heatmap transaction for partial progress preservation.

        Args:
            beneficiary_id: The beneficiary this heatmap belongs to.
            gaps: Ranked gap entries to store.
            total_opportunities_analyzed: Total opps in analysis window.

        Returns:
            The new heatmap's UUID string.
        """
        from decimal import Decimal

        from sqlalchemy import select

        from app.models.gap_analytics import (
            CanonicalCapability,
            GapHeatmap as GapHeatmapModel,
            GapHeatmapEntry,
        )

        # Find previous heatmap ID for linking
        prev_stmt = (
            select(GapHeatmapModel.id)
            .where(GapHeatmapModel.beneficiary_id == beneficiary_id)
            .order_by(GapHeatmapModel.generated_at.desc())
            .limit(1)
        )
        prev_result = await self._db.execute(prev_stmt)
        previous_heatmap_id = prev_result.scalar_one_or_none()

        # Compute total blocked value
        total_blocked = sum(g.blocked_pipeline_value for g in gaps)

        # Create heatmap record
        heatmap = GapHeatmapModel(
            beneficiary_id=beneficiary_id,
            generated_at=datetime.now(timezone.utc),
            analysis_window_days=self._config.analysis_window_days,
            total_opportunities_analyzed=total_opportunities_analyzed,
            total_blocked_value=Decimal(str(round(total_blocked, 2))),
            previous_heatmap_id=previous_heatmap_id,
        )
        self._db.add(heatmap)
        await self._db.flush()

        # Store each gap entry
        for rank_position, gap in enumerate(gaps, start=1):
            # Resolve canonical_id
            canon_stmt = select(CanonicalCapability).where(
                CanonicalCapability.canonical_name == gap.canonical_name
            )
            canon_result = await self._db.execute(canon_stmt)
            canonical = canon_result.scalar_one_or_none()

            if canonical is None:
                # Create canonical entry if it doesn't exist yet
                canonical = CanonicalCapability(
                    canonical_name=gap.canonical_name
                )
                self._db.add(canonical)
                await self._db.flush()

            entry = GapHeatmapEntry(
                heatmap_id=heatmap.id,
                canonical_id=canonical.id,
                classification=gap.classification.value,
                opportunity_count=gap.opportunity_count,
                blocked_pipeline_value=Decimal(
                    str(round(gap.blocked_pipeline_value, 2))
                ),
                is_single_blocker=gap.is_single_blocker,
                weighted_rank_score=Decimal(
                    str(round(gap.weighted_rank_score, 2))
                ),
                trend=gap.trend.value if gap.trend else None,
                rank_position=rank_position,
            )
            self._db.add(entry)

        await self._db.commit()
        logger.info(
            "Stored heatmap %s for beneficiary %s with %d entries",
            str(heatmap.id),
            beneficiary_id,
            len(gaps),
        )

        return str(heatmap.id)

    async def _broadcast_heatmap_available(
        self,
        beneficiary_id: str,
        heatmap_id: str,
        generated_at: str,
    ) -> None:
        """Broadcast heatmap availability notification via WebSocket.

        Uses the WebSocket manager's _send_to_all for direct broadcast, and
        publishes to Redis pub/sub channel "gap_updates" for multi-worker
        distribution.

        Args:
            beneficiary_id: The beneficiary the heatmap is for.
            heatmap_id: UUID of the new heatmap.
            generated_at: ISO timestamp of generation.
        """
        message = json.dumps({
            "type": "gap_heatmap_available",
            "beneficiary_id": beneficiary_id,
            "heatmap_id": heatmap_id,
            "generated_at": generated_at,
        })

        # Publish to Redis pub/sub for multi-worker broadcast
        if self._redis is not None:
            await self._redis.publish("gap_updates", message)

        # Send to locally connected WebSocket clients
        if hasattr(self._ws, "broadcast_heatmap_available"):
            await self._ws.broadcast_heatmap_available(
                beneficiary_id, heatmap_id, generated_at
            )
        elif hasattr(self._ws, "_send_to_all"):
            await self._ws._send_to_all(message)

        logger.debug(
            "Broadcast heatmap available: beneficiary=%s, heatmap=%s",
            beneficiary_id,
            heatmap_id,
        )

    def compute_gaps(
        self,
        demanded_capabilities: list[ExtractedCapability],
        profile_capabilities: set[str],
        opportunity_values: dict[str, float],
        profile_levels: dict[str, str] | None = None,
    ) -> list[GapEntry]:
        """Compute gaps by diffing demanded capabilities against a profile.

        Pure computation — no I/O. Suitable for property-based testing.

        Args:
            demanded_capabilities: All extracted capabilities from analyzed opps.
            profile_capabilities: Set of canonical capability names the Beneficiary has.
            opportunity_values: Map of opportunity_id -> estimated value.
            profile_levels: Optional map of capability -> level ("senior", "mid", "junior").

        Returns:
            List of GapEntry objects, unsorted.
        """
        if profile_levels is None:
            profile_levels = {}

        # 1. Filter to REQUIRED level only
        required_caps = [
            cap for cap in demanded_capabilities
            if cap.level == CapabilityLevel.REQUIRED
        ]

        # 2. Group by canonical_name
        caps_by_name: dict[str, list[ExtractedCapability]] = defaultdict(list)
        for cap in required_caps:
            caps_by_name[cap.canonical_name].append(cap)

        # 3. For each canonical_name that is a gap (absent or junior level)
        gaps: list[GapEntry] = []
        for canonical_name, caps in caps_by_name.items():
            # Determine if this is a gap
            is_absent = canonical_name not in profile_capabilities
            is_junior = (
                canonical_name in profile_capabilities
                and profile_levels.get(canonical_name) == "junior"
            )

            if not is_absent and not is_junior:
                continue  # Not a gap — profile has sufficient capability

            # Compute opportunity_count (distinct opportunity_ids)
            opp_ids = {cap.opportunity_id for cap in caps}
            opportunity_count = len(opp_ids)

            # Compute blocked_pipeline_value (sum values for those opportunities)
            blocked_pipeline_value = sum(
                opportunity_values.get(opp_id, self._config.default_opportunity_value)
                for opp_id in opp_ids
            )

            # Classify gap
            classification = self.classify_gap(
                canonical_name, profile_capabilities, profile_levels
            )

            # is_single_blocker = False (set by detect_single_blockers later)
            # weighted_rank_score = blocked_pipeline_value (no single-blocker weight yet)
            # trend = None (set by compute_trend later)
            gaps.append(GapEntry(
                canonical_name=canonical_name,
                classification=classification,
                opportunity_count=opportunity_count,
                blocked_pipeline_value=blocked_pipeline_value,
                is_single_blocker=False,
                weighted_rank_score=blocked_pipeline_value,
                trend=None,
            ))

        return gaps

    def classify_gap(
        self,
        canonical_name: str,
        profile_capabilities: set[str],
        profile_levels: dict[str, str],
    ) -> GapClassification:
        """Classify a gap as hard (absent) or soft (present but insufficient).

        Args:
            canonical_name: The canonical capability name.
            profile_capabilities: Set of capabilities the profile declares.
            profile_levels: Map of capability -> level ("senior", "mid", "junior").

        Returns:
            HARD if capability absent, SOFT if present but junior/unevidenced.
        """
        if canonical_name not in profile_capabilities:
            return GapClassification.HARD
        # Present but junior level → soft gap
        if profile_levels.get(canonical_name) == "junior":
            return GapClassification.SOFT
        # If we reach here, the capability is sufficient — but this method
        # is only called for identified gaps, so treat as SOFT (unevidenced)
        return GapClassification.SOFT

    def rank_gaps(
        self, gaps: list[GapEntry], max_entries: int = 25
    ) -> list[GapEntry]:
        """Rank gaps by weighted_rank_score descending, truncate to max_entries.

        Args:
            gaps: Unranked gap entries.
            max_entries: Maximum entries to return (default 25).

        Returns:
            Top N gaps sorted by weighted_rank_score descending.
        """
        sorted_gaps = sorted(
            gaps, key=lambda g: g.weighted_rank_score, reverse=True
        )
        return sorted_gaps[:max_entries]

    def compute_trend(
        self, current_gaps: list[GapEntry], previous_gaps: list[GapEntry] | None
    ) -> list[GapEntry]:
        """Compute trend annotations by diffing against previous heatmap.

        Classification rules:
        - NEW: capability not in previous report
        - GROWING: blocked_pipeline_value increased vs previous
        - SHRINKING: blocked_pipeline_value decreased vs previous
        - RESOLVED: was in previous report but no longer a gap
        - None: present in both with same blocked_pipeline_value (stable)

        Args:
            current_gaps: Current cycle's gap entries.
            previous_gaps: Previous heatmap's gap entries (None if first report).

        Returns:
            Current gaps with trend field populated, plus RESOLVED entries
            for gaps that were in previous but are no longer present.
        """
        # If no previous report, all current gaps are NEW
        if previous_gaps is None:
            return [
                GapEntry(
                    canonical_name=gap.canonical_name,
                    classification=gap.classification,
                    opportunity_count=gap.opportunity_count,
                    blocked_pipeline_value=gap.blocked_pipeline_value,
                    is_single_blocker=gap.is_single_blocker,
                    weighted_rank_score=gap.weighted_rank_score,
                    trend=GapTrend.NEW,
                )
                for gap in current_gaps
            ]

        # Build lookup from previous gaps: canonical_name → GapEntry
        previous_lookup: dict[str, GapEntry] = {
            gap.canonical_name: gap for gap in previous_gaps
        }

        # Classify each current gap
        result: list[GapEntry] = []
        current_names: set[str] = set()

        for gap in current_gaps:
            current_names.add(gap.canonical_name)

            if gap.canonical_name not in previous_lookup:
                trend = GapTrend.NEW
            else:
                prev = previous_lookup[gap.canonical_name]
                if gap.blocked_pipeline_value > prev.blocked_pipeline_value:
                    trend = GapTrend.GROWING
                elif gap.blocked_pipeline_value < prev.blocked_pipeline_value:
                    trend = GapTrend.SHRINKING
                else:
                    # Same value — stable, no trend annotation
                    trend = None

            result.append(GapEntry(
                canonical_name=gap.canonical_name,
                classification=gap.classification,
                opportunity_count=gap.opportunity_count,
                blocked_pipeline_value=gap.blocked_pipeline_value,
                is_single_blocker=gap.is_single_blocker,
                weighted_rank_score=gap.weighted_rank_score,
                trend=trend,
            ))

        # Append RESOLVED entries for previous gaps not in current
        for prev_gap in previous_gaps:
            if prev_gap.canonical_name not in current_names:
                result.append(GapEntry(
                    canonical_name=prev_gap.canonical_name,
                    classification=prev_gap.classification,
                    opportunity_count=0,
                    blocked_pipeline_value=0.0,
                    is_single_blocker=False,
                    weighted_rank_score=0.0,
                    trend=GapTrend.RESOLVED,
                ))

        return result

    def detect_single_blockers(
        self,
        demanded_capabilities: list[ExtractedCapability],
        profile_capabilities: set[str],
    ) -> set[str]:
        """Identify capabilities that were the sole unmet required capability.

        For each opportunity, if exactly one required capability is unmet,
        that capability is a single-blocker.

        Args:
            demanded_capabilities: All extracted capabilities (required only).
            profile_capabilities: Set of canonical names the profile has.

        Returns:
            Set of canonical capability names that are single-blockers.
        """
        # 1. Filter to REQUIRED level only
        required_caps = [
            cap for cap in demanded_capabilities
            if cap.level == CapabilityLevel.REQUIRED
        ]

        # 2. Group by opportunity_id
        caps_by_opp: dict[str, set[str]] = defaultdict(set)
        for cap in required_caps:
            caps_by_opp[cap.opportunity_id].add(cap.canonical_name)

        # 3. For each opportunity, find unmet required capabilities
        single_blockers: set[str] = set()
        for _opp_id, required_names in caps_by_opp.items():
            unmet = required_names - profile_capabilities
            # If exactly 1 unmet capability, it's a single-blocker
            if len(unmet) == 1:
                single_blockers.update(unmet)

        return single_blockers

    def apply_single_blocker_weighting(
        self,
        gaps: list[GapEntry],
        single_blockers: set[str],
    ) -> list[GapEntry]:
        """Apply 2x weighting to gaps that are single-blockers.

        Since GapEntry is frozen, creates new instances with updated fields.

        Args:
            gaps: List of computed gap entries.
            single_blockers: Set of canonical names flagged as single-blockers.

        Returns:
            New list of GapEntry with is_single_blocker and weighted_rank_score updated.
        """
        updated_gaps: list[GapEntry] = []
        for gap in gaps:
            if gap.canonical_name in single_blockers:
                updated_gaps.append(GapEntry(
                    canonical_name=gap.canonical_name,
                    classification=gap.classification,
                    opportunity_count=gap.opportunity_count,
                    blocked_pipeline_value=gap.blocked_pipeline_value,
                    is_single_blocker=True,
                    weighted_rank_score=gap.blocked_pipeline_value * self._config.single_blocker_weight,
                    trend=gap.trend,
                ))
            else:
                updated_gaps.append(gap)
        return updated_gaps

    async def load_opportunity_text_for_on_demand(
        self,
        pipeline_record_id: str | None = None,
        opportunity_url: str | None = None,
    ) -> str:
        """Load opportunity text from DB by pipeline_record_id or fetch from URL.

        Exactly one of the two parameters must be provided.

        Args:
            pipeline_record_id: UUID string of an existing pipeline record.
            opportunity_url: URL to fetch opportunity text from.

        Returns:
            The opportunity text suitable for LLM extraction.

        Raises:
            GapAnalysisError: If neither or both are provided, if the record
                is not found, if the URL fetch fails, or if the text is
                too short for meaningful analysis.
        """
        import httpx

        MIN_TEXT_LENGTH = 20  # Minimum chars for meaningful extraction

        if pipeline_record_id is not None and opportunity_url is not None:
            raise GapAnalysisError(
                "Provide only one of pipeline_record_id or opportunity_url",
                opportunity_id=pipeline_record_id,
            )

        if pipeline_record_id is None and opportunity_url is None:
            raise GapAnalysisError(
                "Must provide either pipeline_record_id or opportunity_url"
            )

        # ── Load from DB by pipeline_record_id ────────────────────────────
        if pipeline_record_id is not None:
            if self._db is None:
                raise GapAnalysisError(
                    "Database session not available for pipeline record lookup",
                    opportunity_id=pipeline_record_id,
                )
            text = await self._load_opportunity_text(pipeline_record_id)
            if text is None:
                raise GapAnalysisError(
                    f"Pipeline record '{pipeline_record_id}' not found",
                    opportunity_id=pipeline_record_id,
                )
            if len(text.strip()) < MIN_TEXT_LENGTH:
                raise GapAnalysisError(
                    "Opportunity text is too short for meaningful analysis",
                    opportunity_id=pipeline_record_id,
                )
            return text

        # ── Fetch from URL ────────────────────────────────────────────────
        assert opportunity_url is not None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(opportunity_url)
                response.raise_for_status()
                text = response.text
        except httpx.TimeoutException:
            raise GapAnalysisError(
                f"Timed out fetching opportunity from URL: {opportunity_url}"
            )
        except httpx.HTTPStatusError as exc:
            raise GapAnalysisError(
                f"HTTP {exc.response.status_code} fetching URL: {opportunity_url}"
            )
        except httpx.HTTPError as exc:
            raise GapAnalysisError(
                f"Failed to fetch opportunity from URL: {opportunity_url} — {exc}"
            )

        if len(text.strip()) < MIN_TEXT_LENGTH:
            raise GapAnalysisError(
                "Fetched opportunity text is too short for meaningful analysis"
            )
        return text

    async def analyze_on_demand(
        self,
        opportunity_text: str,
        consultant_id: str,
        opportunity_id: str | None = None,
        opportunity_url: str | None = None,
    ) -> OnDemandGapReport:
        """Perform on-demand gap analysis for a single opportunity.

        Must complete within on_demand_timeout_seconds (default 120s).

        Args:
            opportunity_text: Full text of the opportunity.
            consultant_id: Beneficiary ID to diff against.
            opportunity_id: Optional pipeline record ID.
            opportunity_url: Optional source URL.

        Returns:
            OnDemandGapReport with all identified gaps.

        Raises:
            OnDemandTimeoutError: If analysis exceeds timeout budget.
        """
        import asyncio

        try:
            return await asyncio.wait_for(
                self._analyze_on_demand_inner(
                    opportunity_text=opportunity_text,
                    consultant_id=consultant_id,
                    opportunity_id=opportunity_id,
                    opportunity_url=opportunity_url,
                ),
                timeout=self._config.on_demand_timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise OnDemandTimeoutError(
                message=(
                    f"On-demand gap analysis exceeded "
                    f"{self._config.on_demand_timeout_seconds}s timeout"
                ),
                opportunity_id=opportunity_id,
                timeout_seconds=float(self._config.on_demand_timeout_seconds),
            )

    async def _analyze_on_demand_inner(
        self,
        opportunity_text: str,
        consultant_id: str,
        opportunity_id: str | None = None,
        opportunity_url: str | None = None,
    ) -> OnDemandGapReport:
        """Inner implementation of on-demand analysis (called within timeout).

        Performs: extract → normalize → load profile → diff → classify → report.

        Args:
            opportunity_text: Full text of the opportunity.
            consultant_id: Beneficiary ID to diff against.
            opportunity_id: Optional pipeline record ID.
            opportunity_url: Optional source URL.

        Returns:
            OnDemandGapReport with required and preferred gaps.
        """
        from collections import defaultdict

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.models.gap_analytics import BeneficiaryCapability

        # 1. Extract capabilities via LLM
        effective_opp_id = opportunity_id or str(uuid.uuid4())
        extraction = await self.extract_capabilities(
            effective_opp_id, opportunity_text
        )

        # 2. Normalize extracted capabilities
        required_normalized = self._normalizer.batch_normalize(
            extraction.required_capabilities
        )
        preferred_normalized = self._normalizer.batch_normalize(
            extraction.preferred_capabilities
        )

        # 3. Load consultant profile from DB (beneficiary_capabilities)
        stmt = (
            select(BeneficiaryCapability)
            .where(BeneficiaryCapability.beneficiary_id == consultant_id)
            .options(selectinload(BeneficiaryCapability.canonical))
        )
        result = await self._db.execute(stmt)
        profile_records = result.scalars().all()

        profile_capabilities: set[str] = set()
        profile_levels: dict[str, str] = {}
        for bc in profile_records:
            cap_name = bc.canonical.canonical_name
            profile_capabilities.add(cap_name)
            profile_levels[cap_name] = bc.proficiency_level

        # 4. Compute required gaps
        required_gaps: list[GapEntry] = []
        for raw_name, canonical_name in zip(
            extraction.required_capabilities, required_normalized
        ):
            classification = self.classify_gap(
                canonical_name, profile_capabilities, profile_levels
            )
            # Only include if it's actually a gap
            is_absent = canonical_name not in profile_capabilities
            is_junior = (
                canonical_name in profile_capabilities
                and profile_levels.get(canonical_name) == "junior"
            )
            if is_absent or is_junior:
                required_gaps.append(GapEntry(
                    canonical_name=canonical_name,
                    classification=classification,
                    opportunity_count=1,
                    blocked_pipeline_value=self._config.default_opportunity_value,
                    is_single_blocker=False,
                    weighted_rank_score=self._config.default_opportunity_value,
                    trend=None,
                ))

        # Deduplicate required gaps by canonical_name
        required_gaps = self._deduplicate_gap_entries(required_gaps)

        # 5. Compute preferred gaps
        preferred_gaps: list[GapEntry] = []
        for raw_name, canonical_name in zip(
            extraction.preferred_capabilities, preferred_normalized
        ):
            classification = self.classify_gap(
                canonical_name, profile_capabilities, profile_levels
            )
            is_absent = canonical_name not in profile_capabilities
            is_junior = (
                canonical_name in profile_capabilities
                and profile_levels.get(canonical_name) == "junior"
            )
            if is_absent or is_junior:
                preferred_gaps.append(GapEntry(
                    canonical_name=canonical_name,
                    classification=classification,
                    opportunity_count=1,
                    blocked_pipeline_value=0.0,
                    is_single_blocker=False,
                    weighted_rank_score=0.0,
                    trend=None,
                ))

        # Deduplicate preferred gaps by canonical_name
        preferred_gaps = self._deduplicate_gap_entries(preferred_gaps)

        # 6. Detect single blockers among required gaps
        if len(required_gaps) == 1:
            # Exactly one unmet required capability → it's a single-blocker
            gap = required_gaps[0]
            required_gaps = [GapEntry(
                canonical_name=gap.canonical_name,
                classification=gap.classification,
                opportunity_count=gap.opportunity_count,
                blocked_pipeline_value=gap.blocked_pipeline_value,
                is_single_blocker=True,
                weighted_rank_score=(
                    gap.blocked_pipeline_value * self._config.single_blocker_weight
                ),
                trend=gap.trend,
            )]

        # 7. Build report
        total_required = len(required_normalized)
        # Unique canonical names that matched (not gaps)
        required_canonical_set = set(required_normalized)
        matched_set = required_canonical_set - {
            g.canonical_name for g in required_gaps
        }
        total_matched = len(matched_set)
        gap_percentage = (
            (len(required_gaps) / total_required * 100.0)
            if total_required > 0
            else 0.0
        )

        return OnDemandGapReport(
            opportunity_id=opportunity_id,
            opportunity_url=opportunity_url,
            consultant_id=consultant_id,
            required_gaps=required_gaps,
            preferred_gaps=preferred_gaps,
            total_required=total_required,
            total_matched=total_matched,
            gap_percentage=gap_percentage,
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _deduplicate_gap_entries(gaps: list[GapEntry]) -> list[GapEntry]:
        """Deduplicate gap entries by canonical_name, keeping first occurrence.

        Args:
            gaps: List of potentially duplicate GapEntry objects.

        Returns:
            Deduplicated list preserving order of first occurrence.
        """
        seen: set[str] = set()
        unique_gaps: list[GapEntry] = []
        for gap in gaps:
            if gap.canonical_name not in seen:
                seen.add(gap.canonical_name)
                unique_gaps.append(gap)
        return unique_gaps

    async def generate_learning_recommendation(
        self, canonical_name: str
    ) -> LearningRecommendation:
        """Generate an LLM-based learning recommendation for a gap.

        Calls LLM_Router with capability context. Result is advisory only.

        Args:
            canonical_name: The canonical capability name to recommend for.

        Returns:
            LearningRecommendation with resources and effort estimate.
        """
        prompt = (
            "You are a technical learning advisor. For the following capability, "
            "provide a learning recommendation with specific study resources and "
            "a rough effort estimate.\n\n"
            f"Capability: {canonical_name}\n\n"
            "Respond in JSON format:\n"
            "{\n"
            '  "resources": ["resource1", "resource2", ...],\n'
            '  "effort_estimate": "X-Y weeks part-time"\n'
            "}\n\n"
            "Resources should be specific and actionable (e.g., official docs, "
            "courses, books, certifications). Provide 3-5 resources.\n"
            "Effort estimate should reflect realistic part-time study commitment "
            "for a working professional to reach a competent level."
        )

        response = await retry_llm_call(
            self._llm.dispatch_extraction,
            prompt,
        )

        # Parse resources from response, with defensive defaults
        resources = response.get("resources", [])
        if not isinstance(resources, list):
            resources = [str(resources)]
        # Ensure all entries are strings
        resources = [str(r) for r in resources if r]

        effort_estimate = response.get("effort_estimate", "2-4 weeks part-time")
        if not isinstance(effort_estimate, str):
            effort_estimate = str(effort_estimate)

        return LearningRecommendation(
            canonical_name=canonical_name,
            resources=resources,
            effort_estimate=effort_estimate,
            advisory_note=(
                "This is advisory only — recommendations are AI-generated "
                "and should be validated"
            ),
            generated_at=datetime.now(timezone.utc),
        )


# ─── Module-level helpers ─────────────────────────────────────────────────────


def _proficiency_rank(level: str) -> int:
    """Return a numeric rank for proficiency level comparison.

    Higher rank = more proficient. Used to resolve conflicts when building
    the firm-level aggregate profile (union of all consultants).

    Args:
        level: Proficiency level string ("senior", "mid", "junior").

    Returns:
        Integer rank: senior=3, mid=2, junior=1, unknown=0.
    """
    _RANK_MAP = {
        "senior": 3,
        "mid": 2,
        "junior": 1,
    }
    return _RANK_MAP.get(level, 0)
