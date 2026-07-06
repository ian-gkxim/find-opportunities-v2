"""Tests for the Discovery Pipeline.

Covers:
- Deduplication by domain and normalized company name
- Multi-source bonus computation
- Score threshold filtering
- Source health state machine (active → suspended → permanently_suspended)
- Recovery with backoff
- 5-minute timeout enforcement
- Merge retains most recent values
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.discovery_pipeline import (
    DiscoveryConfig,
    DiscoveryPipeline,
    RawProspect,
    SourceHealthState,
    SourceStatus,
    SourceType,
)
from app.core.scoring_engine import ScoringEngine

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def scoring_engine():
    """Provide a default ScoringEngine."""
    return ScoringEngine()


@pytest.fixture
def pipeline(scoring_engine):
    """Provide a DiscoveryPipeline with no existing prospects."""
    return DiscoveryPipeline(scoring_engine=scoring_engine)


@pytest.fixture
def pipeline_with_existing(scoring_engine):
    """Provide a pipeline with pre-existing prospects for deduplication testing."""
    existing = [
        {
            "company_name": "Acme Inc",
            "company_domain": "acme.com",
            "normalized_name": "acme",
            "source_count": 1,
            "sources": ["adzuna"],
            "enrichment_data": {"industry": "tech", "size": 100},
            "discovered_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        },
        {
            "company_name": "Beta Corp",
            "company_domain": None,
            "normalized_name": "beta",
            "source_count": 1,
            "sources": ["apollo"],
            "enrichment_data": {"industry": "finance"},
            "discovered_at": datetime(2024, 1, 5, tzinfo=timezone.utc),
            "updated_at": datetime(2024, 1, 5, tzinfo=timezone.utc),
        },
    ]
    return DiscoveryPipeline(
        scoring_engine=scoring_engine, existing_prospects=existing
    )


# ─── Test _normalize_company_name ─────────────────────────────────────────────


class TestNormalizeCompanyName:
    """Tests for company name normalization."""

    def test_basic_normalization(self, pipeline):
        assert pipeline._normalize_company_name("Acme Inc.") == "acme"

    def test_strips_suffixes(self, pipeline):
        assert pipeline._normalize_company_name("BETA Corporation") == "beta"
        assert pipeline._normalize_company_name("Gamma LLC") == "gamma"

    def test_handles_empty_string(self, pipeline):
        assert pipeline._normalize_company_name("") == ""

    def test_unicode_normalization(self, pipeline):
        # NFKD normalization handles accented characters
        result = pipeline._normalize_company_name("Café Technologies")
        assert "cafe" in result

    def test_case_insensitive(self, pipeline):
        assert pipeline._normalize_company_name("ACME") == pipeline._normalize_company_name("acme")

    def test_punctuation_stripped(self, pipeline):
        # "Company" and "Inc" are stripped as common suffixes by normalize_company_name
        assert pipeline._normalize_company_name("My-Company, Inc.") == "my"


# ─── Test deduplicate_and_merge ───────────────────────────────────────────────


class TestDeduplicateAndMerge:
    """Tests for deduplication and merging logic."""

    @pytest.mark.asyncio
    async def test_new_prospect_no_match(self, pipeline):
        """A prospect with no matching existing record is marked as new."""
        prospects = [
            RawProspect(
                company_name="New Corp",
                company_domain="newcorp.com",
                source_type=SourceType.ADZUNA,
                beneficiary_id="consultant",
            )
        ]
        result = await pipeline.deduplicate_and_merge(prospects)
        assert len(result) == 1
        assert result[0]["is_new"] is True
        assert result[0]["source_count"] == 1

    @pytest.mark.asyncio
    async def test_match_by_domain(self, pipeline_with_existing):
        """Prospect matching an existing record by domain is merged."""
        prospects = [
            RawProspect(
                company_name="Acme Corporation",
                company_domain="acme.com",
                source_type=SourceType.APOLLO,
                beneficiary_id="consultant",
                enrichment_data={"revenue": "10M"},
            )
        ]
        result = await pipeline_with_existing.deduplicate_and_merge(prospects)
        assert len(result) == 1
        assert result[0]["is_new"] is False
        assert result[0]["source_count"] == 2
        assert "adzuna" in result[0]["sources"]
        assert "apollo" in result[0]["sources"]

    @pytest.mark.asyncio
    async def test_match_by_normalized_name(self, pipeline_with_existing):
        """Prospect matching by normalized name (no domain) is merged."""
        prospects = [
            RawProspect(
                company_name="Beta Corp.",
                company_domain=None,
                source_type=SourceType.INTERNET_SEARCH,
                beneficiary_id="team",
                enrichment_data={"headquarters": "London"},
            )
        ]
        result = await pipeline_with_existing.deduplicate_and_merge(prospects)
        assert len(result) == 1
        assert result[0]["is_new"] is False
        assert result[0]["source_count"] == 2
        assert "internet_search" in result[0]["sources"]

    @pytest.mark.asyncio
    async def test_merge_retains_most_recent_values(self, pipeline_with_existing):
        """Merged prospect retains new enrichment field values."""
        prospects = [
            RawProspect(
                company_name="Acme Inc",
                company_domain="acme.com",
                source_type=SourceType.APOLLO,
                beneficiary_id="consultant",
                enrichment_data={"industry": "software", "funding": "Series B"},
            )
        ]
        result = await pipeline_with_existing.deduplicate_and_merge(prospects)
        enrichment = result[0]["enrichment_data"]
        # New value overwrites old
        assert enrichment["industry"] == "software"
        # Old value retained when not overwritten
        assert enrichment["size"] == 100
        # New field added
        assert enrichment["funding"] == "Series B"

    @pytest.mark.asyncio
    async def test_batch_deduplication_within_batch(self, pipeline):
        """Duplicates within the same batch are merged."""
        prospects = [
            RawProspect(
                company_name="DupCo",
                company_domain="dupco.com",
                source_type=SourceType.ADZUNA,
                beneficiary_id="consultant",
            ),
            RawProspect(
                company_name="DupCo Inc",
                company_domain="dupco.com",
                source_type=SourceType.APOLLO,
                beneficiary_id="consultant",
            ),
        ]
        result = await pipeline.deduplicate_and_merge(prospects)
        assert len(result) == 2  # First creates new, second merges
        # The second should have merged with the first
        merged = [r for r in result if not r.get("is_new", True)]
        new = [r for r in result if r.get("is_new", True)]
        assert len(new) == 1
        assert len(merged) == 1
        assert merged[0]["source_count"] == 2


# ─── Test Multi-Source Bonus ──────────────────────────────────────────────────


class TestMultiSourceBonus:
    """Tests for multi-source bonus computation."""

    def test_single_source_no_bonus(self, pipeline):
        assert pipeline.compute_multi_source_bonus(1) == 0

    def test_two_sources_10_bonus(self, pipeline):
        assert pipeline.compute_multi_source_bonus(2) == 10

    def test_three_sources_20_bonus(self, pipeline):
        assert pipeline.compute_multi_source_bonus(3) == 20

    def test_four_sources_max_30_bonus(self, pipeline):
        assert pipeline.compute_multi_source_bonus(4) == 30

    def test_more_than_four_sources_capped_at_30(self, pipeline):
        assert pipeline.compute_multi_source_bonus(5) == 30
        assert pipeline.compute_multi_source_bonus(10) == 30


# ─── Test Score Threshold Filtering ──────────────────────────────────────────


class TestScoreThresholdFiltering:
    """Tests for score threshold filtering."""

    def test_default_threshold_25(self, pipeline):
        prospects = [
            {"company_name": "A", "score": 24},
            {"company_name": "B", "score": 25},
            {"company_name": "C", "score": 50},
        ]
        result = pipeline.apply_score_threshold(prospects)
        assert len(result) == 2
        assert all(p["score"] >= 25 for p in result)

    def test_custom_threshold(self, pipeline):
        prospects = [
            {"company_name": "A", "score": 49},
            {"company_name": "B", "score": 50},
            {"company_name": "C", "score": 75},
        ]
        result = pipeline.apply_score_threshold(prospects, threshold=50)
        assert len(result) == 2

    def test_threshold_zero_keeps_all(self, pipeline):
        prospects = [
            {"company_name": "A", "score": 0},
            {"company_name": "B", "score": 1},
        ]
        result = pipeline.apply_score_threshold(prospects, threshold=0)
        assert len(result) == 2

    def test_threshold_100_filters_most(self, pipeline):
        prospects = [
            {"company_name": "A", "score": 99},
            {"company_name": "B", "score": 100},
        ]
        result = pipeline.apply_score_threshold(prospects, threshold=100)
        assert len(result) == 1
        assert result[0]["score"] == 100


# ─── Test Source Health State Machine ─────────────────────────────────────────


class TestSourceHealthStateMachine:
    """Tests for source health tracking with suspension and recovery."""

    @pytest.mark.asyncio
    async def test_initial_status_is_active(self, pipeline):
        status = await pipeline.check_source_health(SourceType.ADZUNA)
        assert status == SourceStatus.ACTIVE

    def test_single_failure_stays_active(self, pipeline):
        pipeline._record_failure(SourceType.ADZUNA)
        health = pipeline.get_source_health(SourceType.ADZUNA)
        assert health.status == SourceStatus.ACTIVE
        assert health.consecutive_failures == 1

    def test_three_failures_triggers_suspension(self, pipeline):
        for _ in range(3):
            pipeline._record_failure(SourceType.ADZUNA)
        health = pipeline.get_source_health(SourceType.ADZUNA)
        assert health.status == SourceStatus.SUSPENDED
        assert health.consecutive_failures == 3
        assert health.suspended_at is not None

    def test_success_resets_failure_count(self, pipeline):
        pipeline._record_failure(SourceType.ADZUNA)
        pipeline._record_failure(SourceType.ADZUNA)
        pipeline._record_success(SourceType.ADZUNA)
        health = pipeline.get_source_health(SourceType.ADZUNA)
        assert health.status == SourceStatus.ACTIVE
        assert health.consecutive_failures == 0

    def test_recovery_success_returns_to_active(self, pipeline):
        # Suspend the source
        for _ in range(3):
            pipeline._record_failure(SourceType.APOLLO)
        health = pipeline.get_source_health(SourceType.APOLLO)
        assert health.status == SourceStatus.SUSPENDED

        # Successful recovery
        pipeline._record_success(SourceType.APOLLO)
        health = pipeline.get_source_health(SourceType.APOLLO)
        assert health.status == SourceStatus.ACTIVE
        assert health.recovery_attempts == 0

    def test_three_recovery_failures_permanent_suspension(self, pipeline):
        # Suspend the source
        for _ in range(3):
            pipeline._record_failure(SourceType.ADZUNA)
        health = pipeline.get_source_health(SourceType.ADZUNA)
        assert health.status == SourceStatus.SUSPENDED

        # 3 recovery failures
        for _ in range(3):
            pipeline._record_failure(SourceType.ADZUNA)
        health = pipeline.get_source_health(SourceType.ADZUNA)
        assert health.status == SourceStatus.PERMANENTLY_SUSPENDED
        assert health.recovery_attempts == 3

    def test_backoff_period_check(self, pipeline):
        """Recovery cannot be attempted before 1-hour backoff elapsed."""
        health = SourceHealthState(
            source_type=SourceType.ADZUNA,
            status=SourceStatus.SUSPENDED,
            consecutive_failures=3,
            suspended_at=datetime.now(timezone.utc),  # Just now
            recovery_attempts=0,
        )
        pipeline.set_source_health(SourceType.ADZUNA, health)
        # Should not be able to attempt recovery yet
        assert pipeline._can_attempt_recovery(health) is False

    def test_backoff_period_elapsed(self, pipeline):
        """Recovery can be attempted after 1-hour backoff."""
        health = SourceHealthState(
            source_type=SourceType.ADZUNA,
            status=SourceStatus.SUSPENDED,
            consecutive_failures=3,
            suspended_at=datetime.now(timezone.utc) - timedelta(hours=2),
            recovery_attempts=0,
        )
        pipeline.set_source_health(SourceType.ADZUNA, health)
        assert pipeline._can_attempt_recovery(health) is True


# ─── Test run_discovery ───────────────────────────────────────────────────────


class TestRunDiscovery:
    """Tests for the full discovery run orchestration."""

    @pytest.mark.asyncio
    async def test_successful_discovery_run(self, scoring_engine):
        """A successful run discovers, deduplicates, and scores prospects."""
        mock_client = AsyncMock()
        mock_client.discover.return_value = [
            RawProspect(
                company_name="TestCo",
                company_domain="testco.com",
                source_type=SourceType.ADZUNA,
                beneficiary_id="consultant",
            ),
        ]
        pipeline = DiscoveryPipeline(
            scoring_engine=scoring_engine,
            source_clients={SourceType.ADZUNA: mock_client},
        )
        result = await pipeline.run_discovery(
            SourceType.ADZUNA, "consultant"
        )
        assert result.prospects_found == 1
        assert result.source_type == SourceType.ADZUNA
        assert result.duration_seconds > 0
        mock_client.discover.assert_called_once_with("consultant")

    @pytest.mark.asyncio
    async def test_discovery_timeout(self, scoring_engine):
        """A source that exceeds timeout results in failure."""

        async def slow_discover(beneficiary_id):
            await asyncio.sleep(10)
            return []

        mock_client = AsyncMock()
        mock_client.discover.side_effect = slow_discover

        pipeline = DiscoveryPipeline(
            scoring_engine=scoring_engine,
            source_clients={SourceType.ADZUNA: mock_client},
        )
        config = DiscoveryConfig(
            source_type=SourceType.ADZUNA, max_runtime=1  # 1 second timeout
        )
        result = await pipeline.run_discovery(
            SourceType.ADZUNA, "consultant", config=config
        )
        assert result.prospects_found == 0
        # Failure should be recorded
        health = pipeline.get_source_health(SourceType.ADZUNA)
        assert health.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_discovery_skips_permanently_suspended(self, scoring_engine):
        """Permanently suspended sources are skipped immediately."""
        mock_client = AsyncMock()
        pipeline = DiscoveryPipeline(
            scoring_engine=scoring_engine,
            source_clients={SourceType.APOLLO: mock_client},
        )
        # Set source as permanently suspended
        pipeline.set_source_health(
            SourceType.APOLLO,
            SourceHealthState(
                source_type=SourceType.APOLLO,
                status=SourceStatus.PERMANENTLY_SUSPENDED,
            ),
        )
        result = await pipeline.run_discovery(SourceType.APOLLO, "consultant")
        assert result.prospects_found == 0
        mock_client.discover.assert_not_called()

    @pytest.mark.asyncio
    async def test_discovery_no_client_configured(self, scoring_engine):
        """Missing client configuration returns empty result."""
        pipeline = DiscoveryPipeline(
            scoring_engine=scoring_engine, source_clients={}
        )
        result = await pipeline.run_discovery(SourceType.ADZUNA, "consultant")
        assert result.prospects_found == 0

    @pytest.mark.asyncio
    async def test_discovery_failure_increments_failure_count(self, scoring_engine):
        """A failed discovery increments the consecutive failure counter."""
        mock_client = AsyncMock()
        mock_client.discover.side_effect = RuntimeError("API error")

        pipeline = DiscoveryPipeline(
            scoring_engine=scoring_engine,
            source_clients={SourceType.ADZUNA: mock_client},
        )
        await pipeline.run_discovery(SourceType.ADZUNA, "consultant")
        health = pipeline.get_source_health(SourceType.ADZUNA)
        assert health.consecutive_failures == 1
