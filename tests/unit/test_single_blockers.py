"""Unit tests for GapAnalyzer.detect_single_blockers() and apply_single_blocker_weighting().

Tests requirement 2.3:
- WHEN a Gap appears in an opportunity where it was the only unmet required Capability,
  THE Gap_Analyzer SHALL flag it as a "single-blocker" Gap and weight it 2x in the
  Gap_Heatmap ranking.
"""

import pytest

from app.core.gap_analyzer import (
    CapabilityLevel,
    ExtractedCapability,
    GapAnalysisConfig,
    GapAnalyzer,
    GapClassification,
    GapEntry,
)


@pytest.fixture
def analyzer() -> GapAnalyzer:
    """Create a GapAnalyzer with minimal config and no external deps."""
    config = GapAnalysisConfig(
        default_opportunity_value=10000.0,
        single_blocker_weight=2.0,
    )
    return GapAnalyzer(
        config=config,
        llm_router=None,
        schema_registry=None,
        db_session=None,
        redis_client=None,
        ws_manager=None,
    )


class TestDetectSingleBlockers:
    """Tests for detect_single_blockers()."""

    def test_single_unmet_capability_is_single_blocker(self, analyzer: GapAnalyzer):
        """If opportunity has exactly 1 unmet required capability, it's a single-blocker."""
        demanded = [
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            ExtractedCapability(
                raw_name="AWS",
                canonical_name="aws",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
        ]
        # Profile has aws but not python → python is single-blocker for opp-1
        profile = {"aws"}
        result = analyzer.detect_single_blockers(demanded, profile)
        assert result == {"python"}

    def test_two_unmet_capabilities_not_single_blocker(self, analyzer: GapAnalyzer):
        """If opportunity has >1 unmet required capability, none are single-blockers."""
        demanded = [
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            ExtractedCapability(
                raw_name="Kubernetes",
                canonical_name="kubernetes",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
        ]
        profile: set[str] = set()  # Both are unmet
        result = analyzer.detect_single_blockers(demanded, profile)
        assert result == set()

    def test_zero_unmet_capabilities_not_single_blocker(self, analyzer: GapAnalyzer):
        """If all required capabilities are met, no single-blockers."""
        demanded = [
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
        ]
        profile = {"python"}
        result = analyzer.detect_single_blockers(demanded, profile)
        assert result == set()

    def test_preferred_capabilities_ignored(self, analyzer: GapAnalyzer):
        """Only REQUIRED capabilities are considered for single-blocker detection."""
        demanded = [
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            ExtractedCapability(
                raw_name="Docker",
                canonical_name="docker",
                level=CapabilityLevel.PREFERRED,
                opportunity_id="opp-1",
            ),
        ]
        # python is the only unmet REQUIRED cap (docker is preferred, ignored)
        profile: set[str] = set()
        result = analyzer.detect_single_blockers(demanded, profile)
        assert result == {"python"}

    def test_multiple_opportunities_independent(self, analyzer: GapAnalyzer):
        """Single-blocker detection is per-opportunity."""
        demanded = [
            # opp-1: python is sole unmet (aws is met)
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            ExtractedCapability(
                raw_name="AWS",
                canonical_name="aws",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            # opp-2: kubernetes is sole unmet (python is met... wait, python isn't in profile)
            # Actually let's make it: opp-2 has kubernetes + go, both unmet → no single-blocker
            ExtractedCapability(
                raw_name="Kubernetes",
                canonical_name="kubernetes",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-2",
            ),
            ExtractedCapability(
                raw_name="Go",
                canonical_name="go",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-2",
            ),
        ]
        profile = {"aws"}
        result = analyzer.detect_single_blockers(demanded, profile)
        # opp-1: python is sole unmet → single-blocker
        # opp-2: kubernetes and go both unmet → not single-blockers
        assert result == {"python"}

    def test_same_capability_single_blocker_in_multiple_opps(self, analyzer: GapAnalyzer):
        """A capability can be single-blocker across multiple opportunities."""
        demanded = [
            # opp-1: python sole unmet
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            ExtractedCapability(
                raw_name="AWS",
                canonical_name="aws",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            # opp-2: python sole unmet
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-2",
            ),
            ExtractedCapability(
                raw_name="Go",
                canonical_name="go",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-2",
            ),
        ]
        profile = {"aws", "go"}
        result = analyzer.detect_single_blockers(demanded, profile)
        assert result == {"python"}

    def test_empty_demanded_capabilities(self, analyzer: GapAnalyzer):
        """Empty input returns empty set."""
        result = analyzer.detect_single_blockers([], {"python"})
        assert result == set()

    def test_multiple_single_blockers_from_different_opps(self, analyzer: GapAnalyzer):
        """Different opportunities can yield different single-blockers."""
        demanded = [
            # opp-1: python is sole unmet
            ExtractedCapability(
                raw_name="Python",
                canonical_name="python",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            ExtractedCapability(
                raw_name="AWS",
                canonical_name="aws",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-1",
            ),
            # opp-2: kubernetes is sole unmet
            ExtractedCapability(
                raw_name="Kubernetes",
                canonical_name="kubernetes",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-2",
            ),
            ExtractedCapability(
                raw_name="AWS",
                canonical_name="aws",
                level=CapabilityLevel.REQUIRED,
                opportunity_id="opp-2",
            ),
        ]
        profile = {"aws"}
        result = analyzer.detect_single_blockers(demanded, profile)
        assert result == {"python", "kubernetes"}


class TestApplySingleBlockerWeighting:
    """Tests for apply_single_blocker_weighting()."""

    def test_single_blocker_gets_2x_weight(self, analyzer: GapAnalyzer):
        """Single-blocker gaps should have weighted_rank_score = blocked_value * 2."""
        gaps = [
            GapEntry(
                canonical_name="python",
                classification=GapClassification.HARD,
                opportunity_count=3,
                blocked_pipeline_value=50000.0,
                is_single_blocker=False,
                weighted_rank_score=50000.0,
                trend=None,
            ),
        ]
        single_blockers = {"python"}
        result = analyzer.apply_single_blocker_weighting(gaps, single_blockers)

        assert len(result) == 1
        assert result[0].is_single_blocker is True
        assert result[0].weighted_rank_score == 100000.0  # 50000 * 2
        assert result[0].blocked_pipeline_value == 50000.0  # unchanged

    def test_non_single_blocker_unchanged(self, analyzer: GapAnalyzer):
        """Non-single-blocker gaps remain unchanged."""
        gaps = [
            GapEntry(
                canonical_name="kubernetes",
                classification=GapClassification.HARD,
                opportunity_count=2,
                blocked_pipeline_value=30000.0,
                is_single_blocker=False,
                weighted_rank_score=30000.0,
                trend=None,
            ),
        ]
        single_blockers: set[str] = set()
        result = analyzer.apply_single_blocker_weighting(gaps, single_blockers)

        assert len(result) == 1
        assert result[0].is_single_blocker is False
        assert result[0].weighted_rank_score == 30000.0

    def test_mixed_gaps(self, analyzer: GapAnalyzer):
        """Mix of single-blocker and non-single-blocker gaps."""
        gaps = [
            GapEntry(
                canonical_name="python",
                classification=GapClassification.HARD,
                opportunity_count=3,
                blocked_pipeline_value=50000.0,
                is_single_blocker=False,
                weighted_rank_score=50000.0,
                trend=None,
            ),
            GapEntry(
                canonical_name="kubernetes",
                classification=GapClassification.HARD,
                opportunity_count=2,
                blocked_pipeline_value=30000.0,
                is_single_blocker=False,
                weighted_rank_score=30000.0,
                trend=None,
            ),
        ]
        single_blockers = {"python"}
        result = analyzer.apply_single_blocker_weighting(gaps, single_blockers)

        python_gap = next(g for g in result if g.canonical_name == "python")
        k8s_gap = next(g for g in result if g.canonical_name == "kubernetes")

        assert python_gap.is_single_blocker is True
        assert python_gap.weighted_rank_score == 100000.0
        assert k8s_gap.is_single_blocker is False
        assert k8s_gap.weighted_rank_score == 30000.0

    def test_preserves_other_fields(self, analyzer: GapAnalyzer):
        """All other GapEntry fields are preserved during weighting."""
        from app.core.gap_analyzer import GapTrend

        gaps = [
            GapEntry(
                canonical_name="python",
                classification=GapClassification.SOFT,
                opportunity_count=5,
                blocked_pipeline_value=75000.0,
                is_single_blocker=False,
                weighted_rank_score=75000.0,
                trend=GapTrend.GROWING,
            ),
        ]
        single_blockers = {"python"}
        result = analyzer.apply_single_blocker_weighting(gaps, single_blockers)

        assert result[0].canonical_name == "python"
        assert result[0].classification == GapClassification.SOFT
        assert result[0].opportunity_count == 5
        assert result[0].blocked_pipeline_value == 75000.0
        assert result[0].trend == GapTrend.GROWING

    def test_empty_gaps_returns_empty(self, analyzer: GapAnalyzer):
        """Empty input returns empty list."""
        result = analyzer.apply_single_blocker_weighting([], {"python"})
        assert result == []
