"""Scoring Engine — computes composite Account Scores from multiple signal sources.

Pure computation module with no database access, no async, and no I/O.
Combines firmographic, technographic, intent, LLM relevance, and historical
sub-scores into a weighted total with proportional redistribution for
missing factors.

Requirements 4.1, 4.2, 4.5, 4.6: Account scoring with weighted factors and tiers.
Requirements 3.3: Intent signal boost (+15 for strong signals).
Requirements 10.2: Multi-source bonus (10 per additional source, max 30).
"""

from dataclasses import dataclass
from enum import Enum

# ─── Enums ────────────────────────────────────────────────────────────────────


class ScoreTier(str, Enum):
    """Account score tier classification.

    A: 75-100 — Highest priority prospects
    B: 50-74  — Strong prospects
    C: 25-49  — Moderate prospects
    D: 0-24   — Low priority prospects
    """

    A = "A-tier"
    B = "B-tier"
    C = "C-tier"
    D = "D-tier"


# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoringWeights:
    """Configurable weight distribution across the five scoring factors.

    Each weight represents a percentage (0-100). The sum of all five
    weights must equal exactly 100 for the configuration to be valid.

    Default distribution: firmographic 30%, technographic 25%,
    intent 20%, llm_relevance 15%, historical 10%.
    """

    firmographic: int = 30
    technographic: int = 25
    intent: int = 20
    llm_relevance: int = 15
    historical: int = 10

    def validate(self) -> bool:
        """Validate that each weight is in [0, 100] and all weights sum to 100.

        Returns:
            True if the weight configuration is valid, False otherwise.
        """
        weights = [
            self.firmographic,
            self.technographic,
            self.intent,
            self.llm_relevance,
            self.historical,
        ]
        return all(0 <= w <= 100 for w in weights) and sum(weights) == 100


@dataclass(frozen=True)
class ScoreResult:
    """Result of computing an Account Score for a prospect.

    Attributes:
        total_score: Final composite score (0-100), capped at 100.
        tier: Classification tier based on total_score.
        factor_scores: Map of factor name to its sub-score (0-100).
        missing_factors: List of factor names that were unavailable.
        is_partial: True if any scoring factors were missing.
        multi_source_bonus: Bonus points from multi-source discovery (0, 10, 20, or 30).
    """

    total_score: int
    tier: ScoreTier
    factor_scores: dict[str, int]
    missing_factors: list[str]
    is_partial: bool
    multi_source_bonus: int


# ─── Scoring Engine ───────────────────────────────────────────────────────────

# Factor names used throughout the scoring engine
_FACTOR_FIRMOGRAPHIC = "firmographic"
_FACTOR_TECHNOGRAPHIC = "technographic"
_FACTOR_INTENT = "intent"
_FACTOR_LLM_RELEVANCE = "llm_relevance"
_FACTOR_HISTORICAL = "historical"


class ScoringEngine:
    """Computes composite Account Scores from multiple weighted signal sources.

    This is a pure computation class with no I/O, no database access, and
    no async operations. It receives pre-computed sub-scores and applies
    weighted aggregation with proportional redistribution for missing factors.

    Key behaviors:
    - Missing factors have their weights redistributed proportionally
    - Multi-source bonus: (source_count - 1) * 10, max 30
    - Intent boost: +15 if any strong intent signal exists, applied once
    - Final score is capped at 100
    """

    INTENT_STRONG_BOOST = 15
    MULTI_SOURCE_BONUS_PER_SOURCE = 10
    MULTI_SOURCE_BONUS_MAX = 30

    def __init__(self, weights: ScoringWeights | None = None) -> None:
        """Initialize with optional custom weights. Defaults used if None."""
        self._weights = weights or ScoringWeights()

    @property
    def weights(self) -> ScoringWeights:
        """Current scoring weight configuration."""
        return self._weights

    def compute_score(
        self,
        *,
        firmographic: int | None = None,
        technographic: int | None = None,
        intent: int | None = None,
        llm_relevance: int | None = None,
        historical: int | None = None,
        source_count: int = 1,
        has_strong_intent: bool = False,
    ) -> ScoreResult:
        """Compute a weighted composite score with proportional redistribution.

        Each sub-score is Optional[int] in the range 0-100, or None if the
        factor data is unavailable. Missing factors have their configured
        weights redistributed proportionally among available factors.

        Args:
            firmographic: Firmographic fit sub-score (0-100) or None.
            technographic: Technographic overlap sub-score (0-100) or None.
            intent: Intent signal sub-score (0-100) or None.
            llm_relevance: LLM relevance assessment sub-score (0-100) or None.
            historical: Historical conversion rate sub-score (0-100) or None.
            source_count: Number of discovery sources (1+). Used for multi-source bonus.
            has_strong_intent: Whether any strong intent signal exists for this prospect.

        Returns:
            ScoreResult with total_score, tier, factor breakdowns, and bonuses.
        """
        # Collect available factors and track missing ones
        factors: dict[str, int] = {}
        missing: list[str] = []

        factor_inputs = [
            (_FACTOR_FIRMOGRAPHIC, firmographic),
            (_FACTOR_TECHNOGRAPHIC, technographic),
            (_FACTOR_INTENT, intent),
            (_FACTOR_LLM_RELEVANCE, llm_relevance),
            (_FACTOR_HISTORICAL, historical),
        ]

        for name, value in factor_inputs:
            if value is not None:
                factors[name] = value
            else:
                missing.append(name)

        # Compute weighted total with proportional redistribution
        total = self._weighted_total(factors)

        # Apply multi-source bonus: (source_count - 1) * 10, max 30
        bonus = 0
        if source_count > 1:
            bonus = min(
                (source_count - 1) * self.MULTI_SOURCE_BONUS_PER_SOURCE,
                self.MULTI_SOURCE_BONUS_MAX,
            )
        total = min(total + bonus, 100)

        # Apply intent boost: +15 if any strong signal exists, applied once
        if has_strong_intent:
            total = min(total + self.INTENT_STRONG_BOOST, 100)

        # Cap at 100
        total = min(total, 100)

        return ScoreResult(
            total_score=total,
            tier=self._classify_tier(total),
            factor_scores=dict(factors),
            missing_factors=list(missing),
            is_partial=len(missing) > 0,
            multi_source_bonus=bonus,
        )

    def _weighted_total(self, factors: dict[str, int]) -> int:
        """Compute weighted total with proportional redistribution for missing factors.

        When some factors are missing, their weights are redistributed
        proportionally among the available factors. Each factor's effective
        weight becomes: original_weight / sum_of_available_weights.

        For example, if intent (20%) is missing and firmographic (30%) and
        technographic (25%) are the only available factors, the available
        weights sum to 55 and each factor score is weighted as:
            factor_score * (original_weight / 55)

        Args:
            factors: Map of available factor names to their sub-scores (0-100).

        Returns:
            Weighted total as an integer (rounded), or 0 if no factors available.
        """
        if not factors:
            return 0

        weight_map = self._get_weight_map()
        available_weight = sum(weight_map[f] for f in factors)

        if available_weight == 0:
            return 0

        total = sum(
            factors[f] * (weight_map[f] / available_weight) for f in factors
        )
        return int(round(total))

    @staticmethod
    def _classify_tier(score: int) -> ScoreTier:
        """Classify a score into its tier.

        Tier boundaries:
            A: 75-100
            B: 50-74
            C: 25-49
            D: 0-24

        Args:
            score: Integer score in [0, 100].

        Returns:
            The corresponding ScoreTier.
        """
        if score >= 75:
            return ScoreTier.A
        if score >= 50:
            return ScoreTier.B
        if score >= 25:
            return ScoreTier.C
        return ScoreTier.D

    def _get_weight_map(self) -> dict[str, int]:
        """Return a mapping of factor names to their configured weights."""
        return {
            _FACTOR_FIRMOGRAPHIC: self._weights.firmographic,
            _FACTOR_TECHNOGRAPHIC: self._weights.technographic,
            _FACTOR_INTENT: self._weights.intent,
            _FACTOR_LLM_RELEVANCE: self._weights.llm_relevance,
            _FACTOR_HISTORICAL: self._weights.historical,
        }
