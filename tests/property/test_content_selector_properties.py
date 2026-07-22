# Feature: relevance-weighted-selection, Property 1: Composite Score Formula
"""Property-based tests for ContentSelector._compute_composite_score formula.

Tests that the composite score is computed as the weighted average of
relevance, uniqueness, and narrative_dependency sub-scores, normalized
by dividing by 100 (since weights sum to 100) and rounded to the nearest integer.

**Validates: Requirements 1.2**
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.content_selector import (
    ContentSelector,
    ContentUnit,
    ContentUnitType,
    ConstraintType,
    LengthConstraint,
    SelectionConfig,
    SelectionWeights,
)


# ─── Strategies ───────────────────────────────────────────────────────────────

# Sub-scores: integers in [0, 100]
sub_score_st = st.integers(min_value=0, max_value=100)


@st.composite
def valid_weight_triple_st(draw) -> tuple[int, int, int]:
    """Generate a valid weight triple (w_r, w_u, w_n) where each is in [0, 100]
    and they sum to exactly 100.

    Strategy: draw two integers a, b such that a + b <= 100,
    then c = 100 - a - b.
    """
    a = draw(st.integers(min_value=0, max_value=100))
    b = draw(st.integers(min_value=0, max_value=100 - a))
    c = 100 - a - b
    return (a, b, c)


# ─── Property 1: Composite Score Formula ─────────────────────────────────────


class TestProperty1CompositeScoreFormula:
    """Property 1: Composite Score Formula.

    **Validates: Requirements 1.2**

    For any content unit with sub-scores relevance ∈ [0,100], uniqueness ∈ [0,100],
    narrative_dependency ∈ [0,100] and for any valid weight configuration where
    w_r + w_u + w_n = 100 and each weight ∈ [0,100], the computed composite score
    SHALL equal round((relevance * w_r + uniqueness * w_u + narrative_dependency * w_n) / 100).
    """

    @given(
        relevance=sub_score_st,
        uniqueness=sub_score_st,
        narrative_dependency=sub_score_st,
        weight_triple=valid_weight_triple_st(),
    )
    @settings(max_examples=200)
    def test_composite_score_matches_formula(
        self,
        relevance: int,
        uniqueness: int,
        narrative_dependency: int,
        weight_triple: tuple[int, int, int],
    ) -> None:
        """FOR ANY sub-scores in [0,100] and valid weights summing to 100,
        the composite score equals round((R*w_r + U*w_u + N*w_n) / 100).

        Feature: relevance-weighted-selection, Property 1: Composite Score Formula
        **Validates: Requirements 1.2**
        """
        w_r, w_u, w_n = weight_triple
        weights = SelectionWeights(relevance=w_r, uniqueness=w_u, narrative_dependency=w_n)

        selector = ContentSelector()
        actual = selector._compute_composite_score(
            relevance, uniqueness, narrative_dependency, weights
        )

        expected = round(
            (relevance * w_r + uniqueness * w_u + narrative_dependency * w_n) / 100
        )

        assert actual == expected, (
            f"Composite score mismatch.\n"
            f"Sub-scores: relevance={relevance}, uniqueness={uniqueness}, "
            f"narrative_dependency={narrative_dependency}\n"
            f"Weights: w_r={w_r}, w_u={w_u}, w_n={w_n}\n"
            f"Expected: {expected}, Got: {actual}"
        )


# ─── Strategies for Property 3 ───────────────────────────────────────────────


@st.composite
def content_unit_st(draw, doc_order: int) -> ContentUnit:
    """Generate a random ContentUnit with unique text to ensure varied scoring."""
    unit_id = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=4, max_size=8))
    # Generate text with enough words to be meaningful
    words = draw(st.lists(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=10),
        min_size=2,
        max_size=8,
    ))
    text = " ".join(words)
    return ContentUnit(
        id=f"unit_{doc_order}_{unit_id}",
        unit_type=ContentUnitType.BULLET,
        text=text,
        section="experience",
        document_order=doc_order,
    )


@st.composite
def exceeding_units_and_constraint_st(draw) -> tuple[list[ContentUnit], LengthConstraint]:
    """Generate N content units (3-15) and a MAX_UNITS constraint with max_value < N.

    This guarantees the total length exceeds the constraint, forcing cuts.
    """
    n_units = draw(st.integers(min_value=3, max_value=15))
    units = []
    for i in range(n_units):
        unit = draw(content_unit_st(doc_order=i))
        units.append(unit)

    # Ensure unique IDs
    seen_ids: set[str] = set()
    deduped_units: list[ContentUnit] = []
    for u in units:
        if u.id not in seen_ids:
            seen_ids.add(u.id)
            deduped_units.append(u)

    # Need at least 3 unique units for a meaningful test
    assume(len(deduped_units) >= 3)

    # MAX_UNITS constraint with max_value strictly less than number of units
    max_value = draw(st.integers(min_value=1, max_value=len(deduped_units) - 1))
    constraint = LengthConstraint(
        constraint_type=ConstraintType.MAX_UNITS,
        max_value=max_value,
    )

    return deduped_units, constraint


# ─── Property 3: Cut List Satisfies Constraint with Correct Ordering ─────────


class TestProperty3CutListOrderingAndConstraintSatisfaction:
    """Property 3: Cut List Satisfies Constraint with Correct Ordering.

    Feature: relevance-weighted-selection, Property 3: Cut List Satisfies Constraint with Correct Ordering

    **Validates: Requirements 2.1, 2.3**

    For any set of content units whose total length exceeds a given LengthConstraint,
    the SelectionResult SHALL satisfy:
    1. The cut_list is ordered by ascending composite_score.
    2. The final_length (retained units measured in the constraint's unit type) is ≤ constraint.max_value.
    3. The cut list is minimal: removing any single entry from cut_list would cause
       final_length to exceed the constraint.
    """

    @given(data=exceeding_units_and_constraint_st())
    @settings(max_examples=200)
    def test_cut_list_satisfies_constraint_with_correct_ordering(
        self,
        data: tuple[list[ContentUnit], LengthConstraint],
    ) -> None:
        """FOR ANY set of content units exceeding a MAX_UNITS constraint,
        the cut list is ordered ascending by composite_score, final_length ≤ max_value,
        and the cut list is minimal.

        Feature: relevance-weighted-selection, Property 3: Cut List Satisfies Constraint with Correct Ordering
        **Validates: Requirements 2.1, 2.3**
        """
        units, constraint = data

        # Use default weights and empty companion references for simplicity
        config = SelectionConfig(
            weights=SelectionWeights(),  # default 50/25/25
            protection_threshold=80,
            length_constraint=constraint,
        )

        selector = ContentSelector()
        result = selector.select_content(
            units=units,
            opportunity_keywords=[],
            companion_references=[],
            config=config,
        )

        # Invariant 1: cut_list is ordered by ascending composite_score
        cut_scores = [entry.composite_score for entry in result.cut_list]
        assert cut_scores == sorted(cut_scores), (
            f"Cut list is not ordered by ascending composite_score.\n"
            f"Cut scores: {cut_scores}\n"
            f"Expected: {sorted(cut_scores)}"
        )

        # Invariant 2: final_length ≤ constraint.max_value
        assert result.final_length <= constraint.max_value, (
            f"Final length {result.final_length} exceeds constraint max_value {constraint.max_value}"
        )

        # Invariant 3: cut list is minimal — removing any single entry would exceed constraint
        # For MAX_UNITS, each cut entry contributes exactly 1 unit of length.
        # Restoring any single entry means final_length + 1 > constraint.max_value.
        for i, entry in enumerate(result.cut_list):
            # "Restore" this entry: its contribution is 1 unit (for MAX_UNITS)
            restored_length = result.final_length + 1
            assert restored_length > constraint.max_value, (
                f"Cut list is not minimal: restoring entry {i} "
                f"(unit_id={entry.unit.id}, score={entry.composite_score}) "
                f"would give length {restored_length} which is still within "
                f"constraint max_value={constraint.max_value}. "
                f"This entry was cut unnecessarily."
            )
