"""Content_Selector — scores and ranks content units for inclusion/cutting.

Pure computation module with no database access, no async, and no I/O.
Follows the ScoringEngine pattern: frozen dataclass inputs/outputs,
configurable weights summing to 100, deterministic output.

Requirements 1.1, 1.2, 1.3: Pure scoring with weighted sub-scores.
Requirements 2.1, 2.2, 2.3: Cutting behavior with protection threshold.
"""

from dataclasses import dataclass, field
from enum import Enum


# ─── Enums ────────────────────────────────────────────────────────────────────


class ContentUnitType(str, Enum):
    """Type of atomic content unit."""

    BULLET = "bullet"          # Experience bullet point
    SKILL_ENTRY = "skill"      # Single skill or technology entry
    SENTENCE = "sentence"      # Sentence within a paragraph
    STATEMENT = "statement"    # Profile statement line


class ConstraintType(str, Enum):
    """Type of length constraint from Schema_Registry."""

    MAX_WORDS = "max_words"
    MAX_CHARACTERS = "max_characters"
    MAX_UNITS = "max_units"


# ─── Input Dataclasses ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ContentUnit:
    """An atomic piece of material content that can be independently scored.

    Attributes:
        id: Unique identifier within the material.
        unit_type: Classification of the content unit.
        text: The actual text content.
        section: Which section this unit belongs to (e.g. "experience", "skills").
        document_order: Position in the original document (0-indexed).
        parent_paragraph_id: If sentence, the paragraph it belongs to. None otherwise.
    """

    id: str
    unit_type: ContentUnitType
    text: str
    section: str
    document_order: int
    parent_paragraph_id: str | None = None


@dataclass(frozen=True)
class CompanionReference:
    """A reference from a companion material to a content unit.

    Attributes:
        source_material: Which companion material makes the reference (e.g. "cover_letter").
        source_passage: The text passage in the companion that references this unit.
        target_unit_id: The content unit ID being referenced.
        strength: How strongly the companion depends on this unit (0-100).
    """

    source_material: str
    source_passage: str
    target_unit_id: str
    strength: int  # 0-100


@dataclass(frozen=True)
class SelectionWeights:
    """Configurable weight distribution across the three scoring factors.

    Each weight is an integer percentage (0-100). All three must sum to exactly 100.
    Default: Relevance 50%, Uniqueness 25%, Narrative_Dependency 25%.
    """

    relevance: int = 50
    uniqueness: int = 25
    narrative_dependency: int = 25

    def validate(self) -> tuple[bool, str]:
        """Validate weights are in [0, 100] and sum to 100.

        Returns:
            (True, "") if valid, (False, error_message) otherwise.
        """
        weights = [self.relevance, self.uniqueness, self.narrative_dependency]
        if not all(0 <= w <= 100 for w in weights):
            return False, "Each weight must be between 0 and 100 inclusive"
        if sum(weights) != 100:
            return False, f"Weights must sum to 100, got {sum(weights)}"
        return True, ""


@dataclass(frozen=True)
class LengthConstraint:
    """A per-material-type length constraint from Schema_Registry.

    Attributes:
        constraint_type: The type of limit (words, characters, or units).
        max_value: The numeric limit.
        section: Optional section-specific constraint. None means whole-material.
    """

    constraint_type: ConstraintType
    max_value: int
    section: str | None = None


@dataclass(frozen=True)
class SelectionConfig:
    """Full configuration for a content selection run.

    Attributes:
        weights: Sub-score weight distribution.
        protection_threshold: Narrative_Dependency_Score above which units are protected (0-100).
        length_constraint: The constraint to satisfy.
    """

    weights: SelectionWeights = field(default_factory=SelectionWeights)
    protection_threshold: int = 80
    length_constraint: LengthConstraint = field(
        default_factory=lambda: LengthConstraint(ConstraintType.MAX_WORDS, 500)
    )


# ─── Output Dataclasses ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoredUnit:
    """A content unit with its computed scores.

    Attributes:
        unit: The original content unit.
        relevance_score: Keyword/capability match score (0-100).
        uniqueness_score: Information overlap penalty inverted to uniqueness (0-100).
        narrative_dependency_score: Cross-material dependency score (0-100).
        composite_score: Weighted combination of sub-scores (0-100).
    """

    unit: ContentUnit
    relevance_score: int
    uniqueness_score: int
    narrative_dependency_score: int
    composite_score: int


@dataclass(frozen=True)
class CutEntry:
    """A single entry in the cut list.

    Attributes:
        unit: The content unit to be cut.
        composite_score: The score at time of cutting.
        forced: True if this unit was protected but had to be cut anyway.
    """

    unit: ContentUnit
    composite_score: int
    forced: bool = False


@dataclass(frozen=True)
class ProtectionWarning:
    """Warning emitted when a protected unit must be cut.

    Attributes:
        unit_id: The protected content unit that was force-cut.
        narrative_dependency_score: Its dependency score.
        dependent_passage: The companion passage that depends on this unit.
        source_material: Which companion material is affected.
    """

    unit_id: str
    narrative_dependency_score: int
    dependent_passage: str
    source_material: str


@dataclass(frozen=True)
class SelectionResult:
    """Complete output of the content selection algorithm.

    Attributes:
        scored_units: All units with their computed scores, ordered by composite descending.
        cut_list: Units to cut, ordered lowest-score-first.
        retained_units: Units that survive, ordered by document_order.
        warnings: Protection warnings for force-cut units.
        original_length: Length of input material (in constraint units).
        final_length: Length after cuts (in constraint units).
    """

    scored_units: list[ScoredUnit]
    cut_list: list[CutEntry]
    retained_units: list[ContentUnit]
    warnings: list[ProtectionWarning]
    original_length: int
    final_length: int



# ─── Content Selector Engine ─────────────────────────────────────────────────


class ContentSelector:
    """Pure-function content selection engine.

    Stateless: all configuration is passed per invocation. No instance state
    is mutated between calls. Could be a module-level function, but class
    grouping aids discoverability and future extension.
    """

    def select_content(
        self,
        *,
        units: list[ContentUnit],
        opportunity_keywords: list[str],
        companion_references: list[CompanionReference],
        config: SelectionConfig,
    ) -> SelectionResult:
        """Score all units and produce a cut list to satisfy the length constraint.

        Args:
            units: All content units in the material, in document order.
            opportunity_keywords: Keywords/capabilities extracted from the opportunity.
            companion_references: References from companion materials to these units.
            config: Weights, protection threshold, and length constraint.

        Returns:
            SelectionResult with scored units, cut list, and warnings.

        Raises:
            ValueError: If config.weights fails validation or protection_threshold
                        is out of [0, 100] range, or max_value <= 0.
        """
        # 1. Validate configuration
        valid, error = config.weights.validate()
        if not valid:
            raise ValueError(f"Invalid weight configuration: {error}")

        if not (0 <= config.protection_threshold <= 100):
            raise ValueError(
                f"Protection threshold must be between 0 and 100, got {config.protection_threshold}"
            )

        if config.length_constraint.max_value <= 0:
            raise ValueError(
                f"Length constraint max_value must be positive, got {config.length_constraint.max_value}"
            )

        # 2. Handle empty units
        if not units:
            return SelectionResult(
                scored_units=[],
                cut_list=[],
                retained_units=[],
                warnings=[],
                original_length=0,
                final_length=0,
            )

        # 3. Compute sub-scores for each unit
        scored = self._score_all_units(units, opportunity_keywords, companion_references, config)

        # 4. Generate cut list to satisfy constraint
        cut_list, warnings = self._generate_cut_list(scored, config, companion_references)

        # 5. Compute retained units (original order preserved)
        cut_ids = {entry.unit.id for entry in cut_list}
        retained = [su.unit for su in scored if su.unit.id not in cut_ids]
        retained.sort(key=lambda u: u.document_order)

        # 6. Compute lengths
        original_length = self._measure_length(units, config.length_constraint)
        final_length = self._measure_length(retained, config.length_constraint)

        return SelectionResult(
            scored_units=sorted(scored, key=lambda s: s.composite_score, reverse=True),
            cut_list=cut_list,
            retained_units=retained,
            warnings=warnings,
            original_length=original_length,
            final_length=final_length,
        )

    _STOPWORDS = frozenset({
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then",
        "once", "and", "but", "or", "nor", "not", "so", "yet", "both",
        "either", "neither", "each", "every", "all", "any", "few", "more",
        "most", "other", "some", "such", "no", "only", "own", "same", "than",
        "too", "very", "just", "because", "if", "when", "where", "how", "what",
        "which", "who", "whom", "this", "that", "these", "those", "i", "me",
        "my", "myself", "we", "our", "ours", "ourselves", "you", "your",
        "yours", "yourself", "yourselves", "he", "him", "his", "himself",
        "she", "her", "hers", "herself", "it", "its", "itself", "they",
        "them", "their", "theirs", "themselves",
    })

    def _compute_narrative_dependency_score(
        self,
        unit: ContentUnit,
        companion_references: list[CompanionReference],
    ) -> int:
        """Compute narrative dependency from companion references.

        Algorithm:
        1. Collect all CompanionReferences whose target_unit_id matches this unit's id.
        2. If no references → score 0 (no dependency, safe to cut).
        3. If references exist → score = max(reference.strength for matching refs).

        A unit referenced by a cover letter passage with strength 90 gets
        Narrative_Dependency_Score = 90, making it highly protected.
        """
        matching = [ref for ref in companion_references if ref.target_unit_id == unit.id]
        if not matching:
            return 0
        return max(ref.strength for ref in matching)

    def _measure_length(
        self,
        units: list[ContentUnit],
        constraint: LengthConstraint,
    ) -> int:
        """Measure total length of units in the constraint's unit type."""
        if constraint.constraint_type == ConstraintType.MAX_WORDS:
            return sum(len(u.text.split()) for u in units)
        elif constraint.constraint_type == ConstraintType.MAX_CHARACTERS:
            return sum(len(u.text) for u in units)
        elif constraint.constraint_type == ConstraintType.MAX_UNITS:
            return len(units)
        return 0

    def _compute_uniqueness_scores(
        self,
        units: list[ContentUnit],
    ) -> dict[str, int]:
        """Compute uniqueness scores for all units via pairwise token overlap.

        Algorithm:
        1. For each unit, extract a token set (lowercase, stopwords removed).
        2. For each unit pair, compute Jaccard similarity.
        3. Each unit's overlap = max Jaccard similarity with any other unit.
        4. Uniqueness_Score = 100 - (max_overlap * 100), clamped to [0, 100].

        A unit with no token overlap with anything else gets 100 (fully unique).
        A unit that is a subset of another gets close to 0 (redundant).
        """
        import re

        # Tokenize each unit
        token_sets: dict[str, set[str]] = {}
        for unit in units:
            tokens = set(re.findall(r'\w+', unit.text.lower())) - self._STOPWORDS
            token_sets[unit.id] = tokens

        # Compute pairwise Jaccard, track max overlap per unit
        scores: dict[str, int] = {}
        unit_ids = list(token_sets.keys())

        for i, uid in enumerate(unit_ids):
            max_jaccard = 0.0
            tokens_i = token_sets[uid]

            if not tokens_i:
                scores[uid] = 100  # No tokens → fully unique (nothing to overlap)
                continue

            for j, other_id in enumerate(unit_ids):
                if i == j:
                    continue
                tokens_j = token_sets[other_id]
                if not tokens_j:
                    continue
                intersection = tokens_i & tokens_j
                union = tokens_i | tokens_j
                jaccard = len(intersection) / len(union) if union else 0.0
                max_jaccard = max(max_jaccard, jaccard)

            uniqueness = int(round(100 - (max_jaccard * 100)))
            scores[uid] = max(0, min(100, uniqueness))  # Clamp [0, 100]

        return scores

    def _compute_relevance_score(
        self,
        unit: ContentUnit,
        opportunity_keywords: list[str],
    ) -> int:
        """Compute relevance score as percentage of keywords matched.

        Algorithm:
        1. Normalize unit text to lowercase.
        2. Normalize each keyword to lowercase.
        3. For each keyword, check if it appears as a substring in the unit text.
        4. Score = (matched_keywords / total_keywords) * 100, rounded to int.

        Edge cases:
        - Empty keywords list → score 100 (everything is relevant by default).
        - Empty unit text → score 0.
        """
        if not opportunity_keywords:
            return 100
        if not unit.text.strip():
            return 0

        text_lower = unit.text.lower()
        matched = sum(1 for kw in opportunity_keywords if kw.lower() in text_lower)
        return int(round((matched / len(opportunity_keywords)) * 100))

    def _compute_composite_score(
        self,
        relevance: int,
        uniqueness: int,
        narrative_dependency: int,
        weights: SelectionWeights,
    ) -> int:
        """Weighted composite: (R * w_r + U * w_u + N * w_n) / 100.

        Since weights sum to 100, dividing by 100 normalizes back to 0-100 range.
        Result is rounded to nearest integer.
        """
        raw = (
            relevance * weights.relevance
            + uniqueness * weights.uniqueness
            + narrative_dependency * weights.narrative_dependency
        )
        return int(round(raw / 100))

    def _generate_cut_list(
        self,
        scored_units: list[ScoredUnit],
        config: SelectionConfig,
        companion_references: list[CompanionReference],
    ) -> tuple[list[CutEntry], list[ProtectionWarning]]:
        """Generate a minimal cut list to satisfy the length constraint.

        Algorithm:
        1. Sort scored units ascending by: (composite_score, relevance_score, -document_order)
           - Lower composite_score = cut first
           - On tie: lower relevance_score is cut first (higher retained)
           - On double tie: higher document_order is cut first (last-in-document first)
        2. Check current length against constraint.
        3. If already within constraint, return empty cut list.
        4. Iteratively cut lowest-scoring unprotected units.
        5. If only protected remain and still over limit, force-cut with ProtectionWarnings.

        Args:
            scored_units: All units with their computed scores.
            config: Selection configuration including weights, protection threshold, constraint.
            companion_references: References from companion materials for warning generation.

        Returns:
            Tuple of (cut_list, warnings).
        """
        constraint = config.length_constraint

        # Check if already within constraint
        all_units = [su.unit for su in scored_units]
        current_length = self._measure_length(all_units, constraint)
        if current_length <= constraint.max_value:
            return [], []

        # Sort ascending: lowest composite first (to be cut first)
        # Tie-break: lower relevance first (cut first), then higher document_order first (cut first)
        sorted_scored = sorted(
            scored_units,
            key=lambda su: (su.composite_score, su.relevance_score, -su.unit.document_order),
        )

        cut_list: list[CutEntry] = []
        warnings: list[ProtectionWarning] = []
        retained_units = list(all_units)  # Track what's still retained

        for su in sorted_scored:
            # Check if we've satisfied the constraint
            if self._measure_length(retained_units, constraint) <= constraint.max_value:
                break

            # Check if unit is protected
            if su.narrative_dependency_score > config.protection_threshold:
                # Skip protected units on first pass
                continue

            # Cut this unit
            retained_units = [u for u in retained_units if u.id != su.unit.id]
            cut_list.append(CutEntry(unit=su.unit, composite_score=su.composite_score, forced=False))

        # If still over constraint, force-cut protected units (lowest score first)
        if self._measure_length(retained_units, constraint) > constraint.max_value:
            # Get remaining protected units sorted by composite score ascending
            retained_ids = {u.id for u in retained_units}
            protected_remaining = [
                su for su in sorted_scored
                if su.narrative_dependency_score > config.protection_threshold
                and su.unit.id in retained_ids
            ]

            for su in protected_remaining:
                if self._measure_length(retained_units, constraint) <= constraint.max_value:
                    break

                retained_units = [u for u in retained_units if u.id != su.unit.id]
                cut_list.append(CutEntry(unit=su.unit, composite_score=su.composite_score, forced=True))

                # Find the companion reference with max strength for this unit
                matching_refs = [
                    ref for ref in companion_references if ref.target_unit_id == su.unit.id
                ]
                if matching_refs:
                    strongest_ref = max(matching_refs, key=lambda r: r.strength)
                    warnings.append(ProtectionWarning(
                        unit_id=su.unit.id,
                        narrative_dependency_score=su.narrative_dependency_score,
                        dependent_passage=strongest_ref.source_passage,
                        source_material=strongest_ref.source_material,
                    ))
                else:
                    # Edge case: unit is above threshold but no matching refs found
                    # (shouldn't happen in practice, but handle defensively)
                    warnings.append(ProtectionWarning(
                        unit_id=su.unit.id,
                        narrative_dependency_score=su.narrative_dependency_score,
                        dependent_passage="",
                        source_material="",
                    ))

        return cut_list, warnings

    def _score_all_units(
        self,
        units: list[ContentUnit],
        opportunity_keywords: list[str],
        companion_references: list[CompanionReference],
        config: SelectionConfig,
    ) -> list[ScoredUnit]:
        """Compute all sub-scores and composite for each unit.

        Orchestrates calls to:
        - _compute_relevance_score (per unit)
        - _compute_uniqueness_scores (batch, returns dict)
        - _compute_narrative_dependency_score (per unit)
        - _compute_composite_score (per unit)

        Returns list of ScoredUnit instances.
        """
        uniqueness_scores = self._compute_uniqueness_scores(units)

        scored: list[ScoredUnit] = []
        for unit in units:
            relevance = self._compute_relevance_score(unit, opportunity_keywords)
            uniqueness = uniqueness_scores.get(unit.id, 100)
            narrative_dep = self._compute_narrative_dependency_score(unit, companion_references)
            composite = self._compute_composite_score(
                relevance, uniqueness, narrative_dep, config.weights
            )
            scored.append(ScoredUnit(
                unit=unit,
                relevance_score=relevance,
                uniqueness_score=uniqueness,
                narrative_dependency_score=narrative_dep,
                composite_score=composite,
            ))

        return scored
