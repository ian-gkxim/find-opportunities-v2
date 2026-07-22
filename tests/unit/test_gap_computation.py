"""Unit tests for GapAnalyzer.compute_gaps() and classify_gap().

Tests requirements 2.1 and 2.2:
- Diff demanded capabilities against profile set
- Classify gaps as HARD (absent) or SOFT (junior/unevidenced)
- Compute opportunity_count and blocked_pipeline_value per gap
"""

import pytest

from app.core.gap_analyzer import (
    CapabilityLevel,
    ExtractedCapability,
    GapAnalysisConfig,
    GapAnalyzer,
    GapClassification,
)


@pytest.fixture
def analyzer() -> GapAnalyzer:
    """Create a GapAnalyzer with minimal config and no external deps."""
    config = GapAnalysisConfig(default_opportunity_value=10000.0)
    return GapAnalyzer(
        config=config,
        llm_router=None,
        schema_registry=None,
        db_session=None,
        redis_client=None,
        ws_manager=None,
    )


class TestClassifyGap:
    """Tests for classify_gap()."""

    def test_absent_capability_classified_as_hard(self, analyzer: GapAnalyzer):
        result = analyzer.classify_gap(
            canonical_name="kubernetes",
            profile_capabilities={"python", "aws"},
            profile_levels={"python": "senior", "aws": "mid"},
        )
        assert result == GapClassification.HARD

    def test_junior_capability_classified_as_soft(self, analyzer: GapAnalyzer):
        result = analyzer.classify_gap(
            canonical_name="kubernetes",
            profile_capabilities={"kubernetes", "python"},
            profile_levels={"kubernetes": "junior", "python": "senior"},
        )
        assert result == GapClassification.SOFT

    def test_present_without_level_info_classified_as_soft(self, analyzer: GapAnalyzer):
        """If capability is in profile but not in levels map, still SOFT (unevidenced)."""
        result = analyzer.classify_gap(
            canonical_name="kubernetes",
            profile_capabilities={"kubernetes"},
            profile_levels={},
        )
        assert result == GapClassification.SOFT


class TestComputeGaps:
    """Tests for compute_gaps()."""

    def test_no_gaps_when_profile_covers_all(self, analyzer: GapAnalyzer):
        demanded = [
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
        ]
        profile = {"python"}
        gaps = analyzer.compute_gaps(demanded, profile, {"opp-1": 50000.0})
        assert gaps == []

    def test_absent_capability_produces_hard_gap(self, analyzer: GapAnalyzer):
        demanded = [
            ExtractedCapability(
                raw_name="Kubernetes",
                canonical_name="kubernetes",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
        ]
        profile: set[str] = set()
        gaps = analyzer.compute_gaps(demanded, profile, {"opp-1": 50000.0})

        assert len(gaps) == 1
        gap = gaps[0]
        assert gap.canonical_name == "kubernetes"
        assert gap.classification == GapClassification.HARD
        assert gap.opportunity_count == 1
        assert gap.blocked_pipeline_value == 50000.0
        assert gap.is_single_blocker is False
        assert gap.weighted_rank_score == 50000.0
        assert gap.trend is None

    def test_junior_capability_produces_soft_gap(self, analyzer: GapAnalyzer):
        demanded = [
            ExtractedCapability(
                raw_name="Kubernetes",
                canonical_name="kubernetes",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
        ]
        profile = {"kubernetes"}
        profile_levels = {"kubernetes": "junior"}
        gaps = analyzer.compute_gaps(
            demanded, profile, {"opp-1": 30000.0}, profile_levels=profile_levels
        )

        assert len(gaps) == 1
        assert gaps[0].classification == GapClassification.SOFT

    def test_preferred_capabilities_are_excluded(self, analyzer: GapAnalyzer):
        """Only REQUIRED capabilities contribute to gaps."""
        demanded = [
            ExtractedCapability(
                raw_name="Docker",
                canonical_name="docker",
                level=CapabilityLevel.PREFERRED,
                opportunity_id="opp-1",
            ),
        ]
        profile: set[str] = set()
        gaps = analyzer.compute_gaps(demanded, profile, {"opp-1": 50000.0})
        assert gaps == []

    def test_multiple_opportunities_aggregated(self, analyzer: GapAnalyzer):
        demanded = [
            ExtractedCapability(
                raw_name="K8s",
                canonical_name="kubernetes",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            ExtractedCapability(
                raw_name="Kubernetes",
                canonical_name="kubernetes",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-2",
            ),
            ExtractedCapability(
                raw_name="Kubernetes",
                canonical_name="kubernetes",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-3",
            ),
        ]
        profile: set[str] = set()
        opp_values = {"opp-1": 10000.0, "opp-2": 20000.0, "opp-3": 30000.0}
        gaps = analyzer.compute_gaps(demanded, profile, opp_values)

        assert len(gaps) == 1
        gap = gaps[0]
        assert gap.canonical_name == "kubernetes"
        assert gap.opportunity_count == 3
        assert gap.blocked_pipeline_value == 60000.0

    def test_default_value_used_for_unknown_opportunity(self, analyzer: GapAnalyzer):
        """When opportunity not in values map, use config default."""
        demanded = [
            ExtractedCapability(
                raw_name="Go",
                canonical_name="go",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-unknown",
            ),
        ]
        profile: set[str] = set()
        gaps = analyzer.compute_gaps(demanded, profile, {})

        assert len(gaps) == 1
        assert gaps[0].blocked_pipeline_value == 10000.0  # default

    def test_multiple_gaps_returned(self, analyzer: GapAnalyzer):
        demanded = [
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            ExtractedCapability(
                raw_name="Go",
                canonical_name="go",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
        ]
        profile: set[str] = set()
        gaps = analyzer.compute_gaps(demanded, profile, {"opp-1": 50000.0})

        assert len(gaps) == 2
        gap_names = {g.canonical_name for g in gaps}
        assert gap_names == {"python", "go"}

    def test_duplicate_opportunity_id_counted_once(self, analyzer: GapAnalyzer):
        """Same opportunity appearing twice for same capability counts as 1."""
        demanded = [
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            ExtractedCapability(
                raw_name="Python 3",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
        ]
        profile: set[str] = set()
        gaps = analyzer.compute_gaps(demanded, profile, {"opp-1": 25000.0})

        assert len(gaps) == 1
        assert gaps[0].opportunity_count == 1
        assert gaps[0].blocked_pipeline_value == 25000.0

    def test_senior_capability_not_a_gap(self, analyzer: GapAnalyzer):
        """Profile with senior level should not produce a gap."""
        demanded = [
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
        ]
        profile = {"python"}
        profile_levels = {"python": "senior"}
        gaps = analyzer.compute_gaps(
            demanded, profile, {"opp-1": 50000.0}, profile_levels=profile_levels
        )
        assert gaps == []

    def test_mid_level_capability_not_a_gap(self, analyzer: GapAnalyzer):
        """Profile with mid level should not produce a gap."""
        demanded = [
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
        ]
        profile = {"python"}
        profile_levels = {"python": "mid"}
        gaps = analyzer.compute_gaps(
            demanded, profile, {"opp-1": 50000.0}, profile_levels=profile_levels
        )
        assert gaps == []
