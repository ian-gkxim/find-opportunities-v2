"""Unit tests for the Scoring Engine module.

Tests cover:
- ScoringWeights validation
- ScoreResult construction
- compute_score with all factors present
- compute_score with missing factors and proportional redistribution
- Multi-source bonus calculation
- Intent boost application
- Tier classification
- Score capping at 100
"""

import pytest

from app.core.scoring_engine import ScoreResult, ScoreTier, ScoringEngine, ScoringWeights

# ─── ScoringWeights Tests ─────────────────────────────────────────────────────


class TestScoringWeights:
    """Tests for ScoringWeights.validate() method."""

    def test_default_weights_are_valid(self):
        """Default weights (30+25+20+15+10=100) should validate."""
        weights = ScoringWeights()
        assert weights.validate() is True

    def test_valid_custom_weights(self):
        """Custom weights summing to 100 should validate."""
        weights = ScoringWeights(
            firmographic=20,
            technographic=20,
            intent=20,
            llm_relevance=20,
            historical=20,
        )
        assert weights.validate() is True

    def test_invalid_sum_under_100(self):
        """Weights summing to less than 100 should fail validation."""
        weights = ScoringWeights(
            firmographic=20,
            technographic=20,
            intent=20,
            llm_relevance=20,
            historical=10,
        )
        assert weights.validate() is False

    def test_invalid_sum_over_100(self):
        """Weights summing to more than 100 should fail validation."""
        weights = ScoringWeights(
            firmographic=30,
            technographic=30,
            intent=30,
            llm_relevance=30,
            historical=30,
        )
        assert weights.validate() is False

    def test_negative_weight_invalid(self):
        """Any negative weight should fail validation."""
        weights = ScoringWeights(
            firmographic=-10,
            technographic=40,
            intent=30,
            llm_relevance=20,
            historical=20,
        )
        assert weights.validate() is False

    def test_weight_over_100_invalid(self):
        """A weight exceeding 100 should fail validation (even if sum is 100)."""
        weights = ScoringWeights(
            firmographic=101,
            technographic=-1,
            intent=0,
            llm_relevance=0,
            historical=0,
        )
        assert weights.validate() is False

    def test_all_zeros_except_one_valid(self):
        """One weight at 100, rest at 0 should validate."""
        weights = ScoringWeights(
            firmographic=100,
            technographic=0,
            intent=0,
            llm_relevance=0,
            historical=0,
        )
        assert weights.validate() is True

    def test_weights_at_boundary_valid(self):
        """Weights at exact boundaries (0 and 100) with correct sum."""
        weights = ScoringWeights(
            firmographic=0,
            technographic=0,
            intent=0,
            llm_relevance=0,
            historical=100,
        )
        assert weights.validate() is True


# ─── Tier Classification Tests ────────────────────────────────────────────────


class TestTierClassification:
    """Tests for _classify_tier static method."""

    def test_tier_a_lower_bound(self):
        """Score 75 should be A-tier."""
        assert ScoringEngine._classify_tier(75) == ScoreTier.A

    def test_tier_a_upper_bound(self):
        """Score 100 should be A-tier."""
        assert ScoringEngine._classify_tier(100) == ScoreTier.A

    def test_tier_b_lower_bound(self):
        """Score 50 should be B-tier."""
        assert ScoringEngine._classify_tier(50) == ScoreTier.B

    def test_tier_b_upper_bound(self):
        """Score 74 should be B-tier."""
        assert ScoringEngine._classify_tier(74) == ScoreTier.B

    def test_tier_c_lower_bound(self):
        """Score 25 should be C-tier."""
        assert ScoringEngine._classify_tier(25) == ScoreTier.C

    def test_tier_c_upper_bound(self):
        """Score 49 should be C-tier."""
        assert ScoringEngine._classify_tier(49) == ScoreTier.C

    def test_tier_d_lower_bound(self):
        """Score 0 should be D-tier."""
        assert ScoringEngine._classify_tier(0) == ScoreTier.D

    def test_tier_d_upper_bound(self):
        """Score 24 should be D-tier."""
        assert ScoringEngine._classify_tier(24) == ScoreTier.D


# ─── compute_score Tests ──────────────────────────────────────────────────────


class TestComputeScore:
    """Tests for the compute_score method."""

    def setup_method(self):
        """Create a default scoring engine for each test."""
        self.engine = ScoringEngine()

    def test_all_factors_present_perfect_scores(self):
        """All factors at 100 should produce a total of 100."""
        result = self.engine.compute_score(
            firmographic=100,
            technographic=100,
            intent=100,
            llm_relevance=100,
            historical=100,
        )
        assert result.total_score == 100
        assert result.tier == ScoreTier.A
        assert result.is_partial is False
        assert result.missing_factors == []
        assert result.multi_source_bonus == 0

    def test_all_factors_present_zero_scores(self):
        """All factors at 0 should produce a total of 0."""
        result = self.engine.compute_score(
            firmographic=0,
            technographic=0,
            intent=0,
            llm_relevance=0,
            historical=0,
        )
        assert result.total_score == 0
        assert result.tier == ScoreTier.D

    def test_all_factors_present_weighted_average(self):
        """Verify weighted average calculation with default weights.

        Weighted total = 80*0.30 + 60*0.25 + 40*0.20 + 70*0.15 + 50*0.10
                       = 24 + 15 + 8 + 10.5 + 5 = 62.5 → 62 (rounded)
        """
        result = self.engine.compute_score(
            firmographic=80,
            technographic=60,
            intent=40,
            llm_relevance=70,
            historical=50,
        )
        assert result.total_score == 62
        assert result.tier == ScoreTier.B

    def test_missing_one_factor_redistributes_weights(self):
        """When intent is missing, its weight is redistributed.

        Available weights: firmographic=30, technographic=25, llm_relevance=15, historical=10
        Sum of available = 80
        Weighted total = 80*(30/80) + 60*(25/80) + 70*(15/80) + 50*(10/80)
                       = 30 + 18.75 + 13.125 + 6.25 = 68.125 → 68
        """
        result = self.engine.compute_score(
            firmographic=80,
            technographic=60,
            intent=None,
            llm_relevance=70,
            historical=50,
        )
        assert result.total_score == 68
        assert result.is_partial is True
        assert "intent" in result.missing_factors
        assert "intent" not in result.factor_scores

    def test_missing_multiple_factors(self):
        """When multiple factors are missing, remaining weights are redistributed.

        Only firmographic (30) and technographic (25) available.
        Sum of available = 55
        Weighted total = 80*(30/55) + 60*(25/55)
                       = 80*0.5454... + 60*0.4545...
                       = 43.636 + 27.272 = 70.909 → 71
        """
        result = self.engine.compute_score(
            firmographic=80,
            technographic=60,
            intent=None,
            llm_relevance=None,
            historical=None,
        )
        assert result.total_score == 71
        assert result.is_partial is True
        assert len(result.missing_factors) == 3

    def test_no_factors_available_returns_zero(self):
        """When all factors are missing, score should be 0."""
        result = self.engine.compute_score(
            firmographic=None,
            technographic=None,
            intent=None,
            llm_relevance=None,
            historical=None,
        )
        assert result.total_score == 0
        assert result.tier == ScoreTier.D
        assert result.is_partial is True
        assert len(result.missing_factors) == 5

    def test_factor_scores_dict_contains_only_available(self):
        """factor_scores should only contain factors that were provided."""
        result = self.engine.compute_score(
            firmographic=80,
            technographic=None,
            intent=60,
            llm_relevance=None,
            historical=40,
        )
        assert set(result.factor_scores.keys()) == {"firmographic", "intent", "historical"}
        assert result.factor_scores["firmographic"] == 80
        assert result.factor_scores["intent"] == 60
        assert result.factor_scores["historical"] == 40


# ─── Multi-Source Bonus Tests ─────────────────────────────────────────────────


class TestMultiSourceBonus:
    """Tests for multi-source bonus calculation."""

    def setup_method(self):
        self.engine = ScoringEngine()

    def test_single_source_no_bonus(self):
        """source_count=1 should give 0 bonus."""
        result = self.engine.compute_score(
            firmographic=50, source_count=1
        )
        assert result.multi_source_bonus == 0

    def test_two_sources_bonus_10(self):
        """source_count=2 should give bonus of 10."""
        result = self.engine.compute_score(
            firmographic=50, source_count=2
        )
        assert result.multi_source_bonus == 10

    def test_three_sources_bonus_20(self):
        """source_count=3 should give bonus of 20."""
        result = self.engine.compute_score(
            firmographic=50, source_count=3
        )
        assert result.multi_source_bonus == 20

    def test_four_sources_bonus_30(self):
        """source_count=4 should give max bonus of 30."""
        result = self.engine.compute_score(
            firmographic=50, source_count=4
        )
        assert result.multi_source_bonus == 30

    def test_five_sources_bonus_capped_at_30(self):
        """source_count=5 should still be capped at 30."""
        result = self.engine.compute_score(
            firmographic=50, source_count=5
        )
        assert result.multi_source_bonus == 30

    def test_bonus_added_to_total(self):
        """Multi-source bonus should be added to the weighted total.

        firmographic=50, all other missing. Weighted total = 50.
        Bonus with 3 sources = 20. Total = 50 + 20 = 70.
        """
        result = self.engine.compute_score(
            firmographic=50,
            technographic=None,
            intent=None,
            llm_relevance=None,
            historical=None,
            source_count=3,
        )
        assert result.total_score == 70
        assert result.tier == ScoreTier.B


# ─── Intent Boost Tests ───────────────────────────────────────────────────────


class TestIntentBoost:
    """Tests for intent signal boost."""

    def setup_method(self):
        self.engine = ScoringEngine()

    def test_no_strong_intent_no_boost(self):
        """When has_strong_intent=False, no boost is applied."""
        result = self.engine.compute_score(
            firmographic=50, has_strong_intent=False
        )
        # Weighted total = 50, no bonus, no boost
        assert result.total_score == 50

    def test_strong_intent_adds_15(self):
        """When has_strong_intent=True, +15 is added."""
        result = self.engine.compute_score(
            firmographic=50, has_strong_intent=True
        )
        # Weighted total = 50, no bonus, boost = 15 → total = 65
        assert result.total_score == 65

    def test_intent_boost_applied_once(self):
        """Intent boost is applied exactly once regardless of signal count."""
        result = self.engine.compute_score(
            firmographic=50,
            intent=80,
            has_strong_intent=True,
        )
        # This test verifies the boost isn't applied multiple times.
        # With firmographic=50 (w=30) and intent=80 (w=20), available=50
        # Weighted: 50*(30/50) + 80*(20/50) = 30 + 32 = 62
        # Plus boost: 62 + 15 = 77
        assert result.total_score == 77


# ─── Score Capping Tests ──────────────────────────────────────────────────────


class TestScoreCapping:
    """Tests for score capping at 100."""

    def setup_method(self):
        self.engine = ScoringEngine()

    def test_score_capped_at_100_with_bonus(self):
        """Score shouldn't exceed 100 even with multi-source bonus."""
        result = self.engine.compute_score(
            firmographic=100,
            technographic=100,
            intent=100,
            llm_relevance=100,
            historical=100,
            source_count=4,  # would add 30
        )
        assert result.total_score == 100

    def test_score_capped_at_100_with_intent_boost(self):
        """Score shouldn't exceed 100 even with intent boost."""
        result = self.engine.compute_score(
            firmographic=90,
            technographic=90,
            intent=90,
            llm_relevance=90,
            historical=90,
            has_strong_intent=True,  # would add 15
        )
        assert result.total_score == 100

    def test_score_capped_at_100_with_both_bonuses(self):
        """Score shouldn't exceed 100 with both bonus and boost."""
        result = self.engine.compute_score(
            firmographic=80,
            technographic=80,
            intent=80,
            llm_relevance=80,
            historical=80,
            source_count=4,
            has_strong_intent=True,
        )
        # Weighted total = 80, bonus = 30 → 100 (capped), boost would go to 115 → capped at 100
        assert result.total_score == 100


# ─── Custom Weights Tests ─────────────────────────────────────────────────────


class TestCustomWeights:
    """Tests for scoring engine with custom weight configurations."""

    def test_equal_weights(self):
        """Equal weights (20 each) should produce simple average."""
        weights = ScoringWeights(
            firmographic=20,
            technographic=20,
            intent=20,
            llm_relevance=20,
            historical=20,
        )
        engine = ScoringEngine(weights)
        result = engine.compute_score(
            firmographic=100,
            technographic=50,
            intent=50,
            llm_relevance=50,
            historical=50,
        )
        # Simple average: (100+50+50+50+50)/5 = 60
        assert result.total_score == 60

    def test_single_factor_weight_100(self):
        """When one factor has weight 100, only that factor matters."""
        weights = ScoringWeights(
            firmographic=100,
            technographic=0,
            intent=0,
            llm_relevance=0,
            historical=0,
        )
        engine = ScoringEngine(weights)
        result = engine.compute_score(
            firmographic=75,
            technographic=0,
            intent=0,
            llm_relevance=0,
            historical=0,
        )
        assert result.total_score == 75

    def test_redistribution_with_custom_weights(self):
        """Proportional redistribution should work correctly with custom weights.

        Weights: firm=50, tech=50, intent=0, llm=0, hist=0
        Only firmographic provided (50), tech is missing.
        Available weight = 50 (firmographic only)
        Weighted total = 80 * (50/50) = 80
        """
        weights = ScoringWeights(
            firmographic=50,
            technographic=50,
            intent=0,
            llm_relevance=0,
            historical=0,
        )
        engine = ScoringEngine(weights)
        result = engine.compute_score(
            firmographic=80,
            technographic=None,
            intent=0,
            llm_relevance=0,
            historical=0,
        )
        assert result.total_score == 80


# ─── ScoreResult Tests ────────────────────────────────────────────────────────


class TestScoreResult:
    """Tests for ScoreResult dataclass construction."""

    def test_result_is_frozen(self):
        """ScoreResult should be immutable (frozen dataclass)."""
        result = ScoreResult(
            total_score=75,
            tier=ScoreTier.A,
            factor_scores={"firmographic": 80},
            missing_factors=["intent"],
            is_partial=True,
            multi_source_bonus=10,
        )
        with pytest.raises(AttributeError):
            result.total_score = 50  # type: ignore

    def test_result_fields(self):
        """ScoreResult should expose all expected fields."""
        result = ScoreResult(
            total_score=62,
            tier=ScoreTier.B,
            factor_scores={"firmographic": 80, "technographic": 60},
            missing_factors=["intent", "historical"],
            is_partial=True,
            multi_source_bonus=20,
        )
        assert result.total_score == 62
        assert result.tier == ScoreTier.B
        assert result.factor_scores == {"firmographic": 80, "technographic": 60}
        assert result.missing_factors == ["intent", "historical"]
        assert result.is_partial is True
        assert result.multi_source_bonus == 20
